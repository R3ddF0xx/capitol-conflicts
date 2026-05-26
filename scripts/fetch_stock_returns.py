"""
fetch_stock_returns.py
Looks up stock price changes around each conflict's vote date using Stooq
(free, no API key needed). Stores the 30-day return so the frontend can
show whether the member's stock position made or lost money after the vote.

Uses a local price cache (price_cache.json) so each ticker is only
fetched once.

Run: python fetch_stock_returns.py
     python fetch_stock_returns.py --ticker AAPL
     python fetch_stock_returns.py --limit 100
"""

import os
import json
import time
import argparse
import requests
from datetime import date, timedelta, datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_API_KEY", "")

db = create_client(SUPABASE_URL, SUPABASE_KEY)

CACHE_FILE = os.path.join(os.path.dirname(__file__), "price_cache.json")

# ── Price cache ───────────────────────────────────────────────────────────────
# Structure: { "AAPL": { "2023-09-14": 178.52, "2023-10-14": 182.31, ... } }

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


price_cache = load_cache()
fmp_calls = 0  # legacy name, now counts Stooq calls


def get_price_on_date(ticker, target_date_str):
    """Get closing price for a ticker on or near a date.
    Checks cache first, returns None if unavailable."""
    global fmp_calls

    if not ticker or not target_date_str or not FMP_KEY:
        return None

    ticker = ticker.upper()

    # Check cache — look for exact date or within 5 trading days
    if ticker in price_cache:
        # Exact match
        if target_date_str in price_cache[ticker]:
            return price_cache[ticker][target_date_str]

    return None  # Caller will batch-fetch


def fetch_prices_for_ticker(ticker, from_date, to_date):
    """Fetch daily closing prices from Twelve Data.
    Free tier: 800 calls/day, 8 calls/min.
    Returns dict of { "YYYY-MM-DD": close_price }."""
    global fmp_calls

    if not TWELVEDATA_KEY:
        print("    No TWELVEDATA_API_KEY set in .env — skipping")
        return {}

    ticker = ticker.upper()

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": ticker,
        "interval": "1day",
        "start_date": from_date,
        "end_date": to_date,
        "format": "JSON",
        "apikey": TWELVEDATA_KEY,
    }

    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        fmp_calls += 1
        # 8 calls/min on free tier — sleep 8s to stay just under the limit
        time.sleep(8)
    except Exception as e:
        print(f"    Twelve Data error for {ticker}: {e}")
        return {}

    # Check for API errors
    if isinstance(data, dict) and data.get("status") == "error":
        msg = data.get("message", "unknown")
        print(f"    {ticker}: API error — {msg}")
        # Rate limit hit
        if "limit" in msg.lower() or "exceed" in msg.lower():
            print("    Rate limit hit — sleeping 60s")
            time.sleep(60)
        return {}

    values = data.get("values", []) if isinstance(data, dict) else []
    if not values:
        print(f"    {ticker}: no data returned (delisted or unsupported?)")
        return {}

    prices = {}
    for row in values:
        try:
            d = row["datetime"][:10]  # "2023-09-14"
            prices[d] = float(row["close"])
        except (KeyError, ValueError):
            continue

    # Merge into cache
    if ticker not in price_cache:
        price_cache[ticker] = {}
    price_cache[ticker].update(prices)

    print(f"    {ticker}: {len(prices)} days cached")
    return prices


def find_closest_price(ticker, target_date_str, direction=1, max_gap=10):
    """Find the closest cached price to a target date.
    direction=1 searches forward, -1 searches backward."""
    if ticker not in price_cache:
        return None

    target = date.fromisoformat(target_date_str)
    for offset in range(0, max_gap + 1):
        check = target + timedelta(days=offset * direction)
        check_str = check.isoformat()
        if check_str in price_cache.get(ticker, {}):
            return price_cache[ticker][check_str]

    # Try opposite direction as fallback (weekends/holidays)
    for offset in range(1, max_gap + 1):
        check = target + timedelta(days=offset * -direction)
        check_str = check.isoformat()
        if check_str in price_cache.get(ticker, {}):
            return price_cache[ticker][check_str]

    return None


def compute_return(price_before, price_after):
    """Compute percentage return."""
    if not price_before or not price_after or price_before == 0:
        return None
    return round(((price_after - price_before) / price_before) * 100, 2)


def fetch_conflicts_for_ticker(ticker):
    """Paginate through all conflicts for a given ticker that need a return."""
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        res = db.table("conflicts_view") \
            .select("id, vote_date, transaction_type") \
            .is_("stock_return_30d", "null") \
            .eq("ticker", ticker) \
            .range(offset, offset + page_size - 1) \
            .execute()
        rows = res.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return all_rows


