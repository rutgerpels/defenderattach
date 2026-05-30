// pptx-acr.js — Builds the ACR opportunity PowerPoint deck client-side via PptxGenJS.
// Mirrors src/defender_acr_dashboard/exports.py.
(() => {
  const DEFAULT_THRESHOLD = 6.0;
  const C = {
    BLUE: '0078D4', NAVY: '0F3A5F', DARK: '201F1E', TEXT: '323130',
    MUTED: '605E5C', LIGHT_BG: 'F5F7FB', BORDER: 'D9E2EC',
    RED: 'D13438', ORANGE: 'FF8C00', GREEN: '107C10', WHITE: 'FFFFFF',
    PALE_BLUE: 'C7E0F4', STRIPE: 'F8FAFC',
  };
  const DEFENDER = 'Defender for Cloud';

  function money(v) {
    const n = Number(v || 0);
    if (!Number.isFinite(n)) return '$0';
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
    if (abs >= 1_000)     return `$${(n / 1_000).toFixed(1)}K`;
    return `$${Math.round(n)}`;
  }
  function pct(v) {
    const n = Number(v || 0);
    return `${(n * 100).toFixed(1)}%`;
  }
  function signedPct(v) {
    if (v == null || !Number.isFinite(v)) return 'n/a';
    const n = v * 100;
    return `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`;
  }
  function shortStr(s, max) {
    s = String(s ?? '');
    return s.length > max ? s.slice(0, Math.max(1, max - 1)) + '…' : s;
  }

  function blankSlide(pptx, bg) {
    const slide = pptx.addSlide();
    slide.background = { color: bg || C.WHITE };
    return slide;
  }

  function addTitle(slide, title) {
    slide.addText(title, { x: 0.55, y: 0.35, w: 9.6, h: 0.45, fontSize: 24, color: C.DARK, bold: true, fontFace: 'Segoe UI' });
    slide.addShape('rect', { x: 0.55, y: 0.92, w: 1.1, h: 0.06, fill: { color: C.BLUE }, line: { color: C.BLUE } });
  }

  function addStatCard(slide, label, value, x, y, w, h, color) {
    slide.addShape('rect', { x, y, w, h, fill: { color: C.WHITE }, line: { color: C.BORDER, width: 0.75 } });
    slide.addShape('rect', { x, y, w: 0.08, h, fill: { color }, line: { color } });
    slide.addText(label.toUpperCase(), { x: x + 0.2, y: y + 0.14, w: w - 0.35, h: 0.22, fontSize: 8, color: C.MUTED, bold: true, fontFace: 'Segoe UI' });
    slide.addText(value, { x: x + 0.2, y: y + 0.44, w: w - 0.35, h: 0.42, fontSize: 20, color, bold: true, fontFace: 'Segoe UI' });
  }

  function addLineChart(slide, title, labels, series, x, y, w, h, opts) {
    opts = opts || {};
    const data = series
      .filter(s => Array.isArray(s.values) && s.values.length)
      .map(s => ({ name: s.name, labels, values: s.values.map(v => v == null ? 0 : Number(v)) }));
    if (!data.length || !labels.length) {
      slide.addShape('rect', { x, y, w, h, fill: { color: C.WHITE }, line: { color: C.BORDER } });
      slide.addText(title, { x: x + 0.18, y: y + 0.12, w: w - 0.3, h: 0.25, fontSize: 12, color: C.DARK, bold: true });
      slide.addText('No trend data', { x, y: y + h / 2 - 0.15, w, h: 0.3, fontSize: 10, color: C.MUTED, align: 'center' });
      return;
    }
    const colors = series.filter(s => s.values && s.values.length).map(s => s.color || C.BLUE);
    slide.addChart('line', data, {
      x, y, w, h,
      showTitle: true, title, titleFontSize: 12, titleColor: C.DARK, titleFontFace: 'Segoe UI',
      chartColors: colors,
      showLegend: true, legendPos: 'b', legendFontSize: 9, legendColor: C.TEXT,
      catAxisLabelFontSize: 8, catAxisLabelColor: C.MUTED,
      valAxisLabelFontSize: 8, valAxisLabelColor: C.MUTED,
      valAxisLabelFormatCode: opts.percentAxis ? '0%' : '$#,##0',
      lineDataSymbol: 'none', lineSize: 2,
    });
  }

  function addTable(slide, headers, rows, x, y, w, colW) {
    const headerRow = headers.map(h => ({
      text: h,
      options: { bold: true, color: C.WHITE, fill: { color: C.NAVY }, fontSize: 8, align: 'left', valign: 'middle', fontFace: 'Segoe UI' },
    }));
    const bodyRows = rows.map((r, ri) => r.map((cell, ci) => {
      let color = C.TEXT, bold = false;
      const text = String(cell == null ? '' : cell);
      if (text === 'High')   { color = C.RED;    bold = true; }
      if (text === 'Medium') { color = C.ORANGE; bold = true; }
      if (text === 'Low')    { color = C.GREEN;  bold = true; }
      return { text, options: { color, bold, fontSize: 7, fill: { color: ri % 2 === 1 ? C.STRIPE : C.WHITE }, valign: 'middle', fontFace: 'Segoe UI' } };
    }));
    slide.addTable([headerRow, ...bodyRows], {
      x, y, w, colW,
      border: { type: 'solid', pt: 0.25, color: C.BORDER },
      autoPage: false,
    });
  }

  function addBullets(slide, items, x, y, w, h, fontSize) {
    const text = items.filter(Boolean).map(t => ({ text: t, options: { bullet: { code: '2022' }, breakLine: true } }));
    slide.addText(text, { x, y, w, h, fontSize: fontSize || 11, color: C.TEXT, fontFace: 'Segoe UI', valign: 'top', paraSpaceAfter: 4 });
  }

  function shareSeries(dfc, total) {
    const out = [];
    for (let i = 0; i < total.length; i++) {
      const t = total[i] || 0;
      out.push(t ? (dfc[i] || 0) / t : 0);
    }
    return out;
  }

  function monthlyGap(row, threshold) {
    const total = row.total_monthly_current ?? row.total_current ?? 0;
    const dfc = row.dfc_monthly_current ?? row.dfc_current ?? 0;
    return Math.max(0, total * (threshold / 100) - dfc);
  }

  function actionText(model, row, threshold) {
    const data = (model.customer_data || {})[row.customer] || {};
    const products = data.products || [];
    const wkProd = products.find(p => p.product !== DEFENDER && (p.current || 0) > 0);
    const workload = wkProd ? wkProd.product : 'core Azure workloads';
    const ratio = row.dfc_ratio || 0;
    const belowThreshold = ratio < threshold;
    const dfcCur = row.dfc_monthly_current ?? row.dfc_current ?? 0;
    const totalCur = row.total_monthly_current ?? row.total_current ?? 0;
    if (dfcCur < 30 && totalCur > 3000) {
      return ['Start DfC attach discovery',
        `Open with current ${workload} usage and validate Defender for Cloud coverage.`,
        'Little or no Defender for Cloud ACR against a meaningful Azure footprint.'];
    }
    if (belowThreshold && (row.growth_gap || 0) > 0) {
      return ['Prioritize attach expansion',
        `Lead with ${workload} growth and the Defender share gap to threshold.`,
        'Azure footprint is growing faster than Defender for Cloud attach.'];
    }
    if (belowThreshold) {
      return ['Expand Defender coverage',
        `Review Defender for Cloud coverage across ${workload} and adjacent services.`,
        'Defender for Cloud share is below the selected threshold.'];
    }
    const note = row.notes && row.notes !== '-' ? row.notes : 'No urgent attach gap under the selected threshold.';
    return ['Monitor Defender attach', `Confirm Defender for Cloud coverage keeps pace with ${workload}.`, note];
  }

  function actionRows(model, threshold) {
    const priorityRank = { High: 0, Medium: 1, Low: 2, 'Too small': 3 };
    const rows = [];
    for (const row of model.opportunity || []) {
      if (row.opportunity === 'Too small') continue;
      const gap = monthlyGap(row, threshold);
      const [action, angle, reason] = actionText(model, row, threshold);
      rows.push({ ...row, monthly_gap: gap, annual_opportunity: gap * 12,
        recommended_action: action, conversation_angle: angle, action_reason: reason });
    }
    rows.sort((a, b) => {
      const aAbove = (a.dfc_ratio || 0) >= threshold ? 1 : 0;
      const bAbove = (b.dfc_ratio || 0) >= threshold ? 1 : 0;
      if (aAbove !== bAbove) return aAbove - bAbove;
      const pr = priorityRank[a.opportunity] - priorityRank[b.opportunity];
      if (pr !== 0) return pr;
      const ao = (b.annual_opportunity || 0) - (a.annual_opportunity || 0);
      if (ao !== 0) return ao;
      return (b.growth_gap || 0) - (a.growth_gap || 0);
    });
    return rows;
  }

  function portfolioSummary(model, threshold) {
    const rows = (model.opportunity || []).filter(r => r.opportunity !== 'Too small');
    const sum = (key, alt) => rows.reduce((acc, r) => acc + (r[key] ?? r[alt] ?? 0), 0);
    const monthlyTotal = sum('total_monthly_current', 'total_current');
    const monthlyDfc = sum('dfc_monthly_current', 'dfc_current');
    const monthlyGapSum = rows.reduce((acc, r) => acc + monthlyGap(r, threshold), 0);
    return {
      fytd_total: sum('total_fytd'),
      fytd_dfc: sum('dfc_fytd'),
      monthly_total: monthlyTotal,
      monthly_dfc: monthlyDfc,
      monthly_dfc_share: monthlyTotal ? monthlyDfc / monthlyTotal : 0,
      monthly_gap: monthlyGapSum,
      annual_opportunity: monthlyGapSum * 12,
      below_threshold: rows.filter(r => (r.dfc_ratio || 0) < threshold).length,
    };
  }

  function titleSlide(pptx, sourceName, model, portfolio, threshold) {
    const slide = blankSlide(pptx, C.NAVY);
    slide.addText('Defender for Cloud ACR opportunities', { x: 0.55, y: 0.55, w: 8.6, h: 0.65, fontSize: 32, color: C.WHITE, bold: true, fontFace: 'Segoe UI' });
    slide.addText('Executive opportunity readout', { x: 0.58, y: 1.25, w: 5.0, h: 0.35, fontSize: 15, color: C.PALE_BLUE, fontFace: 'Segoe UI' });
    slide.addText(`Source workbook: ${sourceName}`, { x: 0.58, y: 6.75, w: 7.5, h: 0.25, fontSize: 9, color: C.PALE_BLUE, fontFace: 'Segoe UI' });
    slide.addText(`Latest month: ${model.last_full_month || '-'}`, { x: 9.75, y: 0.65, w: 2.6, h: 0.3, fontSize: 11, color: C.PALE_BLUE, align: 'right', fontFace: 'Segoe UI' });

    addStatCard(slide, 'Annualized DfC opportunity', money(portfolio.annual_opportunity), 0.65, 2.25, 3.7, 1.5, C.RED);
    addStatCard(slide, 'Customers below threshold', String(portfolio.below_threshold), 4.75, 2.25, 3.7, 1.5, C.ORANGE);
    addStatCard(slide, 'Portfolio DfC share', pct(portfolio.monthly_dfc_share), 8.85, 2.25, 3.7, 1.5, C.GREEN);

    const narrative = `At a ${threshold.toFixed(0)}% Defender share threshold, the visible portfolio has ${portfolio.below_threshold} customers below target and an estimated ${money(portfolio.annual_opportunity)} annualized DfC ACR run-rate gap.`;
    slide.addText(narrative, { x: 0.75, y: 4.35, w: 11.7, h: 0.8, fontSize: 20, color: C.WHITE, bold: true, fontFace: 'Segoe UI' });
    slide.addText('This deck uses latest monthly ACR for run-rate opportunity sizing and FY-to-date ACR for total-account context.',
      { x: 0.75, y: 5.25, w: 11.2, h: 0.35, fontSize: 12, color: C.PALE_BLUE, fontFace: 'Segoe UI' });
  }

  function portfolioSlide(pptx, model, portfolio, actions, threshold) {
    const slide = blankSlide(pptx);
    addTitle(slide, 'Portfolio snapshot');

    addStatCard(slide, 'FYTD Total ACR', money(portfolio.fytd_total), 0.55, 1.2, 2.9, 1.0, C.BLUE);
    addStatCard(slide, 'FYTD DfC ACR', money(portfolio.fytd_dfc), 3.7, 1.2, 2.9, 1.0, C.GREEN);
    addStatCard(slide, 'Monthly Total ACR', money(portfolio.monthly_total), 6.85, 1.2, 2.9, 1.0, C.BLUE);
    addStatCard(slide, 'Monthly DfC ACR', money(portfolio.monthly_dfc), 10.0, 1.2, 2.9, 1.0, C.GREEN);

    slide.addText('Executive narrative', { x: 0.65, y: 2.65, w: 3.5, h: 0.3, fontSize: 16, color: C.DARK, bold: true, fontFace: 'Segoe UI' });
    const topAct = actions[0];
    const bullets = [
      `Default export threshold: ${threshold.toFixed(0)}% Defender share of latest monthly Total ACR.`,
      `Annualized opportunity is ${money(portfolio.annual_opportunity)}, calculated from monthly gap to threshold times 12.`,
      `Top action account: ${topAct ? topAct.customer : '-'} with ${topAct ? money(topAct.annual_opportunity) : '$0'} annualized opportunity.`,
      'Opportunity priority keeps the dashboard logic: low Defender share, meaningful Azure footprint, and growth gap.',
    ];
    addBullets(slide, bullets, 0.75, 3.05, 5.45, 2.2, 11);

    const labels = model.month_labels || [];
    const totalSeries = (model.product_monthly && model.product_monthly['Total']) || [];
    const dfcSeries = model.dfc_total_monthly || [];
    addLineChart(slide, 'Monthly ACR trend', labels,
      [{ name: 'Total', values: totalSeries, color: C.BLUE }, { name: 'Defender', values: dfcSeries, color: C.GREEN }],
      6.75, 2.65, 5.75, 2.5);

    slide.addText('Note: FYTD values sum months in the latest fiscal year; monthly values are the latest available month.',
      { x: 0.75, y: 6.65, w: 11.5, h: 0.25, fontSize: 9, color: C.MUTED, fontFace: 'Segoe UI' });
  }

  function actionQueueSlide(pptx, actions, threshold) {
    const slide = blankSlide(pptx);
    addTitle(slide, 'Sales action queue');
    slide.addText(`Prioritized at ${threshold.toFixed(0)}% Defender share. Annualized opportunity is a run-rate estimate, not forecast or pipeline.`,
      { x: 0.65, y: 0.95, w: 11.4, h: 0.3, fontSize: 11, color: C.MUTED, fontFace: 'Segoe UI' });
    const headers = ['#', 'Customer', 'Priority', 'FYTD Total', 'Monthly DfC %', 'Annual opp.', 'Recommended action'];
    const data = actions.slice(0, 9).map((row, i) => [
      String(i + 1),
      shortStr(row.customer, 28),
      row.opportunity,
      money(row.total_fytd),
      pct((row.dfc_ratio || 0) / 100),
      money(row.annual_opportunity),
      shortStr(row.recommended_action, 34),
    ]);
    addTable(slide, headers, data, 0.45, 1.45, 12.45, [0.35, 2.45, 0.8, 1.35, 1.05, 1.25, 5.2]);
  }

  function opportunitySlide(pptx, rows) {
    const slide = blankSlide(pptx);
    addTitle(slide, 'Opportunity matrix details');
    slide.addText('Both FYTD and latest monthly ACR are shown to avoid mixing cumulative account context with run-rate opportunity signals.',
      { x: 0.65, y: 0.95, w: 11.8, h: 0.3, fontSize: 11, color: C.MUTED, fontFace: 'Segoe UI' });
    const priorityRank = { High: 0, Medium: 1, Low: 2 };
    const ordered = [...rows].sort((a, b) => {
      const p = priorityRank[a.opportunity] - priorityRank[b.opportunity];
      if (p !== 0) return p;
      return (b.growth_gap || 0) - (a.growth_gap || 0);
    });
    const headers = ['Customer', 'Priority', 'FYTD Total', 'Monthly Total', 'FYTD DfC', 'Monthly DfC', 'DfC %', 'Signal'];
    const data = ordered.slice(0, 10).map(row => [
      shortStr(row.customer, 26),
      row.opportunity,
      money(row.total_fytd || 0),
      money(row.total_monthly_current ?? row.total_current ?? 0),
      money(row.dfc_fytd || 0),
      money(row.dfc_monthly_current ?? row.dfc_current ?? 0),
      pct((row.dfc_ratio || 0) / 100),
      shortStr(row.notes || '-', 44),
    ]);
    addTable(slide, headers, data, 0.35, 1.35, 12.65, [2.2, 0.75, 1.25, 1.25, 1.15, 1.15, 0.65, 4.25]);
  }

  function customerSlide(pptx, model, row, threshold) {
    const slide = blankSlide(pptx);
    const customer = row.customer;
    const data = (model.customer_data || {})[customer] || {};
    const labels = model.month_labels || [];

    addTitle(slide, customer);
    slide.addText(row.recommended_action, { x: 0.65, y: 0.95, w: 6.0, h: 0.35, fontSize: 14, color: C.RED, bold: true, fontFace: 'Segoe UI' });

    addStatCard(slide, 'FYTD Total ACR', money(row.total_fytd || 0), 0.55, 1.45, 2.5, 0.9, C.BLUE);
    addStatCard(slide, 'Monthly Total ACR', money(row.total_monthly_current || 0), 3.25, 1.45, 2.5, 0.9, C.BLUE);
    addStatCard(slide, 'Monthly DfC share', pct((row.dfc_ratio || 0) / 100), 5.95, 1.45, 2.5, 0.9, C.ORANGE);
    addStatCard(slide, 'Annualized opp.', money(row.annual_opportunity || 0), 8.65, 1.45, 2.5, 0.9, C.RED);

    addLineChart(slide, 'Customer monthly ACR trend', labels,
      [
        { name: 'Total', values: data.total_series || [], color: C.BLUE },
        { name: 'Defender', values: data.dfc_series || [], color: C.GREEN },
      ],
      0.65, 2.75, 5.8, 2.25);

    const share = shareSeries(data.dfc_series || [], data.total_series || []);
    addLineChart(slide, 'Defender share trend', labels,
      [{ name: 'DfC share', values: share, color: C.ORANGE }],
      6.85, 2.75, 5.8, 2.25, { percentAxis: true });

    const products = (data.products || []).filter(p => p.product !== DEFENDER && (p.current || 0) > 0).slice(0, 2);
    const bullets = [row.conversation_angle, row.action_reason,
      ...products.map(p => `${p.product}: ${money(p.current)} monthly ACR, 3M ${signedPct(p.three_m)}`)];
    slide.addText('Recommended follow-up', { x: 0.65, y: 5.45, w: 2.8, h: 0.3, fontSize: 15, color: C.DARK, bold: true, fontFace: 'Segoe UI' });
    addBullets(slide, bullets, 0.75, 5.85, 11.3, 1.25, 9);
    slide.addText(`Threshold basis: ${threshold.toFixed(0)}% of latest monthly Total ACR.`,
      { x: 9.0, y: 0.95, w: 3.2, h: 0.25, fontSize: 9, color: C.MUTED, align: 'right', fontFace: 'Segoe UI' });
  }

  async function exportDeck(model, sourceName, threshold) {
    threshold = threshold ?? DEFAULT_THRESHOLD;
    sourceName = sourceName || model.source_name || 'Workbook';
    const pptx = new PptxGenJS();
    pptx.layout = 'LAYOUT_WIDE'; // 13.333 x 7.5
    pptx.title = 'Defender for Cloud ACR opportunities';

    const visibleRows = (model.opportunity || []).filter(r => r.opportunity !== 'Too small');
    const actions = actionRows(model, threshold);
    const portfolio = portfolioSummary(model, threshold);

    titleSlide(pptx, sourceName, model, portfolio, threshold);
    portfolioSlide(pptx, model, portfolio, actions, threshold);
    actionQueueSlide(pptx, actions, threshold);
    opportunitySlide(pptx, visibleRows);
    actions.slice(0, 3).forEach(row => customerSlide(pptx, model, row, threshold));

    const today = new Date().toISOString().slice(0, 10);
    await pptx.writeFile({ fileName: `defender-acr-opportunities-${today}.pptx` });
  }

  window.PptxAcr = { exportDeck };
})();
