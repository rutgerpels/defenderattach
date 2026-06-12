// Regression tests for the static web app. Run from repo root or web-app/:
//   node web-app/tests/regression.cjs
// Exits non-zero on any failure. No external dependencies.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEBAPP = path.resolve(__dirname, '..');
const LANDING_PAGE = 'index.html';
const ACR_PAGE = 'acr.html';
function loadInto(sb, rel) {
  vm.runInContext(fs.readFileSync(path.join(WEBAPP, rel), 'utf8'), sb, { filename: rel });
}
function makeSandbox() {
  const captured = [];
  const sb = {
    console,
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} },
    Blob: class { constructor(parts) { captured.push((parts || []).join('')); } },
    setTimeout, clearTimeout,
    _csvParts: captured,
  };
  sb.window = sb; sb.self = sb; sb.globalThis = sb;
  sb.document = {
    addEventListener() {},
    body: { appendChild() {}, removeChild() {} },
    createElement: () => ({
      _href: '', set href(v) { this._href = v; }, get href() { return this._href; },
      download: '', click() {}, remove() {}, setAttribute() {}, style: {},
    }),
  };
  vm.createContext(sb);
  return sb;
}

let pass = 0, fail = 0, skip = 0;
function test(name, fn) {
  try { fn(); console.log('  PASS ' + name); pass++; }
  catch (e) { console.log('  FAIL ' + name + '\n      ' + (e.stack || e.message)); fail++; }
}
function skipTest(name, reason) { console.log('  SKIP ' + name + ' (' + reason + ')'); skip++; }
function assert(cond, msg) { if (!cond) throw new Error('assertion failed: ' + msg); }
function assertEqual(actual, expected, msg) {
  if (actual !== expected) throw new Error(`${msg || ''}\n      expected: ${JSON.stringify(expected)}\n      actual:   ${JSON.stringify(actual)}`);
}

// ---- index.html: landing page regressions ----
console.log('\nweb-app/index.html (landing)');
{
  const src = fs.readFileSync(path.join(WEBAPP, LANDING_PAGE), 'utf8');

  test('landing page links to both dashboards without an upload gate', () => {
    assert(/href="acr\.html"/.test(src), 'landing page must link to the ACR dashboard');
    assert(/href="milestones\.html"/.test(src), 'landing page must link to the milestone dashboard');
    assert(!/id="splash"/.test(src), 'landing page must not include the ACR splash overlay');
    assert(!/id="splash-import-btn"/.test(src), 'landing page must not require ACR upload before navigation');
    assert(!/id="file-input"/.test(src), 'landing page must not include dashboard file input');
    assert(!/xlsx\.full\.min\.js/.test(src), 'landing page must not load the Excel parser');
  });
}

