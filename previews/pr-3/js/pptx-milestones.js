// pptx-milestones.js — Builds the milestone gaps PowerPoint deck client-side.
// Mirrors src/defender_acr_dashboard/milestone_export.py.
(() => {
  const C = {
    BLUE: '0078D4', NAVY: '0F3A5F', DARK: '201F1E', TEXT: '323130',
    MUTED: '605E5C', LIGHT_BG: 'F5F7FB', BORDER: 'D9E2EC',
    RED: 'D13438', ORANGE: 'FF8C00', GREEN: '107C10', WHITE: 'FFFFFF',
    PALE_BLUE: 'C7E0F4',
  };

  function shortStr(s, max) {
    s = String(s ?? '');
    return s.length > max ? s.slice(0, Math.max(1, max - 1)) + '…' : s;
  }
  function fmtInt(n) { return Number(n || 0).toLocaleString('en-US'); }

  function blankSlide(pptx, bg) {
    const slide = pptx.addSlide();
    slide.background = { color: bg || C.WHITE };
    return slide;
  }

  function addTitle(slide, title) {
    slide.addText(title, { x: 0.55, y: 0.45, w: 8.0, h: 0.45, fontSize: 24, color: C.DARK, bold: true, fontFace: 'Segoe UI' });
  }

  function addStatCard(slide, label, value, x, y, w, h, accent) {
    slide.addShape('rect', { x, y, w, h, fill: { color: C.WHITE }, line: { color: C.BORDER, width: 0.75 } });
    slide.addShape('rect', { x, y, w: 0.08, h, fill: { color: accent }, line: { color: accent } });
    slide.addText(label.toUpperCase(), { x: x + 0.18, y: y + 0.16, w: w - 0.3, h: 0.24, fontSize: 9, color: C.MUTED, bold: true, fontFace: 'Segoe UI' });
    slide.addText(value, { x: x + 0.18, y: y + 0.48, w: w - 0.3, h: 0.52, fontSize: 24, color: C.DARK, bold: true, fontFace: 'Segoe UI' });
  }

  function addBarList(slide, rows, x, y, w, h) {
    const max = Math.max(1, ...rows.map(r => r[1] || 0));
    const rowH = h / Math.max(rows.length, 1);
    rows.forEach(([label, value, color], i) => {
      const top = y + i * rowH;
      slide.addText(label, { x, y: top, w: 1.65, h: 0.24, fontSize: 10, color: C.TEXT, bold: true, fontFace: 'Segoe UI' });
      slide.addText(fmtInt(value), { x: x + w - 0.65, y: top, w: 0.6, h: 0.24, fontSize: 10, color: C.TEXT, align: 'right', fontFace: 'Segoe UI' });
      const trackX = x + 1.8, trackW = w - 2.6;
      slide.addShape('rect', { x: trackX, y: top + 0.04, w: trackW, h: 0.16, fill: { color: C.LIGHT_BG }, line: { color: C.LIGHT_BG } });
      const barW = Math.max(0.02, trackW * ((value || 0) / max));
      slide.addShape('rect', { x: trackX, y: top + 0.04, w: barW, h: 0.16, fill: { color }, line: { color } });
    });
  }

  function addTable(slide, headers, rows, x, y, w, colW) {
    const headerRow = headers.map(h => ({
      text: h,
      options: { bold: true, color: C.WHITE, fill: { color: C.NAVY }, fontSize: 8, valign: 'middle', fontFace: 'Segoe UI' },
    }));
    const body = rows.map(r => r.map(cell => ({
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
    const text = items.filter(Boolean).map(t => ({ text: t, options: { bullet: { code: '2022' }, breakLine: true } }));
    slide.addText(text, { x, y, w, h, fontSize: 15, color: C.TEXT, fontFace: 'Segoe UI', valign: 'top', paraSpaceAfter: 4 });
  }

  function titleSlide(pptx, model) {
    const slide = blankSlide(pptx, C.NAVY);
    const summary = model.summary || {};
    const sources = model.sources || {};
    slide.addText('Defender milestone attach gaps', { x: 0.6, y: 0.55, w: 8.8, h: 0.65, fontSize: 32, color: C.WHITE, bold: true, fontFace: 'Segoe UI' });
    slide.addText('Migration milestones compared with Defender for Cloud milestones',
      { x: 0.62, y: 1.24, w: 7.5, h: 0.35, fontSize: 15, color: C.PALE_BLUE, fontFace: 'Segoe UI' });
    slide.addText(`Reference date: ${model.reference_date || '-'} | Near-term window: ${model.near_term_days || '-'} days`,
      { x: 0.62, y: 6.55, w: 7.8, h: 0.3, fontSize: 10, color: C.PALE_BLUE, fontFace: 'Segoe UI' });
    slide.addText(`Sources: ${sources.migration || '-'} + ${sources.defender || '-'}`,
      { x: 0.62, y: 6.85, w: 10.8, h: 0.25, fontSize: 9, color: C.PALE_BLUE, fontFace: 'Segoe UI' });

    addStatCard(slide, 'Accounts with gaps', fmtInt(summary.total_accounts_with_gaps), 0.75, 2.25, 3.4, 1.45, C.RED);
    addStatCard(slide, 'Opportunities with gaps', fmtInt(summary.total_opportunities_with_gaps), 4.95, 2.25, 3.4, 1.45, C.ORANGE);
    addStatCard(slide, 'Attached accounts', fmtInt(summary.attached_accounts), 9.15, 2.25, 3.4, 1.45, C.GREEN);

    slide.addText('Opportunity-level gaps use a strict same-account and same-Opportunity-ID comparison.',
      { x: 0.75, y: 4.45, w: 11.8, h: 0.5, fontSize: 20, color: C.WHITE, bold: true, fontFace: 'Segoe UI' });
  }

  function summarySlide(pptx, model) {
    const slide = blankSlide(pptx);
    addTitle(slide, 'Gap summary');
    const summary = model.summary || {};
    const pri = model.priority_counts || {};
    const gt = model.gap_type_counts || {};

    addStatCard(slide, 'Migration accounts', fmtInt(summary.migration_accounts), 0.55, 1.1, 2.6, 0.95, C.BLUE);
    addStatCard(slide, 'Defender accounts', fmtInt(summary.defender_accounts), 3.35, 1.1, 2.6, 0.95, C.GREEN);
    addStatCard(slide, 'Account gaps', fmtInt(summary.account_level_gap_accounts), 6.15, 1.1, 2.6, 0.95, C.RED);
    addStatCard(slide, 'Opportunity gaps', fmtInt(summary.opportunity_level_gaps), 8.95, 1.1, 2.6, 0.95, C.ORANGE);

    slide.addText('Priority mix', { x: 0.75, y: 2.65, w: 3.0, h: 0.3, fontSize: 16, color: C.DARK, bold: true, fontFace: 'Segoe UI' });
    addBarList(slide, [
      ['HIGH', pri.HIGH || 0, C.RED],
      ['MEDIUM', pri.MEDIUM || 0, C.ORANGE],
      ['LOW', pri.LOW || 0, C.GREEN],
    ], 0.75, 3.05, 5.4, 1.45);

    slide.addText('Gap type mix', { x: 6.8, y: 2.65, w: 3.0, h: 0.3, fontSize: 16, color: C.DARK, bold: true, fontFace: 'Segoe UI' });
    addBarList(slide, [
      ['Account-level gap', gt['Account-level gap'] || 0, C.RED],
      ['Opportunity-level gap', gt['Opportunity-level gap'] || 0, C.ORANGE],
    ], 6.8, 3.05, 5.4, 1.1);

    slide.addText('High priority means at least one committed migration milestone or an estimated date inside the near-term window.',
      { x: 0.75, y: 6.55, w: 11.4, h: 0.3, fontSize: 10, color: C.MUTED, fontFace: 'Segoe UI' });
  }

  function topGapsSlide(pptx, model) {
    const slide = blankSlide(pptx);
    addTitle(slide, 'Top 10 highest priority gaps');
    const headers = ['#', 'Account', 'Opportunity', 'Gap type', 'Workload', 'Date', 'Priority'];
    const rows = (model.top_gaps || []).slice(0, 10).map((row, i) => [
      String(i + 1),
      shortStr(row.account, 26),
      shortStr(row.opportunity_id, 14),
      row.gap_type && row.gap_type.startsWith('Account') ? 'Account' : 'Opportunity',
      shortStr(row.workload, 34),
      row.estimated_date || '-',
      row.priority,
    ]);
    addTable(slide, headers, rows, 0.35, 1.15, 12.65, [0.35, 2.35, 1.3, 1.15, 4.25, 1.0, 0.8]);
  }

  function methodologySlide(pptx, model) {
    const slide = blankSlide(pptx);
    addTitle(slide, 'Methodology and interpretation');
    const bullets = [
      'Account-level gap: an account has Migration milestones but no Defender for Cloud milestones in the Defender workbook.',
      'Attached account: an account appears in both Migration and Defender milestone workbooks.',
      'Opportunity-level gap: for attached accounts, a Migration Opportunity ID has no Defender milestone with the same Opportunity ID.',
      `HIGH priority: committed migration milestone or estimated date within ${model.near_term_days || '-'} days of the reference date.`,
      'MEDIUM priority: uncommitted migration milestone with a recognized workload.',
      'LOW priority: unclear or edge-case workload.',
      'Strict Opportunity ID matching may overstate gaps if Migration and Defender work are tracked under separate CRM opportunities.',
    ];
    addBullets(slide, bullets, 0.75, 1.2, 11.8, 4.8);
  }

  async function exportDeck(model) {
    const pptx = new PptxGenJS();
    pptx.layout = 'LAYOUT_WIDE';
    pptx.title = 'Defender milestone attach gaps';
    titleSlide(pptx, model);
    summarySlide(pptx, model);
    topGapsSlide(pptx, model);
    methodologySlide(pptx, model);
    const today = new Date().toISOString().slice(0, 10);
    await pptx.writeFile({ fileName: `defender-milestone-gaps-${today}.pptx` });
  }

  window.PptxMilestones = { exportDeck };
})();
