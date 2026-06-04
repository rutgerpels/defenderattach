// sl-parser.js — Parse the combined SL2/SL4 ACR export (raw 2-D rows from
// SheetJS) into tidy long-format records. Faithful port of
// src/defender_acr_dashboard/service_attach/parser.py.
// Exposes window.SLParser (and module.exports under Node for tests).

(() => {
  'use strict';

  const M = (typeof require !== 'undefined') ? require('./sl-mapping.js')
    : (typeof window !== 'undefined' ? window.SLMapping : null);
  const DEFENDER_SL2 = M.DEFENDER_SL2;
  const TOTAL_TOKEN = M.TOTAL_TOKEN;

  const ACR_MEASURE = '$ ACR';
  const MONTH_GROUP_HEADER = 'FiscalMonth';

  const LEVEL_CUSTOMER_TOTAL = 'customer_total';
  const LEVEL_SERVICE_TOTAL = 'service_total';
  const LEVEL_LEAF = 'leaf';

  function coerceFloat(value) {
    if (value === null || value === undefined) return 0.0;
    if (typeof value === 'number') return Number.isFinite(value) ? value : 0.0;
    if (typeof value === 'boolean') return 0.0;
    if (value instanceof Date) return 0.0;
    const result = Number(value);
    if (!Number.isFinite(result)) return 0.0;
    return result;
  }

  // Ordered (monthLabel, columnIndex) pairs for the "$ ACR" columns, excluding
  // the fiscal-year Total roll-up. Mirrors merged-header carry-forward.
  function monthColumns(headerTop, headerBottom) {
    const months = [];
    let currentGroup = null;
    const width = Math.max(headerTop.length, headerBottom.length);
    for (let idx = 0; idx < width; idx += 1) {
      const top = idx < headerTop.length ? headerTop[idx] : null;
      if (top !== null && top !== undefined) {
        currentGroup = String(top).trim();
      }
      const bottom = idx < headerBottom.length ? headerBottom[idx] : null;
      if (bottom === null || bottom === undefined) continue;
      if (String(bottom).trim() !== ACR_MEASURE) continue;
      if (currentGroup === null || currentGroup === MONTH_GROUP_HEADER || currentGroup === TOTAL_TOKEN) {
        continue;
      }
      months.push([currentGroup, idx]);
    }
    return months;
  }

  function classifyLevel(sl2, sl4) {
    const sl2Clean = (sl2 === null || sl2 === undefined ? '' : String(sl2)).trim();
    const sl4Clean = (sl4 === null || sl4 === undefined ? '' : String(sl4)).trim();

    if (sl2Clean === TOTAL_TOKEN && !sl4Clean) {
      return [LEVEL_CUSTOMER_TOTAL, TOTAL_TOKEN, ''];
    }
    if (sl4Clean === TOTAL_TOKEN) {
      return [LEVEL_SERVICE_TOTAL, sl2Clean, TOTAL_TOKEN];
    }
    if (!sl4Clean) {
      return [LEVEL_LEAF, sl2Clean, sl2Clean];
    }
    return [LEVEL_LEAF, sl2Clean, sl4Clean];
  }

  function parseSl2Sl4(rows, sourceName) {
    if (!Array.isArray(rows) || rows.length < 2) {
      throw new Error('The worksheet does not contain the expected two-row header. Make sure you exported the "Export" sheet from the SL2/SL4 ACR report.');
    }
    const headerTop = rows[0] || [];
    const headerBottom = rows[1] || [];
    const monthCols = monthColumns(headerTop, headerBottom);
    const months = monthCols.map(([label]) => label);

    if (months.length === 0) {
      throw new Error('No monthly "$ ACR" columns were found. The workbook header may not match the SL2/SL4 ACR export layout.');
    }

    let maxNeeded = 2;
    for (const [, col] of monthCols) if (col > maxNeeded) maxNeeded = col;
    maxNeeded += 1;

    const frame = [];
    const customers = [];
    const seenCustomers = new Set();
    let rowCount = 0;

    for (let r = 2; r < rows.length; r += 1) {
      const raw = rows[r];
      if (!raw) continue;
      let row = raw;
      if (row.length < 3) continue;
      let customer = row[0];
      if (typeof customer === 'string') customer = customer.trim();
      if (customer === null || customer === undefined || customer === '') continue;
      if (row.length < maxNeeded) {
        row = row.concat(new Array(maxNeeded - row.length).fill(null));
      }

      const [level, sl2Clean, sl4Clean] = classifyLevel(row[1], row[2]);
      rowCount += 1;

      if (!seenCustomers.has(customer)) {
        seenCustomers.add(customer);
        customers.push(customer);
      }

      for (const [label, col] of monthCols) {
        frame.push({
          customer,
          sl2: sl2Clean,
          sl4: sl4Clean,
          level,
          month: label,
          acr: coerceFloat(row[col]),
        });
      }
    }

    const reconciliation = reconcile(frame, months);

    return {
      frame,
      months,
      customers,
      reconciliation,
      sourceName: sourceName || '',
      rowCount,
      latestMonth: months.length ? months[months.length - 1] : null,
    };
  }

  function relDiff(expected, actual) {
    const base = Math.max(Math.abs(expected), 1.0);
    return Math.abs(expected - actual) / base;
  }

  function reconcile(frame, months) {
    const issues = [];
    if (!frame.length || !months.length) return issues;
    const latest = months[months.length - 1];

    // Group latest-month rows by customer.
    const byCustomer = new Map();
    for (const rec of frame) {
      if (rec.month !== latest) continue;
      if (!byCustomer.has(rec.customer)) byCustomer.set(rec.customer, []);
      byCustomer.get(rec.customer).push(rec);
    }

    for (const [customer, custRows] of byCustomer) {
      let totalRow = 0;
      let sumService = 0;
      const serviceBySl2 = new Map();
      const leafBySl2 = new Map();
      for (const rec of custRows) {
        if (rec.level === LEVEL_CUSTOMER_TOTAL) totalRow += rec.acr;
        else if (rec.level === LEVEL_SERVICE_TOTAL) {
          sumService += rec.acr;
          serviceBySl2.set(rec.sl2, (serviceBySl2.get(rec.sl2) || 0) + rec.acr);
        } else if (rec.level === LEVEL_LEAF) {
          leafBySl2.set(rec.sl2, (leafBySl2.get(rec.sl2) || 0) + rec.acr);
        }
      }
      if (totalRow) {
        issues.push({
          customer,
          scope: 'customer_total_vs_service_subtotals',
          expected: totalRow,
          actual: sumService,
          relDiff: relDiff(totalRow, sumService),
        });
      }
      for (const [sl2, subAcr] of serviceBySl2) {
        const leafSum = leafBySl2.get(sl2) || 0;
        if (subAcr && Math.abs(subAcr - leafSum) / Math.max(Math.abs(subAcr), 1.0) > 0.01) {
          issues.push({
            customer,
            scope: `service_subtotal::${sl2}`,
            expected: subAcr,
            actual: leafSum,
            relDiff: relDiff(subAcr, leafSum),
          });
        }
      }
    }
    return issues;
  }

  const api = {
    LEVEL_CUSTOMER_TOTAL,
    LEVEL_SERVICE_TOTAL,
    LEVEL_LEAF,
    coerceFloat,
    parseSl2Sl4,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.SLParser = api;
})();
