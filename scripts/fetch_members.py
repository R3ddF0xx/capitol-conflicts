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

STATE_ABBREVS = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
    "Puerto Rico": "PR", "Guam": "GU", "American Samoa": "AS",
    "Virgin Islands": "VI", "Northern Mariana Islands": "MP",
}

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

    # Congress.gov returns name as "Last, First" — split it
    name_raw = m.get("name", "")
    if "," in name_raw:
        parts = name_raw.split(",", 1)
        last_name = parts[0].strip()
        full_name = f"{parts[1].strip()} {parts[0].strip()}"  # "First Last"
    else:
        last_name = m.get("lastName", "")
        full_name = name_raw

    # Congress.gov returns full state name — normalize to two-letter code
    raw_state = m.get("state", "")
    state = STATE_ABBREVS.get(raw_state, raw_state)

    raw_chamber = latest_term.get("chamber", "")
    chamber = "Senate" if "Senate" in raw_chamber else "House" if "House" in raw_chamber else raw_chamber

    return {
        "id": m["bioguideId"],
        "first_name": m.get("firstName", ""),
        "last_name": last_name,
        "full_name": full_name,
        "party": m.get("partyName", "")[:1] if m.get("partyName") else None,
        "state": state,
        "chamber": chamber,
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
