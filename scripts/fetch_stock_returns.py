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
        # 8 calls/min on free tier = stay under by sleeping ~8s
        # Actually that's too slow; use ~0.5s and back off on 429
        time.sleep(0.5)
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


def run(ticker_filter=None, limit=None):
    # Step 1: Get conflicts that don't have a return yet, pre-joined with
    # disclosures and votes so we can filter out junk tickers at the DB level.
    # Uses conflicts_view which already joins everything we need.
    query = db.table("conflicts_view") \
        .select("id, member_id, vote_id, ticker, vote_date, transaction_type") \
        .is_("stock_return_30d", "null") \
        .not_.in_("ticker", ["--", "N/A", "NA", "", "NONE"]) \
        .limit(limit or 5000)

    if ticker_filter:
        query = query.eq("ticker", ticker_filter.upper())

    result = query.execute()
    conflicts = result.data
    print(f"Found {len(conflicts)} conflicts with real tickers and no return yet")

    if not conflicts:
        print("All done — no conflicts left to process, or all remaining have junk tickers.")
        return

    # Step 2: Figure out unique (ticker, vote_date) pairs we need prices for
    ticker_dates = {}  # ticker -> set of vote_date strings
    for c in conflicts:
        ticker = c["ticker"].upper()
        vote_date = c["vote_date"]
        if not ticker or not vote_date:
            continue
        if ticker not in ticker_dates:
            ticker_dates[ticker] = set()
        ticker_dates[ticker].add(vote_date)

    print(f"Need prices for {len(ticker_dates)} unique tickers")

    # Step 3: Fetch prices — one API call per ticker covers all its dates
    tickers_fetched = 0
    for ticker, dates in ticker_dates.items():
        # Check if we already have cached prices for all needed dates
        all_cached = True
        for vd in dates:
            vote_d = date.fromisoformat(vd)
            after_d = vote_d + timedelta(days=30)
            if find_closest_price(ticker, vd) is None or find_closest_price(ticker, after_d.isoformat()) is None:
                all_cached = False
                break

        if all_cached:
            continue

        # Need to fetch — find the widest date range needed
        all_dates = [date.fromisoformat(d) for d in dates]
        earliest = min(all_dates) - timedelta(days=5)  # buffer for weekends
        latest = max(all_dates) + timedelta(days=40)    # 30 days + buffer

        # Don't fetch future dates
        today = date.today()
        if latest > today:
            latest = today

        print(f"  Fetching {ticker} prices ({earliest} to {latest})...")
        fetch_prices_for_ticker(ticker, earliest.isoformat(), latest.isoformat())
        tickers_fetched += 1

        # Save cache every 20 tickers
        if tickers_fetched % 20 == 0:
            save_cache(price_cache)
            print(f"  Cache saved ({len(price_cache)} tickers)")

    # Step 4: Compute returns and update conflicts
    updates = []
    skipped = 0
    for c in conflicts:
        ticker = c["ticker"].upper()
        vote_date = c["vote_date"]
        if not ticker or not vote_date:
            skipped += 1
            continue

        after_date = (date.fromisoformat(vote_date) + timedelta(days=30)).isoformat()

        price_at_vote = find_closest_price(ticker, vote_date, direction=1)
        price_30d = find_closest_price(ticker, after_date, direction=-1)

        ret = compute_return(price_at_vote, price_30d)
        if ret is None:
            skipped += 1
            continue

        updates.append({"id": c["id"], "stock_return_30d": ret})

    print(f"Computed {len(updates)} returns, skipped {skipped} (no price data)")

    # Batch update in chunks
    updated = 0
    for i in range(0, len(updates), 100):
        batch = updates[i:i+100]
        for row in batch:
            try:
                db.table("conflicts").update({"stock_return_30d": row["stock_return_30d"]}).eq("id", row["id"]).execute()
                updated += 1
            except Exception as e:
                print(f"  Update error for conflict {row['id']}: {e}")

    save_cache(price_cache)
    print(f"\nDone. Updated {updated} conflicts. FMP API calls: {fmp_calls}")
    print(f"Price cache: {len(price_cache)} tickers saved to {CACHE_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, help="Only process conflicts for this ticker")
    parser.add_argument("--limit", type=int, help="Max conflicts to process (default 5000)")
    args = parser.parse_args()
    run(ticker_filter=args.ticker, limit=args.limit)
