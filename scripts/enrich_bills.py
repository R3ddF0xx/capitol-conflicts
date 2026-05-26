"""
enrich_bills.py
Parses bill references out of vote `question` text, fetches full bill data
from Congress.gov API, populates the `bills` table, and links each vote
back to its bill via `votes.bill_id`.

Vote questions look like:
  "On the Joint Resolution S.J.Res. 82"
  "On Passage of the Bill H.R. 4321"
  "On the Cloture Motion PN615-2"     <-- nomination, skipped
  "On the Motion to Proceed S. 1234"

Bill ID format in our DB: '{type}{number}-{congress}' (e.g. 'hr1234-118')

Run: python enrich_bills.py
     python enrich_bills.py --limit 100
     python enrich_bills.py --congress 118
"""

import os
import re
import time
import argparse
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
CONGRESS_KEY = os.environ["CONGRESS_API_KEY"]

CONGRESS_BASE = "https://api.congress.gov/v3"

db = create_client(SUPABASE_URL, SUPABASE_KEY)

# Maps text form → Congress.gov API form
BILL_TYPE_MAP = {
    "S": "s",
    "H.R.": "hr", "HR": "hr",
    "S.J.RES.": "sjres", "SJRES": "sjres",
    "H.J.RES.": "hjres", "HJRES": "hjres",
    "S.CON.RES.": "sconres", "SCONRES": "sconres",
    "H.CON.RES.": "hconres", "HCONRES": "hconres",
    "S.RES.": "sres", "SRES": "sres",
    "H.RES.": "hres", "HRES": "hres",
}

# Regex catches: H.R. 1234, S. 567, S.J.Res. 82, etc.
# Captures (type, number)
BILL_REF_RE = re.compile(
    r"\b(H\.R\.|S\.J\.Res\.|H\.J\.Res\.|S\.Con\.Res\.|H\.Con\.Res\.|S\.Res\.|H\.Res\.|S\.)\s*(\d+)",
    re.IGNORECASE
)


def parse_bill_ref(question):
    """Extract (bill_type_api, bill_number) from a vote question, or None."""
    if not question:
        return None
    # Skip nominations, treaties, etc.
    if "PN" in question and re.search(r"\bPN\d+", question):
        # Only skip if it's purely a nomination — sometimes nominations have bill refs too
        # but it's rare; safer to check for an actual bill ref first
        pass

    m = BILL_REF_RE.search(question)
    if not m:
        return None
    raw_type = m.group(1).upper()
    number = m.group(2)
    api_type = BILL_TYPE_MAP.get(raw_type)
    if not api_type:
        return None
    return api_type, number


def parse_congress_from_vote_id(vote_id):
    """vote_id format: 'senate-119-1-658' → 119"""
    parts = vote_id.split("-")
    if len(parts) >= 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return None


def fetch_bill(congress, bill_type, bill_number):
    """Fetch bill details from Congress.gov."""
    url = f"{CONGRESS_BASE}/bill/{congress}/{bill_type}/{bill_number}"
    try:
        r = requests.get(url, params={"api_key": CONGRESS_KEY, "format": "json"}, timeout=20)
        r.raise_for_status()
        return r.json().get("bill", {})
    except Exception as e:
        return None


def fetch_bill_subjects(congress, bill_type, bill_number):
    """Subjects come from a separate endpoint."""
    url = f"{CONGRESS_BASE}/bill/{congress}/{bill_type}/{bill_number}/subjects"
    try:
        r = requests.get(url, params={"api_key": CONGRESS_KEY, "format": "json"}, timeout=20)
        r.raise_for_status()
        data = r.json()
        subjects = data.get("subjects", {}).get("legislativeSubjects", [])
        return [s.get("name") for s in subjects if s.get("name")]
    except Exception:
        return []


def get_unlinked_votes(limit=None, congress=None):
    """Pull all votes with no bill_id, paginated."""
    all_votes = []
    page_size = 1000
    offset = 0
    while True:
        q = db.table("votes").select("id, question, congress").is_("bill_id", "null")
        if congress:
            q = q.eq("congress", congress)
        q = q.range(offset, offset + page_size - 1)
        res = q.execute()
        rows = res.data or []
        all_votes.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
        if limit and len(all_votes) >= limit:
            return all_votes[:limit]
    return all_votes


