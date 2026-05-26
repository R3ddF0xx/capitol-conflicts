"""
compute_conflicts.py
Cross-references member votes with their stock disclosures to identify
potential conflicts of interest. Writes results to the `conflicts` table.

Conflict scoring logic (total 1–10):
  +3  Traded within 30 days of vote
  +2  Traded 31–90 days of vote
  +1  Traded 91–180 days of vote
  +2  Bill subjects overlap with stock's sector
  +2  Member sits on relevant committee
  +1  Member received PAC donations from same industry
  +2  Vote benefited the stock position (bought then voted yes on favorable bill, etc.)

Run: python compute_conflicts.py
     python compute_conflicts.py --member A000055
     python compute_conflicts.py --since 2023-01-01
"""

import os
import json
import argparse
import requests
from datetime import date, timedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Rough sector-to-bill-subject mapping
SECTOR_SUBJECTS = {
    "Health Care": ["Health", "Medical", "Pharmaceutical", "Drug", "Medicare", "Medicaid"],
    "Energy": ["Energy", "Oil", "Gas", "Climate", "Environment", "Solar", "Wind"],
    "Financials": ["Finance", "Banking", "Securities", "Insurance", "Credit"],
    "Defense": ["Defense", "Military", "Armed Forces", "Weapons", "National Security"],
    "Technology": ["Technology", "Telecommunications", "Internet", "Cybersecurity", "Data"],
    "Agriculture": ["Agriculture", "Farm", "Food", "Rural"],
    "Real Estate": ["Housing", "Real Estate", "Construction", "Mortgage"],
    "Utilities": ["Energy", "Water", "Electricity", "Infrastructure"],
}


SECTOR_CACHE_FILE = os.path.join(os.path.dirname(__file__), "sector_cache.json")
FMP_KEY = os.environ.get("FMP_API_KEY", "")


