// Replace these with your Supabase project URL and anon key after setup
const SUPABASE_URL = 'YOUR_SUPABASE_URL';
const SUPABASE_ANON_KEY = 'YOUR_SUPABASE_ANON_KEY';

const DEMO_MODE = SUPABASE_URL === 'YOUR_SUPABASE_URL';

// Supabase client (loaded via CDN in HTML)
let supabase = null;
if (!DEMO_MODE) {
  supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
}

// ── DEMO DATA ────────────────────────────────────────────────────────────────
// Shown when Supabase isn't connected yet. Replace with real data once pipeline runs.

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
  return `<span class="tag ${map[party] || 'tag-i'}">${labels[party] || party}</span>`;
}

function chamberTag(chamber) {
  const cls = chamber === 'Senate' ? 'tag-senate' : 'tag-house';
  return `<span class="tag ${cls}">${chamber}</span>`;
}

function voteTag(position) {
  const map = { Yes: 'vote-yes', No: 'vote-no', 'Not Voting': 'vote-abstain', Present: 'vote-abstain' };
  return `<span class="vote-badge ${map[position] || 'vote-abstain'}">${position}</span>`;
}

function timingText(days) {
  if (days === 0) return 'same day as vote';
  const abs = Math.abs(days);
  return days < 0 ? `${abs} days before vote` : `${abs} days after vote`;
}

function memberInitials(name) {
  return name.replace(/^(Sen\.|Rep\.)\s+/, '').split(' ').map(p => p[0]).join('').slice(0, 2);
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
    <a class="conflict-card ${cls}" href="politician.html?id=${c.member.id}">
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
            <strong>${c.stock.ticker}</strong> — ${c.stock.company}
            <br><small style="color:var(--muted)">${c.stock.transaction_type} &nbsp;·&nbsp; ${formatMoney(c.stock.amount_min, c.stock.amount_max)} &nbsp;·&nbsp; ${formatDate(c.stock.transaction_date)}</small>
          </div>
        </div>
      </div>

      <div class="card-footer">
        <span class="${timingCls}">Traded ${timing}</span>
        ${committeeLine}
        ${pacLine}
      </div>
    </a>
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
    // Apply basic demo filters
    if (filters.chamber) conflicts = conflicts.filter(c => c.member.chamber === filters.chamber);
    if (filters.party) conflicts = conflicts.filter(c => c.member.party === filters.party);
    if (filters.state) conflicts = conflicts.filter(c => c.member.state === filters.state);
    if (filters.score === 'high') conflicts = conflicts.filter(c => c.score >= 7);
    if (filters.score === 'medium') conflicts = conflicts.filter(c => c.score >= 4 && c.score < 7);
    if (filters.score === 'low') conflicts = conflicts.filter(c => c.score < 4);
  } else {
    const query = supabase
      .from('conflicts_view')
      .select('*')
      .order('score', { ascending: false })
      .limit(50);

    if (filters.chamber) query.eq('member_chamber', filters.chamber);
    if (filters.party) query.eq('member_party', filters.party);
    if (filters.state) query.eq('member_state', filters.state);
    if (filters.score === 'high') query.gte('score', 7);
    if (filters.score === 'medium') query.gte('score', 4).lt('score', 7);
    if (filters.score === 'low') query.lt('score', 4);
    if (filters.dateFrom) query.gte('vote_date', filters.dateFrom);
    if (filters.dateTo) query.lte('vote_date', filters.dateTo);

    const { data, error } = await query;
    if (error) { feed.innerHTML = `<div class="empty-state"><h3>Error loading data</h3><p>${error.message}</p></div>`; return; }
    conflicts = data;
  }

  if (!conflicts || conflicts.length === 0) {
    feed.innerHTML = '<div class="empty-state"><h3>No conflicts found</h3><p>Try adjusting your filters.</p></div>';
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

function loadStats() {
  const stats = DEMO_MODE ? DEMO_STATS : null;
  if (!stats) return;
  const el = id => document.getElementById(id);
  if (el('stat-conflicts')) el('stat-conflicts').textContent = stats.total_conflicts.toLocaleString();
  if (el('stat-members')) el('stat-members').textContent = stats.members_flagged.toLocaleString();
  if (el('stat-bills')) el('stat-bills').textContent = stats.bills_covered.toLocaleString();
  if (el('stat-high')) el('stat-high').textContent = stats.high_score_count.toLocaleString();
}

// ── POLITICIAN PAGE (politician.html) ─────────────────────────────────────────

async function loadPolitician() {
  const params = new URLSearchParams(window.location.search);
  const memberId = params.get('id');
  if (!memberId) return;

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

  // Load conflicts for this member
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
}

// ── BILL PAGE (bill.html) ──────────────────────────────────────────────────────

async function loadBill() {
  const params = new URLSearchParams(window.location.search);
  const billId = params.get('id');
  if (!billId) return;

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
        <td>${voteTag(c.vote.position)}</td>
        <td>${c.stock.ticker ? `<strong>${c.stock.ticker}</strong> — ${c.stock.company}` : '—'}</td>
        <td>${c.score > 0 ? `<span class="conflict-flag">⚠ ${c.score}/10</span>` : '—'}</td>
      </tr>
    `).join('');
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
