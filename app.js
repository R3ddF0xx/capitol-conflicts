const SUPABASE_URL = 'https://roinpohivmzoepeohjcp.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJvaW5wb2hpdm16b2VwZW9oamNwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzkwMzc3NjEsImV4cCI6MjA5NDYxMzc2MX0.fXGYDzbWVGnWnJHmuMwC5dymSjmQSZGjxXtskYCwy64';

const DEMO_MODE = SUPABASE_URL === 'YOUR_SUPABASE_URL';

let db = null;
if (!DEMO_MODE) {
  db = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
}

// ── DEMO DATA ────────────────────────────────────────────────────────────────

const DEMO_CONFLICTS = [
  {
    id: 1,
    score: 9,
    member: { id: 'demo1', name: 'Sen. Jane Hartwell', party: 'R', state: 'TX', chamber: 'Senate', photo: null },
    bill: { id: 'demo-bill-1', title: 'Pharmaceutical Pricing Transparency Act', link: 'https://congress.gov', subjects: ['Health', 'Pharmaceuticals'] },
    vote: { date: '2023-09-14', position: 'No', result: 'Failed' },
    stock: { ticker: 'PFE', company: 'Pfizer Inc.', transaction_type: 'Purchase', transaction_date: '2023-08-22', amount_min: 50000, amount_max: 100000 },
    days_diff: -23,
    trade_timing: 'before_vote',
    committee: 'Senate Health, Education, Labor & Pensions',
    pac_match: 'PhRMA PAC — $18,500 (2022 cycle)'
  },
  {
    id: 2,
    score: 8,
    member: { id: 'demo2', name: 'Rep. Marcus Cole', party: 'D', state: 'CA', chamber: 'House', photo: null },
    bill: { id: 'demo-bill-2', title: 'Clean Energy Investment Act of 2023', link: 'https://congress.gov', subjects: ['Energy', 'Environment'] },
    vote: { date: '2023-11-02', position: 'Yes', result: 'Passed' },
    stock: { ticker: 'ENPH', company: 'Enphase Energy', transaction_type: 'Purchase', transaction_date: '2023-10-18', amount_min: 15000, amount_max: 50000 },
    days_diff: -15,
    trade_timing: 'before_vote',
    committee: 'House Energy & Commerce',
    pac_match: null
  },
  {
    id: 3,
    score: 7,
    member: { id: 'demo3', name: 'Sen. Robert Finch', party: 'R', state: 'OK', chamber: 'Senate', photo: null },
    bill: { id: 'demo-bill-3', title: 'Defense Appropriations Act FY2024', link: 'https://congress.gov', subjects: ['Defense', 'Military'] },
    vote: { date: '2023-12-07', position: 'Yes', result: 'Passed' },
    stock: { ticker: 'LMT', company: 'Lockheed Martin', transaction_type: 'Purchase', transaction_date: '2023-11-10', amount_min: 100000, amount_max: 250000 },
    days_diff: -27,
    trade_timing: 'before_vote',
    committee: 'Senate Armed Services',
    pac_match: 'Lockheed Martin PAC — $10,000 (2022 cycle)'
  },
  {
    id: 4,
    score: 6,
    member: { id: 'demo4', name: 'Rep. Linda Marsh', party: 'D', state: 'NY', chamber: 'House', photo: null },
    bill: { id: 'demo-bill-4', title: 'Banking Deregulation and Modernization Act', link: 'https://congress.gov', subjects: ['Finance', 'Banking'] },
    vote: { date: '2022-06-15', position: 'Yes', result: 'Passed' },
    stock: { ticker: 'JPM', company: 'JPMorgan Chase', transaction_type: 'Sale', transaction_date: '2022-07-02', amount_min: 50000, amount_max: 100000 },
    days_diff: 17,
    trade_timing: 'after_vote',
    committee: 'House Financial Services',
    pac_match: 'JPMorgan Chase PAC — $7,500 (2022 cycle)'
  },
  {
    id: 5,
    score: 4,
    member: { id: 'demo5', name: 'Sen. Carol Webb', party: 'I', state: 'VT', chamber: 'Senate', photo: null },
    bill: { id: 'demo-bill-5', title: 'Agricultural Subsidy Reform Act', link: 'https://congress.gov', subjects: ['Agriculture', 'Food'] },
    vote: { date: '2021-03-22', position: 'No', result: 'Passed' },
    stock: { ticker: 'DE', company: 'Deere & Company', transaction_type: 'Purchase', transaction_date: '2021-01-15', amount_min: 15000, amount_max: 50000 },
    days_diff: -66,
    trade_timing: 'before_vote',
    committee: null,
    pac_match: null
  }
];

