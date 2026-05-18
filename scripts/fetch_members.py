"""
fetch_members.py
Pulls all current and historical members of Congress from Congress.gov API
and upserts them into the Supabase `members` table.

Run: python fetch_members.py
"""

import os
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
CONGRESS_KEY = os.environ["CONGRESS_API_KEY"]

CONGRESS_BASE = "https://api.congress.gov/v3"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_members_page(offset=0, limit=250):
    url = f"{CONGRESS_BASE}/member"
    params = {
        "api_key": CONGRESS_KEY,
        "offset": offset,
        "limit": limit,
        "format": "json"
    }
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()


def parse_member(m):
    terms = m.get("terms", {}).get("item", [])
    latest_term = terms[-1] if terms else {}
    return {
        "id": m["bioguideId"],
        "first_name": m.get("firstName", ""),
        "last_name": m.get("lastName", ""),
        "full_name": m.get("name", ""),
        "party": m.get("partyName", "")[:1] if m.get("partyName") else None,
        "state": m.get("state", ""),
        "chamber": latest_term.get("chamber", ""),
        "district": str(latest_term.get("district", "")) if latest_term.get("district") else None,
        "photo_url": f"https://bioguide.congress.gov/bioguide/photo/{m['bioguideId'][0]}/{m['bioguideId']}.jpg",
        "active": m.get("currentMember", False)
    }


def run():
    offset = 0
    total_inserted = 0

    print("Fetching members from Congress.gov...")

    while True:
        data = fetch_members_page(offset=offset)
        members = data.get("members", [])
        if not members:
            break

        rows = [parse_member(m) for m in members]
        result = supabase.table("members").upsert(rows).execute()
        total_inserted += len(rows)
        print(f"  Upserted {total_inserted} members so far...")

        pagination = data.get("pagination", {})
        if offset + 250 >= pagination.get("count", 0):
            break
        offset += 250

    print(f"Done. Total members upserted: {total_inserted}")


if __name__ == "__main__":
    run()
