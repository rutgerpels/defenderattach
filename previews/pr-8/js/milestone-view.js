// milestone-view.js — renders the milestone gaps page from a model produced by
// window.MilestoneModel.build(). Exposes window.MilestoneView.
(() => {
  const PRIORITY_ORDER = ['HIGH', 'MEDIUM', 'LOW'];
  const PRIORITY_CLASS = { HIGH: 'high', MEDIUM: 'medium', LOW: 'low' };
  const PRIORITY_RANK = { HIGH: 0, MEDIUM: 1, LOW: 2 };
  let currentModel = null;

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

  function workloadParts(row) {
    return String(row.workload || '').split(';').map(part => part.trim()).filter(Boolean);
  }

  function uniqueSorted(values) {
    return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  }

  function populateFilters(model) {
    const select = document.getElementById('workload-filter');
    if (!select) return;
    const selected = select.value || 'all';
    const workloads = uniqueSorted((model.gaps || []).flatMap(workloadParts));
    select.innerHTML = '<option value="all">All workloads</option>' + workloads.map(workload =>
      `<option value="${escapeHtml(workload)}">${escapeHtml(workload)}</option>`
    ).join('');
    select.value = workloads.includes(selected) ? selected : 'all';
  }

  function filteredRows() {
    if (!currentModel) return [];
    const term = (document.getElementById('milestone-search')?.value || '').trim().toLowerCase();
    const gapType = document.getElementById('gap-filter')?.value || 'all';
    const priority = document.getElementById('priority-filter')?.value || 'all';
    const workload = document.getElementById('workload-filter')?.value || 'all';
    return (currentModel.gaps || []).filter(row => {
      if (gapType !== 'all' && row.gap_type !== gapType) return false;
      if (priority !== 'all' && row.priority !== priority) return false;
      if (workload !== 'all' && !workloadParts(row).includes(workload)) return false;
      if (!term) return true;
      return [
        row.account,
        row.opportunity_id,
        row.gap_type,
        row.workload,
        row.milestone_workload,
        row.sales_stage,
        row.owner,
        row.owner_role,
        row.priority_reason,
        ...(row.milestones || []),
      ].some(value => String(value || '').toLowerCase().includes(term));
    }).sort(compareGapRows);
  }

  function compareGapRows(a, b) {
    return (PRIORITY_RANK[a.priority] ?? 99) - (PRIORITY_RANK[b.priority] ?? 99) ||
      Number(!a.has_committed) - Number(!b.has_committed) ||
      String(a.estimated_date || '9999-12-31').localeCompare(String(b.estimated_date || '9999-12-31')) ||
      Number(b.acr_pipeline || 0) - Number(a.acr_pipeline || 0);
  }

  function renderSummary(model) {
    const summary = model.summary || {};
    const visible = filteredRows();
    const visibleAccounts = new Set(visible.map(row => row.account_key)).size;
    const visibleOpps = new Set(visible.map(row => `${row.account_key}|${row.opportunity_id || ''}`)).size;
    const cards = [
      { label: 'Accounts with gaps', value: summary.total_accounts_with_gaps, hint: `${visibleAccounts} visible` },
      { label: 'Opportunities with gaps', value: summary.total_opportunities_with_gaps, hint: `${visibleOpps} visible` },
      { label: 'Account-level gaps', value: summary.account_level_gaps, hint: pluralise('account', summary.account_level_gap_accounts) },
      { label: 'Opportunity-level gaps', value: summary.opportunity_level_gaps, hint: 'Strict Opportunity ID' },
      { label: 'Attached accounts', value: summary.attached_accounts, hint: 'Migration + Defender' },
      { label: 'High priority', value: (model.priority_counts || {}).HIGH, hint: 'Target sales stage' },
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

  function priorityTag(priority) {
    return `<span class="tag ${PRIORITY_CLASS[priority] || 'low'}">${escapeHtml(priority || 'LOW')}</span>`;
  }

  function tableHtml(rows, compact = false) {
    if (!rows.length) return '<div class="empty">No gaps match the current filters.</div>';
    const displayed = compact ? rows.slice(0, 10) : rows;
    return `<table>
      <thead>
        <tr>
          <th>Account</th>
          <th>Opportunity ID</th>
          <th>Gap type</th>
          <th>Workload</th>
          <th>Estimated date</th>
          <th>Priority</th>
          <th>Sales stage</th>
          <th class="num">Migration pipeline</th>
          <th>Owner</th>
        </tr>
      </thead>
      <tbody>
        ${displayed.map(row => {
          const index = currentModel.gaps.indexOf(row);
          return `<tr class="clickable" data-gap-index="${index}">
            <td><strong>${escapeHtml(row.account)}</strong></td>
            <td><code>${escapeHtml(row.opportunity_id || '-')}</code></td>
            <td>${escapeHtml(row.gap_type)}</td>
            <td>${escapeHtml(row.workload)}</td>
            <td>${escapeHtml(row.estimated_date || '-')}</td>
            <td>${priorityTag(row.priority)}</td>
            <td>${escapeHtml(row.sales_stage || '-')}</td>
            <td class="num">${money(row.acr_pipeline)}</td>
            <td>${escapeHtml(row.owner || row.owner_role || '-')}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
  }

  function renderGapTable() {
    const rows = filteredRows();
    document.getElementById('result-count').textContent = `${rows.length.toLocaleString('en-US')} visible gap rows`;
    document.getElementById('gap-table').innerHTML = tableHtml(rows);
    document.querySelectorAll('#gap-table tr.clickable').forEach(row => {
      row.addEventListener('click', () => showDetails(Number(row.getAttribute('data-gap-index'))));
    });
  }

  function showDetails(index) {
    const row = currentModel?.gaps?.[index];
    if (!row) return;
    const panel = document.getElementById('details-panel');
    panel.hidden = false;
    panel.innerHTML = `
      <div class="section-heading">
        <h2>${escapeHtml(row.account)}</h2>
        <p>${escapeHtml(row.gap_type)} | Opportunity ${escapeHtml(row.opportunity_id || '-')}</p>
      </div>
      <div class="detail-grid">
        <div><span>Priority</span><strong>${escapeHtml(row.priority)}</strong><small>${escapeHtml(row.priority_reason || '-')}</small></div>
        <div><span>Sales stage</span><strong>${escapeHtml(row.sales_stage || '-')}</strong><small>Target: Inspire & Design or Listen and Consult</small></div>
        <div><span>Estimated date</span><strong>${escapeHtml(row.estimated_date || '-')}</strong><small>${escapeHtml(row.commitment || '-')}</small></div>
        <div><span>Pipeline</span><strong>${money(row.acr_pipeline)}</strong><small>${escapeHtml(row.status || '-')}</small></div>
        <div><span>Owner</span><strong>${escapeHtml(row.owner || '-')}</strong><small>${escapeHtml(row.owner_role || '-')}</small></div>
        <div><span>Workload</span><strong>${escapeHtml(row.workload || '-')}</strong><small>${escapeHtml(row.milestone_workload || '-')}</small></div>
        <div><span>Milestones</span><strong>${escapeHtml(String(row.milestone_count || 0))}</strong><small>Migration milestones grouped into this gap</small></div>
      </div>
      <h3>Migration milestones in this gap</h3>
      <ul class="milestone-list">${(row.milestones || []).map(name => `<li>${escapeHtml(name)}</li>`).join('') || '<li>No milestone names available.</li>'}</ul>`;
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function renderInteractiveSections() {
    if (!currentModel) return;
    renderSummary(currentModel);
    renderGapTable();
  }

  function wireFilters() {
    ['milestone-search', 'gap-filter', 'priority-filter', 'workload-filter'].forEach(id => {
      const el = document.getElementById(id);
      if (!el || el.dataset.milestoneWired) return;
      el.dataset.milestoneWired = '1';
      el.addEventListener('input', renderInteractiveSections);
      el.addEventListener('change', renderInteractiveSections);
    });
  }

  function renderQualityNotes(model) {
    const q = model.data_quality || {};
    const sources = model.sources || {};
    document.getElementById('quality-notes').innerHTML = `
      <ul>
        <li>Migration source: <strong>${escapeHtml(sources.migration || '—')}</strong> (${q.migration_rows ?? 0} rows, ${q.migration_invalid_dates ?? 0} invalid dates)</li>
        <li>Defender source: <strong>${escapeHtml(sources.defender || '—')}</strong> (${q.defender_rows ?? 0} rows, ${q.defender_invalid_dates ?? 0} invalid dates)</li>
        <li>Reference date: <strong>${escapeHtml(model.reference_date || '')}</strong>; rows sort by priority, earliest due date, then pipeline size</li>
        <li>${escapeHtml(q.strict_opportunity_match || '')}</li>
      </ul>`;
  }

  function render(model) {
    currentModel = model;
    document.getElementById('milestone-shell').hidden = false;
    document.getElementById('milestone-empty').hidden = true;
    populateFilters(model);
    wireFilters();
    renderSummary(model);
    renderPriorityChart(model);
    renderGapTypeChart(model);
    renderWorkloadChart(model);
    renderTopTable(model);
    renderGapTable();
    renderQualityNotes(model);
  }

  window.MilestoneView = { render };
})();