const DEMO_STATS = {
  total_conflicts: 1842,
  members_flagged: 287,
  bills_covered: 14203,
  high_score_count: 312
};

// ── SHARED UTILITIES ─────────────────────────────────────────────────────────

function formatMoney(min, max) {
  const fmt = n => n >= 1000000 ? `$${(n/1000000).toFixed(1)}M` : n >= 1000 ? `$${(n/1000).toFixed(0)}K` : `$${n}`;
  return `${fmt(min)} – ${fmt(max)}`;
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

function scoreClass(score) {
  if (score >= 7) return 'score-high';
  if (score >= 4) return 'score-medium';
  return 'score-low';
}

function partyTag(party) {
  const map = { R: 'tag-r', D: 'tag-d', I: 'tag-i' };
  const labels = { R: 'Republican', D: 'Democrat', I: 'Independent' };
  return `<span class="tag ${map[party] || 'tag-i'}">${labels[party] || party || '?'}</span>`;
}

function chamberTag(chamber) {
  const cls = chamber === 'Senate' ? 'tag-senate' : 'tag-house';
  return `<span class="tag ${cls}">${chamber || '?'}</span>`;
}

function voteTag(position) {
  const map = { Yes: 'vote-yes', No: 'vote-no', 'Not Voting': 'vote-abstain', Present: 'vote-abstain' };
  return `<span class="vote-badge ${map[position] || 'vote-abstain'}">${position || '—'}</span>`;
}

function timingText(days) {
  if (days === 0) return 'same day as vote';
  const abs = Math.abs(days);
  return days < 0 ? `${abs} days before vote` : `${abs} days after vote`;
}

function memberInitials(name) {
  return (name || '?').replace(/^(Sen\.|Rep\.)\s+/, '').split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase();
}

// ── VIEW ROW NORMALIZER ───────────────────────────────────────────────────────
// Maps flat conflicts_view columns to the nested shape renderConflictCard expects.

function normalizeViewRow(row) {
  return {
    id: row.id,
    score: row.score,
    days_diff: row.days_diff,
    trade_timing: row.trade_timing,
    member: {
      id: row.member_id,
      name: row.member_name,
      party: row.member_party,
      state: row.member_state,
      chamber: row.member_chamber,
      photo: row.photo_url,
    },
    bill: {
      id: row.bill_id,
      title: row.bill_title || 'Procedural Vote',
      link: row.bill_link,
      subjects: row.bill_subjects || [],
    },
    vote: {
      id: row.vote_id,
      date: row.vote_date,
      position: row.vote_position,
      result: row.vote_result,
    },
    stock: {
      ticker: row.ticker,
      company: row.company,
      transaction_type: row.transaction_type,
      transaction_date: row.transaction_date,
      amount_min: row.amount_min,
      amount_max: row.amount_max,
    },
    committee: row.committee_match ? 'Sits on relevant committee' : null,
    pac_match: row.pac_match ? 'PAC contribution from related industry' : null,
  };
}

// ── CONFLICT CARD RENDERER ───────────────────────────────────────────────────

function renderConflictCard(c) {
  const cls = scoreClass(c.score);
  const timing = timingText(c.days_diff);
  const timingCls = Math.abs(c.days_diff) <= 30 ? 'highlight' : 'highlight-amber';
  const avatarContent = c.member.photo
    ? `<img src="${c.member.photo}" alt="${c.member.name}">`
    : memberInitials(c.member.name);

  const pacLine = c.pac_match
    ? `<span>PAC: ${c.pac_match}</span>`
    : '';

  const committeeLine = c.committee
    ? `<span>Committee: ${c.committee}</span>`
    : '';

  return `
    <div class="conflict-card ${cls}" onclick="window.location.href='politician.html?id=${c.member.id}'" style="cursor:pointer">
      <div class="card-top">
        <div class="member-info">
          <div class="member-avatar">${avatarContent}</div>
          <div>
            <div class="member-name">${c.member.name}</div>
            <div class="member-meta">
              ${partyTag(c.member.party)}
              ${chamberTag(c.member.chamber)}
              <span class="tag tag-senate">${c.member.state}</span>
            </div>
          </div>
        </div>
        <div class="score-badge">
          <div class="score-circle">${c.score}</div>
          <span class="score-label">Conflict Score</span>
        </div>
      </div>

      <div class="card-body">
        <div>
          <div class="card-section-label">Bill Voted On</div>
          <div class="card-section-value">
            <a href="bill.html?id=${c.bill.id}" onclick="event.stopPropagation()">
              ${c.bill.title}
            </a>
            <br><small style="color:var(--muted)">${formatDate(c.vote.date)} &nbsp;·&nbsp; ${voteTag(c.vote.position)}</small>
          </div>
        </div>
        <div>
          <div class="card-section-label">Stock Position Held</div>
          <div class="card-section-value">
            <strong>${c.stock.ticker || '—'}</strong>${c.stock.company ? ' — ' + c.stock.company : ''}
            <br><small style="color:var(--muted)">${c.stock.transaction_type || ''} &nbsp;·&nbsp; ${c.stock.amount_min ? formatMoney(c.stock.amount_min, c.stock.amount_max) : '—'} &nbsp;·&nbsp; ${formatDate(c.stock.transaction_date)}</small>
          </div>
        </div>
      </div>

      <div class="card-footer">
        <span class="${timingCls}">Traded ${timing}</span>
        ${committeeLine}
        ${pacLine}
      </div>
    </div>
  `;
}

// ── CONFLICTS FEED (index.html) ───────────────────────────────────────────────

async function loadConflicts(filters = {}) {
  const feed = document.getElementById('conflicts-feed');
  if (!feed) return;

  feed.innerHTML = '<div class="loading"><span class="spinner"></span>Loading conflicts...</div>';

  let conflicts;

  if (DEMO_MODE) {
    conflicts = DEMO_CONFLICTS;
    if (filters.chamber) conflicts = conflicts.filter(c => c.member.chamber === filters.chamber);
    if (filters.party) conflicts = conflicts.filter(c => c.member.party === filters.party);
    if (filters.state) conflicts = conflicts.filter(c => c.member.state === filters.state);
    if (filters.score === 'high') conflicts = conflicts.filter(c => c.score >= 7);
    if (filters.score === 'medium') conflicts = conflicts.filter(c => c.score >= 4 && c.score < 7);
    if (filters.score === 'low') conflicts = conflicts.filter(c => c.score < 4);
  } else {
    let query = db
      .from('conflicts_view')
      .select('*')
      .order('score', { ascending: false })
      .limit(50);

    if (filters.chamber) query = query.eq('member_chamber', filters.chamber);
    if (filters.party) query = query.eq('member_party', filters.party);
    if (filters.state) query = query.eq('member_state', filters.state);
    if (filters.score === 'high') query = query.gte('score', 7);
    if (filters.score === 'medium') { query = query.gte('score', 4); query = query.lt('score', 7); }
    if (filters.score === 'low') query = query.lt('score', 4);
    if (filters.dateFrom) query = query.gte('vote_date', filters.dateFrom);
    if (filters.dateTo) query = query.lte('vote_date', filters.dateTo);

    const { data, error } = await query;
    if (error) {
      feed.innerHTML = `<div class="empty-state"><h3>Error loading data</h3><p>${error.message}</p></div>`;
      return;
    }
    conflicts = (data || []).map(normalizeViewRow);
  }

  if (!conflicts || conflicts.length === 0) {
    feed.innerHTML = '<div class="empty-state"><h3>No conflicts found</h3><p>Try adjusting your filters, or run compute_conflicts.py to populate data.</p></div>';
    return;
  }

  feed.innerHTML = conflicts.map(renderConflictCard).join('');
}

function getFilters() {
  return {
    chamber: document.getElementById('filter-chamber')?.value || '',
    party: document.getElementById('filter-party')?.value || '',
    state: document.getElementById('filter-state')?.value || '',
    score: document.getElementById('filter-score')?.value || '',
    dateFrom: document.getElementById('filter-date-from')?.value || '',
    dateTo: document.getElementById('filter-date-to')?.value || ''
  };
}

// ── STATS (index.html) ────────────────────────────────────────────────────────

async function loadStats() {
  const el = id => document.getElementById(id);

  if (DEMO_MODE) {
    const s = DEMO_STATS;
    if (el('stat-conflicts')) el('stat-conflicts').textContent = s.total_conflicts.toLocaleString();
    if (el('stat-members')) el('stat-members').textContent = s.members_flagged.toLocaleString();
    if (el('stat-bills')) el('stat-bills').textContent = s.bills_covered.toLocaleString();
    if (el('stat-high')) el('stat-high').textContent = s.high_score_count.toLocaleString();
    return;
  }

  const [
    { count: totalConflicts },
    { count: highScore },
    { count: totalVotes },
    { data: memberIds },
  ] = await Promise.all([
    db.from('conflicts').select('*', { count: 'exact', head: true }),
    db.from('conflicts').select('*', { count: 'exact', head: true }).gte('score', 7),
    db.from('votes').select('*', { count: 'exact', head: true }),
    db.from('conflicts').select('member_id'),
  ]);

  const membersCount = memberIds ? new Set(memberIds.map(r => r.member_id)).size : 0;

  if (el('stat-conflicts')) el('stat-conflicts').textContent = (totalConflicts || 0).toLocaleString();
  if (el('stat-members')) el('stat-members').textContent = membersCount.toLocaleString();
  if (el('stat-bills')) el('stat-bills').textContent = (totalVotes || 0).toLocaleString();
  if (el('stat-high')) el('stat-high').textContent = (highScore || 0).toLocaleString();
}

// ── POLITICIAN PAGE (politician.html) ─────────────────────────────────────────

async function loadPolitician() {
  const params = new URLSearchParams(window.location.search);
  const memberId = params.get('id');
  if (!memberId) return;

  if (DEMO_MODE) {
    const demo = DEMO_CONFLICTS.find(c => c.member.id === memberId);
    if (!demo) return;
    const m = demo.member;
    document.title = `${m.name} — Capitol Conflicts`;
    const photoEl = document.getElementById('politician-photo');
    if (photoEl) photoEl.innerHTML = m.photo ? `<img src="${m.photo}" alt="${m.name}">` : memberInitials(m.name);
    const nameEl = document.getElementById('politician-name');
    if (nameEl) nameEl.textContent = m.name;
    const tagsEl = document.getElementById('politician-tags');
    if (tagsEl) tagsEl.innerHTML = `${partyTag(m.party)} ${chamberTag(m.chamber)} <span class="tag tag-senate">${m.state}</span>`;
    const memberConflicts = DEMO_CONFLICTS.filter(c => c.member.id === memberId);
    const tableEl = document.getElementById('conflicts-table-body');
    if (tableEl) {
      tableEl.innerHTML = memberConflicts.map(c => `
        <tr>
          <td>${formatDate(c.vote.date)}</td>
          <td><a href="bill.html?id=${c.bill.id}">${c.bill.title}</a></td>
          <td>${voteTag(c.vote.position)}</td>
          <td><strong>${c.stock.ticker}</strong> ${c.stock.transaction_type} ${formatMoney(c.stock.amount_min, c.stock.amount_max)}</td>
          <td>${timingText(c.days_diff)}</td>
          <td><span class="conflict-flag">⚠ ${c.score}/10</span></td>
        </tr>
      `).join('');
    }
    return;
  }

  // ── Real data ──
  const { data: members, error: memberErr } = await db.from('members').select('*').eq('id', memberId).limit(1);
  if (memberErr || !members?.length) {
    const nameEl = document.getElementById('politician-name');
    if (nameEl) nameEl.textContent = 'Member not found';
    return;
  }
  const m = members[0];

  document.title = `${m.full_name} — Capitol Conflicts`;

  const photoEl = document.getElementById('politician-photo');
  if (photoEl) photoEl.innerHTML = m.photo_url
    ? `<img src="${m.photo_url}" alt="${m.full_name}">`
    : memberInitials(m.full_name);

  const nameEl = document.getElementById('politician-name');
  if (nameEl) nameEl.textContent = m.full_name;

  const tagsEl = document.getElementById('politician-tags');
  if (tagsEl) tagsEl.innerHTML = `${partyTag(m.party)} ${chamberTag(m.chamber)} <span class="tag tag-senate">${m.state}</span>`;

  // Load all tabs in parallel
  const [
    { data: conflicts },
    { data: votes },
    { data: disclosures },
    { data: committees },
    { data: pacs },
  ] = await Promise.all([
    db.from('conflicts_view').select('*').eq('member_id', memberId).order('score', { ascending: false }),
    db.from('member_votes').select('position, votes(vote_date, question, result, bills(id, title))').eq('member_id', memberId).order('vote_id', { ascending: false }).limit(200),
    db.from('stock_disclosures').select('*').eq('member_id', memberId).order('transaction_date', { ascending: false }),
    db.from('committee_assignments').select('*').eq('member_id', memberId).order('congress', { ascending: false }),
    db.from('pac_donations').select('*').eq('member_id', memberId).order('cycle', { ascending: false }),
  ]);

  // Conflicts tab
  const conflictsEl = document.getElementById('conflicts-table-body');
  if (conflictsEl) {
    if (!conflicts?.length) {
      conflictsEl.innerHTML = '<tr><td colspan="6" class="empty-state">No conflicts flagged for this member.</td></tr>';
    } else {
      conflictsEl.innerHTML = conflicts.map(c => `
        <tr>
          <td>${formatDate(c.vote_date)}</td>
          <td><a href="bill.html?id=${c.bill_id}">${c.bill_title || 'Procedural Vote'}</a></td>
          <td>${voteTag(c.vote_position)}</td>
          <td>${c.ticker ? `<strong>${c.ticker}</strong> ${c.transaction_type} ${formatMoney(c.amount_min, c.amount_max)}` : '—'}</td>
          <td>${timingText(c.days_diff)}</td>
          <td><span class="conflict-flag">⚠ ${c.score}/10</span></td>
        </tr>
      `).join('');
    }
  }

  // All Votes tab
  const votesEl = document.getElementById('votes-table-body');
  if (votesEl) {
    if (!votes?.length) {
      votesEl.innerHTML = '<tr><td colspan="4" class="empty-state">No votes found.</td></tr>';
    } else {
      votesEl.innerHTML = votes.map(v => {
        const vote = v.votes || {};
        const bill = vote.bills || {};
        return `
          <tr>
            <td>${formatDate(vote.vote_date)}</td>
            <td>${bill.title || vote.question || '—'}</td>
            <td>${voteTag(v.position)}</td>
            <td>${vote.result || '—'}</td>
          </tr>
        `;
      }).join('');
    }
  }

  // Stock Disclosures tab
  const stocksEl = document.getElementById('stocks-table-body');
  if (stocksEl) {
    if (!disclosures?.length) {
      stocksEl.innerHTML = '<tr><td colspan="6" class="empty-state">No disclosures found.</td></tr>';
    } else {
      stocksEl.innerHTML = disclosures.map(d => `
        <tr>
          <td>${formatDate(d.filed_date)}</td>
          <td>${formatDate(d.transaction_date)}</td>
          <td><strong>${d.ticker || '—'}</strong></td>
          <td>${d.company || '—'}</td>
          <td>${d.transaction_type || '—'}</td>
          <td>${d.amount_min ? formatMoney(d.amount_min, d.amount_max) : '—'}</td>
        </tr>
      `).join('');
    }
  }

  // Committees tab
  const committeesEl = document.getElementById('committees-table-body');
  if (committeesEl) {
    if (!committees?.length) {
      committeesEl.innerHTML = '<tr><td colspan="3" class="empty-state">No committee data available.</td></tr>';
    } else {
      committeesEl.innerHTML = committees.map(c => `
        <tr>
          <td>${c.committee_name}</td>
          <td>${c.role || 'Member'}</td>
          <td>${c.congress || '—'}</td>
        </tr>
      `).join('');
    }
  }

  // PAC tab
  const pacEl = document.getElementById('pac-table-body');
  if (pacEl) {
    if (!pacs?.length) {
      pacEl.innerHTML = '<tr><td colspan="4" class="empty-state">No PAC donation data available.</td></tr>';
    } else {
      pacEl.innerHTML = pacs.map(p => `
        <tr>
          <td>${p.pac_name}</td>
          <td>${p.industry || '—'}</td>
          <td>${p.amount ? '$' + p.amount.toLocaleString() : '—'}</td>
          <td>${p.cycle || '—'}</td>
        </tr>
      `).join('');
    }
  }
}

// ── BILL PAGE (bill.html) ──────────────────────────────────────────────────────

async function loadBill() {
  const params = new URLSearchParams(window.location.search);
  const billId = params.get('id');
  if (!billId) return;

  if (DEMO_MODE) {
    const demo = DEMO_CONFLICTS.find(c => c.bill.id === billId);
    if (!demo) return;
    document.title = `${demo.bill.title} — Capitol Conflicts`;
    const titleEl = document.getElementById('bill-title');
    if (titleEl) titleEl.textContent = demo.bill.title;
    const subjectsEl = document.getElementById('bill-subjects');
    if (subjectsEl) {
      subjectsEl.innerHTML = demo.bill.subjects.map(s => `<span class="subject-tag">${s}</span>`).join('');
    }
    const billConflicts = DEMO_CONFLICTS.filter(c => c.bill.id === billId);
    const tableEl = document.getElementById('bill-votes-body');
    if (tableEl) {
      tableEl.innerHTML = billConflicts.map(c => `
        <tr>
          <td><a href="politician.html?id=${c.member.id}">${c.member.name}</a></td>
          <td>${partyTag(c.member.party)}</td>
          <td>${c.member.state}</td>
          <td>${chamberTag(c.member.chamber)}</td>
          <td>${voteTag(c.vote.position)}</td>
          <td>${c.stock.ticker ? `<strong>${c.stock.ticker}</strong> — ${c.stock.company}` : '—'}</td>
          <td>${c.score > 0 ? `<span class="conflict-flag">⚠ ${c.score}/10</span>` : '—'}</td>
        </tr>
      `).join('');
    }
    return;
  }

  // ── Real data ──
  const { data: bills } = await db.from('bills').select('*').eq('id', billId).limit(1);
  const bill = bills?.[0];
  if (!bill) {
    const titleEl = document.getElementById('bill-title');
    if (titleEl) titleEl.textContent = 'Bill not found';
    return;
  }

  document.title = `${bill.title} — Capitol Conflicts`;
  const titleEl = document.getElementById('bill-title');
  if (titleEl) titleEl.textContent = bill.title;

  const subjectsEl = document.getElementById('bill-subjects');
  if (subjectsEl && bill.subjects?.length) {
    subjectsEl.innerHTML = bill.subjects.map(s => `<span class="subject-tag">${s}</span>`).join('');
  }

  // Fetch vote(s) for this bill
  const { data: votes } = await db.from('votes').select('*').eq('bill_id', billId).limit(1);
  const vote = votes?.[0];
  if (!vote) {
    document.getElementById('vote-result').textContent = 'No vote data';
    return;
  }

  // Parallel: member votes + conflicts
  const [
    { data: memberVotes },
    { data: conflicts },
  ] = await Promise.all([
    db.from('member_votes')
      .select('position, members(id, full_name, party, state, chamber)')
      .eq('vote_id', vote.id),
    db.from('conflicts_view')
      .select('*')
      .eq('vote_id', vote.id)
      .order('score', { ascending: false }),
  ]);

  // Vote summary bar
  const yesCount = memberVotes?.filter(v => v.position === 'Yes').length || 0;
  const noCount = memberVotes?.filter(v => v.position === 'No').length || 0;
  document.getElementById('vote-yes-count').textContent = yesCount;
  document.getElementById('vote-no-count').textContent = noCount;
  document.getElementById('vote-result').textContent = vote.result || '—';
  document.getElementById('conflict-count').textContent = conflicts?.length || 0;

  // Build conflict lookup by member_id
  const conflictMap = {};
  (conflicts || []).forEach(c => { conflictMap[c.member_id] = c; });

  // All Votes tab
  const allVotesEl = document.getElementById('bill-votes-body');
  if (allVotesEl) {
    if (!memberVotes?.length) {
      allVotesEl.innerHTML = '<tr><td colspan="7" class="empty-state">No vote records found.</td></tr>';
    } else {
      allVotesEl.innerHTML = memberVotes.map(v => {
        const m = v.members || {};
        const conflict = conflictMap[m.id];
        return `
          <tr>
            <td><a href="politician.html?id=${m.id}">${m.full_name || '—'}</a></td>
            <td>${partyTag(m.party)}</td>
            <td>${m.state || '—'}</td>
            <td>${chamberTag(m.chamber)}</td>
            <td>${voteTag(v.position)}</td>
            <td>${conflict?.ticker ? `<strong>${conflict.ticker}</strong> — ${conflict.company}` : '—'}</td>
            <td>${conflict ? `<span class="conflict-flag">⚠ ${conflict.score}/10</span>` : '—'}</td>
          </tr>
        `;
      }).join('');
    }
  }

  // Conflicts Only tab
  const conflictsEl = document.getElementById('bill-conflicts-body');
  if (conflictsEl) {
    if (!conflicts?.length) {
      conflictsEl.innerHTML = '<tr><td colspan="7" class="empty-state">No conflicts flagged for this bill.</td></tr>';
    } else {
      conflictsEl.innerHTML = conflicts.map(c => `
        <tr>
          <td><a href="politician.html?id=${c.member_id}">${c.member_name}</a></td>
          <td>${partyTag(c.member_party)}</td>
          <td>${c.member_state}</td>
          <td>${voteTag(c.vote_position)}</td>
          <td>${c.ticker ? `<strong>${c.ticker}</strong> — ${c.company}` : '—'}</td>
          <td>${timingText(c.days_diff)}</td>
          <td><span class="conflict-flag">⚠ ${c.score}/10</span></td>
        </tr>
      `).join('');
    }
  }
}

// ── SEARCH ────────────────────────────────────────────────────────────────────

function setupSearch() {
  const input = document.getElementById('global-search');
  if (!input) return;
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && input.value.trim()) {
      window.location.href = `search.html?q=${encodeURIComponent(input.value.trim())}`;
    }
  });
}

// ── INIT ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  setupSearch();

  const page = document.body.dataset.page;

  if (page === 'feed') {
    loadStats();
    loadConflicts();
    document.getElementById('btn-apply-filters')?.addEventListener('click', () => loadConflicts(getFilters()));
  }

  if (page === 'politician') loadPolitician();
  if (page === 'bill') loadBill();
});