def _load_sector_cache():
    if os.path.exists(SECTOR_CACHE_FILE):
        with open(SECTOR_CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_sector_cache(cache):
    with open(SECTOR_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


_sector_disk_cache = _load_sector_cache()
_fmp_calls_this_run = 0


def get_sector_for_ticker(ticker):
    """Look up sector via local cache first, then FMP API. Results are
    persisted to sector_cache.json so each ticker is only looked up once ever."""
    global _fmp_calls_this_run

    if not ticker:
        return ""

    ticker = ticker.upper()

    # Check local disk cache
    if ticker in _sector_disk_cache:
        return _sector_disk_cache[ticker]

    # Hit FMP API (free tier: 250/day)
    if not FMP_KEY or _fmp_calls_this_run >= 240:
        _sector_disk_cache[ticker] = ""
        return ""

    try:
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}"
        r = requests.get(url, params={"apikey": FMP_KEY}, timeout=10)
        r.raise_for_status()
        data = r.json()
        sector = data[0].get("sector", "") if data else ""
    except Exception:
        sector = ""

    _sector_disk_cache[ticker] = sector
    _fmp_calls_this_run += 1

    # Save cache every 25 lookups
    if _fmp_calls_this_run % 25 == 0:
        _save_sector_cache(_sector_disk_cache)

    return sector


def subjects_match_sector(bill_subjects, sector):
    if not bill_subjects or not sector:
        return False
    keywords = SECTOR_SUBJECTS.get(sector, [])
    return any(kw.lower() in " ".join(bill_subjects).lower() for kw in keywords)


def score_conflict(days_diff, sector_match, committee_match, pac_match, vote_benefited):
    score = 0

    # Trade timing
    abs_days = abs(days_diff)
    if abs_days <= 30:
        score += 3
    elif abs_days <= 90:
        score += 2
    elif abs_days <= 180:
        score += 1

    if sector_match:
        score += 2
    if committee_match:
        score += 2
    if pac_match:
        score += 1
    if vote_benefited:
        score += 2

    return min(score, 10)


def fetch_all_members(member_filter=None):
    query = supabase.table("members").select("id").limit(5000)
    if member_filter:
        query = query.eq("id", member_filter)
    result = query.execute()
    return [r["id"] for r in result.data]


def fetch_disclosures_for_member(member_id):
    result = supabase.table("stock_disclosures") \
        .select("*") \
        .eq("member_id", member_id) \
        .limit(5000) \
        .execute()
    return result.data


def fetch_votes_for_member(member_id, since=None):
    query = supabase.table("member_votes") \
        .select("*, votes(*, bills(*))") \
        .eq("member_id", member_id) \
        .limit(5000)
    result = query.execute()
    return result.data


def fetch_committees_for_member(member_id):
    result = supabase.table("committee_assignments") \
        .select("committee_name") \
        .eq("member_id", member_id) \
        .limit(500) \
        .execute()
    return [r["committee_name"] for r in result.data]


def fetch_pacs_for_member(member_id):
    result = supabase.table("pac_donations") \
        .select("industry") \
        .eq("member_id", member_id) \
        .limit(500) \
        .execute()
    return [r["industry"] for r in result.data if r.get("industry")]


def committee_matches_sector(committees, sector):
    sector_kws = SECTOR_SUBJECTS.get(sector, [])
    committees_str = " ".join(committees).lower()
    return any(kw.lower() in committees_str for kw in sector_kws)


def pac_matches_sector(pac_industries, sector):
    sector_kws = SECTOR_SUBJECTS.get(sector, [])
    industries_str = " ".join(pac_industries).lower()
    return any(kw.lower() in industries_str for kw in sector_kws)


def vote_benefited_position(position, transaction_type, bill_subjects, sector):
    """
    Rough heuristic: if member bought stock and voted Yes on a favorable bill,
    or sold stock and voted Yes on a bill that could hurt the company.
    """
    if not position or not transaction_type:
        return False
    bought = transaction_type in ("Purchase",)
    sold = "Sale" in transaction_type
    voted_yes = position == "Yes"
    voted_no = position == "No"
    return (bought and voted_yes) or (sold and voted_no)


_sector_cache = {}  # global so repeated tickers aren't re-fetched across members


def process_member(member_id):
    disclosures = fetch_disclosures_for_member(member_id)
    if not disclosures:
        return 0

    member_votes = fetch_votes_for_member(member_id)
    if not member_votes:
        return 0

    committees = fetch_committees_for_member(member_id)
    pac_industries = fetch_pacs_for_member(member_id)

    conflicts = []
    sector_cache = _sector_cache  # shared across all members

    for disclosure in disclosures:
        ticker = disclosure.get("ticker")
        tx_date_str = disclosure.get("transaction_date")
        if not tx_date_str or not ticker:
            continue

        tx_date = date.fromisoformat(tx_date_str)

        # Cache sector lookups — expensive API call
        if ticker not in sector_cache:
            sector_cache[ticker] = get_sector_for_ticker(ticker)
        sector = sector_cache[ticker]

        for mv in member_votes:
            vote = mv.get("votes", {})
            if not vote:
                continue

            vote_date_str = vote.get("vote_date")
            if not vote_date_str:
                continue

            vote_date = date.fromisoformat(vote_date_str)
            days_diff = (tx_date - vote_date).days

            # Only flag if trade was within 180 days either side of the vote
            if abs(days_diff) > 180:
                continue

            bill = vote.get("bills") or {}
            bill_subjects = bill.get("subjects") or []

            # Sector match is a score booster but not required
            # (bill subjects are often unpopulated — don't skip just because of that)
            sector_match = subjects_match_sector(bill_subjects, sector)

            committee_match = committee_matches_sector(committees, sector)
            pac_match = pac_matches_sector(pac_industries, sector)
            benefited = vote_benefited_position(
                mv.get("position"),
                disclosure.get("transaction_type"),
                bill_subjects,
                sector
            )

            score = score_conflict(days_diff, sector_match, committee_match, pac_match, benefited)
            if score < 1:
                continue

            conflicts.append({
                "member_id": member_id,
                "vote_id": mv.get("vote_id"),
                "disclosure_id": disclosure["id"],
                "score": score,
                "days_between": days_diff,
                "trade_timing": "before_vote" if days_diff < 0 else "after_vote",
                "sector_match": sector_match,
                "committee_match": committee_match,
                "pac_match": pac_match,
            })

    if conflicts:
        supabase.table("conflicts").upsert(
            conflicts,
            on_conflict="member_id,vote_id,disclosure_id"
        ).execute()

    return len(conflicts)


def run(member_filter=None, since=None):
    members = fetch_all_members(member_filter)
    print(f"Processing {len(members)} members...")

    total = 0
    for i, member_id in enumerate(members, 1):
        try:
            count = process_member(member_id)
            if count:
                print(f"  [{i}/{len(members)}] {member_id}: {count} conflicts flagged")
            else:
                print(f"  [{i}/{len(members)}] {member_id}: no conflicts")
            total += count
        except Exception as e:
            print(f"  [{i}/{len(members)}] {member_id}: ERROR — {e}")

    # Save sector cache so future runs skip all API calls
    _save_sector_cache(_sector_disk_cache)
    print(f"Sector cache: {len(_sector_disk_cache)} tickers saved to {SECTOR_CACHE_FILE}")
    print(f"FMP API calls this run: {_fmp_calls_this_run}")
    print(f"\nDone. Total conflicts written: {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--member", type=str, help="Process a single member by bioguide ID")
    parser.add_argument("--since", type=str, help="Only process votes since this date (YYYY-MM-DD)")
    args = parser.parse_args()
    run(member_filter=args.member, since=args.since)