def run(limit=None, congress_filter=None):
    votes = get_unlinked_votes(limit=limit, congress=congress_filter)
    print(f"Found {len(votes)} unlinked votes to scan")

    # Step 1: Parse all bill refs from votes
    vote_to_billkey = {}    # vote_id → (congress, type, number)
    bill_keys_to_fetch = set()

    parseable = 0
    for v in votes:
        ref = parse_bill_ref(v.get("question"))
        if not ref:
            continue
        bill_type, number = ref
        cg = v.get("congress") or parse_congress_from_vote_id(v["id"])
        if not cg:
            continue
        key = (cg, bill_type, number)
        vote_to_billkey[v["id"]] = key
        bill_keys_to_fetch.add(key)
        parseable += 1

    print(f"  {parseable} votes reference a bill")
    print(f"  {len(bill_keys_to_fetch)} unique bills to fetch from Congress.gov")

    if not bill_keys_to_fetch:
        print("Nothing to do.")
        return

    # Step 2: Get list of bills we already have so we don't refetch
    existing_ids = set()
    page_size = 1000
    offset = 0
    while True:
        res = db.table("bills").select("id").range(offset, offset + page_size - 1).execute()
        rows = res.data or []
        for r in rows:
            existing_ids.add(r["id"])
        if len(rows) < page_size:
            break
        offset += page_size

    print(f"  {len(existing_ids)} bills already in DB")

    # Step 3: Fetch missing bills from Congress.gov
    bills_to_insert = []
    fetched = 0
    failed = 0

    for i, (cg, btype, num) in enumerate(sorted(bill_keys_to_fetch), 1):
        bill_id = f"{btype}{num}-{cg}"
        if bill_id in existing_ids:
            continue

        bill_data = fetch_bill(cg, btype, num)
        time.sleep(0.2)
        if not bill_data:
            failed += 1
            if i % 25 == 0:
                print(f"  [{i}/{len(bill_keys_to_fetch)}] {bill_id}: fetch failed")
            continue

        # Subjects come separately
        subjects = fetch_bill_subjects(cg, btype, num)
        time.sleep(0.2)

        # Congress.gov bill response shape
        title = bill_data.get("title") or "Untitled"
        introduced = bill_data.get("introducedDate")
        summary_obj = bill_data.get("summary") or bill_data.get("summaries")
        summary_text = None
        if isinstance(summary_obj, dict):
            summary_text = summary_obj.get("text")
        elif isinstance(summary_obj, list) and summary_obj:
            summary_text = summary_obj[0].get("text") if isinstance(summary_obj[0], dict) else None

        # Congress.gov public URL for the bill
        public_link = f"https://www.congress.gov/bill/{cg}th-congress/{_url_type(btype)}/{num}"

        bills_to_insert.append({
            "id": bill_id,
            "congress": cg,
            "bill_type": btype,
            "bill_number": int(num),
            "title": title,
            "summary": summary_text,
            "link": public_link,
            "introduced_date": introduced,
            "subjects": subjects or None,
        })

        fetched += 1
        existing_ids.add(bill_id)

        if i % 25 == 0:
            print(f"  [{i}/{len(bill_keys_to_fetch)}] fetched {fetched}, failed {failed}")

        # Flush every 100 to keep memory down and provide progress
        if len(bills_to_insert) >= 100:
            _insert_bills(bills_to_insert)
            bills_to_insert.clear()

    if bills_to_insert:
        _insert_bills(bills_to_insert)

    print(f"\nFetched {fetched} new bills, {failed} failed")

    # Step 4: Update votes with bill_id links
    print("\nLinking votes to bills...")
    updated = 0
    for vote_id, (cg, btype, num) in vote_to_billkey.items():
        bill_id = f"{btype}{num}-{cg}"
        if bill_id not in existing_ids:
            continue  # bill fetch failed, skip
        try:
            db.table("votes").update({"bill_id": bill_id}).eq("id", vote_id).execute()
            updated += 1
            if updated % 100 == 0:
                print(f"  Linked {updated} votes")
        except Exception as e:
            print(f"  Link error for {vote_id}: {e}")

    print(f"\n=== Done. Linked {updated} votes to bills ===")


def _insert_bills(bills):
    try:
        db.table("bills").upsert(bills, on_conflict="id").execute()
        print(f"  Inserted/upserted {len(bills)} bills")
    except Exception as e:
        print(f"  Bulk insert error: {e}")


def _url_type(api_type):
    """Map our internal type to Congress.gov URL slug."""
    return {
        "hr": "house-bill", "s": "senate-bill",
        "hjres": "house-joint-resolution", "sjres": "senate-joint-resolution",
        "hconres": "house-concurrent-resolution", "sconres": "senate-concurrent-resolution",
        "hres": "house-resolution", "sres": "senate-resolution",
    }.get(api_type, api_type)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Only scan first N unlinked votes")
    parser.add_argument("--congress", type=int, help="Only process this congress number")
    args = parser.parse_args()
    run(limit=args.limit, congress_filter=args.congress)
