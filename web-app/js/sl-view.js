// sl-view.js — Renders the service-attach model: corp KPI headline, manager
// leaderboard, and the per-customer attach dossier. All Excel-derived strings
// are HTML-escaped before they touch innerHTML/SVG. Exposes window.SLView.
(() => {
  'use strict';

  let currentModel = null;
  let selectedCustomer = null;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function money(value) {
    if (value === null || value === undefined || !Number.isFinite(value)) return '$0';
    return '$' + Math.round(value).toLocaleString('en-US');
  }

  function pct(value) {
    if (value === null || value === undefined || !Number.isFinite(value)) return 'n/a';
    return (value * 100).toFixed(1) + '%';
  }

  function growth(value) {
    if (value === null || value === undefined || !Number.isFinite(value)) return 'n/a';
    const sign = value > 0 ? '+' : '';
    return sign + (value * 100).toFixed(0) + '%';
  }

  function score0(value) {
    if (value === null || value === undefined || !Number.isFinite(value)) return '0';
    return Math.round(value).toString();
  }

  // --- Corp KPI headline ---------------------------------------------------
  function renderCorpKpis(model) {
    const el = document.getElementById('sa-corp-kpis');
    const cards = [
      { label: 'Book attach ratio', value: pct(model.bookAttachRatio), hint: 'DfC $ ÷ eligible workload $' },
      { label: 'Defender for Cloud ACR', value: money(model.totalDfcAcr), hint: 'latest month, ' + escapeHtml(model.latestMonth) },
      { label: 'Eligible workload ACR', value: money(model.totalEligibleWorkloadAcr), hint: 'mapped Azure workloads' },
      { label: 'Quantified attach gap', value: money(model.totalGapDollars) + '/mo', hint: 'benchmarked $ gaps only' },
      { label: 'Customers', value: model.dossiers.length.toString(), hint: 'in this book' },
    ];
    el.innerHTML = cards.map((c) => `
      <div class="metric-card">
        <div class="metric-value">${escapeHtml(c.value)}</div>
        <div class="metric-label">${escapeHtml(c.label)}</div>
        <div class="metric-hint">${c.hint}</div>
      </div>`).join('');
  }

  // --- Manager leaderboard -------------------------------------------------
  function renderLeaderboard(model, filterText) {
    const body = document.getElementById('sa-leaderboard-body');
    const needle = (filterText || '').trim().toLowerCase();
    const rows = [];
    model.dossiers.forEach((d, idx) => {
      if (needle && !d.customer.toLowerCase().includes(needle)) return;
      const selected = d.customer === selectedCustomer ? ' selected' : '';
      rows.push(`
        <tr class="clickable${selected}" data-customer="${escapeHtml(d.customer)}">
          <td><span class="sa-rank">${idx + 1}</span></td>
          <td>${escapeHtml(d.customer)}</td>
          <td class="num">${score0(d.customerScore)}</td>
          <td class="num">${pct(d.attachRatio)}</td>
          <td class="num">${money(d.totalGapDollars)}</td>
          <td class="num">${d.uncoveredEligibleCount}/${d.presentEligibleCount}</td>
        </tr>`);
    });
    body.innerHTML = rows.length
      ? rows.join('')
      : '<tr><td colspan="6" class="sa-empty-dossier">No customers match that filter.</td></tr>';

    body.querySelectorAll('tr.clickable').forEach((tr) => {
      tr.addEventListener('click', () => selectCustomer(tr.dataset.customer));
    });
  }

  function selectCustomer(name) {
    selectedCustomer = name;
    const dossier = currentModel.dossiers.find((d) => d.customer === name);
    renderDossier(dossier);
    const body = document.getElementById('sa-leaderboard-body');
    body.querySelectorAll('tr.clickable').forEach((tr) => {
      tr.classList.toggle('selected', tr.dataset.customer === name);
    });
  }

  // --- Mini trend sparkline (workload vs defender) -------------------------
  function spark(workloadSeries, defenderSeries) {
    const w = 120, h = 30, pad = 2;
    const all = workloadSeries.concat(defenderSeries).filter((v) => Number.isFinite(v));
    const max = Math.max(1, ...all);
    const n = workloadSeries.length;
    if (n < 2) return '';
    const xFor = (i) => pad + (i * (w - 2 * pad)) / (n - 1);
    const yFor = (v) => h - pad - (Math.max(0, v) / max) * (h - 2 * pad);
    const line = (series, color) => {
      const pts = series.map((v, i) => `${xFor(i).toFixed(1)},${yFor(v).toFixed(1)}`).join(' ');
      return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" />`;
    };
    return `<svg class="sa-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="workload vs defender trend">`
      + line(workloadSeries, 'var(--cp-link)')
      + line(defenderSeries, 'var(--cp-success, #107c10)')
      + '</svg>';
  }

  function oppCard(opp) {
    const signalClass = opp.signal === 'attach' ? 'attach' : 'expand';
    const signalTag = opp.signal === 'attach'
      ? '<span class="sa-tag attach">Attach</span>'
      : '<span class="sa-tag expand">Expand</span>';
    const dollarTag = opp.hasDollarGap
      ? '<span class="sa-tag coverage">💲 $ benchmark</span>'
      : '<span class="sa-tag coverage">● coverage signal</span>';
    const momentumTag = opp.defenderZeroWithWorkloadGrowth
      ? '<span class="sa-tag attach">📈 workload growing, Defender flat</span>' : '';

    const metrics = [
      ['Workload $/mo', money(opp.workloadAcr)],
      ['Defender $/mo', money(opp.defenderActual)],
    ];
    if (opp.hasDollarGap) {
      metrics.push(['Benchmark $/mo', money(opp.expected)]);
      metrics.push(['Gap $/mo', money(opp.gapDollars)]);
      metrics.push(['Coverage', pct(opp.coveragePct)]);
    }
    metrics.push(['Workload 3m', growth(opp.workloadGrowth)]);
    metrics.push(['Defender 3m', growth(opp.defenderGrowth)]);

    const metricsHtml = metrics.map(([label, value]) => `
      <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('');

    return `
      <div class="sa-opp ${signalClass}">
        <div class="sa-opp-head">
          <h4>${escapeHtml(opp.planLabel)}</h4>
          <div class="sa-opp-tags">${signalTag}${dollarTag}${momentumTag}</div>
        </div>
        <p class="sa-opener">${escapeHtml(opp.opener)}</p>
        <div class="sa-opp-head">
          <div class="sa-opp-metrics" style="flex:1">${metricsHtml}</div>
          ${spark(opp.workloadSeries, opp.defenderSeries)}
        </div>
        <p class="metric-hint" style="margin-top:8px">Confidence: ${escapeHtml(opp.confidence)} · ${escapeHtml(opp.pricingDriver)}</p>
      </div>`;
  }

  function renderDossier(d) {
    const el = document.getElementById('sa-dossier');
    if (!d) {
      el.innerHTML = '<p class="sa-empty-dossier">Select a customer to see their attach dossier.</p>';
      return;
    }

    const opps = d.opportunities.slice().sort((a, b) => b.blendedScore - a.blendedScore);

    const kpis = [
      ['Attach ratio', pct(d.attachRatio)],
      ['Eligible workload', money(d.eligibleWorkloadAcr)],
      ['Defender for Cloud', money(d.dfcAcr)],
      ['Attach gap', money(d.totalGapDollars) + '/mo'],
      ['Unprotected', d.uncoveredEligibleCount + ' / ' + d.presentEligibleCount],
      ['Customer score', score0(d.customerScore)],
    ];
    const kpiHtml = kpis.map(([label, value]) => `
      <div class="sa-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('');

    const recon = d.reconciliationOk ? ''
      : '<div class="sa-recon-warn">⚠️ Subtotal reconciliation mismatch for this customer — treat figures as indicative and verify against source.</div>';

    const oppsHtml = opps.length
      ? opps.map(oppCard).join('')
      : '<p class="sa-empty-dossier">No open attach opportunities — eligible workloads are already covered.</p>';

    const foundHtml = d.foundational.map((f) => `
      <span class="sa-found-pill${f.present ? ' present' : ''}">${f.present ? '✓' : '○'} ${escapeHtml(f.planLabel)}</span>`).join('');

    const maxSpend = Math.max(1, ...d.topSpend.map((s) => s.acr));
    const spendHtml = d.topSpend.length ? d.topSpend.map((s) => `
      <div class="bar-row">
        <div class="bar-label">${escapeHtml(s.sl2)}</div>
        <div class="bar-track"><div class="bar-fill high" style="width:${Math.max(2, (s.acr / maxSpend) * 100).toFixed(1)}%"></div></div>
        <div class="bar-value">${money(s.acr)}</div>
      </div>`).join('') : '<p class="sa-empty-dossier">No Azure spend categories found.</p>';

    el.innerHTML = `
      <div class="sa-dossier-head">
        <h2>${escapeHtml(d.customer)}</h2>
      </div>
      ${recon}
      <div class="sa-kpi-row">${kpiHtml}</div>

      <h3>Attach opportunities</h3>
      ${oppsHtml}

      <h3>Foundational coverage</h3>
      <div class="sa-foundational">${foundHtml}</div>

      <h3 style="margin-top:16px">Top Azure spend</h3>
      <div class="bar-list">${spendHtml}</div>`;
  }

  // --- Public entry --------------------------------------------------------
  function render(model) {
    currentModel = model;
    document.getElementById('sa-empty').hidden = true;
    document.getElementById('sa-shell').hidden = false;

    renderCorpKpis(model);

    const search = document.getElementById('sa-search');
    search.oninput = () => renderLeaderboard(model, search.value);
    renderLeaderboard(model, search.value);

    // Preserve selection across rebuilds when the customer still exists.
    if (selectedCustomer && model.dossiers.some((d) => d.customer === selectedCustomer)) {
      selectCustomer(selectedCustomer);
    } else if (model.dossiers.length) {
      selectCustomer(model.dossiers[0].customer);
    } else {
      renderDossier(null);
    }
  }

  function reset() {
    currentModel = null;
    selectedCustomer = null;
  }

  const api = { render, reset };
  if (typeof window !== 'undefined') window.SLView = api;
})();
