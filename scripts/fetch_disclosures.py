"""
fetch_disclosures.py
Pulls politician stock disclosures from Capitol Trades API and upserts
them into the Supabase `stock_disclosures` table.

Capitol Trades aggregates STOCK Act filings for House and Senate members.
STOCK Act was enacted in 2012 — no data before that date.

Run: python fetch_disclosures.py
     python fetch_disclosures.py --year 2023
"""

import os
import argparse
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

CAPITOL_TRADES_BASE = "https://api.capitoltrades.com/v1"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_trades_page(page=1, page_size=100, year=None):
    url = f"{CAPITOL_TRADES_BASE}/trades"
    params = {"page": page, "pageSize": page_size}
    if year:
        params["txDateMin"] = f"{year}-01-01"
        params["txDateMax"] = f"{year}-12-31"
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()


def parse_trade(t):
    politician = t.get("politician", {})
    issuer = t.get("issuer", {})

    return {
        "member_id": politician.get("id"),
        "ticker": issuer.get("ticker"),
        "company": issuer.get("name"),
        "asset_description": issuer.get("name"),
        "transaction_type": t.get("type"),
        "transaction_date": t.get("txDate"),
        "amount_min": t.get("amounts", {}).get("min"),
        "amount_max": t.get("amounts", {}).get("max"),
        "filed_date": t.get("filingDate"),
        "source": "capitaltrades"
    }


def run(year=None):
    page = 1
    total = 0

    print(f"Fetching stock disclosures{' for ' + str(year) if year else ''}...")

    while True:
        data = fetch_trades_page(page=page, year=year)
        trades = data.get("data", [])
        if not trades:
            break

        rows = []
        for t in trades:
            parsed = parse_trade(t)
            if parsed["member_id"]:
                rows.append(parsed)

        if rows:
            supabase.table("stock_disclosures").upsert(rows).execute()
            total += len(rows)
            print(f"  Page {page}: upserted {len(rows)} trades (total: {total})")

        meta = data.get("meta", {})
        total_pages = meta.get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1

    print(f"\nDone. Total disclosures upserted: {total}")
    print("Note: STOCK Act data only available from 2012 onward.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="Limit to a specific year (e.g. 2023)")
    args = parser.parse_args()
    run(year=args.year)
