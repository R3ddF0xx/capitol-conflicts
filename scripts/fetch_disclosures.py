"""
fetch_disclosures.py
Pulls politician stock disclosures from two free sources:

  Senate: GitHub repo (timothycarambat/senate-stock-watcher-data)
          Raw JSON — no API key required.

  House:  Financial Modeling Prep (FMP) free API
          Requires a free API key from financialmodelingprep.com
          Free tier: 250 calls/day — run this script over multiple days
          for full history, or just run it once for recent data.

STOCK Act was enacted in 2012 — no data before that date.

Run: python fetch_disclosures.py
     python fetch_disclosures.py --chamber senate
     python fetch_disclosures.py --chamber house
"""

import os
import argparse
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
FMP_KEY      = os.environ.get("FMP_API_KEY", "")

SENATE_JSON_URL = "https://raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data/master/aggregate/all_transactions.json"
HOUSE_JSON_URL  = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
FMP_HOUSE_URL   = "https://financialmodelingprep.com/api/v4/house-disclosure"
FMP_SENATE_URL  = "https://financialmodelingprep.com/api/v4/senate-trading"

db = create_client(SUPABASE_URL, SUPABASE_KEY)


def normalize_type(raw):
    if not raw:
        return "Unknown"
    raw = raw.strip().lower()
    if "purchase" in raw or "buy" in raw:
        return "Purchase"
    if "sale (full)" in raw:
        return "Sale (Full)"
    if "sale (partial)" in raw:
        return "Sale (Partial)"
    if "sale" in raw or "sell" in raw:
        return "Sale"
    if "exchange" in raw:
        return "Exchange"
    return raw.title()


def parse_amount(raw):
    if not raw:
        return None, None
    raw = str(raw).replace(",", "").replace("$", "").replace("+", "").strip()
    if " - " in raw:
        parts = raw.split(" - ")
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            return None, None
    try:
        val = int(raw.strip())
        return val, val
    except ValueError:
        return None, None


def clean_date(d):
    if not d:
        return None
    d = str(d).strip()
    if len(d) > 10:
        d = d[:10]
    return d if len(d) == 10 else None


_members_cache = {}

def load_members_cache():
    """Load all members from Supabase into memory once."""
    global _members_cache
    if _members_cache:
        return
    print("  Loading members into memory...")
    result = db.table("members").select("id, full_name, chamber").limit(5000).execute()
    for m in result.data:
        key = (m["full_name"].lower(), m["chamber"])
        _members_cache[key] = m["id"]
    print(f"  {len(_members_cache)} members loaded.")


def match_member(name, chamber):
    """Find a member's bioguide ID by last name match — uses local cache."""
    if not name:
        return None
    load_members_cache()
    name = name.strip().lower()
    last = name.split()[-1]
    for (full_name, ch), member_id in _members_cache.items():
        if ch == chamber and last in full_name:
            return member_id
    return None


def upsert_batch(rows):
    if rows:
        db.table("stock_disclosures").upsert(rows).execute()


# ── SENATE via GitHub ─────────────────────────────────────────────────────────

def fetch_senate_github():
    local_file = os.path.join(os.path.dirname(__file__), "all_transactions.json")

    print(f"Looking for local file at: {local_file} — exists: {os.path.exists(local_file)}")
    if os.path.exists(local_file):
        print(f"Reading Senate disclosures from local file: {local_file}")
        with open(local_file, "r", encoding="utf-8") as f:
            import json
            trades = json.load(f)
    else:
        print("Fetching Senate disclosures from GitHub...")
        r = requests.get(SENATE_JSON_URL, timeout=60)
        r.raise_for_status()
        trades = r.json()

    print(f"  {len(trades)} Senate trades found")

    rows, skipped, total = [], 0, 0

    for t in trades:
        member_id = match_member(t.get("senator"), "Senate")
        if not member_id:
            skipped += 1
            continue

        amount_min, amount_max = parse_amount(t.get("amount"))

        rows.append({
            "member_id": member_id,
            "ticker": t.get("ticker", "").upper() if t.get("ticker") else None,
            "company": t.get("asset_description", "") or t.get("asset_name", ""),
            "asset_description": t.get("asset_description", ""),
            "transaction_type": normalize_type(t.get("type")),
            "transaction_date": clean_date(t.get("transaction_date")),
            "amount_min": amount_min,
            "amount_max": amount_max,
            "filed_date": clean_date(t.get("disclosure_date") or t.get("date_received")),
            "source": "senate-stock-watcher-github"
        })

        if len(rows) >= 500:
            upsert_batch(rows)
            total += len(rows)
            print(f"  Upserted {total} so far (skipped {skipped} unmatched)...")
            rows = []

    upsert_batch(rows)
    total += len(rows)
    print(f"  Senate done. {total} upserted, {skipped} skipped.")


