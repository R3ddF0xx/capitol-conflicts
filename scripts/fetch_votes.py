"""
fetch_votes.py
Pulls roll call votes and bill data from Congress.gov API for a given
congress range and upserts into Supabase `bills`, `votes`, and `member_votes`.

Run: python fetch_votes.py
     python fetch_votes.py --congress 118        (single congress)
     python fetch_votes.py --start 111 --end 118 (range)

Congress numbers:
  111 = Obama Term 1 start (2009)
  118 = current (2023-2024)
  119 = 2025-2026
"""

import os
import sys
import argparse
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
CONGRESS_KEY = os.environ["CONGRESS_API_KEY"]

CONGRESS_BASE = "https://api.congress.gov/v3"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_votes_for_congress(congress, chamber, offset=0, limit=250):
    chamber_path = "senate" if chamber == "Senate" else "house"
    url = f"{CONGRESS_BASE}/vote/{congress}/{chamber_path}"
    params = {"api_key": CONGRESS_KEY, "offset": offset, "limit": limit, "format": "json"}
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()


def fetch_vote_detail(congress, chamber, session, vote_number):
    chamber_path = "senate" if chamber == "Senate" else "house"
    url = f"{CONGRESS_BASE}/vote/{congress}/{chamber_path}/{session}/{vote_number}"
    params = {"api_key": CONGRESS_KEY, "format": "json"}
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()


def fetch_bill_summary(congress, bill_type, bill_number):
    url = f"{CONGRESS_BASE}/bill/{congress}/{bill_type.lower()}/{bill_number}/summaries"
    params = {"api_key": CONGRESS_KEY, "format": "json"}
    r = requests.get(url, params=params)
    if r.status_code != 200:
        return None
    data = r.json()
    summaries = data.get("summaries", [])
    return summaries[-1]["text"] if summaries else None


def upsert_bill(vote_detail):
    bill_info = vote_detail.get("vote", {}).get("bill", {})
    if not bill_info:
        return None

    congress = bill_info.get("congress")
    bill_type = bill_info.get("type", "")
    bill_number = bill_info.get("number")
    bill_id = f"{bill_type.lower()}{bill_number}-{congress}"

    summary = fetch_bill_summary(congress, bill_type, bill_number)

    row = {
        "id": bill_id,
        "congress": congress,
        "bill_type": bill_type,
        "bill_number": bill_number,
        "title": bill_info.get("title", ""),
        "summary": summary,
        "link": f"https://congress.gov/bill/{congress}th-congress/{bill_type.lower()}-bill/{bill_number}",
    }
    supabase.table("bills").upsert(row).execute()
    return bill_id


def process_vote(v, congress, chamber):
    session = v.get("session")
    vote_number = v.get("rollNumber") or v.get("voteNumber")
    if not vote_number:
        return

    vote_id = f"{chamber.lower()}-{congress}-{session}-{vote_number}"

    detail_data = fetch_vote_detail(congress, chamber, session, vote_number)
    vote_detail = detail_data.get("vote", {})

    bill_id = upsert_bill(detail_data)

    vote_row = {
        "id": vote_id,
        "bill_id": bill_id,
        "congress": congress,
        "session": session,
        "chamber": chamber,
        "vote_number": vote_number,
        "vote_date": vote_detail.get("date", "")[:10] if vote_detail.get("date") else None,
        "question": vote_detail.get("question", ""),
        "description": vote_detail.get("description", ""),
        "result": vote_detail.get("result", "")
    }
    supabase.table("votes").upsert(vote_row).execute()

    positions = vote_detail.get("positions", [])
    member_vote_rows = []
    for pos in positions:
        member_id = pos.get("member", {}).get("bioguideId")
        if not member_id:
            continue
        member_vote_rows.append({
            "member_id": member_id,
            "vote_id": vote_id,
            "position": pos.get("votePosition", "Not Voting")
        })

    if member_vote_rows:
        supabase.table("member_votes").upsert(member_vote_rows).execute()

    print(f"  Processed vote {vote_id} ({len(member_vote_rows)} positions)")


def run(start_congress=111, end_congress=119):
    for congress in range(start_congress, end_congress + 1):
        for chamber in ["Senate", "House"]:
            print(f"\nFetching {chamber} votes for Congress {congress}...")
            offset = 0
            while True:
                data = fetch_votes_for_congress(congress, chamber, offset=offset)
                votes = data.get("votes", [])
                if not votes:
                    break
                for v in votes:
                    try:
                        process_vote(v, congress, chamber)
                    except Exception as e:
                        print(f"  Error on vote {v}: {e}")
                pagination = data.get("pagination", {})
                if offset + 250 >= pagination.get("count", 0):
                    break
                offset += 250

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--congress", type=int, help="Single congress number")
    parser.add_argument("--start", type=int, default=111, help="Start congress (default 111 = 2009)")
    parser.add_argument("--end", type=int, default=119, help="End congress (default 119 = current)")
    args = parser.parse_args()

    if args.congress:
        run(start_congress=args.congress, end_congress=args.congress)
    else:
        run(start_congress=args.start, end_congress=args.end)
