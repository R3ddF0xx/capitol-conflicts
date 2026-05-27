"""
fetch_votes.py
Pulls roll call votes directly from official government XML sources.

Senate: senate.gov LIS XML files (confirmed accessible, no key needed)
House:  clerk.house.gov EVS XML files (no key needed)

Run: python fetch_votes.py                        # all congresses 111-119
     python fetch_votes.py --congress 119          # single congress
     python fetch_votes.py --start 116 --end 119   # range
     python fetch_votes.py --chamber senate        # senate only

Congress number to years:
  111 = 2009-2010    115 = 2017-2018
  112 = 2011-2012    116 = 2019-2020
  113 = 2013-2014    117 = 2021-2022
  114 = 2015-2016    118 = 2023-2024
                     119 = 2025-2026
"""

import os
import time
import argparse
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

db = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {"User-Agent": "Capitol Conflicts Research Tool / contact: public data use"}

SENATE_MENU_URL   = "https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_{congress}_{session}.xml"
SENATE_VOTE_URL   = "https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress}{session}/vote_{congress}_{session}_{number:05d}.xml"
HOUSE_VOTE_URL    = "https://clerk.house.gov/evs/{year}/roll{number:03d}.xml"

# Maps congress number -> list of (session, year) tuples
CONGRESS_SESSIONS = {
    111: [(1, 2009), (2, 2010)],
    112: [(1, 2011), (2, 2012)],
    113: [(1, 2013), (2, 2014)],
    114: [(1, 2015), (2, 2016)],
    115: [(1, 2017), (2, 2018)],
    116: [(1, 2019), (2, 2020)],
    117: [(1, 2021), (2, 2022)],
    118: [(1, 2023), (2, 2024)],
    119: [(1, 2025), (2, 2026)],
}

_members_cache = {}

def load_members_cache(chamber):
    key = f"loaded_{chamber}"
    if _members_cache.get(key):
        return
    result = db.table("members").select("id, last_name, state, chamber").eq("chamber", chamber).limit(5000).execute()
    for m in result.data:
        k = (m["last_name"].lower(), m["state"].upper())
        _members_cache[k] = m["id"]
    _members_cache[key] = True
    print(f"  Loaded {len([k for k in _members_cache if k != key])} {chamber} members into cache")


def match_member(last_name, state, chamber):
    if not last_name or not state:
        return None
    load_members_cache(chamber)
    return _members_cache.get((last_name.lower(), state.upper()))


def parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    # Senate XML often appends time like "December 20, 2013,  11:25 AM" — strip it
    # Look for the pattern: month day, year followed by a comma+time
    import re
    raw = re.sub(r',\s*\d{1,2}:\d{2}\s*(AM|PM|am|pm)?\s*$', '', raw)
    for fmt in ("%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
        try:
            d = datetime.strptime(raw, fmt)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def get_xml(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return ET.fromstring(r.content)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return None
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return None


def already_processed(vote_id):
    vote_exists = db.table("votes").select("id").eq("id", vote_id).limit(1).execute()
    if not vote_exists.data:
        return False  # vote not in DB at all — full processing needed
    # Vote exists but member_votes might be missing (e.g. member cache was wrong on first run)
    mv_exists = db.table("member_votes").select("id").eq("vote_id", vote_id).limit(1).execute()
    return len(mv_exists.data) > 0  # skip only if member_votes are also present


# ── SENATE ────────────────────────────────────────────────────────────────────

def fetch_senate_session(congress, session):
    url = SENATE_MENU_URL.format(congress=congress, session=session)
    root = get_xml(url)
    if root is None:
        print(f"    No Senate votes found for Congress {congress} Session {session}")
        return

    votes_el = root.find("votes")
    if votes_el is None:
        return

    vote_entries = votes_el.findall("vote")
    print(f"    {len(vote_entries)} Senate votes in Congress {congress} Session {session}")

    processed = 0
    for ve in vote_entries:
        vote_num_str = ve.findtext("vote_number", "")
        if not vote_num_str:
            continue
        try:
            vote_num = int(vote_num_str)
        except ValueError:
            continue

        vote_id = f"senate-{congress}-{session}-{vote_num}"

        if already_processed(vote_id):
            continue

        detail_url = SENATE_VOTE_URL.format(congress=congress, session=session, number=vote_num)
        detail = get_xml(detail_url)
        if detail is None:
            continue

        vote_date = parse_date(detail.findtext("vote_date", ""))
        if not vote_date:
            continue  # schema requires vote_date NOT NULL

        # Bill info
        issue = detail.findtext("issue", "")
        bill_id = None
        if issue:
            clean = issue.replace(" ", "").replace(".", "").lower()
            bill_id = f"{clean}-{congress}" if clean else None

        if bill_id:
            db.table("bills").upsert({
                "id": bill_id,
                "congress": congress,
                "title": detail.findtext("vote_title", issue),
                "bill_type": issue.split(".")[0].strip() if "." in issue else None,
            }).execute()

        db.table("votes").upsert({
            "id": vote_id,
            "bill_id": bill_id,
            "congress": congress,
            "session": session,
            "chamber": "Senate",
            "vote_number": vote_num,
            "vote_date": vote_date or None,
            "question": detail.findtext("vote_question_text", ""),
            "result": detail.findtext("vote_result_text", ""),
        }).execute()

        # Member votes
        member_rows = []
        for member_el in detail.findall(".//member"):
            last  = member_el.findtext("last_name", "").strip()
            state = member_el.findtext("state", "").strip()
            cast  = member_el.findtext("vote_cast", "Not Voting").strip()
            member_id = match_member(last, state, "Senate")
            if member_id:
                position = "Yes" if cast == "Yea" else "No" if cast == "Nay" else cast
                member_rows.append({
                    "member_id": member_id,
                    "vote_id": vote_id,
                    "position": position
                })

        if member_rows:
            db.table("member_votes").upsert(member_rows).execute()

        processed += 1
        if processed % 25 == 0:
            print(f"      {processed}/{len(vote_entries)} votes processed...")

        time.sleep(0.3)  # be polite to senate.gov

    print(f"    Done: {processed} votes processed.")


# ── HOUSE ─────────────────────────────────────────────────────────────────────

def fetch_house_year(congress, year):
    print(f"    Fetching House votes for {year} (Congress {congress})...")
    processed = 0
    vote_num = 1

    while True:
        vote_id = f"house-{congress}-{year}-{vote_num}"

        if already_processed(vote_id):
            vote_num += 1
            if vote_num > 800:
                break
            continue

        url = HOUSE_VOTE_URL.format(year=year, number=vote_num)
        root = get_xml(url)

        if root is None:
            if vote_num > 10 and processed == 0:
                print(f"    House votes not accessible for {year} (server blocking). Skipping.")
                break
            elif vote_num > processed + 50:
                break
            vote_num += 1
            continue

        vote_date = parse_date(root.findtext(".//action-date", "") or root.findtext(".//vote-date", ""))
        if not vote_date:
            vote_num += 1
            continue  # schema requires vote_date NOT NULL

        bill_el = root.find(".//legis-num")
        bill_id = None
        if bill_el is not None and bill_el.text:
            clean = bill_el.text.replace(" ", "").replace(".", "").lower()
            bill_id = f"{clean}-{congress}"
            db.table("bills").upsert({
                "id": bill_id,
                "congress": congress,
                "title": root.findtext(".//vote-desc", bill_el.text or ""),
            }).execute()

        question = root.findtext(".//vote-question", "") or root.findtext(".//question", "")
        result   = root.findtext(".//vote-result", "")   or root.findtext(".//result", "")

        db.table("votes").upsert({
            "id": vote_id,
            "bill_id": bill_id,
            "congress": congress,
            "session": 1 if year % 2 == 1 else 2,
            "chamber": "House",
            "vote_number": vote_num,
            "vote_date": vote_date or None,
            "question": question,
            "result": result,
        }).execute()

        member_rows = []
        for voter in root.findall(".//recorded-vote"):
            legislator = voter.find("legislator")
            if legislator is None:
                continue
            last  = legislator.get("sort-field", "").split(",")[0].strip()
            state = legislator.get("state", "").strip()
            cast  = voter.findtext("vote", "Not Voting")
            member_id = match_member(last, state, "House")
            if member_id:
                position = "Yes" if cast in ("Yea", "Aye", "Yes") else "No" if cast in ("Nay", "No") else "Not Voting"
                member_rows.append({
                    "member_id": member_id,
                    "vote_id": vote_id,
                    "position": position
                })

        # De-dupe: House XML sometimes lists same member twice (vote corrections).
        # Keep the last occurrence so the corrected vote wins.
        if member_rows:
            seen = {}
            for r in member_rows:
                seen[(r["member_id"], r["vote_id"])] = r
            unique_rows = list(seen.values())
            db.table("member_votes").upsert(unique_rows, on_conflict="member_id,vote_id").execute()

        processed += 1
        vote_num += 1
        time.sleep(0.2)

    print(f"    House {year}: {processed} votes processed.")


# ── MAIN ─────────────────────────────────────────────────────────────────────

def run(start_congress=111, end_congress=119, chamber=None):
    for congress in range(start_congress, end_congress + 1):
        sessions = CONGRESS_SESSIONS.get(congress, [])

        if chamber != "house":
            print(f"\nSenate — Congress {congress}")
            for session, year in sessions:
                fetch_senate_session(congress, session)

        if chamber != "senate":
            print(f"\nHouse — Congress {congress}")
            for session, year in sessions:
                fetch_house_year(congress, year)

    print("\nAll done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--congress", type=int)
    parser.add_argument("--start",   type=int, default=111)
    parser.add_argument("--end",     type=int, default=119)
    parser.add_argument("--chamber", choices=["senate", "house"])
    args = parser.parse_args()

    if args.congress:
        run(start_congress=args.congress, end_congress=args.congress, chamber=args.chamber)
    else:
        run(start_congress=args.start, end_congress=args.end, chamber=args.chamber)