// ---- acr.html: generated-artifact regressions ----
console.log('\nweb-app/acr.html (generated)');
{
  const src = fs.readFileSync(path.join(WEBAPP, ACR_PAGE), 'utf8');
  const appNavSrc = fs.readFileSync(path.join(WEBAPP, 'js', 'app-nav.js'), 'utf8');

  test('uses vendored SheetJS, not CDN', () => {
    assert(!/cdn\.sheetjs\.com/.test(src), 'CDN SheetJS URL must not appear');
    assert(/<script src="\.\/vendor\/xlsx\.full\.min\.js"><\/script>/.test(src), 'expected vendored xlsx script tag');
  });
  test('uses AcrModel.build instead of parseAndScore', () => {
    assert(/const newData = AcrModel\.build\(rows, file\.name\);/.test(src),
      'import handler must delegate to AcrModel.build');
    assert(!/= parseAndScore\(/.test(src), 'parseAndScore call must be replaced');
  });
  test('sales-plan placeholder replaces the visible PowerPoint export button', () => {
    assert(/id="build-sales-plan-btn"/.test(appNavSrc), 'sales-plan placeholder must exist in the shared topbar');
    assert(/Build sales plan/.test(appNavSrc), 'placeholder must be labeled Build sales plan');
    assert(!/id="export-pptx-btn"/.test(appNavSrc), 'old export button must not be visible in the shared topbar');
    assert(!/getElementById\('export-pptx-btn'\)/.test(src), 'old export click handler must not be wired in generated HTML');
  });
  test('shared nav links home, ACR, and milestones without gating navigation', () => {
    assert(/href="index\.html"/.test(appNavSrc), 'shared nav must link back to the landing page');
    assert(/href="acr\.html"/.test(appNavSrc), 'shared nav must link to the generated ACR dashboard');
    assert(/href="milestones\.html"/.test(appNavSrc), 'shared nav must link to the milestone dashboard');
  });
  test('overview guide sits above tabs and opens an accessible sales explanation modal', () => {
    const guideIndex = src.indexOf('id="overview-guide-trigger"');
    const tabsIndex = src.indexOf('<div class="tabs">');
    assert(guideIndex >= 0, 'overview guide trigger must exist');
    assert(tabsIndex >= 0, 'tabs container must exist');
    assert(guideIndex < tabsIndex, 'overview guide trigger must appear above tabs');
    assert(/<button class="note guide-note" id="overview-guide-trigger" type="button" aria-haspopup="dialog" aria-controls="view-guide-modal">/.test(src),
      'guide trigger must be a dialog button');
    assert(/id="view-guide-modal" role="dialog" aria-modal="true"/.test(src),
      'guide modal must expose dialog semantics');
    assert(/Which view should I use\?/.test(src), 'guide modal title must be present');
    assert(/Service Attach Opportunities/.test(src), 'service attach guidance must be included');
    assert(/Defender Coverage Drift/.test(src), 'coverage drift guidance must be included');
    assert(/event\.target === modal/.test(src), 'guide modal must close on backdrop click');
    assert(/event\.key === 'Escape' && !modal\.hidden/.test(src), 'guide modal must close on Escape');
    assert(/returnFocusTo\.focus\(\)/.test(src), 'guide modal must return focus to trigger');
  });
  test('renderOpportunityHeatmap escapes customer + derived fields', () => {
    const start = src.indexOf('function renderOpportunityHeatmap()');
    assert(start >= 0, 'renderOpportunityHeatmap function must exist in generated HTML');
    // Inspect the next ~6 KB — comfortably covers the function body.
    const body = src.slice(start, start + 6000);
    assert(/\$\{escapeHtml\(r\.customer\)\}/.test(body), 'customer must be escaped in heatmap');
    assert(/\$\{escapeHtml\(r\.topServiceLabel\)\}/.test(body), 'top gap service label must be escaped in heatmap');
    assert(/\$\{escapeHtml\(r\.actionReason\)\}/.test(body), 'signal/reason must be escaped in heatmap');
    assert(!/\$\{r\.customer\}/.test(body), 'no raw r.customer interpolation in heatmap');
    assert(!/\$\{r\.notes\}/.test(body), 'no raw r.notes interpolation in heatmap');
  });
  test('SVG chart helpers escape Excel-derived customer labels', () => {
    // barChartHorizontal: <text> body, data-customer attribute, tooltip readback.
    assert(/\$\{escapeHtml\(d\.label\.length > 28/.test(src),
      'bar chart label text must go through escapeHtml');
    assert(/data-customer="\$\{escapeHtml\(d\.label\)\}"/.test(src),
      'bar chart data-customer must use escapeHtml, not quote-only escape');
    assert(/<b>\$\{escapeHtml\(r\.getAttribute\('data-customer'\)\)\}<\/b>/.test(src),
      'bar chart tooltip must escape data-customer readback');
    // quadrantChart (both definitions): bubble attribute, direct label, tooltip.
    const quadrantAttrCount = (src.match(/data-customer="\$\{escapeHtml\(p\.label\)\}"/g) || []).length;
    assert(quadrantAttrCount === 2, `expected 2 quadrant data-customer attrs, found ${quadrantAttrCount}`);
    const quadrantLabelCount = (src.match(/>\$\{escapeHtml\(truncated\)\}<\/text>/g) || []).length;
    assert(quadrantLabelCount === 2, `expected 2 quadrant direct labels, found ${quadrantLabelCount}`);
    const quadrantTooltipCount = (src.match(/<b>\$\{escapeHtml\(c\.getAttribute\('data-customer'\)\)\}<\/b>/g) || []).length;
    assert(quadrantTooltipCount === 2, `expected 2 quadrant tooltip escapes, found ${quadrantTooltipCount}`);
    // Negative: no quote-only escapes left in chart label interpolations.
    assert(!/\.label\.replace\(\/"\/g, '&quot;'\)/.test(src),
      'no .label.replace(/"/g, "&quot;") quote-only escape may remain');
  });
  test('csvCell guards against CSV formula injection', () => {
    assert(/CSV_FORMULA_LEADERS = \['=', '\+', '-', '@', '\\t', '\\r'\]/.test(src),
      'expected CSV_FORMULA_LEADERS allowlist');
    assert(/CSV_FORMULA_LEADERS\.includes\(s\.charAt\(0\)\)/.test(src),
      'csvCell must check leading character against CSV_FORMULA_LEADERS');
  });
  test('ships with empty bundled DATA (no customer leakage)', () => {
    const m = src.match(/let DATA = \{([\s\S]+?)\};/);
    assert(m, 'DATA literal must exist');
    assert(/customers: \[\]/.test(m[1]) && /opportunity: \[\]/.test(m[1]),
      'bundled DATA must start empty');
  });
  test('shared app nav + ACR-specific scripts are loaded without retired ACR PowerPoint export', () => {
    for (const tag of [
      '<div id="app-nav" data-active="acr"></div>',
      './js/acr-model.js',
      './js/app-nav.js',
    ]) {
      assert(src.includes(tag), `expected to find ${tag}`);
    }
    assert(!src.includes('./js/pptx-acr.js'), 'retired ACR PowerPoint script must not load on the ACR page');
    assert(!src.includes('./vendor/pptxgen.bundle.js'), 'PptxGenJS must not load on the ACR page while export is retired');
  });
  test('nav has fixed app shell layout (regression: shell CSS must be injected)', () => {
    assert(/#app-nav \.app-topbar \{[\s\S]{0,400}position:\s*fixed/.test(src),
      'topbar must be fixed — nav CSS not injected');
    assert(/#app-nav \.app-sidebar \{[\s\S]{0,400}position:\s*fixed/.test(src),
      'sidebar must be fixed — nav CSS not injected');
    assert(/#app-nav \.app-menu \{[\s\S]{0,400}display:\s*grid/.test(src),
      'app-menu must have grid layout — nav CSS not injected');
    assert(/#app-nav \.app-menu a\.active/.test(src), 'active link styling required');
    assert(/#app-nav \.source-pill/.test(src), 'source pill styling required');
  });
  test('empty-state splash is present and hides on import', () => {
    assert(/id="splash"/.test(src), 'splash overlay must exist');
    assert(/id="splash-import-btn"/.test(src), 'splash must have an import button');
    assert(/id="splash-dropzone"/.test(src), 'splash must have a drag-and-drop zone');
    assert(/splash\.hidden = true/.test(src), 'splash must be hidden after a successful import');
    assert(/function renderAll\(\) \{\s*if \(!DATA\.customers \|\| DATA\.customers\.length === 0\) return;/.test(src),
      'renderAll must bail out when DATA is empty (prevents broken empty charts)');
  });
  test('dropzone wires drag-and-drop into the existing file input', () => {
    assert(/dz\.addEventListener\('drop'/.test(src), 'dropzone must handle drop event');
    assert(/fileInput\.files = dt\.files/.test(src), 'dropped file must be assigned to #file-input');
    assert(/fileInput\.dispatchEvent\(new Event\('change'/.test(src),
      'dropped file must trigger the existing change handler');
    assert(/\\\.\(xlsx\|xls\)\$\/i\.test\(file\.name\)/.test(src),
      'dropped file extension must be validated');
  });
  test('ACR data is persisted to sessionStorage across navigation', () => {
    assert(/ACR_CACHE_KEY = 'defenderattach:acr:v3'/.test(src),
      'versioned sessionStorage key must be defined (v3 invalidates pre-product_skus caches)');
    assert(/sessionStorage\.setItem\(ACR_CACHE_KEY, json\)/.test(src),
      'must cache DATA after successful import');
    assert(/sessionStorage\.getItem\(ACR_CACHE_KEY\)/.test(src),
      'must restore DATA on page load');
    assert(/AppNav\.onReload\(function\(\)\{[\s\S]{0,200}sessionStorage\.removeItem\(ACR_CACHE_KEY\)/.test(src),
      'AppNav reload handler must clear the cache');
  });
  test('Customer Drill-Down has escaped Sales Stories cards and copy action', () => {
    assert(/function renderCustomerSalesStories\(idp, name\)/.test(src),
      'customer sales stories renderer must exist');
    assert(/function customerDivergenceStories\(name\)/.test(src),
      'customer divergence story selector must exist');
    assert(/id="cust-sales-stories"/.test(src),
      'inline customer sales stories mount must exist');
    assert(/id="m-cust-sales-stories"/.test(src),
      'modal customer sales stories mount must exist');
    assert(/renderCustomerSalesStories\(idp, name\);/.test(src),
      'id-prefixed render call must run from customer detail');
    assert(/data-customer-stories-copy/.test(src),
      'compact copy action must be wired');
    assert(/No sales stories detected for this customer yet\./.test(src),
      'quiet no-story empty state must exist');
    const start = src.indexOf('function renderCustomerSalesStories(idp, name)');
    assert(start >= 0, 'renderCustomerSalesStories function missing');
    const body = src.slice(start, start + 9000);
    for (const expr of [
      'escapeHtml(headline)',
      'escapeHtml(plan)',
      'escapeHtml(_storyTypeLabel(s))',
      'escapeHtml(severity)',
      'escapeHtml(_storyTrendLine(s))',
      'escapeHtml(momentum)',
      'escapeHtml(item)',
      'escapeHtml(pricing)',
      'escapeHtml(caveat)',
      'escapeHtml(action)',
    ]) {
      assert(body.includes(expr), `expected ${expr} in sales story renderer`);
    }
  });
}

// ---- milestone-app persistence ----
console.log('\nmilestone-app.js');
{
  const ms = fs.readFileSync(path.join(WEBAPP, 'js', 'milestone-app.js'), 'utf8');
  test('milestone data is persisted to sessionStorage across navigation', () => {
    assert(/CACHE_KEY = 'defenderattach:milestones:v1'/.test(ms),
      'versioned sessionStorage key must be defined');
    assert(/sessionStorage\.setItem\(CACHE_KEY, payload\)/.test(ms),
      'must cache rows + filenames after each successful file load');
    assert(/sessionStorage\.getItem\(CACHE_KEY\)/.test(ms),
      'must attempt restore on init');
    assert(/sessionStorage\.removeItem\(CACHE_KEY\)/.test(ms),
      'reload handler must clear the cache');
  });
  test('milestone page exposes print/PDF export action', () => {
    assert(/getElementById\('print-btn'\)\.addEventListener\('click', \(\) => window\.print\(\)\)/.test(ms),
      'print button must call window.print');
    assert(/getElementById\('print-btn'\)\.disabled = false/.test(ms),
      'print button must enable after the model is built');
  });
}

// ---- milestone page drilldown ----
console.log('\nmilestones.html + milestone-view.js');
{
  const html = fs.readFileSync(path.join(WEBAPP, 'milestones.html'), 'utf8');
  const view = fs.readFileSync(path.join(WEBAPP, 'js', 'milestone-view.js'), 'utf8');
  test('milestone page includes filters, all-gaps table, details panel, and methodology', () => {
    for (const id of ['milestone-search', 'gap-filter', 'priority-filter', 'workload-filter', 'gap-table', 'details-panel']) {
      assert(html.includes(`id="${id}"`), `missing ${id}`);
    }
    assert(/Click a row to drill into priority rationale/.test(html), 'row drilldown guidance must be visible');
    assert(/Account-level gap:<\/strong> account has Migration milestones/.test(html), 'methodology must explain account-level gaps');
  });
  test('milestone view filters by search, gap type, priority, and workload', () => {
    assert(/function filteredRows\(\)/.test(view), 'filteredRows helper must exist');
    assert(/document\.getElementById\('milestone-search'\)\?\.value/.test(view), 'search input must be read');
    assert(/row\.gap_type !== gapType/.test(view), 'gap type filter must be applied');
    assert(/row\.priority !== priority/.test(view), 'priority filter must be applied');
    assert(/!workloadParts\(row\)\.includes\(workload\)/.test(view), 'workload filter must be applied');
    assert(/No gaps match the current filters\./.test(view), 'empty filter state must be rendered');
  });
  test('milestone view renders escaped row drilldown with milestone names', () => {
    assert(/function showDetails\(index\)/.test(view), 'showDetails helper must exist');
    assert(/data-gap-index/.test(view), 'rows must carry a stable data index');
    assert(/escapeHtml\(row\.priority_reason/.test(view), 'priority reason must be escaped');
    assert(/row\.milestones \|\| \[\]\)\.map\(name => `<li>\$\{escapeHtml\(name\)\}<\/li>`/.test(view),
      'milestone names must be escaped in the detail panel');
    assert(/panel\.scrollIntoView/.test(view), 'details panel should be brought into view after row click');
  });
  test('milestone view renders a model without browser runtime errors', () => {
    const sb = makeSandbox();
    const elements = new Map();
    function el(id, value = '') {
      const item = {
        id,
        value,
        hidden: false,
        innerHTML: '',
        textContent: '',
        dataset: {},
        listeners: {},
        addEventListener(type, fn) { this.listeners[type] = fn; },
        scrollIntoView() {},
      };
      elements.set(id, item);
      return item;
    }
    for (const id of [
      'milestone-shell', 'milestone-empty', 'summary-cards', 'priority-chart',
      'gap-type-chart', 'workload-chart', 'top-gaps-tbody', 'result-count',
      'gap-table', 'details-panel', 'quality-notes',
    ]) el(id);
    el('milestone-search', '');
    el('gap-filter', 'all');
    el('priority-filter', 'all');
    el('workload-filter', 'all');
    sb.document.getElementById = id => elements.get(id);
    sb.document.querySelectorAll = () => [];
    loadInto(sb, 'js/milestone-view.js');
    const gap = {
      account_key: 'contoso',
      account: 'Contoso',
      opportunity_id: 'OPP-1',
      gap_type: 'Opportunity-level gap',
      workload: 'Azure VMware Solution',
      milestone_workload: 'Migrate',
      estimated_date: '2026-06-30',
      priority: 'HIGH',
      commitment: 'Committed',
      status: 'Open',
      sales_stage: 'Inspire & Design',
      acr_pipeline: 120000,
      owner_role: 'Specialist',
      owner: 'Avery',
      milestone_count: 1,
      has_committed: true,
      priority_reason: 'Target sales stage: Inspire & Design',
      milestones: ['Migrate AVS pilot'],
    };
    sb.MilestoneView.render({
      summary: {
        migration_accounts: 1,
        defender_accounts: 1,
        attached_accounts: 1,
        account_level_gap_accounts: 0,
        total_accounts_with_gaps: 1,
        total_opportunities_with_gaps: 1,
        account_level_gaps: 0,
        opportunity_level_gaps: 1,
        total_gap_rows: 1,
      },
      priority_counts: { HIGH: 1, MEDIUM: 0, LOW: 0 },
      gap_type_counts: { 'Account-level gap': 0, 'Opportunity-level gap': 1 },
      workload_counts: [{ workload: 'Azure VMware Solution', count: 1 }],
      gaps: [gap],
      top_gaps: [gap],
      data_quality: { migration_rows: 1, defender_rows: 0, migration_invalid_dates: 0, defender_invalid_dates: 0 },
      sources: { migration: 'migration.xlsx', defender: 'defender.xlsx' },
      near_term_days: 60,
      reference_date: '2026-06-05',
    });
    assert(elements.get('gap-table').innerHTML.includes('Contoso'), 'all-gaps table should render account');
    assert(elements.get('result-count').textContent === '1 visible gap rows', 'result count should update');
    assert(elements.get('workload-filter').innerHTML.includes('Azure VMware Solution'), 'workload filter should populate');
  });
}

// ---- csv-export (still used by milestones page) ----
console.log('\ncsv-export.js');
{
  const sb = makeSandbox();
  loadInto(sb, 'js/csv-export.js');

  function csvFor(val) {
    sb._csvParts.length = 0;
    sb.CsvExport.download('t.csv', [{ key: 'v', label: 'col' }], [{ v: val }]);
    return sb._csvParts[0] || '';
  }

  test('prefixes leading = with a single quote', () => {
    const csv = csvFor('=1+2');
    assert(csv.includes("'=1+2"), 'expected leading-quote escape in: ' + JSON.stringify(csv));
  });
  test('prefixes leading +, -, @, tab, CR', () => {
    for (const ch of ['+', '-', '@', '\t', '\r']) {
      const csv = csvFor(ch + 'cmd');
      const row = csv.split('\r\n')[1] || '';
      assert(row.includes("'" + ch) || row.includes('"\'' + ch),
        `expected formula-prefix escape for char ${JSON.stringify(ch)} in row: ${JSON.stringify(row)}`);
    }
  });
  test('does not prefix plain text', () => {
    const csv = csvFor('Hello world');
    assert(!csv.includes("'Hello world"), 'plain text should not be prefixed: ' + csv);
  });
  test('still quotes embedded commas/quotes', () => {
    const csv = csvFor('a,"b"');
    assert(csv.includes('"a,""b"""'), 'expected RFC-4180 quoting in: ' + csv);
  });
  test('handles null and undefined safely', () => {
    const a = csvFor(null).split('\r\n')[1];
    const b = csvFor(undefined).split('\r\n')[1];
    assertEqual(a, '', 'null cell should be empty');
    assertEqual(b, '', 'undefined cell should be empty');
  });
}

// ---- milestone-model: sales-stage priority ----
console.log('\nmilestone-model.js');
{
  // Force JS interpreter to do TZ math in PST so date-ordering boundary bugs surface.
  process.env.TZ = 'America/Los_Angeles';
  const sb = makeSandbox();
  loadInto(sb, 'js/milestone-model.js');

  const headers = ['Translated Account Name','Opportunity ID','Milestone ID','Milestone Name','Milestone Workload','Workload','ACR Pipeline $','Status','Commitment','Due Date','Category','Owner Role','Owner'];
  const stageHeaders = [...headers, 'SalesStageName'];
  const stageRows = [
    stageHeaders,
    ['Target Later','OPP-1','MS-1','Pilot','Compute','Compute',1000,'Open','No','2026-12-01','Discover','AE','Alice','Inspire & Design'],
    ['Target Earlier','OPP-2','MS-2','Pilot','Compute','Compute',1000,'Open','No','2026-09-01','Discover','AE','Bob','Listen and Consult'],
    ['Other Earlier','OPP-3','MS-3','Pilot','Compute','Compute',1000,'Open','No','2026-06-01','Discover','AE','Cara','Empower & Achieve'],
  ];
  const stagedModel = sb.MilestoneModel.build(stageRows, [stageHeaders], { reference_date: '2026-06-05' });

  test('target sales stages are HIGH and sorted by earliest due date before other stages', () => {
    assertEqual(stagedModel.gaps.map(g => g.account).join('|'), 'Target Earlier|Target Later|Other Earlier',
      'target stages should rank before non-target rows, then sort by due date');
    assertEqual(stagedModel.gaps[0].priority, 'HIGH', 'Listen and Consult should be HIGH');
    assertEqual(stagedModel.gaps[0].priority_reason, 'Target sales stage: Listen and Consult', 'target reason');
    assertEqual(stagedModel.gaps[2].priority, 'MEDIUM', 'other stage should be MEDIUM');
    assertEqual(stagedModel.gaps[2].sales_stage, 'Empower & Achieve', 'sales stage should be retained');
  });

  const legacyRows = [headers, ['Legacy Co','OPP-4','MS-4','Pilot','Compute','Compute',1000,'Open','No','2026-06-01','Discover','AE','Dana']];
  const legacyModel = sb.MilestoneModel.build(legacyRows, [headers], { reference_date: '2026-06-05' });

  test('legacy milestone workbooks without SalesStageName still load', () => {
    assertEqual(legacyModel.gaps[0].priority, 'MEDIUM', 'legacy valid workload priority');
    assertEqual(legacyModel.gaps[0].priority_reason, 'No sales stage provided; valid workload', 'legacy reason');
  });
}

// ---- acr-model: required model fields are populated ----
console.log('\nacr-model.js');
{
  const sb = makeSandbox();
  loadInto(sb, 'js/acr-model.js');

  // The real workbook uses a 2-row header: row 0 carries fiscal month names
  // (e.g. "FY26-Jan"), row 1 carries the metric label ("$ ACR"). Non-metric
  // columns repeat their name on both rows.
  const top = ['Customer Tpid', 'TPAccountName', 'ServiceCompGrouping',
               'FY26-Jan', 'FY26-Feb', 'FY26-Mar', 'FY26-Apr'];
  const bot = ['Customer Tpid', 'TPAccountName', 'ServiceCompGrouping',
               '$ ACR', '$ ACR', '$ ACR', '$ ACR'];
  const rows = [
    top, bot,
    [1, 'Acme', 'Defender for Cloud',       100, 110, 120, 130],
    [1, 'Acme', 'General Purpose Compute',  900, 950, 1000, 1100],
    [1, 'Acme', 'Total',                   1000, 1060, 1120, 1230],
    [2, 'Beta', 'Defender for Cloud',         5,   5,    5,    5],
    [2, 'Beta', 'Azure Virtual Desktop',    500, 600,  700,  800],
    [2, 'Beta', 'Total',                    505, 605,  705,  805],
  ];
  const model = sb.AcrModel.build(rows, 'unit-test.xlsx');

  test('exposes the canonical top-level fields', () => {
    for (const k of ['months', 'month_labels', 'partial_month_idx', 'last_full_month',
                     'prior_month', 'customers', 'products', 'opportunity']) {
      assert(k in model, `model missing key ${k}`);
    }
    assert(Array.isArray(model.opportunity) && model.opportunity.length === 2,
      'expected 2 opportunity rows, got ' + (model.opportunity || []).length);
  });
  test('opportunity rows include all action-queue/heatmap fields', () => {
    const row = model.opportunity[0];
    for (const k of ['customer', 'opportunity', 'notes', 'dfc_current', 'other_current',
                     'total_current', 'dfc_ratio', 'total_fytd', 'dfc_fytd',
                     'total_monthly_current', 'dfc_monthly_current',
                     'dfc_3m_delta', 'other_3m_delta', 'growth_gap']) {
      assert(k in row, `opportunity row missing ${k}: ${JSON.stringify(row)}`);
    }
    assert(row.total_fytd > 0, 'total_fytd must be nonzero with positive sample data');
    assert(row.dfc_fytd > 0, 'dfc_fytd must be nonzero with positive sample data');
  });
}

// ---- acr-model: new ServiceLevel1/ServiceLevel2 weekly format ----
console.log('\nacr-model.js (new weekly format)');
{
  const sb = makeSandbox();
  loadInto(sb, 'js/sl-mapping.js');
  loadInto(sb, 'js/sl-parser.js');
  loadInto(sb, 'js/sl-engine.js');
  loadInto(sb, 'js/acr-model.js');

  // 3-row header: row0 fiscal-month band, row1 week-start (or 'Total'), row2 dims + '$ ACR'.
  // Cols: Timezone(0) TPAccountName(1) ServiceLevel1(2) ServiceLevel2(3),
  // then weekly/Total $ ACR cols 4..11 and a grand-Total col 12.
  const h0 = ['FiscalMonth', null, null, null,
              'FY26-Mar', 'FY26-Mar', 'FY26-Mar', 'FY26-Apr', 'FY26-Apr', 'FY26-Apr', 'FY26-May', 'FY26-May', 'Total'];
  const h1 = ['FiscalWeekStartDate', null, null, null,
              '2026-03-01', '2026-03-29', 'Total', '2026-03-29', '2026-04-12', 'Total', '2026-05-03', 'Total', null];
  const h2 = ['Timezone', 'TPAccountName', 'ServiceLevel1', 'ServiceLevel2',
              '$ ACR', '$ ACR', '$ ACR', '$ ACR', '$ ACR', '$ ACR', '$ ACR', '$ ACR', '$ ACR'];
  const rows = [
    h0, h1, h2,
    ['UTC', 'Acme', 'Security', 'Microsoft Defender for Cloud',          10, 10, 20, 10, 10, 20, 30, 30, 70],
    ['UTC', 'Acme', 'Compute', 'Virtual Machines',                      100, 100, 200, 100, 100, 200, 300, 300, 700],
    ['UTC', 'Acme', 'Compute', 'Total',                                 100, 100, 200, 100, 100, 200, 300, 300, 700], // S1 subtotal — must be skipped
    ['UTC', 'Acme', 'Management and Governance', 'Sentinel',              5, 5, 10, 5, 5, 10, 10, 10, 30],
    ['UTC', 'Acme', 'Total', null,                                      115, 115, 230, 115, 115, 230, 340, 340, 800],
    ['UTC', 'Beta', 'Compute', '<img src=x onerror=alert(1)>',           50, 50, 100, 50, 50, 100, 200, 200, 400],
    ['UTC', 'Beta', 'Total', null,                                       50, 50, 100, 50, 50, 100, 200, 200, 400],
    ['UTC', 'Total', 'Total', null,                                     165, 165, 330, 165, 165, 330, 540, 540, 1200], // grand-total customer — excluded
    ['Applied filters: Foo=Bar', null, null, null, null, null, null, null, null, null, null, null, null], // footer — excluded
  ];
  const m = sb.AcrModel.build(rows, 'new.xlsx');

  test('detects and tags the new format', () => assertEqual(m.format, 'new', 'format'));
  test('excludes grand-total customer and applied-filters footer', () => {
    assertEqual(JSON.stringify(m.customers), JSON.stringify(['Acme', 'Beta']), 'customers');
  });
  test('treats the latest month as partial and scores on the last full month', () => {
    assertEqual(m.partial_month_idx, 2, 'partial_month_idx');
    assertEqual(m.last_full_month, 'FY26-Apr', 'last_full_month');
    assertEqual(m.months.length, 3, 'months count');
  });
  test('splits Sentinel and DfC out of their parent categories', () => {
    assert(m.products.includes('Defender for Cloud'), 'DfC product present');
    assert(m.products.includes('Sentinel'), 'Sentinel product present');
    assert(!m.products.includes('Security'), 'Security parent must not appear (DfC reassigned)');
    assert(!m.products.includes('Management and Governance'), 'M&G parent must not appear (Sentinel reassigned)');
  });
  test('does not double-count S1 subtotal rows', () => {
    const compute = m.customer_data['Acme'].products.find(p => p.product === 'Compute');
    assert(compute, 'Compute product present for Acme');
    assertEqual(compute.series[1], 200, 'Acme Compute Apr should be 200, not 400');
  });
  test('emits zero DfC series for customers without DfC', () => {
    assert(m.customer_data['Beta'].dfc_series.every(v => v === 0), 'Beta DfC must be all zeros');
  });
  test('reconciles product groups to the account total each month', () => {
    for (let i = 0; i < m.months.length; i++) {
      const sum = m.products.reduce((a, p) => a + (m.product_monthly[p][i] || 0), 0);
      assert(Math.abs(sum - m.product_monthly['Total'][i]) < 0.5,
        `month ${i}: products ${sum} vs Total ${m.product_monthly['Total'][i]}`);
    }
  });
  test('builds track_products from real keys with DfC first and valid hex colours', () => {
    assertEqual(m.track_products[0], 'Defender for Cloud', 'DfC first');
    assert(m.track_products.every(p => m.product_monthly[p]), 'track_products reference real keys');
    assert(Object.values(m.product_colors).every(v => /^#[0-9a-fA-F]{6}$/.test(v)), 'all colours hex');
  });
  test('merges boundary weeks into a continuous weekly series', () => {
    assert(m.weekly_enabled, 'weekly enabled');
    assertEqual(JSON.stringify(m.week_labels), JSON.stringify(['Mar 01', 'Mar 29', 'Apr 12', 'May 03']), 'week labels');
    // 03-29 is split across Mar and Apr; merged value for Acme total = 115 + 115 = 230.
    assertEqual(m.customer_data['Acme'].total_weekly[1], 230, 'merged boundary week');
  });
  test('carries SKU drill-down on product breakdown entries', () => {
    const hasSkus = m.customer_data['Acme'].products.some(p => Array.isArray(p.skus) && p.skus.length);
    assert(hasSkus, 'expected at least one product with skus[]');
  });
  test('emits portfolio product_skus that reconcile to product_monthly per category', () => {
    assert(m.product_skus && typeof m.product_skus === 'object', 'product_skus map emitted');
    // Pick a real (non-Total) category that has SKU leaves and verify the leaf sum
    // matches the category group total for every month.
    const cats = Object.keys(m.product_skus);
    assert(cats.length > 0, 'at least one category has SKU leaves');
    let checked = 0;
    for (const cat of cats) {
      const leaves = m.product_skus[cat];
      const groupSeries = m.product_monthly[cat];
      assert(Array.isArray(leaves), `${cat} leaves is a list of {sku, monthly}`);
      assert(Array.isArray(groupSeries), `product_monthly has the ${cat} group`);
      for (let i = 0; i < m.months.length; i++) {
        const leafSum = leaves.reduce((a, s) => a + (s.monthly[i] || 0), 0);
        assert(Math.abs(leafSum - groupSeries[i]) < 0.5,
          `${cat} month ${i}: leaves ${leafSum} vs group ${groupSeries[i]}`);
      }
      checked++;
    }
    assert(checked > 0, 'reconciled at least one category');
  });

  // ---- edge cases surfaced in review ----
  const mkHeader = (months, weeks) => {
    const h0 = ['FiscalMonth', null, null, null];
    const h1 = ['FiscalWeekStartDate', null, null, null];
    const h2 = ['Timezone', 'TPAccountName', 'ServiceLevel1', 'ServiceLevel2'];
    months.forEach((mo, i) => {
      weeks[i].forEach(w => { h0.push(mo); h1.push(w); h2.push('$ ACR'); });
      h0.push(mo); h1.push('Total'); h2.push('$ ACR');
    });
    h0.push('Total'); h1.push(null); h2.push('$ ACR');
    return [h0, h1, h2];
  };

  test('keeps a zero DfC line for segments with no Defender spend', () => {
    const rows2 = [
      ...mkHeader(['FY26-Mar', 'FY26-Apr'], [['2026-03-01'], ['2026-04-05']]),
      ['UTC', 'NoDfc', 'Compute', 'Virtual Machines', 100, 100, 200, 200, 300],
      ['UTC', 'NoDfc', 'Total', null,                  100, 100, 200, 200, 300],
    ];
    const z = sb.AcrModel.build(rows2, 'nodfc.xlsx');
    assert(!z.products.includes('Defender for Cloud'), 'no DfC product when there is no DfC spend');
    assert(Array.isArray(z.product_monthly['Defender for Cloud']), 'DfC must still exist in product_monthly');
    assert(z.product_monthly['Defender for Cloud'].every(v => v === 0), 'DfC line must be all zeros');
    assertEqual(z.track_products[0], 'Defender for Cloud', 'DfC still pinned first in track_products');
  });

  test('rejects a single-month workbook (no completed month to score on)', () => {
    const rows1 = [
      ...mkHeader(['FY26-Mar'], [['2026-03-01']]),
      ['UTC', 'Solo', 'Compute', 'Virtual Machines', 100, 100, 100],
      ['UTC', 'Solo', 'Total', null,                  100, 100, 100],
    ];
    let threw = false;
    try { sb.AcrModel.build(rows1, 'one-month.xlsx'); } catch (e) { threw = /one fiscal month|completed month/i.test(e.message); }
    assert(threw, 'expected build to throw for a single-month export');
  });

  test('builds an SL2/SL4 export into the corp dashboard contract (single source)', () => {
    const rows = [
      [null, null, null, 'FY26-Jul', null, null, null, null, 'FY26-Aug', null, null, null, null],
      ['TPAccountName', 'ServiceLevel2', 'ServiceLevel4',
       '$ ACR', '$ ACR MoM', '$ Average Daily ACR', '$ Avg Daily ACR MoM', '% Avg Daily ACR MoM',
       '$ ACR', '$ ACR MoM', '$ Average Daily ACR', '$ Avg Daily ACR MoM', '% Avg Daily ACR MoM'],
      ['Acme', 'Container Registry', 'Total',                  100, 0, 3, 0, 0, 120, 0, 4, 0, 0],
      ['Acme', 'Container Registry', 'Basic Registry',          25, 0, 1, 0, 0,  20, 0, 1, 0, 0],
      ['Acme', 'Container Registry', 'Premium Registry',        75, 0, 2, 0, 0, 100, 0, 3, 0, 0],
      ['Acme', 'Microsoft Defender for Cloud', 'Total',          5, 0, 0, 0, 0,   6, 0, 0, 0, 0],
      ['Acme', 'Microsoft Defender for Cloud', 'Container Registries', 5, 0, 0, 0, 0, 6, 0, 0, 0, 0],
      ['Acme', 'Total', null,                                  105, 0, 3, 0, 0, 126, 0, 4, 0, 0],
    ];
    const d = sb.AcrModel.build(rows, 'sl2sl4.xlsx');
    assertEqual(d.format, 'sl2sl4', 'SL2/SL4 import flagged as sl2sl4 format');
    assertEqual(d.months.length, 2, 'two months parsed');
    assertEqual(d.last_full_month, 'FY26-Aug', 'latest month treated as the full month');
    assertEqual(d.partial_month_idx, -1, 'monthly data has no partial-month tail');
    assert(d.products.includes('Defender for Cloud'), 'DfC normalised as a product');
    assert(!d.products.includes('Total'), 'customer Total roll-up is not a product');
    assert(!d.customers.includes('Total'), 'Total is not surfaced as a customer');
    const cd = d.customer_data['Acme'];
    for (let i = 0; i < d.months.length; i += 1) {
      assert(Math.abs(cd.other_series[i] - (cd.total_series[i] - cd.dfc_series[i])) < 0.01,
        'other = total − dfc holds');
      assert(cd.other_series[i] >= -0.01, 'no negative non-Defender ACR');
    }
    assertEqual(d.opportunity.length, d.customers.length, 'one opportunity row per customer');
    const container = cd.products.find(p => p.product === 'Container Registry');
    assert(container && Array.isArray(container.skus), 'SL2 category exposes SL4 service details');
    assertEqual(container.skus.length, 2, 'two active SL4 details attached');
    assertEqual(container.skus[0].sku, 'Premium Registry', 'SL4 details sorted by current ACR');
    assertEqual(container.skus[0].current, 100, 'SL4 current ACR preserved');
    assertEqual(container.skus[1].series[0], 25, 'SL4 monthly series preserved');
    const defender = cd.products.find(p => p.product === 'Defender for Cloud');
    assert(defender && Array.isArray(defender.skus), 'DfC category exposes Defender plan details');
    assertEqual(defender.skus[0].sku, 'Container Registries', 'Defender SL4 detail preserved');
    assert(d.service_attach && Array.isArray(d.service_attach.dossiers),
      'per-service attach model attached for drill-down');
    assert(!d.service_attach_error, 'no service-attach build error');
  });

  test('parses real Date week-start cells (not just ISO strings)', () => {
    const rows3 = [
      ...mkHeader(['FY26-Mar', 'FY26-Apr'], [[new Date(2026, 2, 1)], [new Date(2026, 3, 5)]]),
      ['UTC', 'Acme', 'Compute', 'Virtual Machines', 100, 100, 200, 200, 300],
      ['UTC', 'Acme', 'Total', null,                  100, 100, 200, 200, 300],
    ];
    const d = sb.AcrModel.build(rows3, 'dates.xlsx');
    assert(d.weekly_enabled, 'weekly should enable with valid Date headers');
    assertEqual(JSON.stringify(d.week_labels), JSON.stringify(['Mar 01', 'Apr 05']), 'Date-derived week labels');
  });

  test('disables weekly output when a week-start header is unparseable', () => {
    const rows4 = [
      ...mkHeader(['FY26-Mar', 'FY26-Apr'], [['not-a-date'], ['2026-04-05']]),
      ['UTC', 'Acme', 'Compute', 'Virtual Machines', 100, 100, 200, 200, 300],
      ['UTC', 'Acme', 'Total', null,                  100, 100, 200, 200, 300],
    ];
    const b = sb.AcrModel.build(rows4, 'bad-week.xlsx');
    assertEqual(b.weekly_enabled, false, 'weekly must disable on unparseable header');
    assert(!('week_labels' in b), 'week_labels omitted when weekly disabled');
  });
}

// ---- generated acr.html: taxonomy/SKU hardening ----
console.log('\nweb-app/acr.html (taxonomy + SKU drill-down)');
{
  const src = fs.readFileSync(path.join(WEBAPP, ACR_PAGE), 'utf8');
  test('product mix donut sources product_monthly with validated colours', () => {
    assert(/Object\.keys\(src\)\.filter\(k => k !== 'Total'\)/.test(src), 'donut sources all product_monthly categories');
    assert(/const colorFor = \(label, rank\) =>/.test(src), 'rank-based colorFor helper present');
    assert(/\/\^#\[0-9a-fA-F\]\{6\}\$\/\.test\(c\)/.test(src), 'hex allowlist validation');
  });
  test('escapes Excel-derived product and SKU names', () => {
    assert(/const nameEsc = escapeHtml\(p\.product\);/.test(src), 'product name escaped');
    assert(/\$\{escapeHtml\(s\.sku\)\}/.test(src), 'SKU name escaped');
    assert(/\$\{escapeHtml\(d\.label\)\}<\/span>/.test(src), 'legend label escaped');
    assert(!/style="background:\$\{PRODUCT_COLORS\[p\]\}"><\/span>\$\{p\}/.test(src), 'no unescaped legend label');
  });
  test('escapes Excel-derived series labels in the line chart', () => {
    assert(/data-label="\$\{escapeHtml\(s\.label\)\}"/.test(src), 'line chart data-label escaped');
    assert(/showTooltip\(`<b>\$\{escapeHtml\(label\)\}<\/b>/.test(src), 'line chart tooltip label escaped');
    assert(!/data-label="\$\{s\.label\}"/.test(src), 'no unescaped line chart data-label');
  });
  test('renders collapsible SKU rows with a toggle handler', () => {
    assert(/data-sku-toggle/.test(src), 'SKU toggle markup present');
    assert(/closest\('\[data-sku-toggle\]'\)/.test(src), 'delegated toggle handler present');
    assert(/Service Level 4 detail/.test(src), 'SL4 detail copy present');
    assert(/aria-expanded="false"/.test(src), 'category rows expose expanded state');
    assert(/Click to show \$\{skus\.length\} service detail/.test(src), 'category rows explain drill-down');
    assert(/addEventListener\('keydown'/.test(src), 'keyboard drill-down handler present');
    assert(/\.product-row\[hidden\]\s*\{\s*display:\s*none;\s*\}/.test(src), 'hidden SKU rows are not overridden by grid display CSS');
  });
  test('KPI uses the last full month when the latest month is partial', () => {
    assert(/Math\.max\(0, DATA\.months\.length - 2\) : DATA\.months\.length - 1/.test(src), 'partial-month KPI guard');
  });
}

console.log('\nweb-app/acr.html (weekly-only trend views)');
{
  const src = fs.readFileSync(path.join(WEBAPP, ACR_PAGE), 'utf8');
  test('monthly/weekly granularity toggle is removed', () => {
    assert(!/id="product-trend-grain"/.test(src), 'no overview grain select');
    assert(!/id="cust-trend-grain"/.test(src), 'no customer grain select');
    assert(!/function initGrainControls\(\)/.test(src), 'no initGrainControls');
    assert(!/id="grain-ctl"/.test(src), 'no overview grain control wrapper');
    assert(!/id="cust-grain-ctl"/.test(src), 'no customer grain control wrapper');
  });
  test('product-mix line-chart mode select is removed', () => {
    assert(!/id="product-trend-mode"/.test(src), 'no product trend mode select');
    assert(!/Indexed to first point \(=100\)/.test(src), 'no indexed mode option');
    assert(!/id="chart-product-trend"/.test(src), 'no product trend line container');
    assert(!/id="legend-product-trend"/.test(src), 'no product trend legend');
    assert(!/function renderProductTrend\(\)/.test(src), 'no product trend line renderer');
  });
  test('overview trends auto-select weekly when available', () => {
    assert(/function renderDfcTrend\(\)/.test(src), 'weekly-preferring DfC trend defined');
    assert(/const weekly = !!\(DATA\.weekly_enabled && DATA\.dfc_total_weekly\);/.test(src), 'DfC weekly auto-selected');
    assert(/labels = weekly \? DATA\.week_labels : DATA\.month_labels/.test(src), 'weekly x-axis labels wired');
    assert(!/lineChart\('chart-dfc-trend', \[\{label: 'Defender for Cloud', values: DATA\.dfc_total_monthly, color: '#0078d4'\}\]\);/.test(src), 'no stale month-only DfC trend call');
  });
  test('legacy monthly data still falls back without blank charts', () => {
    assert(/weekly \? DATA\.dfc_total_weekly : DATA\.dfc_total_monthly/.test(src), 'DfC monthly fallback retained');
  });
  test('partial-month marker is suppressed on weekly charts', () => {
    assert(/const partialIdx = \(opts\.partialIdx != null\) \? opts\.partialIdx : DATA\.partial_month_idx;/.test(src), 'lineChart honours opts.partialIdx');
    assert(/const isPartial = i === partialIdx;/.test(src), 'marker uses resolved partialIdx');
    assert(!/const isPartial = i === DATA\.partial_month_idx;/.test(src), 'no hard-coded monthly partial index');
    const passed = (src.match(/partialIdx: weekly \? -1 : DATA\.partial_month_idx/g) || []).length;
    assert(passed === 1, 'overview DfC chart passes weekly partialIdx (got ' + passed + ')');
  });
  test('trend chart titles/subtitles no longer hard-code "monthly"', () => {
    assert(/Defender for Cloud — ACR across all customers/.test(src), 'DfC trend title neutral');
    assert(/ACR trend \(weekly where available\)/.test(src), 'DfC trend sub clarifies weekly');
    assert(/Product mix — share of ACR by service/.test(src), 'product mix donut title');
    assert(!/Monthly ACR across all customers/.test(src), 'no stale DfC trend title');
    assert(!/monthly ACR trend by service/.test(src), 'no stale product trend title');
  });
}

console.log('\nweb-app/acr.html (product-mix donut)');
{
  const src = fs.readFileSync(path.join(WEBAPP, ACR_PAGE), 'utf8');
  test('donut replaces the product-trend line chart on the overview', () => {
    assert(/function donutChart\(/.test(src), 'donutChart helper defined');
    assert(/function renderProductMix\(\)/.test(src), 'renderProductMix defined');
    assert(/id="chart-product-mix"/.test(src), 'donut container present');
    assert(/id="legend-product-mix"/.test(src), 'donut legend present');
    assert(/donutChart\('chart-product-mix', r\.items\)/.test(src), 'donut render call wired');
    assert(/\n {2}renderProductMix\(\);/.test(src), 'renderAll calls renderProductMix');
    assert(!/\n {2}renderProductTrend\(\);/.test(src), 'renderAll no longer calls renderProductTrend');
  });
  test('donut lives next to the weekly total-ACR chart in grid-2', () => {
    const gridOpen = src.indexOf('<div class="grid-2">');
    const gridClose = src.indexOf('\n  </div>', gridOpen);
    assert(gridOpen >= 0 && gridClose > gridOpen, 'grid-2 block found');
    const dfcIdx = src.indexOf('id="chart-dfc-trend"');
    const mixIdx = src.indexOf('id="chart-product-mix"');
    const topIdx = src.indexOf('id="chart-top-dfc"');
    assert(dfcIdx > gridOpen && dfcIdx < gridClose, 'weekly total ACR chart inside grid-2');
    assert(mixIdx > gridOpen && mixIdx < gridClose, 'product-mix donut inside grid-2');
    assert(topIdx > gridClose, 'Top 15 chart outside (below) grid-2');
  });
  test('Top 15 chart moved to a full-width box below grid-2', () => {
    const gridClose = src.indexOf('\n  </div>', src.indexOf('<div class="grid-2">'));
    const topIdx = src.indexOf('id="chart-top-dfc"');
    assert(topIdx > gridClose, 'Top 15 box appears after the grid-2 row');
    assert(/Top 15 customers by Defender for Cloud monthly ACR/.test(src), 'Top 15 title retained');
  });
  test('donut output is XSS-safe', () => {
    assert(/data-label="\$\{escapeHtml\(d\.label\)\}"/.test(src), 'donut segment label escaped');
    assert(/showTooltip\(`<b>\$\{escapeHtml\(label\)\}<\/b>/.test(src), 'donut tooltip label escaped');
  });
  test('donut shows average monthly ACR over complete months', () => {
    assert(/const avgOf = a => \{ const arr = Array\.isArray\(a\) \? a : \[\];/.test(src), 'avgOf guards non-arrays');
    assert(/vals = arr\.filter\(\(_, i\) => i !== partial\)/.test(src), 'partial/accumulating month excluded from average');
    assert(/const totalAvg = avgOf\(src\['Total'\]\);/.test(src), 'centre total uses avg monthly Total ACR');
    assert(/label: 'Other services'/.test(src), 'Other services slice rolls up untracked services');
    assert(/avg monthly ACR<\/text>/.test(src), 'donut centre sublabel reads avg monthly ACR');
    assert(/total >= 1e6 \? '\$' \+ \(total \/ 1e6\)\.toFixed\(2\) \+ 'M'/.test(src), 'centre value formats millions as $X.XXM');
    assert(/\.filter\(d => d\.value > 0\)/.test(src), 'zero-value services filtered out');
    assert(/No service ACR to display/.test(src), 'empty-state guard present');
    assert(!/const sumOf = a => \(Array\.isArray\(a\) \? a : \[\]\)\.reduce/.test(src) || !/sumOf\(src\[p\]\)/.test(src), 'donut no longer sums cumulative across all periods');
  });
  test('donut shows top-12 real categories, pins DfC, and decouples from track_products', () => {
    assert(/const MAX_SLICES = 12;/.test(src), 'top-12 slice cap present');
    assert(/Object\.keys\(src\)\.filter\(k => k !== 'Total'\)/.test(src), 'sources every product_monthly category (not the 8-cap track list)');
    assert(/const dfc = all\.find\(d => d\.label === DFC\);/.test(src), 'Defender for Cloud located for pinning');
    assert(/named\[named\.length - 1\] = dfc; named\.sort/.test(src), 'DfC swapped into the named slices if below the cap');
    // The donut must NOT reuse the taxonomy 8-cap track_products list for its slices.
    assert(!/tracks = \(DATA\.track_products[^\n]*\n[^\n]*donutChart/.test(src), 'donut not fed by track_products');
  });
  test('donut Other slice reconciles to its drill-down rows', () => {
    assert(/const otherVal = Math\.max\(0, totalAvg - namedSum\);/.test(src), 'Other value = total avg minus named slices');
    assert(/window\._donutOtherCats = r\.otherCats;/.test(src), 'tail categories stashed for the Other drill-down');
    assert(/otherCats\.push\(\{label: 'Unmapped \/ residual', value: otherVal - tailSum\}\)/.test(src), 'total-vs-leaf residual surfaced in the Other drill-down');
    assert(/if \(otherVal > 1\) items\.push\(\{label: 'Other services'/.test(src), 'Other slice only rendered when material');
  });
  test('donut slices drill into their underlying services (accessible)', () => {
    assert(/function openCategoryBreakdown\(/.test(src), 'category breakdown opener defined');
    assert(/function _ensureCatOverlay\(/.test(src), 'category modal overlay builder defined');
    assert(/seg\.setAttribute\('tabindex', '0'\);/.test(src), 'donut slices are focusable');
    assert(/seg\.setAttribute\('role', 'button'\);/.test(src), 'donut slices expose a button role');
    assert(/if \(e\.key === 'Enter' \|\| e\.key === ' ' \|\| e\.key === 'Spacebar'\)/.test(src), 'Enter/Space open the drill-down');
    assert(/openCategoryBreakdown\(seg\.getAttribute\('data-label'\)\)/.test(src), 'click/keyboard pass the slice label');
  });
  test('category modal sources SKU leaves, folds Other, and is XSS-safe', () => {
    assert(/const skus = \(DATA\.product_skus && DATA\.product_skus\[label\]\) \|\| null;/.test(src), 'real category rows come from product_skus');
    assert(/if \(label === 'Other services'\)/.test(src), 'Other slice lists its folded categories');
    assert(/Array\.isArray\(window\._donutOtherCats\)/.test(src), 'Other drill-down reads the stashed categories defensively');
    assert(/Service-level breakdown is not available for this data source/.test(src), 'graceful fallback when SKU leaves are absent (legacy/old format)');
    assert(/escapeHtml\(r\.name\)/.test(src), 'service names escaped in the modal table');
    assert(/if \(titleEl\) titleEl\.textContent = label;/.test(src), 'category title set via textContent (no HTML injection)');
  });
  test('computeDonutSlices: top-12 cap, DfC pin, and Other reconciliation (behavioral)', () => {
    // Extract the pure slice-builder from the generated page and execute it against a
    // synthetic product_monthly with >12 categories and a deliberately low-ranked DfC.
    const start = src.indexOf('function computeDonutSlices(src, partial)');
    const end = src.indexOf('\nfunction renderProductMix()', start);
    assert(start >= 0 && end > start, 'computeDonutSlices source extracted');
    const fnSrc = src.slice(start, end);
    const sb = { console };
    vm.createContext(sb);
    vm.runInContext(fnSrc + '\nthis.computeDonutSlices = computeDonutSlices;', sb);
    // 14 real categories + Total. DfC is the smallest non-zero category (ranks last).
    const months = 3;
    const partial = 2; // exclude the 3rd (accumulating) month from the average
    const cat = (a, b) => [a, b, 999]; // 3rd month value ignored by avgOf
    const data = { Total: cat(0, 0) };
    const big = [
      ['Compute', 100], ['Storage', 90], ['Networking', 80], ['Databases', 70],
      ['AI + Machine Learning', 60], ['Containers', 50], ['Integration', 40],
      ['Developer Tools', 30], ['Analytics', 25], ['Web', 20], ['IoT', 15],
      ['Management', 12], ['Identity', 8],
    ];
    let total = 0;
    for (const [name, v] of big) { data[name] = cat(v, v); total += v; }
    data['Defender for Cloud'] = cat(3, 3); total += 3; // 14th, below the 12 cap
    data.Total = cat(total, total);

    const r = sb.computeDonutSlices(data, partial);
    const labels = r.items.map(d => d.label);
    // DfC must be pinned in despite ranking 14th.
    assert(labels.includes('Defender for Cloud'), 'DfC pinned into the named slices');
    // Cap respected: <=12 named + at most one 'Other services' slice.
    const named = r.items.filter(d => d.label !== 'Other services');
    assert(named.length <= 12, 'no more than 12 named slices');
    assert(labels.filter(l => l === 'Other services').length <= 1, 'at most one Other slice');
    // Slices reconcile to the true average monthly total.
    const sliceSum = r.items.reduce((s, d) => s + d.value, 0);
    assert(Math.abs(sliceSum - r.totalAvg) < 0.5, `slices (${sliceSum}) sum to total avg (${r.totalAvg})`);
    // The Other drill-down reconciles to the Other slice value.
    const otherSum = r.otherCats.reduce((s, d) => s + d.value, 0);
    assert(Math.abs(otherSum - r.otherVal) < 0.5, `Other drill-down (${otherSum}) reconciles to Other slice (${r.otherVal})`);
    // The lowest-ranked categories (Identity, then Management) were displaced into Other.
    assert(!labels.includes('Identity'), 'lowest category folded into Other');
    assert(r.otherCats.some(d => d.label === 'Identity'), 'displaced category appears in the Other drill-down');
  });
}

// ---- acr-model: opportunity classification rules (baseline + break-of-trend) ----
console.log('\nacr-model.js (opportunity rules)');
{
  const sb = makeSandbox();
  loadInto(sb, 'js/acr-model.js');
  const classify = sb.AcrModel.classifyOpportunity;

  test('"Too small" customers short-circuit regardless of other signals', () => {
    const [p] = classify({ dfc_current: 0, total_current: 1000, dfc_ratio: 0, dfc_3m: 0.5, other_3m: 0.5, growth_cat_3m: 0.5 });
    assertEqual(p, 'Too small', 'priority');
  });

  test('baseline rule: DfC share below the threshold bumps to at least Medium', () => {
    const [p, notes] = classify({ dfc_current: 400, total_current: 20000, dfc_ratio: 0.02, dfc_3m: 0, other_3m: 0 });
    assertEqual(p, 'Medium', 'below-baseline priority');
    assert(/attach baseline/.test(notes), 'note must mention the attach baseline: ' + notes);
    assert(/6%/.test(notes), 'note must cite the default 6% baseline: ' + notes);
  });

  test('baseline rule: DfC share at/above the threshold stays Low when flat', () => {
    const [p] = classify({ dfc_current: 2000, total_current: 20000, dfc_ratio: 0.10, dfc_3m: 0, other_3m: 0 });
    assertEqual(p, 'Low', 'above-baseline flat priority');
  });

  test('baseline rule is threshold-reactive (slider drives priority)', () => {
    const args = { dfc_current: 1400, total_current: 20000, dfc_ratio: 0.07, dfc_3m: 0, other_3m: 0 };
    assertEqual(classify({ ...args, threshold: 0.06 })[0], 'Low', 'Low at 6% threshold');
    assertEqual(classify({ ...args, threshold: 0.10 })[0], 'Medium', 'Medium at 10% threshold');
  });

  test('break-of-trend: core workloads growing while DfC lags + below baseline => High', () => {
    const [p, notes] = classify({
      dfc_current: 600, total_current: 20000, dfc_ratio: 0.03, dfc_3m: -0.20, other_3m: 0,
      growth_cat_3m: 0.30, growth_cat_names: ['Compute', 'Databases'],
    });
    assertEqual(p, 'High', 'break-of-trend below baseline priority');
    assert(/Break of trend/.test(notes), 'note must flag break of trend: ' + notes);
    assert(/Compute, Databases/.test(notes), 'note must list the growing categories: ' + notes);
  });

  test('break-of-trend does not fire when DfC keeps pace with category growth', () => {
    const [p, notes] = classify({
      dfc_current: 2000, total_current: 20000, dfc_ratio: 0.10, dfc_3m: 0.30, other_3m: 0,
      growth_cat_3m: 0.30, growth_cat_names: ['Compute'],
    });
    assertEqual(p, 'Low', 'priority stays Low when DfC keeps pace');
    assert(!/Break of trend/.test(notes), 'must not flag break of trend: ' + notes);
  });

  test('null DfC 3m growth only lags when still below baseline', () => {
    // Below baseline + categories growing + no DfC base => lagging => bumped.
    const below = classify({
      dfc_current: 100, total_current: 20000, dfc_ratio: 0.01, dfc_3m: null, other_3m: 0,
      growth_cat_3m: 0.30, growth_cat_names: ['Compute'],
    });
    assert(/Break of trend/.test(below[1]), 'below-baseline null-DfC must flag: ' + below[1]);
    // At/above baseline with DfC that grew from zero => not flagged as lagging.
    const ok = classify({
      dfc_current: 3000, total_current: 20000, dfc_ratio: 0.15, dfc_3m: null, other_3m: 0,
      growth_cat_3m: 0.30, growth_cat_names: ['Compute'],
    });
    assert(!/Break of trend/.test(ok[1]), 'above-baseline null-DfC must not flag: ' + ok[1]);
  });

  test('build emits growth_cat_3m + growth_cat_names on opportunity rows', () => {
    const h0 = ['FiscalMonth', null, null, null, 'FY26-Feb', 'FY26-Mar', 'FY26-Apr', 'Total'];
    const h1 = ['FiscalWeekStartDate', null, null, null, 'Total', 'Total', 'Total', null];
    const h2 = ['Timezone', 'TPAccountName', 'ServiceLevel1', 'ServiceLevel2', '$ ACR', '$ ACR', '$ ACR', '$ ACR'];
    const rows = [
      h0, h1, h2,
      ['UTC', 'Grow', 'Compute', 'Virtual Machines',                 1000, 1500, 2000, 4500],
      ['UTC', 'Grow', 'Security', 'Microsoft Defender for Cloud',       10,   11,   12,   33],
      ['UTC', 'Grow', 'Total', null,                                  1010, 1511, 2012, 4533],
    ];
    const gm = sb.AcrModel.build(rows, 'grow.xlsx');
    const row = gm.opportunity.find(r => r.customer === 'Grow');
    assert(row, 'Grow opportunity row present');
    assert('growth_cat_3m' in row, 'row must carry growth_cat_3m');
    assert(typeof row.growth_cat_3m === 'number' && row.growth_cat_3m > 0.05, 'Compute growth should be positive: ' + row.growth_cat_3m);
    assert(Array.isArray(row.growth_cat_names) && row.growth_cat_names.includes('Compute'), 'growth_cat_names should list Compute: ' + JSON.stringify(row.growth_cat_names));
  });

  test('reclassifying at the model default (6%) reproduces baked counts', () => {
    // Mirror the client reclassify path: re-run classify on emitted rows and
    // recompute counts; they must equal the counts baked by build at 0.06.
    const h0 = ['FiscalMonth', null, null, null, 'FY26-Feb', 'FY26-Mar', 'FY26-Apr', 'Total'];
    const h1 = ['FiscalWeekStartDate', null, null, null, 'Total', 'Total', 'Total', null];
    const h2 = ['Timezone', 'TPAccountName', 'ServiceLevel1', 'ServiceLevel2', '$ ACR', '$ ACR', '$ ACR', '$ ACR'];
    const rows = [
      h0, h1, h2,
      ['UTC', 'Big', 'Compute', 'Virtual Machines',               5000, 6000, 7000, 18000],
      ['UTC', 'Big', 'Security', 'Microsoft Defender for Cloud',    20,   20,   20,    60],
      ['UTC', 'Big', 'Total', null,                               5020, 6020, 7020, 18060],
      ['UTC', 'Tiny', 'Compute', 'Virtual Machines',               300,  300,  300,   900],
      ['UTC', 'Tiny', 'Total', null,                               300,  300,  300,   900],
    ];
    const m = sb.AcrModel.build(rows, 'parity.xlsx');
    const recount = { high: 0, medium: 0, low: 0, too_small: 0, total: m.customers.length };
    for (const r of m.opportunity) {
      const [p] = sb.AcrModel.classifyOpportunity({
        dfc_current: r.dfc_current, total_current: r.total_current,
        dfc_ratio: (Number(r.dfc_ratio) || 0) / 100,
        dfc_3m: r.dfc_3m, other_3m: r.other_3m,
        growth_cat_3m: r.growth_cat_3m, growth_cat_names: r.growth_cat_names,
        threshold: 0.06,
      });
      const key = p === 'Too small' ? 'too_small' : p.toLowerCase();
      recount[key]++;
    }
    assertEqual(JSON.stringify(recount), JSON.stringify(m.counts), 'reclassified counts must equal baked counts');
  });
}

// ---- generated acr.html: slider-driven reclassification ----
console.log('\nweb-app/acr.html (attach baseline + reclassification)');
{
  const src = fs.readFileSync(path.join(WEBAPP, ACR_PAGE), 'utf8');
  test('default Defender share threshold is the 6% attach baseline', () => {
    assert(/const DEFAULT_DFC_SHARE_THRESHOLD = 6;/.test(src), 'default threshold must be 6');
    assert(/attach baseline/.test(src), 'footer copy must reference the attach baseline');
    assert(!/Default 8% is aligned/.test(src), 'stale 8% footer copy must be gone');
  });
  test('reclassifyOpportunities recomputes priorities and counts', () => {
    assert(/function reclassifyOpportunities\(thresholdPct\)/.test(src), 'reclassify function defined');
    assert(/AcrModel\.classifyOpportunity\(\{/.test(src), 'reclassify calls the model classifier');
    assert(/dfc_ratio: \(Number\(row\.dfc_ratio\) \|\| 0\) \/ 100/.test(src), 'dfc_ratio converted percent->fraction');
    assert(/threshold: threshold,/.test(src), 'threshold passed as a fraction');
    assert(/DATA\.counts = \{/.test(src), 'reclassify recomputes DATA.counts');
  });
  test('renderAll reclassifies at the default baseline before rendering KPIs', () => {
    assert(/reclassifyOpportunities\(dfcShareThreshold\);\r?\n  renderKpis\(\);/.test(src), 'renderAll must reclassify before renderKpis');
  });
  test('threshold slider drives reclassification + re-render', () => {
    assert(/reclassifyOpportunities\(dfcShareThreshold\);\r?\n    applyThresholdRender\(\);/.test(src), 'slider handler must reclassify then re-render');
    assert(/function applyThresholdRender\(\)/.test(src), 'debounced render helper present');
  });
  test('priority badges are clickable and open a service evidence card', () => {
    assert(/tagFor = function \(opp\) \{/.test(src), 'tagFor reassigned to clickable badge');
    assert(/class="tag ' \+ cls \+ ' prio-badge"/.test(src), 'badge carries the prio-badge hook + role');
    assert(/function openPriorityExplainer\(customer\)/.test(src), 'explainer open function present');
  });
  test('explainer avoids legacy corporate attach-rate grading', () => {
    assert(/function _prioDossier\(customer\)/.test(src), 'service dossier lookup present');
    assert(/Why ' \+ escapeHtml\(customer\) \+ ' is a ' \+ escapeHtml\(ratingTier\) \+ ' service attach opportunity/.test(src),
      'customer name escaped in service-opportunity title');
    assert(!/function priorityGradingRules\(\)/.test(src), 'corporate grading helper removed');
  });
  test('badge clicks are intercepted in capture phase (no drill-down navigation)', () => {
    assert(/document\.addEventListener\('click', function \(e\) \{[\s\S]*?e\.target\.closest\('\.prio-badge'\)[\s\S]*?e\.stopPropagation\(\);[\s\S]*?\}, true\);/.test(src),
      'capture-phase click handler must stopPropagation on badge clicks');
    assert(/if \(e\.key === 'Escape'\) \{ closePriorityExplainer\(\); return; \}/.test(src), 'Escape closes the explainer');
  });
}

// ---- generated acr.html: Opportunity Matrix customer breakdown modal ----
console.log('\nweb-app/acr.html (customer breakdown modal)');
{
  const src = fs.readFileSync(path.join(WEBAPP, ACR_PAGE), 'utf8');
  test('renderCustomerDetail is id-prefix aware (shared by panel + modal)', () => {
    assert(/function renderCustomerDetail\(name, idp\) \{/.test(src), 'renderCustomerDetail accepts an id prefix');
    assert(/idp = idp \|\| '';/.test(src), 'idp defaults to empty (drill-down panel)');
    assert(/document\.getElementById\(idp \+ 'cust-cards'\)\.innerHTML = /.test(src), 'cards target is prefixed');
    assert(/document\.getElementById\(idp \+ 'cust-priority'\)\.innerHTML = tagFor/.test(src), 'priority target is prefixed');
    assert(/const note = document\.getElementById\(idp \+ 'cust-signal'\);/.test(src), 'signal target is prefixed');
    assert(/const ph = document\.getElementById\(idp \+ 'cust-products'\);/.test(src), 'products target is prefixed');
  });
  test('drill-down signal note escapes Excel-derived notes (XSS)', () => {
    assert(/note\.innerHTML = `<strong>Signal:<\/strong> \$\{escapeHtml\(opp\.notes\)\}`;/.test(src), 'opp.notes must be escaped');
    assert(!/<strong>Signal:<\/strong> \$\{opp\.notes\}/.test(src), 'raw opp.notes interpolation must be gone');
  });
  test('customer modal markup + openers are present', () => {
    assert(/function openCustomerModal\(name\)/.test(src), 'openCustomerModal defined');
    assert(/function closeCustomerModal\(\)/.test(src), 'closeCustomerModal defined');
    assert(/function _ensureCustOverlay\(\)/.test(src), 'overlay builder defined');
    assert(/id="m-cust-title"/.test(src), 'modal title node present');
    assert(/id="m-cust-cards"/.test(src), 'modal cards node present');
    assert(/id="m-cust-signal"/.test(src), 'modal signal node present');
    assert(/id="m-cust-products"/.test(src), 'modal products node present');
    assert(/renderCustomerDetail\(name, 'm-'\);/.test(src), 'modal renders the breakdown with the m- prefix');
    assert(/if \(title\) title\.textContent = name;/.test(src), 'modal title set via textContent (safe)');
  });
  test('matrix customer clicks open the modal instead of navigating', () => {
    assert(/e\.target\.closest\('#chart-quadrant \[data-customer\], #chart-top-dfc \[data-customer\], #action-queue tr\[data-customer\]'\)/.test(src),
      'interceptor targets heatmap + overview top-customers chart + sales action queue');
    assert(/if \(e\.target\.closest\('\.prio-badge'\)\) return;/.test(src), 'priority badges are skipped (explainer wins)');
    assert(/openCustomerModal\(name\);/.test(src), 'interceptor opens the modal');
    assert(/document\.addEventListener\('click', function \(e\) \{[\s\S]*?#chart-quadrant \[data-customer\][\s\S]*?e\.stopPropagation\(\);[\s\S]*?e\.preventDefault\(\);[\s\S]*?\}, true\);/.test(src),
      'capture-phase handler stops propagation + default (no selectCustomer navigation)');
  });
  test('sales action queue rows open the modal', () => {
    assert(/#action-queue tr\[data-customer\]/.test(src),
      'sales action queue rows are in the modal interceptor selector');
    assert(/\['chart-quadrant', 'chart-top-dfc', 'action-queue'\]\.forEach/.test(src),
      'a11y observers cover the remaining customer-target hosts');
    assert(!/#all-tbody tr\[data-customer\]/.test(src), 'removed all-customers table from modal interceptor selector');
    assert(!/#opp-tbody tr\[data-customer\]/.test(src), 'removed opportunity table from modal interceptor selector');
  });
  test('overview top-customers chart opens the modal (not the drill-down tab)', () => {
    assert(/#chart-top-dfc \[data-customer\]/.test(src),
      'top-customers bars are in the modal interceptor selector');
  });
  test('customer targets are keyboard accessible (focusable + Enter/Space)', () => {
    assert(/function _enhanceCustomerTargetsA11y\(\)/.test(src), 'a11y enhancer defined');
    assert(/n\.setAttribute\('tabindex', '0'\)/.test(src), 'targets get tabindex');
    assert(/n\.setAttribute\('role', 'button'\)/.test(src), 'targets get button role');
    assert(/n\.tagName !== 'TR' && !n\.getAttribute\('role'\)/.test(src), 'table rows keep row semantics (no button role)');
    assert(/n\.setAttribute\('aria-label', 'Open breakdown for ' \+ nm\)/.test(src), 'targets get an aria-label');
    assert(/new MutationObserver\(_enhanceCustomerTargetsA11y\)\.observe\(host, \{ childList: true, subtree: true \}\);/.test(src),
      'observers re-apply a11y attributes after each render');
    assert(/document\.addEventListener\('keydown', function \(e\) \{[\s\S]*?if \(e\.key !== 'Enter' && e\.key !== ' ' && e\.key !== 'Spacebar'\) return;[\s\S]*?if \(e\.target\.closest\('\.prio-badge'\)\) return;[\s\S]*?#chart-quadrant \[data-customer\][\s\S]*?openCustomerModal\(name\);[\s\S]*?\}, true\);/.test(src),
      'keydown handler opens the modal, skips prio badges, mirrors the selector');
  });
  test('stacked Escape disambiguation via window-capture sentinel', () => {
    assert(/_custPrioWasOpenOnEscape = \(typeof _prioOverlay !== 'undefined'\) && !!\(_prioOverlay && !_prioOverlay\.hasAttribute\('hidden'\)\);/.test(src),
      'window-capture sentinel records prio-open state (guarded against undefined)');
    assert(/if \(_custPrioWasOpenOnEscape\) \{ _custPrioWasOpenOnEscape = false; return; \}/.test(src),
      'customer Escape handler defers to the priority modal when stacked');
  });
  test('modal product table has its own scoped SKU toggle', () => {
    assert(/mprod\.addEventListener\('click', \(e\) => \{/.test(src), 'modal SKU listener bound');
    assert(/mprod\.querySelectorAll\('\.' \+ sid\)/.test(src), 'SKU rows queried within the modal subtree');
    assert(/if \(!head \|\| !mprod\.contains\(head\)\) return;/.test(src), 'containment guard present');
  });
}

// ---- generated acr.html: per-service Defender attach (AE talk-track) ----
console.log('\nweb-app/acr.html (per-service Defender attach)');
{
  const src = fs.readFileSync(path.join(WEBAPP, ACR_PAGE), 'utf8');
  test('per-service attach renderer is defined and mounted (inline + modal)', () => {
    assert(/function renderServiceAttach\(idp, name\) \{/.test(src), 'renderServiceAttach defined');
    assert(/<div id="cust-attach"><\/div>/.test(src), 'inline mount present');
    assert(/<div id="m-cust-attach"><\/div>/.test(src), 'modal mount present');
    assert(/renderServiceAttach\(idp, name\);/.test(src), 'renderer invoked from renderCustomerDetail');
    assert(/const host = document\.getElementById\(idp \+ 'cust-attach'\);/.test(src), 'host target is id-prefix aware');
  });
  test('per-service attach hides gracefully without SL2/SL4 data', () => {
    assert(/if \(!sa \|\| !Array\.isArray\(sa\.dossiers\)\) \{/.test(src), 'guards on missing service_attach');
    assert(/host\.style\.display = 'none';/.test(src), 'hides host when no dossier');
    assert(/DATA\.service_attach_error/.test(src), 'surfaces engine error when present');
    assert(/sa\.dossiers\.find\(function \(x\) \{ return x\.customer === name; \}\)/.test(src), 'looks up dossier by customer');
  });
  test('per-service attach escapes all customer-derived strings (XSS)', () => {
    assert(/escapeHtml\(o\.planLabel\)/.test(src), 'plan label escaped');
    assert(/escapeHtml\(o\.opener\)/.test(src), 'AE opener escaped');
    assert(/escapeHtml\(f\.planLabel\)/.test(src), 'foundational plan label escaped');
    assert(/escapeHtml\(String\(saErr\)\)/.test(src), 'engine error escaped');
    assert(!/\$\{o\.opener\}/.test(src), 'no raw opener interpolation');
  });
  test('per-service attach respects dollar-gap eligibility + ranks by priority then score', () => {
    assert(/o\.hasDollarGap[\s\S]*?\/ mo gap/.test(src), 'dollar gap shown only when hasDollarGap');
    assert(/usage-priced/.test(src), 'usage-priced plans shown as coverage signal');
    assert(/a\.priorityRank == null \? 9 : a\.priorityRank/.test(src),
      'opportunities ranked by priorityRank first');
    assert(/\(b\.blendedScore \|\| 0\) - \(a\.blendedScore \|\| 0\)/.test(src),
      'blended score is the tie-breaker within a priority tier');
  });
  test('per-service attach surfaces High/Medium/Low priority tiers', () => {
    assert(/const prTag = o\.priority/.test(src), 'priority tag built per opportunity');
    assert(/escapeHtml\(o\.priority\) \+ ' priority/.test(src), 'priority label rendered and escaped');
    assert(/escapeHtml\(o\.priorityReason\)/.test(src), 'priority reason rendered and escaped');
    assert(/const tierLegend = opps\.length/.test(src), 'tier-definition legend present');
    assert(/workload growing faster than Defender attach/.test(src), 'High tier defined in legend');
  });
  test('service attach opportunities table includes search filtering', () => {
    assert(/id="action-queue-search"/.test(src), 'search input is rendered with action queue controls');
    assert(/Search service attach opportunities/.test(src), 'search input has an accessible label');
    assert(/document\.getElementById\('action-queue-search'\)\.addEventListener\('input', renderOpportunityHeatmap\)/.test(src),
      'search input re-renders the table on input');
    assert(/const term = \(document\.getElementById\('action-queue-search'\)\?\.value \|\| ''\)\.trim\(\)\.toLowerCase\(\)/.test(src),
      'action queue rows read the normalized search term');
    assert(/row\.topServiceLabel[\s\S]*row\.conversationAngle/.test(src),
      'search matches service, action, reason, and conversation fields');
    assert(/No opportunities match the current filters\./.test(src), 'empty search state is rendered');
  });
  test('per-service attach renders narrative sentence + all-plans scorecard (no SVG chart)', () => {
    assert(/function _saSentence\(customer, c\)/.test(src), '_saSentence helper defined');
    assert(/function _saScorecard\(d\)/.test(src), '_saScorecard helper defined');
    assert(/attach gap\./.test(src), 'narrative gap sentence phrasing present');
    assert(/Defender coverage scorecard/.test(src), 'all-plans scorecard title present');
    assert(/below_threshold: 0, on_track: 1, not_deployed: 2/.test(src),
      'scorecard sorts below-threshold first');
    assert(/const scorecard = _saScorecard\(d\);/.test(src), 'scorecard wired into renderer');
    assert(!/function _saGapChart\(/.test(src), 'old SVG gap chart helper removed');
    assert(!/Workload vs Defender ACR by service/.test(src), 'old chart title removed');
  });
  test('per-service attach folds scoring into click-to-expand scorecard accordions', () => {
    assert(/function _saOppDetail\(o\)/.test(src), '_saOppDetail expanded-detail helper defined');
    assert(/data-sa-toggle/.test(src), 'scorecard rows carry the accordion toggle hook');
    assert(/class="sa-detail"/.test(src), 'hidden per-plan detail panel present');
    assert(/window\.__saAccordionWired/.test(src), 'accordion handler wired once');
    assert(/aria-expanded/.test(src), 'accordion rows expose aria-expanded state');
    // The standalone opportunity cards must be gone (folded into the scorecard).
    assert(!/let oppHtml;/.test(src), 'old standalone opportunity-card block removed');
  });
  test('per-service attach shows the Total ACR gap banner (no "on the table" wording)', () => {
    assert(/Total ACR gap per month/.test(src), 'monthly gap headline present');
    assert(/Total ACR gap per year/.test(src), 'annual gap headline present');
    assert(!/on the table/.test(src), '"on the table" wording removed everywhere');
    assert(/const monthlyGap = d\.totalGapDollars \|\| 0/.test(src), 'monthly gap sourced from totalGapDollars');
    assert(/const annualGap = monthlyGap \* 12/.test(src), 'annual gap is monthly x12');
  });
  test('priority modal is simplified around service-level attach evidence', () => {
    assert(/function _prioServiceEvidence\(customer\)/.test(src), '_prioServiceEvidence helper defined');
    assert(/Service-level summary/.test(src), 'modal service summary present');
    assert(/Top service attach gaps/.test(src), 'modal top service gaps present');
    assert(/Why this is a priority/.test(src), 'modal concise priority bullets present');
    assert(/Suggested seller conversation/.test(src), 'modal seller prompt present');
    assert(/Eligible Azure workload ACR \/ mo/.test(src), 'eligible workload KPI present');
    assert(/Mapped Defender ACR \/ mo/.test(src), 'mapped Defender KPI present');
    assert(/const svcEvidenceHtml = _prioServiceEvidence\(customer\)/.test(src),
      'modal computes per-service evidence');
    assert(!/Corporate context/.test(src), 'corp context removed from modal');
    assert(!/How the corporate attach rating is graded/.test(src), 'corporate grading rubric removed from modal');
    assert(!/Defender share of total/.test(src), 'corp attach-rate metric removed from modal');
    assert(/escapeHtml\(o\.planLabel\)/.test(src), 'service labels escaped in modal evidence');
  });
}

// ---- generated acr.html: separate divergence stories page ----
console.log('\nweb-app/acr.html (divergence stories page)');
{
  const src = fs.readFileSync(path.join(WEBAPP, ACR_PAGE), 'utf8');
  test('service opportunities and divergence stories are separate tabs', () => {
    const divStart = src.indexOf('function ensureDivergenceStoriesShell()');
    const divEnd = src.indexOf('\nfunction setDivergenceStatus', divStart);
    const divShell = divStart >= 0 && divEnd > divStart ? src.slice(divStart, divEnd) : '';
    assert(/data-tab="opportunity">Service Attach Opportunities<\/button>/.test(src),
      'service attach tab has explicit seller-motion label');
    assert(/data-tab="divergence">Defender Coverage Drift<\/button>/.test(src),
      'divergence tab present');
    assert(/id="panel-divergence"/.test(src), 'divergence panel present');
    assert(/const host = document\.getElementById\('panel-divergence'\);/.test(src),
      'divergence shell mounts into its own panel');
    assert(!/chartBox\.parentElement\.insertBefore\(section, chartBox\)/.test(divShell),
      'divergence section is no longer inserted into the service opportunity panel');
  });
  test('divergence information cards are scenario-specific', () => {
    assert(/Coverage drift signals/.test(src), 'story count KPI present');
    assert(/Accounts affected/.test(src), 'affected-account KPI present');
    assert(/High severity/.test(src), 'high-severity KPI present');
    assert(/Largest momentum spread/.test(src), 'momentum-spread KPI present');
    assert(/workload and Defender trends misaligned/.test(src),
      'KPI copy describes divergence rather than attach opportunity estimates');
    assert(!/id="divergence-stories-section"[\s\S]{0,900}Annualized DfC Attach Opportunity/.test(src),
      'divergence page does not reuse service attach opportunity estimate cards');
  });
  test('divergence stories use customer queue layout with modal drill-down', () => {
    assert(/id="divergence-filter"/.test(src), 'divergence table has a priority-style filter');
    assert(/id="divergence-search"/.test(src), 'divergence table has a search box');
    assert(/id="divergence-limit"/.test(src), 'divergence table has a rows selector');
    assert(/<div class="scroll-table" style="max-height:620px;">/.test(src), 'divergence stories render in the shared scroll-table layout');
    assert(/<th>Customer<\/th>[\s\S]*<th>Severity<\/th>[\s\S]*<th class="num">Account ACR\/mo<\/th>[\s\S]*<th class="num">Divergence services<\/th>/.test(src),
      'divergence table uses customer-level queue columns');
    assert(/function divergenceCustomerRows\(\)/.test(src), 'customer grouping prevents duplicate customers in the main table');
    assert(/data-divergence-customer/.test(src), 'manager customer rows are clickable summaries');
    assert(/function openDivergenceCustomerModal\(name\)/.test(src), 'clicking a customer opens a divergence modal');
    assert(/Highest-opportunity divergences are listed first/.test(src), 'modal explains service comparisons are opportunity-sorted');
    assert(/Defender service \+ Azure workload/.test(src), 'modal compares Defender services to Azure workloads');
    assert(/data-customer-divergence-card/.test(src), 'customer drill-down stories render as expandable cards');
    assert(/Azure workload trend/.test(src), 'workload trend detail panel present');
    assert(/Matching Defender trend/.test(src), 'Defender trend detail panel present');
    assert(/function _storyEvidencePanel\(story\)/.test(src), 'shared side-by-side evidence renderer defined');
    assert(/function _seriesSpark\(values, color\)/.test(src), 'mini trend renderer defined');
    assert(/storyOpportunity\(story\)/.test(src), 'detail joins stories back to matching opportunity series');
  });
  test('divergence severity has its own explanation, separate from service attach priority', () => {
    assert(/function divergenceSeverityTag\(severity\)/.test(src), 'divergence severity badge helper exists');
    assert(/function openDivergenceSeverityExplainer\(severity\)/.test(src), 'divergence severity explainer exists');
    assert(/Divergence severity is separate from Service Attach priority/.test(src),
      'divergence explainer does not reuse service attach priority copy');
    assert(/<td>\$\{divergenceSeverityTag\(r\.severity\)\}<\/td>/.test(src),
      'main divergence table uses divergence severity badges');
    assert(!/<td>\$\{tagFor\(r\.severity\)\}<\/td>/.test(src),
      'main divergence table no longer uses service attach priority tag helper');
  });
}

// ---- service-level (SL2/SL4) attach: pipeline parity + privacy guards ----
console.log('\nweb-app service-level attach (SL2/SL4)');
{
  const ROOT = path.resolve(WEBAPP, '..');
  // SL/vendor modules are CommonJS-friendly; xlsx wants a window global.
  global.window = global.window || global;
  const XLSX = require(path.join(WEBAPP, 'vendor', 'xlsx.full.min.js'));
  const SLParser = require(path.join(WEBAPP, 'js', 'sl-parser.js'));
  const SLMapping = require(path.join(WEBAPP, 'js', 'sl-mapping.js'));
  const SLEngine = require(path.join(WEBAPP, 'js', 'sl-engine.js'));
  const SLExport = require(path.join(WEBAPP, 'js', 'sl-export.js'));

  const FIXTURE = path.join(ROOT, 'inputfolder', 'ACR Details SL2-SL4.xlsx');
  const GOLDEN = path.join(WEBAPP, 'tests', 'sl-golden.json');

  // The fixture (*.xlsx) and golden oracle (sl-golden.json) are derived from
  // real customer data and are gitignored — they exist only on the developer's
  // machine. Skip the parity check on a fresh clone rather than failing it.
  if (!fs.existsSync(FIXTURE) || !fs.existsSync(GOLDEN)) {
    skipTest('SL pipeline output matches Python golden oracle within tolerance',
      'gitignored customer fixture/golden not present');
  } else {
    const goldenForSchema = JSON.parse(fs.readFileSync(GOLDEN, 'utf8'));
    if (!goldenForSchema.meta || !Object.prototype.hasOwnProperty.call(goldenForSchema.meta, 'divergence_story_count')) {
      skipTest('SL pipeline output matches Python golden oracle within tolerance',
        'local gitignored sl-golden.json predates divergence-story export schema');
    } else {
      test('SL pipeline output matches Python golden oracle within tolerance', () => {
        assert(fs.existsSync(FIXTURE), 'fixture ACR Details SL2-SL4.xlsx must exist');
        assert(fs.existsSync(GOLDEN), 'sl-golden.json oracle must exist');
        const buf = fs.readFileSync(FIXTURE);
        const wb = XLSX.read(buf, { type: 'buffer', cellDates: true });
        const sheet = wb.Sheets.Export || wb.Sheets[wb.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: null, raw: true, cellDates: true });
        const parsed = SLParser.parseSl2Sl4(rows, 'ACR Details SL2-SL4.xlsx');
        const model = SLEngine.buildModel(parsed, undefined);
        const jsJson = SLExport.buildJson(model);
        const golden = goldenForSchema;
        jsJson.meta.generated_at = golden.meta.generated_at;

        assertEqual(jsJson.customers.length, golden.customers.length, 'customer count must match golden');

        function deepDiff(a, b, p, diffs, tol) {
          if (diffs.length > 40) return;
          if (typeof a === 'number' && typeof b === 'number') {
            if (!Number.isFinite(a) || !Number.isFinite(b)) { if (a !== b) diffs.push(`${p}: ${a} != ${b}`); return; }
            const t = p.includes('ratio') ? 1e-6 : tol;
            if (Math.abs(a - b) > t) diffs.push(`${p}: ${a} != ${b} (Δ ${Math.abs(a - b)})`);
            return;
          }
          if (Array.isArray(a) || Array.isArray(b)) {
            if (!Array.isArray(a) || !Array.isArray(b)) { diffs.push(`${p}: array mismatch`); return; }
            if (a.length !== b.length) diffs.push(`${p}: length ${a.length} != ${b.length}`);
            const n = Math.min(a.length, b.length);
            for (let i = 0; i < n; i += 1) deepDiff(a[i], b[i], `${p}[${i}]`, diffs, tol);
            return;
          }
          if (a && b && typeof a === 'object' && typeof b === 'object') {
            for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
              if (!(k in a)) { diffs.push(`${p}.${k}: missing in JS`); continue; }
              if (!(k in b)) { diffs.push(`${p}.${k}: missing in golden`); continue; }
              deepDiff(a[k], b[k], `${p}.${k}`, diffs, tol);
            }
            return;
          }
          if (a !== b) diffs.push(`${p}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`);
        }
        const diffs = [];
        deepDiff(jsJson, golden, '$', diffs, 0.011);
        assert(diffs.length === 0, 'SL output diverged from golden:\n      ' + diffs.slice(0, 10).join('\n      '));
      });
    }
  }

  if (!fs.existsSync(FIXTURE)) {
    skipTest('SL engine builds an all-plans catalog per dossier (golden-safe)',
      'gitignored customer fixture not present');
  } else {
    test('SL engine builds an all-plans catalog per dossier (golden-safe)', () => {
      const buf = fs.readFileSync(FIXTURE);
      const wb = XLSX.read(buf, { type: 'buffer', cellDates: true });
      const sheet = wb.Sheets.Export || wb.Sheets[wb.SheetNames[0]];
      const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: null, raw: true, cellDates: true });
      const parsed = SLParser.parseSl2Sl4(rows, 'ACR Details SL2-SL4.xlsx');
      const model = SLEngine.buildModel(parsed, undefined);
      const d = model.dossiers[0];
      assert(Array.isArray(d.catalog) && d.catalog.length > 0, 'dossier exposes a catalog array');
      const allowed = new Set(['below_threshold', 'on_track', 'not_deployed']);
      for (const c of d.catalog) {
        assert(allowed.has(c.status), `catalog status ${c.status} is from the allowed set`);
        assert(typeof c.planLabel === 'string' && c.planLabel.length, 'catalog entry has a plan label');
      }
      const labels = d.catalog.map((c) => c.planLabel);
      assert(new Set(labels).size === labels.length, 'catalog has one entry per plan');
      const jsJson = SLExport.buildJson(model);
      assert(jsJson.customers.every((c) => !('catalog' in c)), 'catalog is not serialized (parity preserved)');
    });
  }

  test('SL divergence stories are exported at book and customer level', () => {
    const months = ['M1', 'M2', 'M3', 'M4', 'M5', 'M6'];
    const frame = [];
    function add(customer, sl2, sl4, level, series) {
      months.forEach((month, idx) => {
        frame.push({ customer, sl2, sl4, level, month, acr: Number(series[idx]) });
      });
    }
    add('ExportCo', SLMapping.TOTAL_TOKEN, '', SLParser.LEVEL_CUSTOMER_TOTAL,
      [10000, 10000, 10000, 20000, 20000, 20000]);
    add('ExportCo', 'SQL Database', SLMapping.TOTAL_TOKEN, SLParser.LEVEL_SERVICE_TOTAL,
      [10000, 10000, 10000, 20000, 20000, 20000]);
    add('ExportCo', SLMapping.DEFENDER_SL2, SLMapping.TOTAL_TOKEN, SLParser.LEVEL_SERVICE_TOTAL,
      [100, 100, 100, 100, 100, 100]);
    add('ExportCo', SLMapping.DEFENDER_SL2, 'Microsoft Defender for SQL', SLParser.LEVEL_LEAF,
      [100, 100, 100, 100, 100, 100]);

    const parsed = {
      frame,
      months,
      customers: ['ExportCo'],
      reconciliation: [],
      sourceName: 'synthetic',
      rowCount: frame.length,
      latestMonth: 'M6',
    };
    const config = SLMapping.defaultConfig();
    config.useCohortMedian = false;
    const model = SLEngine.buildModel(parsed, config);
    const payload = SLExport.buildJson(model);
    const bookStory = payload.divergence_stories[0];
    const customerStory = payload.customers[0].divergence_stories[0];
    const requiredFields = [
      'customer', 'plan_label', 'workload_sl2_categories', 'workload_categories',
      'story_type', 'severity', 'confidence', 'pricing_driver',
      'latest_workload_acr', 'latest_defender_acr', 'compared_months',
      'workload_start_value', 'workload_end_value', 'defender_start_value',
      'defender_end_value', 'workload_delta', 'defender_delta',
      'workload_pct_change', 'defender_pct_change', 'momentum_spread',
      'has_dollar_gap', 'gap_dollars', 'headline', 'evidence_bullets',
      'recommended_action', 'caveat', 'caveat_text',
    ];

    assertEqual(payload.meta.divergence_story_count, 1, 'book story count');
    assert(bookStory && customerStory, 'story exists at book and customer level');
    assertEqual(JSON.stringify(bookStory), JSON.stringify(customerStory), 'book/customer story payloads match');
    requiredFields.forEach((field) => assert(field in customerStory, `missing story field ${field}`));
    assertEqual(customerStory.customer, 'ExportCo', 'story customer');
    assertEqual(customerStory.story_type, SLEngine.STORY_GROWTH_DIVERGENCE, 'story type');
    assertEqual(customerStory.workload_sl2_categories[0], 'SQL Database', 'workload category');
    assertEqual(customerStory.compared_months.length, months.length, 'compared months');
    assertEqual(customerStory.workload_pct_change, 1, 'workload safe percentage');
    assertEqual(customerStory.defender_pct_change, 0, 'defender safe percentage');
    assert(customerStory.caveat.includes('Directional signal'), 'caveat included');
    assertEqual(customerStory.caveat, customerStory.caveat_text, 'caveat alias');
  });

  test('SL coverage-only opportunity below the per-service floor is capped at Low priority', () => {
    const months = ['M1', 'M2', 'M3', 'M4', 'M5', 'M6'];
    function buildModelFor(sqlSeries) {
      const frame = [];
      const add = (sl2, sl4, level, series) => months.forEach((month, idx) => {
        frame.push({ customer: 'C', sl2, sl4, level, month, acr: Number(series[idx]) });
      });
      add(SLMapping.TOTAL_TOKEN, '', SLParser.LEVEL_CUSTOMER_TOTAL, [20000, 20000, 20000, 20000, 20000, 20000]);
      add('SQL Database', SLMapping.TOTAL_TOKEN, SLParser.LEVEL_SERVICE_TOTAL, sqlSeries);
      add(SLMapping.DEFENDER_SL2, SLMapping.TOTAL_TOKEN, SLParser.LEVEL_SERVICE_TOTAL, [0, 0, 0, 0, 0, 0]);
      add(SLMapping.DEFENDER_SL2, 'Microsoft Defender for SQL', SLParser.LEVEL_LEAF, [0, 0, 0, 0, 0, 0]);
      const parsed = {
        frame, months, customers: ['C'], reconciliation: [],
        sourceName: 'synthetic', rowCount: frame.length, latestMonth: 'M6',
      };
      const config = SLMapping.defaultConfig();
      config.useCohortMedian = false;
      const model = SLEngine.buildModel(parsed, config);
      return model.dossiers[0].opportunities.find((o) => o.planLabel === 'Defender for SQL');
    }
    // SQL floor is $500. Growing+unattached would normally be High; below the
    // floor the materiality gate caps it at Low. Above the floor it escalates.
    const low = buildModelFor([100, 150, 200, 250, 300, 350]);
    assert(low && low.hasDollarGap === false, 'sub-floor SQL opp is coverage-only');
    assert(low.workloadAcr < low.coveragePriorityFloor, 'sub-floor workload below the floor');
    assertEqual(low.priority, 'Low', 'sub-floor coverage-only opp capped at Low');

    const high = buildModelFor([300, 400, 500, 600, 700, 800]);
    assert(high && high.hasDollarGap === false, 'above-floor SQL opp is coverage-only');
    assert(high.workloadAcr >= high.coveragePriorityFloor, 'above-floor workload clears the floor');
    assertEqual(high.priority, 'High', 'above-floor coverage-only growth divergence stays High');
  });

  test('SL app scripts make no network calls (client-side privacy guard)', () => {
    const files = fs.readdirSync(path.join(WEBAPP, 'js'))
      .filter((f) => f.startsWith('sl-') && f.endsWith('.js'));
    assert(files.length >= 3, 'expected the reusable SL modules to be present');
    for (const f of files) {
      const src = fs.readFileSync(path.join(WEBAPP, 'js', f), 'utf8');
      assert(!/https?:\/\//.test(src), `${f} must not reference any remote URL (keep data in-browser)`);
      assert(!/\bfetch\s*\(/.test(src), `${f} must not call fetch() (no server round-trips)`);
      assert(!/XMLHttpRequest/.test(src), `${f} must not use XMLHttpRequest`);
    }
  });
}

console.log(`\nResults: ${pass} passed, ${fail} failed${skip ? ', ' + skip + ' skipped' : ''}`);
if (fail > 0) process.exit(1);
