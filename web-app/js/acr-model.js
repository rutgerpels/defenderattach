// acr-model.js — port of src/defender_acr_dashboard/{data,dashboard_model,analytics}.py.
// Builds the dashboard model from the raw SheetJS rows of the ACR workbook.
// Exposes window.AcrModel.build(rows)

(() => {
  const DEFENDER_SERVICE = 'Defender for Cloud';
  const TOTAL_SERVICE = 'Total';
  const MONTHS = { Jan:1,Feb:2,Mar:3,Apr:4,May:5,Jun:6,Jul:7,Aug:8,Sep:9,Oct:10,Nov:11,Dec:12 };

  // Mirrors data.fiscal_month_to_period — used to sort months chronologically.
  function fiscalMonthRank(name) {
    const m = /^FY(\d{2})-([A-Za-z]{3})$/.exec(String(name).trim());
    if (!m) return [9999, 0];
    const fy = 2000 + Number(m[1]);
    const mon = m[2][0].toUpperCase() + m[2].slice(1, 3).toLowerCase();
    const month = MONTHS[mon] || 0;
    const calendarYear = month >= 7 ? fy - 1 : fy;
    return [calendarYear, month];
  }

  function cleanHeaderPart(value) {
    if (value == null) return '';
    const text = String(value).trim();
    if (text.startsWith('Unnamed:')) return '';
    return text;
  }

  function roundMoney(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0;
  }

  function pctChange(start, end) {
    if (start == null || start === 0) return null;
    return (end - start) / start;
  }

  // Corporate "Defender attach" baseline: every customer should run at least
  // this share of total ACR on Defender workloads. Drives the default priority
  // classification; the dashboard slider can override it client-side.
  const DEFAULT_DFC_SHARE = 0.06;

  // Core Azure workload categories (ServiceLevel1 names) used by the
  // break-of-trend rule. Names match the consumption workbook exactly.
  const GROWTH_CATEGORIES = ['Compute', 'Databases', 'Developer Tools', 'Integration', 'AI + Machine Learning', 'Containers'];

  // Aggregate (ACR-weighted) 3-month growth across the core workload categories
  // the customer actually uses. Summing dollars avoids a tiny category with a
  // huge percentage swing dominating an arithmetic mean. Returns the growth
  // fraction (null when there was no base spend) plus the names of categories
  // individually growing more than 5%.
  function categoryGrowth(breakdown, base3mIdx, latestIdx) {
    let base = 0;
    let latest = 0;
    const growing = [];
    for (const entry of (breakdown || [])) {
      if (GROWTH_CATEGORIES.indexOf(entry.product) === -1) continue;
      const s = Array.isArray(entry.series) ? entry.series : [];
      const b = Number(s[base3mIdx]) || 0;
      const l = Number(s[latestIdx]) || 0;
      base += b;
      latest += l;
      if (b > 0 && l > 0 && (l - b) / b > 0.05) growing.push(entry.product);
    }
    return { growth: base > 0 ? (latest - base) / base : null, growing };
  }

  const DEFENDER_NEW_S2 = 'Microsoft Defender for Cloud';
  const SENTINEL_S2 = 'Sentinel';
  // Deterministic, hex-validated palette for trend lines (DfC/Sentinel pinned).
  const TREND_PALETTE = ['#107c10', '#ff8c00', '#8764b8', '#d13438', '#00b294',
                         '#5c2d91', '#e3008c', '#0099bc', '#498205', '#c19c00'];
  const MAX_TRACK_PRODUCTS = 8;

  // Detect which workbook layout we were handed by inspecting header rows.
  // New layout: third row carries TPAccountName/ServiceLevel1/ServiceLevel2 + repeated '$ ACR',
  //             first row carries FY##-MMM fiscal-month bands.
  // Old layout: second row carries TPAccountName + ServiceCompGrouping.
  function detectFormat(rows) {
    const lc = v => String(v == null ? '' : v).replace(/\u00a0/g, ' ').trim().toLowerCase();
    const r0 = (rows[0] || []).map(lc);
    const r1 = (rows[1] || []).map(lc);
    const r2 = (rows[2] || []).map(lc);
    const hasFiscalBand = r0.some(v => /^fy\d{2}-/.test(v));
    const isNew = rows.length > 3
      && r2.includes('tpaccountname')
      && r2.includes('servicelevel1')
      && r2.includes('servicelevel2')
      && r2.includes('$ acr')
      && hasFiscalBand;
    const isOld = r1.includes('tpaccountname') && r1.includes('servicecompgrouping');
    // SL2/SL4 service-attach export: two-row header (FiscalMonth band over a
      // TPAccountName/ServiceLevel2/ServiceLevel4 + repeated '$ ACR' block). Folded
      // into this dashboard as the single, more granular data source.
    const isSlAttach = r1.includes('tpaccountname')
      && r1.includes('servicelevel2')
      && r1.includes('servicelevel4')
      && r1.includes('$ acr');
    if (isNew && isOld) {
      throw new Error('Workbook header matched both the old and new layouts; cannot disambiguate the format.');
    }
    if (isNew) return 'new';
    if (isOld) return 'old';
    if (isSlAttach) return 'sl2sl4';
    return 'unknown';
  }

  // Dispatcher: route to the legacy ServiceCompGrouping builder or the new
  // ServiceLevel1/ServiceLevel2 weekly-grain builder, both emitting the same DATA contract.
  function build(rows, sourceName = '') {
    if (!Array.isArray(rows) || rows.length < 3) {
      throw new Error('Worksheet has fewer than 3 rows; expected a header followed by data.');
    }
    const format = detectFormat(rows);
    if (format === 'new') return buildNew(rows, sourceName);
    if (format === 'old') return buildOld(rows, sourceName);
    if (format === 'sl2sl4') return buildSl2Sl4(rows, sourceName);
    throw new Error('Unrecognised workbook layout. Expected either a TPAccountName/ServiceCompGrouping export or a TPAccountName/ServiceLevel1/ServiceLevel2 weekly export.');
  }

  // Lazily resolve the SL2/SL4 helper modules. Resolved at call time (not at IIFE
  // eval) because, in the browser, the SL <script> tags load before this file but
  // window.SLParser may still be assigned in any order; require() wins in Node.
  function slParser() {
    if (typeof require !== 'undefined') { try { return require('./sl-parser.js'); } catch (e) { /* browser */ } }
    return (typeof window !== 'undefined') ? window.SLParser : null;
  }
  function slEngine() {
    if (typeof require !== 'undefined') { try { return require('./sl-engine.js'); } catch (e) { /* browser */ } }
    return (typeof window !== 'undefined') ? window.SLEngine : null;
  }

  // Build the corp dashboard DATA contract from a Service Level 2/4 export.
  // The SL2/SL4 file is the single source: the customer 'Total' row gives the
  // authoritative total ACR, the 'Microsoft Defender for Cloud' service subtotal
  // gives DfC ACR, and every other ServiceLevel2 subtotal becomes a product. Only
  // Total/subtotal rows feed the pivot (leaf SL4 rows already roll up into them,
  // so including them would double-count). The RAW frame additionally powers the
  // per-service attach drill-down via SLEngine (model.service_attach).
  function buildSl2Sl4(rows, sourceName = '') {
    const Parser = slParser();
    if (!Parser || typeof Parser.parseSl2Sl4 !== 'function') {
      throw new Error('The Service Level 2/4 parser (sl-parser.js) is not loaded; cannot import this export.');
    }
    const parsed = Parser.parseSl2Sl4(rows, sourceName);
    if (!parsed.months || parsed.months.length < 2) {
      throw new Error('The Service Level 2/4 export must contain at least two completed fiscal months of $ ACR.');
    }
    const SERVICE_TOTAL  = Parser.LEVEL_SERVICE_TOTAL  || 'service_total';
    const CUSTOMER_TOTAL = Parser.LEVEL_CUSTOMER_TOTAL || 'customer_total';

    const months = parsed.months.slice().sort((a, b) => {
      const ra = fiscalMonthRank(a), rb = fiscalMonthRank(b);
      return ra[0] - rb[0] || ra[1] - rb[1];
    });
    const monthIndex = new Map(months.map((m, i) => [m, i]));
    const monthLabels = months.map(m => (m.includes('-') ? m.split('-', 2)[1] : m));

    const DEFENDER_SL2 = 'Microsoft Defender for Cloud';
    const normalize = sl2 => (sl2 === DEFENDER_SL2 ? DEFENDER_SERVICE : sl2);

    const pivot = new Map();         // key: customer||product -> number[] (per month)
    const customersSet = new Set();
    const productsSet = new Set();
    const zeroes = () => months.map(() => 0);

    for (const rec of parsed.frame) {
      if (rec.level !== SERVICE_TOTAL && rec.level !== CUSTOMER_TOTAL) continue;
      const idx = monthIndex.get(rec.month);
      if (idx === undefined) continue;  // skips any 'Total' aggregate column
      const cust = rec.customer;
      if (!cust || cust === 'Total') continue;
      customersSet.add(cust);
      let product;
      if (rec.level === CUSTOMER_TOTAL) {
        product = TOTAL_SERVICE;
      } else {
        product = normalize(rec.sl2);
        if (product === TOTAL_SERVICE) continue;  // never let a service masquerade as the customer total
        productsSet.add(product);
      }
      const key = cust + '||' + product;
      let s = pivot.get(key);
      if (!s) { s = zeroes(); pivot.set(key, s); }
      const num = typeof rec.acr === 'number' ? rec.acr : (rec.acr == null || rec.acr === '' ? 0 : (parseFloat(rec.acr) || 0));
      s[idx] += num;
    }

    customersSet.delete('Total');
    const customers = [...customersSet].sort();
    const products  = [...productsSet].sort();
    const series = (c, p) => pivot.get(c + '||' + p) || zeroes();

    const model = assembleFromPivot({ series, customers, products, months, monthLabels, sourceName });
    model.format = 'sl2sl4';
    model.reconciliation = parsed.reconciliation || [];

    // Per-service attach drill-down uses the RAW (un-normalised) frame because
    // SLEngine keys on the original 'Microsoft Defender for Cloud' SL2 and
    // SLMapping.WORKLOAD_PLANS. Never mutate parsed.frame above.
    const Engine = slEngine();
    if (Engine && typeof Engine.buildModel === 'function') {
      try { model.service_attach = Engine.buildModel(parsed); }
      catch (e) { model.service_attach_error = String((e && e.message) || e); }
    }
    return model;
  }

  // --- Week-start header helpers (cells may be Date, Excel serial, or ISO string) ---
  // Returns [year, monthIndex, day] using calendar parts, stable across timezones.
  function weekParts(value) {
    if (value && typeof value === 'object' && typeof value.getTime === 'function' && !isNaN(value.getTime())) {
      return [value.getFullYear(), value.getMonth(), value.getDate()];
    }
    if (typeof value === 'number' && Number.isFinite(value)) {
      // Excel serial date -> calendar day (epoch 1899-12-30), read in UTC to avoid drift.
      const d = new Date(Math.round((value - 25569) * 86400 * 1000));
      return [d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()];
    }
    const m = /(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
    if (m) return [Number(m[1]), Number(m[2]) - 1, Number(m[3])];
    return null;
  }
  const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function weekKey(value) {
    const p = weekParts(value);
    return p ? p[0] + '-' + String(p[1] + 1).padStart(2, '0') + '-' + String(p[2]).padStart(2, '0') : String(value).slice(0, 10);
  }
  function weekSort(value) {
    const p = weekParts(value);
    return p ? Date.UTC(p[0], p[1], p[2]) : 0;
  }
  function weekStartLabel(value) {
    const p = weekParts(value);
    return p ? MONTH_ABBR[p[1]] + ' ' + String(p[2]).padStart(2, '0') : String(value).slice(0, 10);
  }

  function isHexColor(v) { return typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v); }

  // New-format builder: ServiceLevel1 categories with ServiceLevel2 SKU leaves and
  // weekly $ ACR columns. Emits the identical DATA contract consumed by the dashboard,
  // plus SKU drill-down (skus[]), weekly series, and a taxonomy-aware product list.
  function buildNew(rows, sourceName = '') {
    const h0 = (rows[0] || []).map(cleanText);
    const h1 = rows[1] || [];
    const h2 = (rows[2] || []).map(cleanText);
    const lc = s => String(s == null ? '' : s).toLowerCase();
    const find2 = name => { const t = name.toLowerCase(); for (let i = 0; i < h2.length; i++) if (lc(h2[i]) === t) return i; return -1; };
    const tzCol = find2('Timezone');
    const tpCol = find2('TPAccountName');
    const s1Col = find2('ServiceLevel1');
    const s2Col = find2('ServiceLevel2');
    if (tpCol < 0 || s1Col < 0 || s2Col < 0) {
      throw new Error('New-format workbook is missing one of the required columns: TPAccountName, ServiceLevel1, ServiceLevel2.');
    }

    // Classify every '$ ACR' column as a month subtotal ('Total' week), a weekly bucket, or the grand total.
    const monthTotalCol = new Map();   // fiscalMonth -> column index
    const weeklyCols = [];             // {month, key, label, sort, index}
    let weekParseError = false;
    for (let i = 0; i < h2.length; i++) {
      if (cleanText(h2[i]) !== '$ ACR') continue;
      const month = cleanText(h0[i]);
      const wkText = cleanText(h1[i]);
      if (/^FY\d{2}-/.test(month)) {
        if (wkText === 'Total') monthTotalCol.set(month, i);
        else if (wkText) {
          if (!weekParts(h1[i])) weekParseError = true;   // unrecognized week-start header
          weeklyCols.push({ month, key: weekKey(h1[i]), label: weekStartLabel(h1[i]), sort: weekSort(h1[i]), index: i });
        }
      }
    }
    const months = [...monthTotalCol.keys()].sort((a, b) => {
      const ra = fiscalMonthRank(a), rb = fiscalMonthRank(b);
      return ra[0] - rb[0] || ra[1] - rb[1];
    });
    if (!months.length) {
      throw new Error("No monthly '$ ACR' subtotal columns were found in the new-format workbook.");
    }
    if (months.length < 2) {
      throw new Error('The weekly export contains only one fiscal month (' + months[0] +
        "). At least one completed month before the in-progress month is required to score opportunities.");
    }
    const monthLabels = months.map(m => m.includes('-') ? m.split('-', 2)[1] : m);
    const monthCols = months.map(m => monthTotalCol.get(m));

    // Merge boundary weeks that share a week-start date (split across two fiscal months).
    const weekColsByKey = new Map();
    const weekLabelByKey = new Map();
    const weekSortByKey = new Map();
    for (const w of weeklyCols) {
      if (!weekColsByKey.has(w.key)) { weekColsByKey.set(w.key, []); weekLabelByKey.set(w.key, w.label); weekSortByKey.set(w.key, w.sort); }
      weekColsByKey.get(w.key).push(w.index);
    }
    const weekOrder = [...weekColsByKey.keys()].sort((a, b) => weekSortByKey.get(a) - weekSortByKey.get(b));
    const weekLabels = weekOrder.map(k => weekLabelByKey.get(k));

    const num = v => (typeof v === 'number' ? v : (v == null || v === '' ? 0 : (parseFloat(v) || 0)));
    const zerosM = () => months.map(() => 0);
    const zerosW = () => weekOrder.map(() => 0);
    const monthlyOf = row => monthCols.map(ci => num(row[ci]));
    const weeklyOf = row => weekOrder.map(k => weekColsByKey.get(k).reduce((acc, ci) => acc + num(row[ci]), 0));
    const addArr = (target, src) => { for (let i = 0; i < target.length; i++) target[i] += src[i]; };

    const customersSet = new Set();
    const productsSet = new Set();
    const totalMonthly = new Map();   // cust -> number[months]
    const totalWeekly = new Map();    // cust -> number[weeks]
    const groupMonthly = new Map();   // cust -> Map(group -> number[months])
    const groupWeekly = new Map();    // cust -> Map(group -> number[weeks])
    const skuMonthly = new Map();     // cust -> Map(group -> Map(sku -> number[months]))

    const groupOf = (s1, s2) => (s2 === DEFENDER_NEW_S2 ? DEFENDER_SERVICE : (s2 === SENTINEL_S2 ? 'Sentinel' : s1));

    for (let r = 3; r < rows.length; r++) {
      const row = rows[r] || [];
      const tz = cleanText(tzCol >= 0 ? row[tzCol] : row[0]);
      if (tz.toLowerCase().startsWith('applied filters')) continue;   // trailing filter banner
      const cust = cleanText(row[tpCol]);
      if (!cust || cust === 'Total') continue;                        // skip grand-total customer
      const s1 = cleanText(row[s1Col]);
      const s2 = cleanText(row[s2Col]);
      const mser = monthlyOf(row);

      if (s1 === 'Total') {
        // Account-total pivot row: authoritative per-customer total.
        customersSet.add(cust);
        if (!totalMonthly.has(cust)) { totalMonthly.set(cust, zerosM()); totalWeekly.set(cust, zerosW()); }
        addArr(totalMonthly.get(cust), mser);
        if (weekOrder.length) addArr(totalWeekly.get(cust), weeklyOf(row));
        continue;
      }
      if (!s1 || !s2 || s2 === 'Total') continue;                     // skip S1 subtotal / blank to avoid double counting

      // SKU leaf row.
      customersSet.add(cust);
      const group = groupOf(s1, s2);
      productsSet.add(group);
      if (!groupMonthly.has(cust)) { groupMonthly.set(cust, new Map()); groupWeekly.set(cust, new Map()); skuMonthly.set(cust, new Map()); }
      const gm = groupMonthly.get(cust);
      if (!gm.has(group)) { gm.set(group, zerosM()); }
      addArr(gm.get(group), mser);
      if (weekOrder.length) {
        const gw = groupWeekly.get(cust);
        if (!gw.has(group)) gw.set(group, zerosW());
        addArr(gw.get(group), weeklyOf(row));
      }
      const sm = skuMonthly.get(cust);
      if (!sm.has(group)) sm.set(group, new Map());
      const skuMap = sm.get(group);
      if (!skuMap.has(s2)) skuMap.set(s2, zerosM());
      addArr(skuMap.get(s2), mser);
    }

    const customers = [...customersSet].sort();
    const products = [...productsSet].sort();

    // Validate the boundary-week merge before trusting weekly output. An unparseable
    // week-start header, or any customer whose merged weekly series does not reconcile
    // with its monthly subtotals, disables weekly output entirely.
    let weeklyEnabled = weekOrder.length > 0 && !weekParseError;
    if (weeklyEnabled) {
      for (const c of customers) {
        const m = totalMonthly.get(c) || [];
        const w = totalWeekly.get(c) || [];
        let sm = 0, sw = 0;
        m.forEach(v => sm += v);
        w.forEach(v => sw += v);
        const tol = Math.max(1, Math.abs(sm) * 0.001);
        if (Math.abs(sm - sw) > tol) { weeklyEnabled = false; break; }
      }
    }

    // Partial-month handling: a weekly date-grain export's latest month is in progress.
    // Score KPIs/opportunities on the last FULL month; keep the partial month in the charts.
    const partialIdx = months.length - 1;
    const latestIdx = partialIdx > 0 ? partialIdx - 1 : partialIdx;   // last full month
    const priorIdx = Math.max(0, latestIdx - 1);
    const base3mIdx = Math.max(0, latestIdx - 2);
    const latestFy = months[latestIdx] ? months[latestIdx].split('-', 2)[0] : '';
    const fytdIndices = months.map((m, i) => (m.split('-', 2)[0] === latestFy && i <= latestIdx) ? i : -1).filter(i => i >= 0);

    const opportunity = [];
    const customerData = {};

    for (const customer of customers) {
      const total = (totalMonthly.get(customer) || zerosM()).map(roundMoney);
      const gm = groupMonthly.get(customer) || new Map();
      const dfc = (gm.get(DEFENDER_SERVICE) || zerosM()).map(roundMoney);
      const other = total.map((t, i) => roundMoney(t - dfc[i]));

      const dfc_current = dfc[latestIdx];
      const total_current = total[latestIdx];
      const other_current = other[latestIdx];
      const dfc_fytd = fytdIndices.reduce((a, i) => a + dfc[i], 0);
      const total_fytd = fytdIndices.reduce((a, i) => a + total[i], 0);
      const other_fytd = fytdIndices.reduce((a, i) => a + other[i], 0);

      const dfc_mom = pctChange(dfc[priorIdx], dfc[latestIdx]);
      const other_mom = pctChange(other[priorIdx], other[latestIdx]);
      const total_mom = pctChange(total[priorIdx], total[latestIdx]);
      const dfc_3m = pctChange(dfc[base3mIdx], dfc[latestIdx]);
      const other_3m = pctChange(other[base3mIdx], other[latestIdx]);
      const total_3m = pctChange(total[base3mIdx], total[latestIdx]);

      const dfc_3m_delta = dfc[latestIdx] - dfc[base3mIdx];
      const other_3m_delta = other[latestIdx] - other[base3mIdx];
      const total_3m_delta = total[latestIdx] - total[base3mIdx];

      const dfc_ratio = total_current > 0 ? (dfc_current / total_current) : 0;
      const dfc_fytd_ratio = total_fytd > 0 ? (dfc_fytd / total_fytd) : 0;

      // Reconcile SKU groups against the account total; surface any residual explicitly.
      const groupSum = zerosM();
      for (const arr of gm.values()) addArr(groupSum, arr);
      const residual = total.map((t, i) => roundMoney(t - groupSum[i]));
      const residualMax = Math.max.apply(null, residual.map(Math.abs).concat([0]));

      const skuByGroup = skuMonthly.get(customer) || new Map();
      const gw = groupWeekly.get(customer) || new Map();
      const breakdown = [];
      const groupNames = [...gm.keys()];
      if (residualMax > 1) { groupNames.push('Other (unmapped)'); }
      for (const p of groupNames) {
        const ps = (p === 'Other (unmapped)' ? residual : (gm.get(p) || zerosM())).map(roundMoney);
        const current = ps[latestIdx];
        const maxV = Math.max.apply(null, ps.length ? ps : [0]);
        if (current < 1 && maxV < 1) continue;
        const skus = [];
        const skuMap = skuByGroup.get(p);
        if (skuMap) {
          for (const [name, arr] of skuMap) {
            const ss = arr.map(roundMoney);
            const sc = ss[latestIdx];
            const sMax = Math.max.apply(null, ss.length ? ss : [0]);
            if (sc < 1 && sMax < 1) continue;
            skus.push({ sku: name, current: roundMoney(sc), mom: pctChange(ss[priorIdx], ss[latestIdx]), three_m: pctChange(ss[base3mIdx], ss[latestIdx]), series: ss });
          }
          skus.sort((a, b) => b.current - a.current);
        }
        const entry = { product: p, current: roundMoney(current), mom: pctChange(ps[priorIdx], ps[latestIdx]), three_m: pctChange(ps[base3mIdx], ps[latestIdx]), series: ps };
        if (skus.length) entry.skus = skus;
        breakdown.push(entry);
      }
      breakdown.sort((a, b) => b.current - a.current);

      const catGrowth = categoryGrowth(breakdown, base3mIdx, latestIdx);
      const growth_cat_3m = catGrowth.growth;
      const growth_cat_names = catGrowth.growing;
      const [priority, notes] = classifyOpportunity({ dfc_current, total_current, dfc_ratio, dfc_3m, other_3m, growth_cat_3m, growth_cat_names });

      opportunity.push({
        customer,
        opportunity: priority,
        notes,
        dfc_current: roundMoney(dfc_current),
        other_current: roundMoney(other_current),
        total_current: roundMoney(total_current),
        dfc_monthly_current: roundMoney(dfc_current),
        other_monthly_current: roundMoney(other_current),
        total_monthly_current: roundMoney(total_current),
        dfc_fytd: roundMoney(dfc_fytd),
        other_fytd: roundMoney(other_fytd),
        total_fytd: roundMoney(total_fytd),
        dfc_ratio: round2(dfc_ratio * 100),
        dfc_fytd_ratio: round2(dfc_fytd_ratio * 100),
        dfc_mom, other_mom, total_mom, dfc_3m, other_3m, total_3m,
        dfc_3m_delta: roundMoney(dfc_3m_delta),
        other_3m_delta: roundMoney(other_3m_delta),
        total_3m_delta: roundMoney(total_3m_delta),
        growth_gap: roundMoney(other_3m_delta - dfc_3m_delta),
        growth_cat_3m,
        growth_cat_names,
      });

      const cd = {
        dfc_series: dfc,
        other_series: other,
        total_series: total,
        products: breakdown,
      };
      if (weeklyEnabled) {
        const tw = (totalWeekly.get(customer) || zerosW()).map(roundMoney);
        const dw = (gw.get(DEFENDER_SERVICE) || zerosW()).map(roundMoney);
        cd.total_weekly = tw;
        cd.dfc_weekly = dw;
        cd.other_weekly = tw.map((t, i) => roundMoney(t - dw[i]));
      }
      customerData[customer] = cd;
    }

    // Product aggregations across customers.
    const productMonthly = {};
    for (const p of products) {
      const monthly = zerosM();
      for (const c of customers) { const g = groupMonthly.get(c); if (g && g.has(p)) addArr(monthly, g.get(p)); }
      productMonthly[p] = monthly.map(roundMoney);
    }
    {
      const totals = zerosM();
      for (const c of customers) addArr(totals, totalMonthly.get(c) || zerosM());
      productMonthly[TOTAL_SERVICE] = totals.map(roundMoney);
    }
    // Always surface the Defender line, even for segments with zero DfC spend (the core
    // opportunity story): the trend chart drops any product missing from product_monthly.
    if (!productMonthly[DEFENDER_SERVICE]) productMonthly[DEFENDER_SERVICE] = zerosM();

    const productWeekly = {};
    if (weeklyEnabled) {
      for (const p of products) {
        const weekly = zerosW();
        for (const c of customers) { const g = groupWeekly.get(c); if (g && g.has(p)) addArr(weekly, g.get(p)); }
        productWeekly[p] = weekly.map(roundMoney);
      }
      // Mirror the monthly guard: keep the Defender line present in weekly mode too.
      if (!productWeekly[DEFENDER_SERVICE]) productWeekly[DEFENDER_SERVICE] = zerosW();
    }

    // Track-products: build from the actual product list (DfC pinned first), ranked by last-full-month ACR.
    const ranked = products
      .filter(p => p !== DEFENDER_SERVICE)
      .map(p => ({ p, v: (productMonthly[p] || [])[latestIdx] || 0 }))
      .sort((a, b) => b.v - a.v)
      .map(o => o.p);
    const trackProducts = [DEFENDER_SERVICE, ...ranked].slice(0, MAX_TRACK_PRODUCTS);
    const productColors = {};
    let pi = 0;
    for (const p of trackProducts) {
      const c = p === DEFENDER_SERVICE ? '#0078d4' : (p === 'Sentinel' ? '#005a9e' : TREND_PALETTE[pi++ % TREND_PALETTE.length]);
      if (isHexColor(c)) productColors[p] = c;
    }

    // Aggregate per-customer SKU leaves into an overview-level category -> SKU map so the
    // product-mix donut can drill into each slice. Keyed by the same group() taxonomy as
    // product_monthly, so sum(product_skus[group]) reconciles with product_monthly[group].
    const productSkus = {};
    for (const c of customers) {
      const sm = skuMonthly.get(c);
      if (!sm) continue;
      for (const [group, skuMap] of sm) {
        if (!productSkus[group]) productSkus[group] = new Map();
        const agg = productSkus[group];
        for (const [sku, arr] of skuMap) {
          if (!agg.has(sku)) agg.set(sku, zerosM());
          addArr(agg.get(sku), arr);
        }
      }
    }
    const productSkusOut = {};
    for (const group of Object.keys(productSkus)) {
      const list = [];
      for (const [sku, arr] of productSkus[group]) list.push({ sku, monthly: arr.map(roundMoney) });
      list.sort((a, b) => b.monthly.reduce((s, v) => s + v, 0) - a.monthly.reduce((s, v) => s + v, 0));
      productSkusOut[group] = list;
    }

    const priorityRank = { High: 0, Medium: 1, Low: 2, 'Too small': 3 };
    opportunity.sort((a, b) => priorityRank[a.opportunity] - priorityRank[b.opportunity] || b.total_current - a.total_current);

    const result = {
      format: 'new',
      months,
      month_labels: monthLabels,
      partial_month_idx: partialIdx,
      last_full_month: months[latestIdx] || '',
      prior_month: months[priorIdx] || '',
      current_fiscal_year: latestFy,
      classification_basis: months[latestIdx] || '',
      fytd_months: fytdIndices.map(i => months[i]),
      customers,
      products,
      opportunity,
      customer_data: customerData,
      product_monthly: productMonthly,
      dfc_total_monthly: productMonthly[DEFENDER_SERVICE] || zerosM(),
      track_products: trackProducts,
      product_colors: productColors,
      product_skus: productSkusOut,
      counts: {
        high: opportunity.filter(r => r.opportunity === 'High').length,
        medium: opportunity.filter(r => r.opportunity === 'Medium').length,
        low: opportunity.filter(r => r.opportunity === 'Low').length,
        too_small: opportunity.filter(r => r.opportunity === 'Too small').length,
        total: customers.length,
      },
      source_name: sourceName,
    };
    if (weeklyEnabled) {
      result.week_labels = weekLabels;
      result.product_weekly = productWeekly;
      result.dfc_total_weekly = productWeekly[DEFENDER_SERVICE] || zerosW();
      result.weekly_enabled = true;
    } else {
      result.weekly_enabled = false;
    }
    return result;
  }

  // Parses rows from XLSX.utils.sheet_to_json(sheet, {header:1}) for the Export sheet.
  // Builds the same shape as dashboard_model.build_dashboard_model in Python.
  function buildOld(rows, sourceName = '') {
    if (!Array.isArray(rows) || rows.length < 3) {
      throw new Error('Worksheet has fewer than 3 rows; expected a two-row header followed by data.');
    }
    const headerTop = (rows[0] || []).map(cleanHeaderPart);
    const headerBottom = (rows[1] || []).map(cleanHeaderPart);

    // Locate column indices.
    const customerCol = findIndex(headerTop, headerBottom, 'TPAccountName');
    const serviceCol  = findIndex(headerTop, headerBottom, 'ServiceCompGrouping');
    if (customerCol < 0) throw new Error("Required column 'TPAccountName' was not found in the workbook header.");
    if (serviceCol < 0)  throw new Error("Required column 'ServiceCompGrouping' was not found in the workbook header.");

    // Identify "$ ACR" metric columns: row 0 contains FY##-MMM and row 1 contains '$ ACR'.
    const metricColumns = [];
    for (let i = 0; i < Math.max(headerTop.length, headerBottom.length); i++) {
      if (headerBottom[i] === '$ ACR' && /^FY\d{2}-/.test(headerTop[i] || '')) {
        metricColumns.push({ index: i, fiscal_month: headerTop[i] });
      }
    }
    if (!metricColumns.length) {
      throw new Error("No monthly '$ ACR' metric columns were found in the workbook. Confirm the export was generated with monthly ACR metrics enabled.");
    }
    // Sort chronologically.
    metricColumns.sort((a, b) => {
      const ra = fiscalMonthRank(a.fiscal_month), rb = fiscalMonthRank(b.fiscal_month);
      return ra[0] - rb[0] || ra[1] - rb[1];
    });
    const months = metricColumns.map(c => c.fiscal_month);
    const monthLabels = months.map(m => m.includes('-') ? m.split('-', 2)[1] : m);

    // Build per-(customer,service) monthly series, summing duplicate rows like pivot_table would.
    const pivot = new Map();  // key: customer||service → number[] (per month)
    const customersSet = new Set();
    const productsSet = new Set();
    const zeroes = () => months.map(() => 0);

    for (let r = 2; r < rows.length; r++) {
      const row = rows[r] || [];
      const cust = cleanText(row[customerCol]);
      const svc = cleanText(row[serviceCol]);
      if (!cust || !svc) continue;
      // Skip the workbook's own "Total" rollup customer and applied-filter banners.
      if (cust.toLowerCase().startsWith('applied filters')) continue;
      customersSet.add(cust);
      if (svc !== TOTAL_SERVICE) productsSet.add(svc);
      const key = cust + '||' + svc;
      let series = pivot.get(key);
      if (!series) { series = zeroes(); pivot.set(key, series); }
      for (let mi = 0; mi < months.length; mi++) {
        const cell = row[metricColumns[mi].index];
        const num = typeof cell === 'number' ? cell : (cell == null || cell === '' ? 0 : (parseFloat(cell) || 0));
        series[mi] += num;
      }
    }

    // Drop the workbook's own "Total" customer if present (we compute totals from service rows).
    customersSet.delete('Total');
    const customers = [...customersSet].sort();
    const products  = [...productsSet].sort();

    const series = (c, p) => pivot.get(c + '||' + p) || zeroes();

    return assembleFromPivot({ series, customers, products, months, monthLabels, sourceName });
  }

  // Shared assembler: turns a (customer, product) -> monthly-series accessor into
  // the dashboard DATA contract. Used by both the legacy ServiceCompGrouping
  // builder and the SL2/SL4 service-level builder so they emit identical shapes.
  // `defenderKey`/`totalKey` name the Defender-for-Cloud and customer-total
  // pseudo-products within the pivot.
  function assembleFromPivot({ series, customers, products, months, monthLabels, sourceName = '', defenderKey = DEFENDER_SERVICE, totalKey = TOTAL_SERVICE }) {
    const latestIdx = months.length - 1;
    const priorIdx  = Math.max(0, latestIdx - 1);
    const base3mIdx = Math.max(0, latestIdx - 2);
    const latestFy  = months[latestIdx] ? months[latestIdx].split('-', 2)[0] : '';
    const fytdIndices = months.map((m, i) => m.split('-', 2)[0] === latestFy ? i : -1).filter(i => i >= 0 && i <= latestIdx);

    const opportunity = [];
    const customerData = {};

    for (const customer of customers) {
      const dfc   = series(customer, defenderKey).map(roundMoney);
      const total = series(customer, totalKey).map(roundMoney);
      const other = total.map((t, i) => roundMoney(t - dfc[i]));

      const dfc_current   = dfc[latestIdx];
      const total_current = total[latestIdx];
      const other_current = other[latestIdx];
      const dfc_fytd   = fytdIndices.reduce((acc, i) => acc + dfc[i], 0);
      const total_fytd = fytdIndices.reduce((acc, i) => acc + total[i], 0);
      const other_fytd = fytdIndices.reduce((acc, i) => acc + other[i], 0);

      const dfc_mom   = pctChange(dfc[priorIdx], dfc[latestIdx]);
      const other_mom = pctChange(other[priorIdx], other[latestIdx]);
      const total_mom = pctChange(total[priorIdx], total[latestIdx]);
      const dfc_3m    = pctChange(dfc[base3mIdx], dfc[latestIdx]);
      const other_3m  = pctChange(other[base3mIdx], other[latestIdx]);
      const total_3m  = pctChange(total[base3mIdx], total[latestIdx]);

      const dfc_3m_delta   = dfc[latestIdx] - dfc[base3mIdx];
      const other_3m_delta = other[latestIdx] - other[base3mIdx];
      const total_3m_delta = total[latestIdx] - total[base3mIdx];

      const dfc_ratio      = total_current > 0 ? (dfc_current / total_current) : 0;
      const dfc_fytd_ratio = total_fytd > 0 ? (dfc_fytd / total_fytd) : 0;

      const breakdown = [];
      for (const p of products) {
        const ps = series(customer, p).map(roundMoney);
        const current = ps[latestIdx];
        const maxV = Math.max.apply(null, ps.length ? ps : [0]);
        if (current < 1 && maxV < 1) continue;
        breakdown.push({
          product: p,
          current: roundMoney(current),
          mom: pctChange(ps[priorIdx], ps[latestIdx]),
          three_m: pctChange(ps[base3mIdx], ps[latestIdx]),
          series: ps,
        });
      }
      breakdown.sort((a, b) => b.current - a.current);

      const catGrowth = categoryGrowth(breakdown, base3mIdx, latestIdx);
      const growth_cat_3m = catGrowth.growth;
      const growth_cat_names = catGrowth.growing;
      const [priority, notes] = classifyOpportunity({
        dfc_current, total_current, dfc_ratio, dfc_3m, other_3m, growth_cat_3m, growth_cat_names,
      });

      opportunity.push({
        customer,
        opportunity: priority,
        notes,
        dfc_current: roundMoney(dfc_current),
        other_current: roundMoney(other_current),
        total_current: roundMoney(total_current),
        dfc_monthly_current: roundMoney(dfc_current),
        other_monthly_current: roundMoney(other_current),
        total_monthly_current: roundMoney(total_current),
        dfc_fytd: roundMoney(dfc_fytd),
        other_fytd: roundMoney(other_fytd),
        total_fytd: roundMoney(total_fytd),
        dfc_ratio: round2(dfc_ratio * 100),
        dfc_fytd_ratio: round2(dfc_fytd_ratio * 100),
        dfc_mom, other_mom, total_mom, dfc_3m, other_3m, total_3m,
        dfc_3m_delta: roundMoney(dfc_3m_delta),
        other_3m_delta: roundMoney(other_3m_delta),
        total_3m_delta: roundMoney(total_3m_delta),
        growth_gap: roundMoney(other_3m_delta - dfc_3m_delta),
        growth_cat_3m,
        growth_cat_names,
      });

      customerData[customer] = {
        dfc_series: dfc,
        other_series: other,
        total_series: total,
        products: breakdown,
      };
    }

    // Product monthly aggregations summed across customers.
    const productMonthly = {};
    for (const p of [...products, totalKey]) {
      const monthly = months.map(() => 0);
      for (const c of customers) {
        const s = series(c, p);
        for (let i = 0; i < months.length; i++) monthly[i] += s[i];
      }
      productMonthly[p] = monthly.map(roundMoney);
    }

    const priorityRank = { High: 0, Medium: 1, Low: 2, 'Too small': 3 };
    opportunity.sort((a, b) => priorityRank[a.opportunity] - priorityRank[b.opportunity] || b.total_current - a.total_current);

    return {
      months,
      month_labels: monthLabels,
      partial_month_idx: -1,
      last_full_month: months[latestIdx] || '',
      prior_month: months[priorIdx] || '',
      current_fiscal_year: latestFy,
      fytd_months: fytdIndices.map(i => months[i]),
      customers,
      products,
      opportunity,
      customer_data: customerData,
      product_monthly: productMonthly,
      dfc_total_monthly: productMonthly[defenderKey] || months.map(() => 0),
      counts: {
        high:      opportunity.filter(r => r.opportunity === 'High').length,
        medium:    opportunity.filter(r => r.opportunity === 'Medium').length,
        low:       opportunity.filter(r => r.opportunity === 'Low').length,
        too_small: opportunity.filter(r => r.opportunity === 'Too small').length,
        total:     customers.length,
      },
      source_name: sourceName,
    };
  }

  const PRIORITY_RANK = { 'Too small': 0, Low: 1, Medium: 2, High: 3 };

  // Same thresholds & wording as dashboard_model._classify_opportunity, plus
  // two corporate rules: the Defender attach baseline (DfC share must be >=
  // threshold of total ACR) and a break-of-trend rule (core Azure workloads
  // growing while DfC fails to keep pace). `threshold` is a fraction (0.06).
  function classifyOpportunity({ dfc_current, total_current, dfc_ratio, dfc_3m, other_3m, growth_cat_3m = null, growth_cat_names = null, threshold = DEFAULT_DFC_SHARE }) {
    const notes = [];
    let priority = 'Low';
    const bump = p => { if (PRIORITY_RANK[p] > PRIORITY_RANK[priority]) priority = p; };
    const baselinePct = threshold * 100;
    const baselineLabel = baselinePct % 1 === 0 ? baselinePct.toFixed(0) : baselinePct.toFixed(1);

    if (total_current < 1500) {
      return ['Too small', 'Customer ACR under $1,500/month - sales priority low'];
    }
    if (dfc_current < 15 && total_current > 3000) {
      return ['High', `No Defender for Cloud spend at all - 0% vs the ${baselineLabel}% attach baseline`];
    }

    const belowBaseline = dfc_ratio < threshold;

    if (other_3m != null && other_3m > 0.05) {
      if (dfc_3m == null || dfc_3m < -0.05) {
        bump('High');
        notes.push(`Other Azure +${(other_3m * 100).toFixed(0)}% over 3 months while DfC declining`);
      } else if (dfc_3m < 0.02 && dfc_ratio < 0.02) {
        bump('High');
        notes.push('Other Azure growing, DfC flat AND under 2% of total ACR');
      } else if (dfc_ratio < 0.015) {
        bump('Medium');
        notes.push(`DfC penetration only ${(dfc_ratio * 100).toFixed(1)}% - undersold`);
      } else if (dfc_3m < other_3m - 0.05) {
        bump('Medium');
        notes.push('DfC growing slower than rest of Azure');
      }
    } else if (dfc_ratio < 0.005 && total_current > 6000) {
      bump('Medium');
      notes.push('Very low DfC penetration');
    }

    // Break of trend: core Azure workloads growing but DfC not keeping pace.
    // A null DfC 3-month change (no base spend) only counts as lagging when the
    // customer is still below the attach baseline; a customer that grew DfC from
    // zero to >= baseline is attaching well and should not be flagged.
    if (growth_cat_3m != null && growth_cat_3m > 0.05) {
      const dfcLagging = (dfc_3m == null) ? belowBaseline : (dfc_3m < growth_cat_3m - 0.05);
      if (dfcLagging) {
        bump(belowBaseline ? 'High' : 'Medium');
        const cats = Array.isArray(growth_cat_names) && growth_cat_names.length
          ? growth_cat_names.join(', ')
          : 'core Azure workloads';
        const dfcText = dfc_3m == null ? 'absent' : `${(dfc_3m * 100).toFixed(0)}%`;
        notes.push(`Break of trend: ${cats} +${(growth_cat_3m * 100).toFixed(0)}% over 3 months while DfC ${dfcText}`);
      }
    }

    // Corporate attach baseline.
    if (belowBaseline) {
      bump('Medium');
      notes.push(`DfC share ${(dfc_ratio * 100).toFixed(1)}% is below the ${baselineLabel}% attach baseline`);
    }

    // Healthy DfC growth note (only when nothing else elevated priority).
    if (dfc_3m != null && dfc_3m > 0.10 && (other_3m == null || dfc_3m > other_3m)) {
      if (priority === 'Low' || priority === 'Too small') {
        notes.push(`DfC growing healthily +${(dfc_3m * 100).toFixed(0)}% over 3 months`);
      }
    }

    return [priority, notes.length ? notes.join('; ') : '-'];
  }

  function findIndex(top, bottom, name) {
    const target = name.toLowerCase();
    for (let i = 0; i < Math.max(top.length, bottom.length); i++) {
      if ((top[i] || '').toLowerCase() === target) return i;
      if ((bottom[i] || '').toLowerCase() === target) return i;
    }
    return -1;
  }

  function cleanText(value) {
    if (value == null) return '';
    return String(value).replace(/\u00a0/g, ' ').trim();
  }

  function round2(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0;
  }

  window.AcrModel = { build, classifyOpportunity };
})();
