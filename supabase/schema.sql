-- Capitol Conflicts — Supabase Schema
-- Run this in the Supabase SQL editor after creating your project.

-- ── MEMBERS ──────────────────────────────────────────────────────────────────
CREATE TABLE members (
  id          TEXT PRIMARY KEY,  -- bioguide_id from Congress.gov (e.g. A000001)
  first_name  TEXT,
  last_name   TEXT NOT NULL,
  full_name   TEXT NOT NULL,
  party       TEXT,              -- R, D, I
  state       TEXT,              -- two-letter code
  chamber     TEXT,              -- 'Senate' or 'House'
  district    TEXT,              -- House only
  photo_url   TEXT,
  active      BOOLEAN DEFAULT true,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── BILLS ────────────────────────────────────────────────────────────────────
CREATE TABLE bills (
  id              TEXT PRIMARY KEY,  -- e.g. 'hr1234-118'
  congress        INTEGER NOT NULL,
  bill_type       TEXT,              -- hr, s, hjres, sjres, hconres, sconres
  bill_number     INTEGER,
  title           TEXT NOT NULL,
  summary         TEXT,
  link            TEXT,              -- congress.gov URL
  introduced_date DATE,
  subjects        TEXT[],            -- subject tags from Congress.gov
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── VOTES (roll call events) ──────────────────────────────────────────────────
CREATE TABLE votes (
  id          TEXT PRIMARY KEY,  -- e.g. 'senate-118-2023-45'
  bill_id     TEXT REFERENCES bills(id) ON DELETE SET NULL,
  congress    INTEGER,
  session     INTEGER,
  chamber     TEXT NOT NULL,     -- 'Senate' or 'House'
  vote_number INTEGER,
  vote_date   DATE NOT NULL,
  question    TEXT,
  description TEXT,
  result      TEXT,              -- 'Passed', 'Failed', 'Agreed to', etc.
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── MEMBER VOTES (individual positions) ──────────────────────────────────────
CREATE TABLE member_votes (
  id         BIGSERIAL PRIMARY KEY,
  member_id  TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  vote_id    TEXT NOT NULL REFERENCES votes(id) ON DELETE CASCADE,
  position   TEXT NOT NULL,     -- 'Yes', 'No', 'Not Voting', 'Present'
  UNIQUE(member_id, vote_id)
);

-- ── STOCK DISCLOSURES (STOCK Act filings) ────────────────────────────────────
-- Note: STOCK Act enacted 2012. Pre-2012 data unavailable.
CREATE TABLE stock_disclosures (
  id                  BIGSERIAL PRIMARY KEY,
  member_id           TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  ticker              TEXT,
  company             TEXT,
  asset_description   TEXT,
  transaction_type    TEXT,       -- 'Purchase', 'Sale', 'Sale (Full)', 'Sale (Partial)', 'Exchange'
  transaction_date    DATE,
  amount_min          INTEGER,    -- lower bound of disclosed range in USD
  amount_max          INTEGER,    -- upper bound of disclosed range in USD
  filed_date          DATE,
  source              TEXT,       -- 'house' or 'senate' or 'capitaltrades'
  created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── COMMITTEE ASSIGNMENTS ─────────────────────────────────────────────────────
CREATE TABLE committee_assignments (
  id               BIGSERIAL PRIMARY KEY,
  member_id        TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  committee_name   TEXT NOT NULL,
  committee_code   TEXT,
  role             TEXT DEFAULT 'Member',   -- 'Member', 'Chair', 'Ranking Member'
  congress         INTEGER,
  chamber          TEXT,
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ── PAC DONATIONS ────────────────────────────────────────────────────────────
CREATE TABLE pac_donations (
  id              BIGSERIAL PRIMARY KEY,
  member_id       TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  pac_name        TEXT NOT NULL,
  industry        TEXT,
  amount          INTEGER,        -- in USD
  cycle           INTEGER,        -- election cycle year (e.g. 2022)
  donation_date   DATE,
  source          TEXT,           -- 'opensecrets' or 'fec'
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── CONFLICTS (computed) ──────────────────────────────────────────────────────
-- Populated by compute_conflicts.py — do not edit manually.
CREATE TABLE conflicts (
  id                        BIGSERIAL PRIMARY KEY,
  member_id                 TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  vote_id                   TEXT NOT NULL REFERENCES votes(id) ON DELETE CASCADE,
  disclosure_id             BIGINT REFERENCES stock_disclosures(id) ON DELETE CASCADE,
  score                     INTEGER NOT NULL CHECK (score BETWEEN 1 AND 10),
  days_between              INTEGER,    -- negative = trade before vote, positive = after
  trade_timing              TEXT,       -- 'before_vote' | 'after_vote'
  sector_match              BOOLEAN DEFAULT false,
  committee_match           BOOLEAN DEFAULT false,
  pac_match                 BOOLEAN DEFAULT false,
  stock_return_30d          NUMERIC,    -- % change in stock price from vote date to 30 days later
  notes                     TEXT,
  created_at                TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(member_id, vote_id, disclosure_id)
);

-- ── FLAT VIEW for frontend queries ───────────────────────────────────────────
-- Joins everything the conflicts feed needs into one query.
CREATE VIEW conflicts_view AS
SELECT
  c.id,
  c.score,
  c.days_between             AS days_diff,
  c.trade_timing,
  c.sector_match,
  c.committee_match,
  c.pac_match,
  c.stock_return_30d,
  -- member
  m.id                       AS member_id,
  m.full_name                AS member_name,
  m.party                    AS member_party,
  m.state                    AS member_state,
  m.chamber                  AS member_chamber,
  m.photo_url,
  -- vote
  v.id                       AS vote_id,
  v.vote_date,
  mv.position                AS vote_position,
  v.result                   AS vote_result,
  -- bill
  b.id                       AS bill_id,
  b.title                    AS bill_title,
  b.link                     AS bill_link,
  b.subjects                 AS bill_subjects,
  -- disclosure
  d.ticker,
  d.company,
  d.transaction_type,
  d.transaction_date,
  d.amount_min,
  d.amount_max
FROM conflicts c
JOIN members          m  ON m.id = c.member_id
JOIN votes            v  ON v.id = c.vote_id
JOIN member_votes     mv ON mv.member_id = c.member_id AND mv.vote_id = c.vote_id
LEFT JOIN bills       b  ON b.id = v.bill_id
LEFT JOIN stock_disclosures d ON d.id = c.disclosure_id;

-- ── POLITICIANS SUMMARY VIEW ─────────────────────────────────────────────────
-- One row per member showing total conflicts and severity.
CREATE OR REPLACE VIEW politicians_summary AS
SELECT
  m.id,
  m.full_name,
  m.party,
  m.state,
  m.chamber,
  m.photo_url,
  COUNT(c.id)                                                 AS conflict_count,
  COALESCE(MAX(c.score), 0)                                   AS max_score,
  ROUND(AVG(c.score)::numeric, 1)                             AS avg_score,
  COUNT(DISTINCT c.vote_id)                                   AS votes_with_conflicts,
  ROUND(AVG(c.stock_return_30d)::numeric, 2)                  AS avg_return_30d
FROM members m
LEFT JOIN conflicts c ON c.member_id = m.id
GROUP BY m.id, m.full_name, m.party, m.state, m.chamber, m.photo_url;

-- ── BILLS SUMMARY VIEW ───────────────────────────────────────────────────────
-- One row per bill showing total conflicts and severity.
CREATE OR REPLACE VIEW bills_summary AS
SELECT
  b.id,
  b.title,
  b.link,
  b.introduced_date,
  b.subjects,
  b.congress,
  b.bill_type,
  b.bill_number,
  COUNT(c.id)                                                 AS conflict_count,
  COALESCE(MAX(c.score), 0)                                   AS max_score,
  COUNT(DISTINCT c.member_id)                                 AS members_flagged,
  MAX(v.vote_date)                                            AS latest_vote_date
FROM bills b
LEFT JOIN votes v     ON v.bill_id = b.id
LEFT JOIN conflicts c ON c.vote_id = v.id
GROUP BY b.id, b.title, b.link, b.introduced_date, b.subjects, b.congress, b.bill_type, b.bill_number;

-- ── INDEXES ───────────────────────────────────────────────────────────────────
CREATE INDEX idx_member_votes_member   ON member_votes(member_id);
CREATE INDEX idx_member_votes_vote     ON member_votes(vote_id);
CREATE INDEX idx_disclosures_member    ON stock_disclosures(member_id);
CREATE INDEX idx_disclosures_ticker    ON stock_disclosures(ticker);
CREATE INDEX idx_conflicts_member      ON conflicts(member_id);
CREATE INDEX idx_conflicts_vote        ON conflicts(vote_id);
CREATE INDEX idx_conflicts_score       ON conflicts(score DESC);
CREATE INDEX idx_votes_date            ON votes(vote_date DESC);

-- ── ROW LEVEL SECURITY ────────────────────────────────────────────────────────
-- All data is public (read-only for anon users).
ALTER TABLE members              ENABLE ROW LEVEL SECURITY;
ALTER TABLE bills                ENABLE ROW LEVEL SECURITY;
ALTER TABLE votes                ENABLE ROW LEVEL SECURITY;
ALTER TABLE member_votes         ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_disclosures    ENABLE ROW LEVEL SECURITY;
ALTER TABLE committee_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE pac_donations        ENABLE ROW LEVEL SECURITY;
ALTER TABLE conflicts            ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON members              FOR SELECT USING (true);
CREATE POLICY "Public read" ON bills                FOR SELECT USING (true);
CREATE POLICY "Public read" ON votes                FOR SELECT USING (true);
CREATE POLICY "Public read" ON member_votes         FOR SELECT USING (true);
CREATE POLICY "Public read" ON stock_disclosures    FOR SELECT USING (true);
CREATE POLICY "Public read" ON committee_assignments FOR SELECT USING (true);
CREATE POLICY "Public read" ON pac_donations        FOR SELECT USING (true);
CREATE POLICY "Public read" ON conflicts            FOR SELECT USING (true);
