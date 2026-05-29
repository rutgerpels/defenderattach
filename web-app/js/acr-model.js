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

  // Parses rows from XLSX.utils.sheet_to_json(sheet, {header:1}) for the Export sheet.
  // Builds the same shape as dashboard_model.build_dashboard_model in Python.
  function build(rows, sourceName = '') {
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

    const latestIdx = months.length - 1;
    const priorIdx  = Math.max(0, latestIdx - 1);
    const base3mIdx = Math.max(0, latestIdx - 2);
    const latestFy  = months[latestIdx] ? months[latestIdx].split('-', 2)[0] : '';
    const fytdIndices = months.map((m, i) => m.split('-', 2)[0] === latestFy ? i : -1).filter(i => i >= 0 && i <= latestIdx);

    const opportunity = [];
    const customerData = {};

    for (const customer of customers) {
      const dfc   = series(customer, DEFENDER_SERVICE).map(roundMoney);
      const total = series(customer, TOTAL_SERVICE).map(roundMoney);
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

      const [priority, notes] = classifyOpportunity({
        dfc_current, total_current, dfc_ratio, dfc_3m, other_3m,
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
    for (const p of [...products, TOTAL_SERVICE]) {
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
      dfc_total_monthly: productMonthly[DEFENDER_SERVICE] || months.map(() => 0),
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

  // Same thresholds & wording as dashboard_model._classify_opportunity.
  function classifyOpportunity({ dfc_current, total_current, dfc_ratio, dfc_3m, other_3m }) {
    let priority = 'Low';
    const notes = [];
    if (total_current < 1500) {
      return ['Too small', 'Customer ACR under $1,500/month - sales priority low'];
    }
    if (dfc_current < 15 && total_current > 3000) {
      return ['High', 'No Defender for Cloud spend at all'];
    }
    if (other_3m != null && other_3m > 0.05) {
      if (dfc_3m == null || dfc_3m < -0.05) {
        priority = 'High';
        notes.push(`Other Azure +${(other_3m * 100).toFixed(0)}% over 3 months while DfC declining`);
      } else if (dfc_3m < 0.02 && dfc_ratio < 0.02) {
        priority = 'High';
        notes.push('Other Azure growing, DfC flat AND under 2% of total ACR');
      } else if (dfc_ratio < 0.015) {
        priority = 'Medium';
        notes.push(`DfC penetration only ${(dfc_ratio * 100).toFixed(1)}% - undersold`);
      } else if (dfc_3m < other_3m - 0.05) {
        priority = 'Medium';
        notes.push('DfC growing slower than rest of Azure');
      }
    } else if (dfc_ratio < 0.005 && total_current > 6000) {
      priority = 'Medium';
      notes.push('Very low DfC penetration');
    }
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
