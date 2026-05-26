"""
fetch_pac_donations.py
Pulls top PAC industry donations per member from OpenSecrets API and
stores them in the Supabase `pac_donations` table.

OpenSecrets aggregates PAC money by industry per candidate — much more
useful than raw FEC data for our "PAC from same industry" scoring.

Sources:
  - bioguide → opensecrets CID mapping: unitedstates/congress-legislators
  - PAC industry donations: OpenSecrets `candIndustry` method

OpenSecrets free tier: 200 calls/day. Each member burns 1 call per cycle.

Run: python fetch_pac_donations.py
     python fetch_pac_donations.py --member A000055
     python fetch_pac_donations.py --cycle 2022
     python fetch_pac_donations.py --clear   # wipe before reload
"""

import os
import time
import argparse
import requests
import yaml
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
OPENSECRETS_KEY = os.environ.get("OPENSECRETS_API_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

LEGISLATORS_URLS = [
    "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml",
    "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-historical.yaml",
]

OPENSECRETS_BASE = "https://www.opensecrets.org/api/"

# Default cycles to fetch (OpenSecrets uses even-year cycles)
DEFAULT_CYCLES = [2024, 2022, 2020, 2018, 2016, 2014, 2012]


def fetch_yaml(url):
    print(f"Downloading {url}...")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return yaml.safe_load(r.text)


def build_bioguide_to_cid():
    """Build a map of {bioguide_id: opensecrets_cid} from the legislators files."""
    mapping = {}
    for url in LEGISLATORS_URLS:
        data = fetch_yaml(url)
        for legislator in data:
            ids = legislator.get("id", {})
            bioguide = ids.get("bioguide")
            cid = ids.get("opensecrets")
            if bioguide and cid:
                mapping[bioguide] = cid
    return mapping


def get_our_member_ids():
    ids = []
    page_size = 1000
    offset = 0
    while True:
        res = supabase.table("members").select("id").range(offset, offset + page_size - 1).execute()
        rows = res.data or []
        ids.extend([r["id"] for r in rows])
        if len(rows) < page_size:
            break
        offset += page_size
    return ids


def fetch_industries_for_member(cid, cycle):
    """Call OpenSecrets candIndustry method. Returns list of {industry, amount}."""
    params = {
        "method": "candIndustry",
        "cid": cid,
        "cycle": cycle,
        "output": "json",
        "apikey": OPENSECRETS_KEY,
    }
    try:
        r = requests.get(OPENSECRETS_BASE, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return [], f"error: {e}"

    # OpenSecrets nests data oddly: response.industries.industry = [list of @attributes]
    try:
        industries = data["response"]["industries"]["industry"]
        if isinstance(industries, dict):
            industries = [industries]  # single result comes as dict not list
    except (KeyError, TypeError):
        return [], "no data"

    results = []
    for item in industries:
        attrs = item.get("@attributes", item) if isinstance(item, dict) else {}
        industry_name = attrs.get("industry_name") or attrs.get("industry_code")
        if not industry_name:
            continue
        # Total = individuals + pacs combined; we mostly care about PAC money
        try:
            pac_amount = int(float(attrs.get("pacs", 0)))
        except (ValueError, TypeError):
            pac_amount = 0
        if pac_amount <= 0:
            continue
        results.append({
            "pac_name": f"{industry_name} (industry aggregate)",
            "industry": industry_name,
            "amount": pac_amount,
            "cycle": cycle,
        })

    return results, None


def clear_existing():
    print("Wiping existing pac_donations...")
    supabase.table("pac_donations").delete().neq("id", 0).execute()


def run(member_filter=None, cycle_filter=None, clear=False):
    if not OPENSECRETS_KEY:
        print("ERROR: OPENSECRETS_API_KEY not set in .env")
        return

    if clear:
        clear_existing()

    print("Building bioguide → opensecrets CID map...")
    bioguide_to_cid = build_bioguide_to_cid()
    print(f"  Mapped {len(bioguide_to_cid)} legislators with OpenSecrets IDs")

    our_members = get_our_member_ids()
    if member_filter:
        our_members = [m for m in our_members if m == member_filter]
    print(f"  Have {len(our_members)} members to process")

    cycles = [cycle_filter] if cycle_filter else DEFAULT_CYCLES

    total_inserted = 0
    api_calls = 0
    skipped_no_cid = 0
    errors = 0

    for i, bioguide in enumerate(our_members, 1):
        cid = bioguide_to_cid.get(bioguide)
        if not cid:
            skipped_no_cid += 1
            continue

        for cycle in cycles:
            industries, err = fetch_industries_for_member(cid, cycle)
            api_calls += 1
            time.sleep(0.5)  # respect rate limits

            if err == "error: ...":
                errors += 1
                continue

            if not industries:
                continue

            rows = []
            for item in industries:
                rows.append({
                    "member_id": bioguide,
                    "pac_name": item["pac_name"],
                    "industry": item["industry"],
                    "amount": item["amount"],
                    "cycle": item["cycle"],
                    "donation_date": None,
                    "source": "opensecrets",
                })

            if rows:
                try:
                    supabase.table("pac_donations").insert(rows).execute()
                    total_inserted += len(rows)
                except Exception as e:
                    print(f"  Insert error for {bioguide}/{cycle}: {e}")
                    errors += 1

        if i % 25 == 0:
            print(f"  [{i}/{len(our_members)}] {bioguide}: {total_inserted} inserted so far, {api_calls} API calls")

        # OpenSecrets free tier: 200 calls/day
        if api_calls >= 195:
            print(f"\nNear OpenSecrets rate limit ({api_calls} calls). Stopping.")
            print(f"Resume tomorrow with: python fetch_pac_donations.py --start-from {bioguide}")
            break

    print(f"\n=== Done ===")
    print(f"  Inserted: {total_inserted} donation rows")
    print(f"  API calls: {api_calls}")
    print(f"  Members without OpenSecrets ID: {skipped_no_cid}")
    print(f"  Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--member", type=str, help="Process a single member bioguide ID")
    parser.add_argument("--cycle", type=int, help="Process only one cycle year (e.g. 2022)")
    parser.add_argument("--clear", action="store_true", help="Wipe pac_donations table first")
    args = parser.parse_args()
    run(member_filter=args.member, cycle_filter=args.cycle, clear=args.clear)
