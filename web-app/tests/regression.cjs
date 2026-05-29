// Regression tests for the static web app. Run from repo root or web-app/:
//   node web-app/tests/regression.cjs
// Exits non-zero on any failure. No external dependencies.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEBAPP = path.resolve(__dirname, '..');
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

let pass = 0, fail = 0;
function test(name, fn) {
  try { fn(); console.log('  PASS ' + name); pass++; }
  catch (e) { console.log('  FAIL ' + name + '\n      ' + (e.stack || e.message)); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error('assertion failed: ' + msg); }
function assertEqual(actual, expected, msg) {
  if (actual !== expected) throw new Error(`${msg || ''}\n      expected: ${JSON.stringify(expected)}\n      actual:   ${JSON.stringify(actual)}`);
}

// ---- acr index.html: generated-artifact regressions ----
console.log('\nweb-app/index.html (generated)');
{
  const src = fs.readFileSync(path.join(WEBAPP, 'index.html'), 'utf8');

  test('uses vendored SheetJS, not CDN', () => {
    assert(!/cdn\.sheetjs\.com/.test(src), 'CDN SheetJS URL must not appear');
    assert(/<script src="\.\/vendor\/xlsx\.full\.min\.js"><\/script>/.test(src), 'expected vendored xlsx script tag');
  });
  test('uses AcrModel.build instead of parseAndScore', () => {
    assert(/const newData = AcrModel\.build\(rows, file\.name\);/.test(src),
      'import handler must delegate to AcrModel.build');
    assert(!/= parseAndScore\(/.test(src), 'parseAndScore call must be replaced');
  });
  test('PowerPoint export wired to window.PptxAcr.exportDeck', () => {
    assert(/id="export-pptx-btn"/.test(src), 'export-pptx-btn must exist');
    assert(/window\.PptxAcr\.exportDeck\(DATA, sourceName, threshold\)/.test(src),
      'export handler must call PptxAcr.exportDeck with source + threshold');
  });
  test('renderOpportunityHeatmap escapes customer + notes', () => {
    const start = src.indexOf('function renderOpportunityHeatmap()');
    assert(start >= 0, 'renderOpportunityHeatmap function must exist in generated HTML');
    // Inspect the next ~6 KB — comfortably covers the function body.
    const body = src.slice(start, start + 6000);
    assert(/\$\{escapeHtml\(r\.customer\)\}/.test(body), 'customer must be escaped in heatmap');
    assert(/\$\{escapeHtml\(r\.notes\)\}/.test(body), 'notes must be escaped in heatmap');
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
  test('shared app nav + ACR-specific scripts are loaded', () => {
    for (const tag of [
      '<div id="app-nav" data-active="acr"></div>',
      './js/acr-model.js',
      './vendor/pptxgen.bundle.js',
      './js/pptx-acr.js',
      './js/app-nav.js',
    ]) {
      assert(src.includes(tag), `expected to find ${tag}`);
    }
  });
  test('nav has flex layout (regression: app-menu must not fall back to UA styles)', () => {
    assert(/#app-nav \.app-menu \{[\s\S]{0,400}display:\s*flex/.test(src),
      'app-menu must have flex layout — nav CSS not injected');
    assert(/#app-nav \.app-menu a\.active/.test(src), 'active link styling required');
    assert(/#app-nav \.app-menu \.source-pill/.test(src), 'source pill styling required');
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
    assert(/ACR_CACHE_KEY = 'defenderattach:acr:v2'/.test(src),
      'versioned sessionStorage key must be defined');
    assert(/sessionStorage\.setItem\(ACR_CACHE_KEY, json\)/.test(src),
      'must cache DATA after successful import');
    assert(/sessionStorage\.getItem\(ACR_CACHE_KEY\)/.test(src),
      'must restore DATA on page load');
    assert(/AppNav\.onReload\(function\(\)\{[\s\S]{0,200}sessionStorage\.removeItem\(ACR_CACHE_KEY\)/.test(src),
      'AppNav reload handler must clear the cache');
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
      'must cache rows + filenames + nearTerm after each successful file load');
    assert(/sessionStorage\.getItem\(CACHE_KEY\)/.test(ms),
      'must attempt restore on init');
    assert(/sessionStorage\.removeItem\(CACHE_KEY\)/.test(ms),
      'reload handler must clear the cache');
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

// ---- milestone-model: timezone boundary ----
console.log('\nmilestone-model.js');
{
  // Force JS interpreter to do TZ math in PST so the old bug would surface.
  process.env.TZ = 'America/Los_Angeles';
  const sb = makeSandbox();
  loadInto(sb, 'js/milestone-model.js');

  const headers = ['Translated Account Name','Opportunity ID','Milestone ID','Milestone Name','Milestone Workload','Workload','ACR Pipeline $','Status','Commitment','Due Date','Category','Owner Role','Owner'];
  const REF = '2024-03-15';
  const NEAR_TERM = 60;
  // 60 days after 2024-03-15 = 2024-05-14
  const onBoundary = '2024-05-14';
  const oneDayPast = '2024-05-15';

  const migA = [headers, ['Acme Corp','OPP-1','MS-1','Pilot','Compute','Compute',1000,'Open','No',onBoundary,'Discover','AE','Alice']];
  const modelA = sb.MilestoneModel.build(migA, [headers], { near_term_days: NEAR_TERM, reference_date: REF });
  const gapA = modelA.gaps.find(g => g.account === 'Acme Corp');

  test('account with due date exactly nearTermDays out is HIGH (boundary)', () => {
    assert(gapA, 'expected a gap row for Acme Corp');
    assertEqual(gapA.priority, 'HIGH', 'priority on the boundary');
  });

  const migB = [headers, ['Beta Inc','OPP-2','MS-2','Pilot','Compute','Compute',1000,'Open','No',oneDayPast,'Discover','AE','Bob']];
  const modelB = sb.MilestoneModel.build(migB, [headers], { near_term_days: NEAR_TERM, reference_date: REF });
  const gapB = modelB.gaps.find(g => g.account === 'Beta Inc');

  test('account with due date one day past nearTermDays is MEDIUM', () => {
    assert(gapB, 'expected a gap row for Beta Inc');
    assertEqual(gapB.priority, 'MEDIUM', 'priority one day past the boundary');
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

// ---- generated index.html: taxonomy/SKU hardening ----
console.log('\nweb-app/index.html (taxonomy + SKU drill-down)');
{
  const src = fs.readFileSync(path.join(WEBAPP, 'index.html'), 'utf8');
  test('product trend prefers DATA.track_products with validated colours', () => {
    assert(/DATA\.track_products && DATA\.track_products\.length/.test(src), 'taxonomy-aware track list');
    assert(/const colorFor = p =>/.test(src), 'colorFor helper present');
    assert(/\/\^#\[0-9a-fA-F\]\{6\}\$\/\.test\(c\)/.test(src), 'hex allowlist validation');
  });
  test('escapes Excel-derived product and SKU names', () => {
    assert(/const nameEsc = escapeHtml\(p\.product\);/.test(src), 'product name escaped');
    assert(/\$\{escapeHtml\(s\.sku\)\}/.test(src), 'SKU name escaped');
    assert(/\$\{escapeHtml\(p\)\}<\/span>/.test(src), 'legend label escaped');
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
  });
  test('KPI uses the last full month when the latest month is partial', () => {
    assert(/Math\.max\(0, DATA\.months\.length - 2\) : DATA\.months\.length - 1/.test(src), 'partial-month KPI guard');
  });
}

console.log('\nweb-app/index.html (weekly granularity views)');
{
  const src = fs.readFileSync(path.join(WEBAPP, 'index.html'), 'utf8');
  test('exposes monthly/weekly granularity controls, hidden by default', () => {
    assert(/id="product-trend-grain"/.test(src), 'overview grain select present');
    assert(/id="cust-trend-grain"/.test(src), 'customer grain select present');
    assert(/id="grain-ctl" hidden/.test(src), 'overview grain control hidden by default');
    assert(/id="cust-grain-ctl" hidden/.test(src), 'customer grain control hidden by default');
  });
  test('grain controls are only shown when weekly data is available', () => {
    assert(/function initGrainControls\(\)/.test(src), 'initGrainControls defined');
    assert(/const show = !!DATA\.weekly_enabled;/.test(src), 'visibility gated on weekly_enabled');
    assert(/initGrainControls\(\);/.test(src), 'initGrainControls invoked in renderAll');
  });
  test('overview trends switch between monthly and weekly series', () => {
    assert(/function renderDfcTrend\(\)/.test(src), 'grain-aware DfC trend defined');
    assert(/weekly \? DATA\.dfc_total_weekly : DATA\.dfc_total_monthly/.test(src), 'DfC weekly source wired');
    assert(/const src = weekly \? DATA\.product_weekly : DATA\.product_monthly;/.test(src), 'product weekly source wired');
    assert(/labels = weekly \? DATA\.week_labels : DATA\.month_labels/.test(src), 'weekly x-axis labels wired');
    assert(!/lineChart\('chart-dfc-trend', \[\{label: 'Defender for Cloud', values: DATA\.dfc_total_monthly, color: '#0078d4'\}\]\);/.test(src), 'no stale month-only DfC trend call');
  });
  test('customer drill-down charts switch granularity', () => {
    assert(/const cWeekly = !!\(cg && cg\.value === 'weekly' && DATA\.weekly_enabled && Array\.isArray\(cd\.dfc_weekly\) && Array\.isArray\(cd\.other_weekly\) && Array\.isArray\(cd\.total_weekly\)\);/.test(src), 'customer weekly guard present');
    assert(/const dfcSeries = cWeekly \? cd\.dfc_weekly : cd\.dfc_series;/.test(src), 'customer DfC series switched');
    assert(/lineChart\('chart-cust-dfc', \[[\s\S]*?\], \{labels: cLabels\}\);/.test(src), 'customer DfC chart relabelled');
    assert(/lineChart\('chart-cust-pct', .*\{labels: cLabels\}\);/.test(src), 'customer % chart relabelled');
  });
  test('granularity selects are wired to re-render their panels', () => {
    assert(/g\.addEventListener\('change', \(\) => \{ renderProductTrend\(\); renderDfcTrend\(\); \}\);/.test(src), 'overview grain listener present');
    assert(/cg\.addEventListener\('change', \(\) => \{ const cs = document\.getElementById\('customer-select'\); if \(cs && cs\.value\) renderCustomerDetail\(cs\.value\); \}\);/.test(src), 'customer grain listener present');
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

// ---- generated index.html: slider-driven reclassification ----
console.log('\nweb-app/index.html (attach baseline + reclassification)');
{
  const src = fs.readFileSync(path.join(WEBAPP, 'index.html'), 'utf8');
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
  test('PPTX export reclassifies against the current threshold', () => {
    assert(/if \(typeof reclassifyOpportunities === 'function'\) reclassifyOpportunities\(threshold\);/.test(src), 'export must reclassify before building the deck');
    assert(!/: 8;\n.*const sourceName = DATA\.source_name/.test(src), 'stale 8% export fallback must be gone');
  });
}

console.log(`\nResults: ${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
