"""
diagnose.py
Quick checks to find why compute_conflicts.py finds nothing.
Run: python diagnose.py
"""

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

print("=" * 60)

# Quick reality check: does a specific Congress 113 vote exist? Does it have member_votes?
test_id = "senate-113-1-291"
test_vote = db.table("votes").select("id").eq("id", test_id).limit(1).execute()
print(f"Vote '{test_id}' exists in votes table: {len(test_vote.data) > 0}")
test_mv = db.table("member_votes").select("id, member_id").eq("vote_id", test_id).limit(5).execute()
print(f"member_votes for '{test_id}': {len(test_mv.data)} rows")
if test_mv.data:
    print(f"  Sample: {test_mv.data[0]}")
print()

# Actual row counts (not relying on count="exact")
all_votes = db.table("votes").select("id").limit(5000).execute()
print(f"Votes in DB (up to 5000): {len(all_votes.data)}")
all_mv = db.table("member_votes").select("id").limit(5000).execute()
print(f"member_votes in DB (up to 5000): {len(all_mv.data)}")
print()

# 0a. What do senators actually look like in the members table?
print("Sample senators in members table:")
senators = db.table("members").select("id, first_name, last_name, state, chamber").eq("chamber", "Senate").limit(10).execute()
for s in senators.data:
    print(f"  {s['id']} | last='{s['last_name']}' | state='{s['state']}' | chamber='{s['chamber']}'")
print()

# 0b. How many rows are in the votes table?
votes_count = db.table("votes").select("*", count="exact").execute()
print(f"Total rows in votes table: {votes_count.count}")
member_votes_count = db.table("member_votes").select("*", count="exact").execute()
print(f"Total rows in member_votes table: {member_votes_count.count}")
print()

# 0. What values are actually in the chamber field?
print("Chamber field distribution in members table:")
result0 = db.table("members").select("chamber").execute()
from collections import Counter
chamber_counts = Counter(r["chamber"] for r in result0.data)
for val, count in chamber_counts.most_common():
    print(f"  '{val}': {count}")
print()

# 1. How many disclosures do we have, and are they linked to members?
result = db.table("stock_disclosures").select("member_id, transaction_date").execute()
disclosures = result.data
print(f"Total disclosures: {len(disclosures)}")

linked = [d for d in disclosures if d["member_id"]]
print(f"Linked to a member_id: {len(linked)}")
print(f"Unlinked (no member_id): {len(disclosures) - len(linked)}")

members_with_disclosures = set(d["member_id"] for d in linked)
print(f"Unique members with disclosures: {len(members_with_disclosures)}")

# Date range of disclosures
dates = sorted([d["transaction_date"] for d in linked if d["transaction_date"]])
if dates:
    print(f"Disclosure date range: {dates[0]} → {dates[-1]}")

print()

# 2. How many member_votes do we have?
result2 = db.table("member_votes").select("member_id", count="exact").execute()
print(f"Total member_vote rows: {result2.count}")

members_with_votes_result = db.table("member_votes").select("member_id").execute()
members_with_votes = set(r["member_id"] for r in members_with_votes_result.data)
print(f"Unique members with votes (may be capped at 1000): {len(members_with_votes)}")

print()

# 3. Overlap
overlap = members_with_disclosures & members_with_votes
print(f"Members with BOTH disclosures AND votes: {len(overlap)}")

if not overlap:
    print(">>> PROBLEM: No member has both disclosures and votes. Member IDs aren't matching.")
    print()
    print("Sample member IDs from disclosures:", list(members_with_disclosures)[:5])
    print("Sample member IDs from votes:", list(members_with_votes)[:5])
else:
    sample_id = list(overlap)[0]
    print(f"Sample overlapping member: {sample_id}")

    # 4. Test the Supabase join for that member
    print()
    print(f"Testing join for {sample_id}...")
    disc_result = db.table("stock_disclosures").select("*").eq("member_id", sample_id).limit(3).execute()
    print(f"  Disclosures: {len(disc_result.data)}")
    if disc_result.data:
        print(f"  Sample disclosure date: {disc_result.data[0].get('transaction_date')}")
        print(f"  Sample ticker: {disc_result.data[0].get('ticker')}")

    vote_result = db.table("member_votes").select("*, votes(*)").eq("member_id", sample_id).limit(3).execute()
    print(f"  Vote rows returned: {len(vote_result.data)}")
    if vote_result.data:
        mv = vote_result.data[0]
        vote = mv.get("votes")
        print(f"  'votes' key present: {vote is not None}")
        if vote:
            print(f"  Sample vote_date: {vote.get('vote_date')}")
        else:
            print("  >>> PROBLEM: 'votes' key is None — the join is failing")

    # 5. Date overlap check
    print()
    print("Checking date overlap for this member...")
    all_disc = db.table("stock_disclosures").select("transaction_date").eq("member_id", sample_id).execute()
    all_votes = db.table("member_votes").select("votes(vote_date)").eq("member_id", sample_id).execute()

    disc_dates = sorted([d["transaction_date"] for d in all_disc.data if d["transaction_date"]])
    vote_dates = sorted([v["votes"]["vote_date"] for v in all_votes.data if v.get("votes") and v["votes"].get("vote_date")])

    if disc_dates:
        print(f"  Disclosure dates: {disc_dates[0]} → {disc_dates[-1]} ({len(disc_dates)} total)")
    if vote_dates:
        print(f"  Vote dates: {vote_dates[0]} → {vote_dates[-1]} ({len(vote_dates)} total)")

    if disc_dates and vote_dates:
        from datetime import date
        last_disc = date.fromisoformat(disc_dates[-1])
        first_vote = date.fromisoformat(vote_dates[0])
        gap = (first_vote - last_disc).days
        print(f"  Gap between last disclosure and first vote: {gap} days")
        if gap > 180:
            print(f"  >>> PROBLEM: Gap of {gap} days exceeds 180-day window — no overlap possible")
        else:
            print(f"  Gap is within 180 days — dates should overlap fine")

print()
print("=" * 60)
