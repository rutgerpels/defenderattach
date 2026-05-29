// milestone-view.js — renders the milestone gaps page from a model produced by
// window.MilestoneModel.build(). Exposes window.MilestoneView.
(() => {
  const PRIORITY_ORDER = ['HIGH', 'MEDIUM', 'LOW'];
  const PRIORITY_CLASS = { HIGH: 'high', MEDIUM: 'medium', LOW: 'low' };

  function escapeHtml(value) {
    if (value == null) return '';
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function money(value) {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return '–';
    return '$' + n.toLocaleString('en-US', { maximumFractionDigits: 0 });
  }

  function pluralise(label, count) { return `${count} ${label}${count === 1 ? '' : 's'}`; }

  function renderSummary(model) {
    const summary = model.summary || {};
    const cards = [
      { label: 'Migration accounts', value: summary.migration_accounts, hint: 'Accounts in the migration workbook' },
      { label: 'Accounts attached', value: summary.attached_accounts, hint: 'Have at least one Defender milestone' },
      { label: 'Accounts with gaps', value: summary.total_accounts_with_gaps, hint: pluralise('account-level gap', summary.account_level_gap_accounts) },
      { label: 'Opportunities with gaps', value: summary.total_opportunities_with_gaps, hint: 'Migration opps missing Defender milestones' },
      { label: 'Total gap rows', value: summary.total_gap_rows, hint: 'After deduplication' },
    ];
    document.getElementById('summary-cards').innerHTML = cards.map(c => `
      <article class="metric-card">
        <h3>${escapeHtml(c.label)}</h3>
        <p class="metric-value">${escapeHtml(String(c.value ?? 0))}</p>
        <p class="metric-hint">${escapeHtml(c.hint)}</p>
      </article>`).join('');
  }

  function renderPriorityChart(model) {
    const counts = model.priority_counts || {};
    const total = PRIORITY_ORDER.reduce((sum, k) => sum + (counts[k] || 0), 0) || 1;
    document.getElementById('priority-chart').innerHTML = PRIORITY_ORDER.map(level => {
      const v = counts[level] || 0;
      const pct = (v / total) * 100;
      return `<div class="bar-row">
        <span class="bar-label">${level}</span>
        <span class="bar-track"><span class="bar-fill ${PRIORITY_CLASS[level]}" style="width:${pct.toFixed(1)}%"></span></span>
        <span class="bar-value">${v}</span>
      </div>`;
    }).join('');
  }

  function renderGapTypeChart(model) {
    const counts = model.gap_type_counts || {};
    const entries = Object.entries(counts);
    const total = entries.reduce((sum, [, v]) => sum + v, 0) || 1;
    document.getElementById('gap-type-chart').innerHTML = entries.map(([label, v]) => {
      const pct = (v / total) * 100;
      return `<div class="bar-row">
        <span class="bar-label">${escapeHtml(label)}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${pct.toFixed(1)}%"></span></span>
        <span class="bar-value">${v}</span>
      </div>`;
    }).join('');
  }

  function renderWorkloadChart(model) {
    const items = model.workload_counts || [];
    if (!items.length) { document.getElementById('workload-chart').innerHTML = '<p class="metric-hint">No workload data available.</p>'; return; }
    const max = items.reduce((m, item) => Math.max(m, item.count), 0) || 1;
    document.getElementById('workload-chart').innerHTML = items.map(item => {
      const pct = (item.count / max) * 100;
      return `<div class="bar-row">
        <span class="bar-label" title="${escapeHtml(item.workload)}">${escapeHtml(item.workload)}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${pct.toFixed(1)}%"></span></span>
        <span class="bar-value">${item.count}</span>
      </div>`;
    }).join('');
  }

  function renderTopTable(model) {
    const tbody = document.getElementById('top-gaps-tbody');
    const rows = model.top_gaps || [];
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="metric-hint">No gaps to display.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${escapeHtml(r.account)}</td>
        <td>${escapeHtml(r.opportunity_id || '–')}</td>
        <td>${escapeHtml(r.workload)}</td>
        <td>${escapeHtml(r.estimated_date || '–')}</td>
        <td><span class="tag ${PRIORITY_CLASS[r.priority] || 'low'}">${escapeHtml(r.priority)}</span></td>
        <td class="num">${money(r.acr_pipeline)}</td>
      </tr>`).join('');
  }

  function renderQualityNotes(model) {
    const q = model.data_quality || {};
    const sources = model.sources || {};
    document.getElementById('quality-notes').innerHTML = `
      <ul>
        <li>Migration source: <strong>${escapeHtml(sources.migration || '—')}</strong> (${q.migration_rows ?? 0} rows, ${q.migration_invalid_dates ?? 0} invalid dates)</li>
        <li>Defender source: <strong>${escapeHtml(sources.defender || '—')}</strong> (${q.defender_rows ?? 0} rows, ${q.defender_invalid_dates ?? 0} invalid dates)</li>
        <li>Reference date: <strong>${escapeHtml(model.reference_date || '')}</strong>, near-term window: <strong>${model.near_term_days} days</strong></li>
        <li>${escapeHtml(q.strict_opportunity_match || '')}</li>
      </ul>`;
  }

  function render(model) {
    document.getElementById('milestone-shell').hidden = false;
    document.getElementById('milestone-empty').hidden = true;
    renderSummary(model);
    renderPriorityChart(model);
    renderGapTypeChart(model);
    renderWorkloadChart(model);
    renderTopTable(model);
    renderQualityNotes(model);
  }

  window.MilestoneView = { render };
})();
