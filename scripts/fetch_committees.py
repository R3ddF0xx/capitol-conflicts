"""
fetch_committees.py
Pulls current committee assignments from the unitedstates/congress-legislators
GitHub dataset and inserts them into the Supabase `committee_assignments` table.

Source files (free, no auth):
  https://github.com/unitedstates/congress-legislators

Note: This pulls CURRENT committee membership only. The community-maintained
dataset doesn't track full historical membership for every congress.

Run: python fetch_committees.py
     python fetch_committees.py --clear   # wipe existing rows first
"""

import os
import argparse
import requests
import yaml
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

COMMITTEES_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committees-current.yaml"
MEMBERSHIP_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committee-membership-current.yaml"


def fetch_yaml(url):
    print(f"Downloading {url}...")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return yaml.safe_load(r.text)


def build_committee_lookup(committees):
    """Build a dict of {thomas_id: {name, chamber, parent_id}}.
    Includes both parent committees and subcommittees."""
    lookup = {}
    for c in committees:
        code = c.get("thomas_id")
        if not code:
            continue
        lookup[code] = {
            "name": c.get("name", ""),
            "chamber": "House" if c.get("type") == "house" else "Senate" if c.get("type") == "senate" else "Joint",
            "parent_id": None,
        }
        # Subcommittees
        for sub in c.get("subcommittees", []):
            sub_code = sub.get("thomas_id")
            if not sub_code:
                continue
            # Subcommittee codes in the membership file are parent_code + subcommittee_code
            full_code = code + sub_code
            lookup[full_code] = {
                "name": f"{c.get('name', '')} — {sub.get('name', '')}",
                "chamber": lookup[code]["chamber"],
                "parent_id": code,
            }
    return lookup


def get_our_member_ids():
    """Return the set of member bioguide IDs we have in Supabase."""
    ids = set()
    page_size = 1000
    offset = 0
    while True:
        res = supabase.table("members").select("id").range(offset, offset + page_size - 1).execute()
        rows = res.data or []
        for r in rows:
            ids.add(r["id"])
        if len(rows) < page_size:
            break
        offset += page_size
    return ids


def clear_existing():
    print("Wiping existing committee_assignments...")
    supabase.table("committee_assignments").delete().neq("id", 0).execute()


def run(clear=False):
    if clear:
        clear_existing()

    committees_data = fetch_yaml(COMMITTEES_URL)
    membership_data = fetch_yaml(MEMBERSHIP_URL)

    committee_lookup = build_committee_lookup(committees_data)
    print(f"Loaded {len(committee_lookup)} committees + subcommittees")

    our_members = get_our_member_ids()
    print(f"Have {len(our_members)} members in DB")

    rows_to_insert = []
    skipped_unknown_member = 0
    skipped_unknown_committee = 0

    for committee_code, members in membership_data.items():
        committee = committee_lookup.get(committee_code)
        if not committee:
            skipped_unknown_committee += 1
            continue

        for m in members:
            bioguide = m.get("bioguide")
            if not bioguide:
                continue
            if bioguide not in our_members:
                skipped_unknown_member += 1
                continue

            rows_to_insert.append({
                "member_id": bioguide,
                "committee_name": committee["name"],
                "committee_code": committee_code,
                "role": m.get("title", "Member") or "Member",
                "congress": None,  # current congress; unitedstates dataset doesn't tag it explicitly
                "chamber": committee["chamber"],
            })

    print(f"Prepared {len(rows_to_insert)} assignments")
    print(f"  Skipped (committee not in lookup): {skipped_unknown_committee}")
    print(f"  Skipped (member not in our DB): {skipped_unknown_member}")

    # Batch insert
    inserted = 0
    batch_size = 500
    for i in range(0, len(rows_to_insert), batch_size):
        batch = rows_to_insert[i:i + batch_size]
        try:
            supabase.table("committee_assignments").insert(batch).execute()
            inserted += len(batch)
            print(f"  Inserted {inserted}/{len(rows_to_insert)}")
        except Exception as e:
            print(f"  Insert error on batch starting {i}: {e}")

    print(f"\n=== Done. Inserted {inserted} committee assignments ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true", help="Wipe existing committee_assignments first")
    args = parser.parse_args()
    run(clear=args.clear)
