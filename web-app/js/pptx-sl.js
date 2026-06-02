// pptx-sl.js — Builds the service-attach (SL2/SL4) PowerPoint deck client-side.
// Mirrors the executive narrative: corp headline → manager book → top
// cross-book opportunities → methodology. Reuses the milestone deck's visual
// language (color palette, stat cards, tables) for a consistent house style.
(() => {
  'use strict';

  const C = {
    BLUE: '0078D4', NAVY: '0F3A5F', DARK: '201F1E', TEXT: '323130',
    MUTED: '605E5C', LIGHT_BG: 'F5F7FB', BORDER: 'D9E2EC',
    RED: 'D13438', ORANGE: 'FF8C00', GREEN: '107C10', WHITE: 'FFFFFF',
    PALE_BLUE: 'C7E0F4',
  };

  function shortStr(s, max) {
    s = String(s == null ? '' : s);
    return s.length > max ? s.slice(0, Math.max(1, max - 1)) + '…' : s;
  }
  function money(n) {
    if (!Number.isFinite(n)) return '$0';
    return '$' + Math.round(n).toLocaleString('en-US');
  }
  function pct(n) {
    if (!Number.isFinite(n)) return 'n/a';
    return (n * 100).toFixed(1) + '%';
  }
  function growth(n) {
    if (!Number.isFinite(n)) return 'n/a';
    return (n > 0 ? '+' : '') + (n * 100).toFixed(0) + '%';
  }

  function blankSlide(pptx, bg) {
    const slide = pptx.addSlide();
    slide.background = { color: bg || C.WHITE };
    return slide;
  }

  function addTitle(slide, title) {
    slide.addText(title, { x: 0.55, y: 0.45, w: 12.0, h: 0.45, fontSize: 24, color: C.DARK, bold: true, fontFace: 'Segoe UI' });
  }

  function addStatCard(slide, label, value, x, y, w, h, accent) {
    slide.addShape('rect', { x, y, w, h, fill: { color: C.WHITE }, line: { color: C.BORDER, width: 0.75 } });
    slide.addShape('rect', { x, y, w: 0.08, h, fill: { color: accent }, line: { color: accent } });
    slide.addText(label.toUpperCase(), { x: x + 0.18, y: y + 0.16, w: w - 0.3, h: 0.24, fontSize: 9, color: C.MUTED, bold: true, fontFace: 'Segoe UI' });
    slide.addText(value, { x: x + 0.18, y: y + 0.48, w: w - 0.3, h: 0.52, fontSize: 22, color: C.DARK, bold: true, fontFace: 'Segoe UI' });
  }

  function addTable(slide, headers, rows, x, y, w, colW) {
    const headerRow = headers.map((h) => ({
      text: h,
      options: { bold: true, color: C.WHITE, fill: { color: C.NAVY }, fontSize: 8, valign: 'middle', fontFace: 'Segoe UI' },
    }));
    const body = rows.map((r) => r.map((cell) => ({
      text: String(cell == null ? '' : cell),
      options: { fontSize: 7, color: C.TEXT, valign: 'middle', fontFace: 'Segoe UI' },
    })));
    slide.addTable([headerRow, ...body], {
      x, y, w, colW,
      border: { type: 'solid', pt: 0.25, color: C.BORDER },
      autoPage: false,
    });
  }

  function addBullets(slide, items, x, y, w, h) {
    const text = items.filter(Boolean).map((t) => ({ text: t, options: { bullet: { code: '2022' }, breakLine: true } }));
    slide.addText(text, { x, y, w, h, fontSize: 14, color: C.TEXT, fontFace: 'Segoe UI', valign: 'top', paraSpaceAfter: 6 });
  }

  // Flatten every opportunity across the book, tagging each with its customer,
  // so the executive view can rank conversation starters globally.
  function flattenOpportunities(model) {
    const all = [];
    for (const d of model.dossiers) {
      for (const o of d.opportunities) all.push({ customer: d.customer, opp: o });
    }
    all.sort((a, b) => b.opp.blendedScore - a.opp.blendedScore);
    return all;
  }

  function titleSlide(pptx, model) {
    const slide = blankSlide(pptx, C.NAVY);
    slide.addText('Defender for Cloud — service attach', { x: 0.6, y: 0.55, w: 11.8, h: 0.65, fontSize: 32, color: C.WHITE, bold: true, fontFace: 'Segoe UI' });
    slide.addText('Where customers buy a workload but do not protect it with the matching Defender plan',
      { x: 0.62, y: 1.24, w: 11.5, h: 0.35, fontSize: 15, color: C.PALE_BLUE, fontFace: 'Segoe UI' });

    addStatCard(slide, 'Book attach ratio', pct(model.bookAttachRatio), 0.75, 2.25, 3.0, 1.45, C.RED);
    addStatCard(slide, 'Defender for Cloud ACR', money(model.totalDfcAcr) + '/mo', 3.95, 2.25, 3.0, 1.45, C.GREEN);
    addStatCard(slide, 'Eligible workload ACR', money(model.totalEligibleWorkloadAcr) + '/mo', 7.15, 2.25, 3.0, 1.45, C.BLUE);
    addStatCard(slide, 'Quantified gap', money(model.totalGapDollars) + '/mo', 10.35, 2.25, 2.2, 1.45, C.ORANGE);

    slide.addText(`${model.dossiers.length} customers in book · attach ratio = Defender for Cloud $ ÷ eligible mapped-workload $.`,
      { x: 0.75, y: 4.3, w: 11.8, h: 0.5, fontSize: 18, color: C.WHITE, bold: true, fontFace: 'Segoe UI' });

    slide.addText(`Source: ${model.sourceName || '-'} · Latest month: ${model.latestMonth || '-'}`,
      { x: 0.62, y: 6.85, w: 11.8, h: 0.25, fontSize: 9, color: C.PALE_BLUE, fontFace: 'Segoe UI' });
  }

  function leaderboardSlide(pptx, model) {
    const slide = blankSlide(pptx);
    addTitle(slide, 'Manager book — top attach opportunities by customer');
    const headers = ['#', 'Customer', 'Score', 'Attach %', 'Eligible $/mo', 'DfC $/mo', 'Gap $/mo', 'Unprotected'];
    const rows = model.dossiers.slice(0, 14).map((d, i) => [
      String(i + 1),
      shortStr(d.customer, 30),
      Math.round(d.customerScore),
      pct(d.attachRatio),
      money(d.eligibleWorkloadAcr),
      money(d.dfcAcr),
      money(d.totalGapDollars),
      `${d.uncoveredEligibleCount}/${d.presentEligibleCount}`,
    ]);
    addTable(slide, headers, rows, 0.35, 1.15, 12.65, [0.4, 3.1, 0.8, 1.1, 1.7, 1.5, 1.5, 1.35]);
    slide.addText('Score blends $ gap, momentum (workload outpacing Defender), and breadth of unprotected workloads.',
      { x: 0.35, y: 6.85, w: 12.4, h: 0.3, fontSize: 10, color: C.MUTED, fontFace: 'Segoe UI' });
  }

  function topOpportunitiesSlide(pptx, model) {
    const slide = blankSlide(pptx);
    addTitle(slide, 'Top conversation starters across the book');
    const headers = ['#', 'Customer', 'Defender plan', 'Signal', 'Workload $/mo', 'DfC $/mo', 'Gap $/mo', 'WL 3m', 'Score'];
    const rows = flattenOpportunities(model).slice(0, 14).map((item, i) => {
      const o = item.opp;
      return [
        String(i + 1),
        shortStr(item.customer, 24),
        shortStr(o.planLabel, 22),
        o.signal === 'attach' ? 'Attach' : 'Expand',
        money(o.workloadAcr),
        money(o.defenderActual),
        o.hasDollarGap ? money(o.gapDollars) : 'signal',
        growth(o.workloadGrowth),
        Math.round(o.blendedScore),
      ];
    });
    addTable(slide, headers, rows, 0.35, 1.15, 12.65, [0.4, 2.5, 2.4, 1.0, 1.6, 1.4, 1.4, 0.95, 0.85]);
    slide.addText('"Attach" = workload present, Defender plan absent/low. "Expand" = Defender present but below benchmark. "signal" = unit-priced plan, no $ benchmark.',
      { x: 0.35, y: 6.85, w: 12.4, h: 0.3, fontSize: 10, color: C.MUTED, fontFace: 'Segoe UI' });
  }

  function methodologySlide(pptx, model) {
    const slide = blankSlide(pptx);
    addTitle(slide, 'Methodology and interpretation');
    const ratio = model.config && Number.isFinite(model.config.targetRatio)
      ? (model.config.targetRatio * 100).toFixed(1) + '%' : '6%';
    const bullets = [
      'Each Azure workload (e.g. Containers, SQL, Storage, Servers) is mapped to the Defender for Cloud plan that protects it.',
      `Benchmark spend per plan = workload ACR × target attach ratio (default ${ratio}, configurable, with cohort-median fallback).`,
      'Benchmark gap $/mo = max(0, benchmark − actual Defender plan spend). Only medium/high-confidence, value-priced plans get a $ benchmark.',
      'Unit-priced plans (Servers per-node, Storage per-transaction) are shown as coverage signals — workload present, Defender absent — with no fabricated dollar gap.',
      'Momentum compares 3-month workload growth against Defender-plan growth; a workload growing while Defender is flat is a strong attach trigger.',
      'Attach ratio denominator is eligible mapped-workload ACR only, excluding non-Azure consumption (e.g. Power BI, GitHub) for a fair penetration read.',
      'Customer subtotals are reconciled against independent leaf sums; mismatches are flagged in the dossier so figures stay trustworthy.',
    ];
    addBullets(slide, bullets, 0.6, 1.2, 12.2, 5.2);
  }

  async function exportDeck(model) {
    const pptx = new PptxGenJS();
    pptx.layout = 'LAYOUT_WIDE';
    pptx.title = 'Defender for Cloud service attach';
    titleSlide(pptx, model);
    leaderboardSlide(pptx, model);
    topOpportunitiesSlide(pptx, model);
    methodologySlide(pptx, model);
    const today = new Date().toISOString().slice(0, 10);
    await pptx.writeFile({ fileName: `defender-service-attach-${today}.pptx` });
  }

  window.PptxSl = { exportDeck };
})();
