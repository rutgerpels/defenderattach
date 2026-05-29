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
    assert(/ACR_CACHE_KEY = 'defenderattach:acr:v1'/.test(src),
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

console.log(`\nResults: ${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