def get_unique_tickers_needing_returns():
    """Get a list of unique tickers that still have unprocessed conflicts.
    Uses pagination since Supabase caps at 1000 rows per request."""
    seen = set()
    page_size = 1000
    offset = 0
    while True:
        res = db.table("conflicts_view") \
            .select("ticker") \
            .is_("stock_return_30d", "null") \
            .not_.in_("ticker", ["--", "N/A", "NA", "", "NONE"]) \
            .range(offset, offset + page_size - 1) \
            .execute()
        rows = res.data or []
        for r in rows:
            t = (r.get("ticker") or "").upper()
            if t:
                seen.add(t)
        if len(rows) < page_size:
            break
        offset += page_size
        if offset % 10000 == 0:
            print(f"  ...scanned {offset} rows, {len(seen)} unique tickers so far")
    return sorted(seen)


def run(ticker_filter=None, limit=None):
    # Step 1: Discover all unique tickers that need returns
    if ticker_filter:
        tickers = [ticker_filter.upper()]
    else:
        print("Scanning for unique tickers needing returns...")
        tickers = get_unique_tickers_needing_returns()
        print(f"Found {len(tickers)} unique tickers to process")

    if not tickers:
        print("All done — no tickers left to process.")
        return

    total_updated = 0
    total_skipped = 0

    # Step 2: For each ticker, fetch its full price history and update conflicts
    for i, ticker in enumerate(tickers, 1):
        # Get all conflicts for this ticker
        conflicts = fetch_conflicts_for_ticker(ticker)
        if not conflicts:
            continue

        print(f"\n[{i}/{len(tickers)}] {ticker}: {len(conflicts)} conflicts to process")

        # Determine the full date range we need
        vote_dates = [date.fromisoformat(c["vote_date"]) for c in conflicts if c.get("vote_date")]
        if not vote_dates:
            continue
        earliest = min(vote_dates) - timedelta(days=5)
        latest = min(max(vote_dates) + timedelta(days=40), date.today())

        # Check if we already have full cache coverage
        needs_fetch = False
        for vd in vote_dates:
            if find_closest_price(ticker, vd.isoformat()) is None or \
               find_closest_price(ticker, (vd + timedelta(days=30)).isoformat()) is None:
                needs_fetch = True
                break

        if needs_fetch:
            print(f"  Fetching prices ({earliest} to {latest})...")
            fetch_prices_for_ticker(ticker, earliest.isoformat(), latest.isoformat())

            # If still no data after fetch attempt, mark conflicts with 0 to skip them next run
            # (Use NULL → set to a sentinel? Better: leave NULL and they'll just stay skipped)
            if ticker not in price_cache or not price_cache.get(ticker):
                print(f"  No price data available for {ticker}, skipping all {len(conflicts)} conflicts")
                total_skipped += len(conflicts)
                continue
        else:
            print(f"  All prices cached — no API call needed")

        # Compute returns for all conflicts of this ticker
        updates = []
        skipped_here = 0
        for c in conflicts:
            vote_date = c["vote_date"]
            if not vote_date:
                skipped_here += 1
                continue
            after_date = (date.fromisoformat(vote_date) + timedelta(days=30)).isoformat()
            price_at_vote = find_closest_price(ticker, vote_date, direction=1)
            price_30d = find_closest_price(ticker, after_date, direction=-1)
            ret = compute_return(price_at_vote, price_30d)
            if ret is None:
                skipped_here += 1
                continue
            updates.append({"id": c["id"], "stock_return_30d": ret})

        # Push updates
        updated_here = 0
        for row in updates:
            try:
                db.table("conflicts").update({"stock_return_30d": row["stock_return_30d"]}).eq("id", row["id"]).execute()
                updated_here += 1
            except Exception as e:
                print(f"  Update error for {row['id']}: {e}")

        total_updated += updated_here
        total_skipped += skipped_here
        print(f"  Updated {updated_here}, skipped {skipped_here}")

        # Save cache every 10 tickers
        if i % 10 == 0:
            save_cache(price_cache)

        # Optional: respect a per-run limit on number of tickers processed
        if limit and i >= limit:
            print(f"\nHit ticker limit ({limit}). Stopping.")
            break

    save_cache(price_cache)
    print(f"\n=== Done. Updated {total_updated} conflicts, skipped {total_skipped} ===")
    print(f"API calls this run: {fmp_calls}")
    print(f"Price cache: {len(price_cache)} tickers in {CACHE_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, help="Only process conflicts for this ticker")
    parser.add_argument("--limit", type=int, help="Max tickers to process in this run")
    args = parser.parse_args()
    run(ticker_filter=args.ticker, limit=args.limit)