# ── HOUSE via GitHub ──────────────────────────────────────────────────────────

def fetch_house_github():
    """Pull House disclosures from the house-stock-watcher GitHub repo.
    Free, no API key. Falls back to FMP if this fails."""
    print("Fetching House disclosures from GitHub (jeremiak/house-stock-watcher-data)...")

    try:
        r = requests.get(HOUSE_JSON_URL, timeout=120)
        r.raise_for_status()
        trades = r.json()
    except Exception as e:
        print(f"  GitHub fetch failed ({e}), falling back to FMP")
        return fetch_house_fmp()

    print(f"  {len(trades)} House trades found")

    rows, skipped, total = [], 0, 0

    for t in trades:
        # House data uses "representative" field; sometimes "name" or "member"
        rep_name = t.get("representative") or t.get("name") or t.get("member")
        member_id = match_member(rep_name, "House")
        if not member_id:
            skipped += 1
            continue

        amount_min, amount_max = parse_amount(t.get("amount"))

        rows.append({
            "member_id": member_id,
            "ticker": t.get("ticker", "").upper() if t.get("ticker") else None,
            "company": t.get("asset_description") or t.get("assetDescription") or "",
            "asset_description": t.get("asset_description") or t.get("assetDescription") or "",
            "transaction_type": normalize_type(t.get("type") or t.get("transaction_type")),
            "transaction_date": clean_date(t.get("transaction_date") or t.get("transactionDate")),
            "amount_min": amount_min,
            "amount_max": amount_max,
            "filed_date": clean_date(t.get("disclosure_date") or t.get("disclosureDate")),
            "source": "house-stock-watcher-github"
        })

        if len(rows) >= 500:
            upsert_batch(rows)
            total += len(rows)
            print(f"  Upserted {total} so far (skipped {skipped} unmatched)...")
            rows = []

    upsert_batch(rows)
    total += len(rows)
    print(f"  House done. {total} upserted, {skipped} skipped.")


# ── HOUSE via FMP (fallback only) ─────────────────────────────────────────────

def fetch_house_fmp():
    if not FMP_KEY:
        print("  Skipping House — FMP_API_KEY not set in .env")
        print("  Get a free key at https://financialmodelingprep.com/register")
        print("  Then add FMP_API_KEY=your_key to scripts/.env and re-run with --chamber house")
        return

    print("Fetching House disclosures from FMP...")
    page, total, skipped = 0, 0, 0

    while True:
        params = {"apikey": FMP_KEY, "page": page}
        r = requests.get(FMP_HOUSE_URL, params=params, timeout=30)
        r.raise_for_status()
        trades = r.json()

        if not trades:
            break

        rows = []
        for t in trades:
            member_id = match_member(t.get("representative"), "House")
            if not member_id:
                skipped += 1
                continue

            amount_min, amount_max = parse_amount(t.get("amount"))

            rows.append({
                "member_id": member_id,
                "ticker": t.get("ticker", "").upper() if t.get("ticker") else None,
                "company": t.get("assetDescription", "") or t.get("asset_description", ""),
                "asset_description": t.get("assetDescription", ""),
                "transaction_type": normalize_type(t.get("type")),
                "transaction_date": clean_date(t.get("transactionDate")),
                "amount_min": amount_min,
                "amount_max": amount_max,
                "filed_date": clean_date(t.get("disclosureDate")),
                "source": "fmp-house"
            })

        upsert_batch(rows)
        total += len(rows)
        print(f"  Page {page}: {len(rows)} trades (total: {total}, skipped: {skipped})")
        page += 1

    print(f"  House done. {total} upserted, {skipped} skipped.")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run(chamber=None):
    print("Note: STOCK Act data only available from 2012 onward.\n")

    if chamber == "senate":
        fetch_senate_github()
    elif chamber == "house":
        fetch_house_github()
    else:
        fetch_senate_github()
        fetch_house_github()

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chamber", choices=["house", "senate"])
    args = parser.parse_args()
    run(chamber=args.chamber)
