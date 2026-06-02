// sl-engine.js — Attach-gap scoring engine. Faithful port of
// src/defender_acr_dashboard/service_attach/engine.py.
// Exposes window.SLEngine (and module.exports under Node for tests).

(() => {
  'use strict';

  const M = (typeof require !== 'undefined') ? require('./sl-mapping.js')
    : (typeof window !== 'undefined' ? window.SLMapping : null);
  const P = (typeof require !== 'undefined') ? require('./sl-parser.js')
    : (typeof window !== 'undefined' ? window.SLParser : null);

  const {
    DEFENDER_SL2, TOTAL_TOKEN, FOUNDATIONAL_PLANS, NON_AZURE_SL2, WORKLOAD_PLANS,
    defaultConfig, ratioFor, normalizedWeights,
  } = M;
  const { LEVEL_CUSTOMER_TOTAL, LEVEL_SERVICE_TOTAL, LEVEL_LEAF } = P;

  const SIGNAL_ATTACH = 'attach';
  const SIGNAL_EXPAND = 'expand';

  function toSet(values) {
    return values === null || values === undefined ? null : new Set(values);
  }

  // Sum ACR by month for matching rows, returned in month order (0.0 missing).
  function seriesFor(records, months, sl2Values, sl4Values, level) {
    const sl2Set = toSet(sl2Values);
    const sl4Set = toSet(sl4Values);
    const sums = new Map();
    let any = false;
    for (const rec of records) {
      if (rec.level !== level) continue;
      if (sl2Set && !sl2Set.has(rec.sl2)) continue;
      if (sl4Set && !sl4Set.has(rec.sl4)) continue;
      any = true;
      sums.set(rec.month, (sums.get(rec.month) || 0) + rec.acr);
    }
    if (!any) return months.map(() => 0.0);
    return months.map((m) => (sums.has(m) ? sums.get(m) : 0.0));
  }

  function last(arr) {
    return arr.length ? arr[arr.length - 1] : 0.0;
  }

  function rollingGrowth(series, window, cap) {
    const n = series.length;
    let recent;
    let prior;
    if (n < 2 * window) {
      if (n === 0) return [0.0, false];
      recent = series[n - 1];
      prior = series[0];
    } else {
      let s = 0;
      for (let i = n - window; i < n; i += 1) s += series[i];
      recent = s / window;
      let p = 0;
      for (let i = n - 2 * window; i < n - window; i += 1) p += series[i];
      prior = p / window;
    }
    if (prior <= 0) {
      const grewFromZero = recent > 0;
      return [grewFromZero ? cap : 0.0, grewFromZero];
    }
    let growth = (recent - prior) / prior;
    growth = Math.max(-cap, Math.min(cap, growth));
    return [growth, false];
  }

  // pandas Series.rank(method="average", pct=True) * 100
  function percentileScores(values) {
    const n = values.length;
    if (n === 0) return [];
    const uniq = new Set(values);
    if (uniq.size <= 1) return values.map(() => (n > 1 ? 50.0 : 100.0));
    const idx = values.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]);
    const ranks = new Array(n);
    let i = 0;
    while (i < n) {
      let j = i;
      while (j + 1 < n && idx[j + 1][0] === idx[i][0]) j += 1;
      const avgRank = ((i + 1) + (j + 1)) / 2;
      for (let k = i; k <= j; k += 1) ranks[idx[k][1]] = avgRank;
      i = j + 1;
    }
    return ranks.map((r) => (r / n) * 100.0);
  }

  function median(values) {
    if (!values.length) return NaN;
    const sorted = values.slice().sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    if (sorted.length % 2 === 1) return sorted[mid];
    return (sorted[mid - 1] + sorted[mid]) / 2;
  }

  function cohortRatios(frame, latest, config) {
    const ratios = {};
    if (!config.useCohortMedian || latest === null || latest === undefined) return ratios;

    // Group latest-month rows by customer.
    const byCustomer = new Map();
    for (const rec of frame) {
      if (rec.month !== latest) continue;
      if (!byCustomer.has(rec.customer)) byCustomer.set(rec.customer, []);
      byCustomer.get(rec.customer).push(rec);
    }

    for (const plan of WORKLOAD_PLANS) {
      if (!plan.eligibleForGap) continue;
      const wSet = new Set(plan.workloadSl2);
      const dSet = new Set(plan.defenderSl4);
      const observed = [];
      for (const rows of byCustomer.values()) {
        let workload = 0;
        let defender = 0;
        for (const rec of rows) {
          if (rec.level === LEVEL_SERVICE_TOTAL && wSet.has(rec.sl2)) workload += rec.acr;
          else if (rec.level === LEVEL_LEAF && dSet.has(rec.sl4)) defender += rec.acr;
        }
        if (workload >= config.minDenominator && defender > config.attachThreshold) {
          observed.push(defender / workload);
        }
      }
      if (observed.length >= config.cohortMinSample) {
        ratios[plan.planLabel] = median(observed);
      }
    }
    return ratios;
  }

  function buildOpportunity(plan, frame, months, config, benchmarkRatio) {
    const workloadSeries = seriesFor(frame, months, plan.workloadSl2, null, LEVEL_SERVICE_TOTAL);
    const workloadAcr = last(workloadSeries);
    if (workloadAcr <= 0) return null;

    const defenderSeries = seriesFor(frame, months, [DEFENDER_SL2], plan.defenderSl4, LEVEL_LEAF);
    const defenderActual = last(defenderSeries);

    const presentSet = new Set();
    for (const sl2 of plan.workloadSl2) {
      if (last(seriesFor(frame, months, [sl2], null, LEVEL_SERVICE_TOTAL)) > 0) presentSet.add(sl2);
    }
    const presentSl2 = Array.from(presentSet).sort();

    const attached = defenderActual > config.attachThreshold;

    let expected = null;
    let coveragePct = null;
    let gapDollars = 0.0;
    let hasDollarGap = false;

    if (plan.eligibleForGap) {
      expected = workloadAcr * benchmarkRatio;
      hasDollarGap = expected >= config.minDenominator;
      if (hasDollarGap) {
        gapDollars = Math.max(0.0, expected - defenderActual);
        coveragePct = expected > 0 ? defenderActual / expected : null;
      }
    }

    let signal;
    if (!attached) signal = SIGNAL_ATTACH;
    else if (hasDollarGap && gapDollars > 0) signal = SIGNAL_EXPAND;
    else return null;

    const [workloadGrowth] = rollingGrowth(workloadSeries, config.momentumWindow, config.momentumCap);
    const [defenderGrowth] = rollingGrowth(defenderSeries, config.momentumWindow, config.momentumCap);
    let recentDefender;
    if (defenderSeries.length >= config.momentumWindow) {
      let s = 0;
      for (let i = defenderSeries.length - config.momentumWindow; i < defenderSeries.length; i += 1) s += defenderSeries[i];
      recentDefender = s / config.momentumWindow;
    } else {
      recentDefender = last(defenderSeries);
    }
    const zeroWithGrowth = recentDefender <= config.attachThreshold && workloadGrowth > 0;
    const momentumRaw = workloadGrowth - defenderGrowth;

    const sizeValue = hasDollarGap ? gapDollars : workloadAcr;

    return {
      planLabel: plan.planLabel,
      confidence: plan.confidence,
      pricingDriver: plan.pricingDriver,
      eligibleForGap: plan.eligibleForGap,
      signal,
      workloadSl2Present: presentSl2,
      workloadAcr,
      defenderActual,
      benchmarkRatio: plan.eligibleForGap ? benchmarkRatio : null,
      expected,
      gapDollars,
      coveragePct,
      hasDollarGap,
      workloadSeries,
      defenderSeries,
      workloadGrowth,
      defenderGrowth,
      momentumRaw,
      defenderZeroWithWorkloadGrowth: zeroWithGrowth,
      sizeValue,
      gapScore: 0.0,
      momentumScore: 0.0,
      blendedScore: 0.0,
      opener: '',
    };
  }

  function fmtInt(value) {
    // Match Python f"{value:,.0f}" — thousands separators, round half to even at 0 dp.
    const rounded = bankRound(value, 0);
    return rounded.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function opener(customer, opp) {
    const workload = opp.workloadSl2Present.length ? opp.workloadSl2Present.join(', ') : 'this workload';
    if (opp.hasDollarGap) {
      return `${customer} spends $${fmtInt(opp.workloadAcr)}/mo on ${workload} but only `
        + `$${fmtInt(opp.defenderActual)} on ${opp.planLabel} — roughly a `
        + `$${fmtInt(opp.gapDollars)}/mo attach gap.`;
    }
    return `${customer} runs ${workload} ($${fmtInt(opp.workloadAcr)}/mo) with no `
      + `${opp.planLabel} coverage in place.`;
  }

  // Python round(): round half to even.
  function bankRound(value, digits) {
    if (!Number.isFinite(value)) return value;
    const factor = Math.pow(10, digits);
    const scaled = value * factor;
    const floor = Math.floor(scaled);
    const diff = scaled - floor;
    let result;
    const eps = 1e-9;
    if (Math.abs(diff - 0.5) < eps) {
      result = (floor % 2 === 0) ? floor : floor + 1;
    } else {
      result = Math.round(scaled);
    }
    return result / factor;
  }

  function buildModel(parsed, config) {
    config = config || defaultConfig();
    const frame = parsed.frame;
    const months = parsed.months;
    const latest = parsed.latestMonth;

    const reconByCustomer = new Map();
    for (const issue of parsed.reconciliation) {
      const ok = issue.relDiff <= 0.01;
      const prev = reconByCustomer.has(issue.customer) ? reconByCustomer.get(issue.customer) : true;
      reconByCustomer.set(issue.customer, prev && ok);
    }

    const cohort = cohortRatios(frame, latest, config);

    const nonAzure = new Set(NON_AZURE_SL2);
    const eligibleSl2 = [];
    for (const p of WORKLOAD_PLANS) for (const s of p.workloadSl2) eligibleSl2.push(s);

    // Pre-group records by customer.
    const byCustomer = new Map();
    for (const c of parsed.customers) byCustomer.set(c, []);
    for (const rec of frame) {
      if (byCustomer.has(rec.customer)) byCustomer.get(rec.customer).push(rec);
    }

    const dossiers = [];
    const allOpps = [];

    for (const customer of parsed.customers) {
      const cust = byCustomer.get(customer);

      const customerTotalAcr = last(seriesFor(cust, months, [TOTAL_TOKEN], null, LEVEL_CUSTOMER_TOTAL));
      const dfcAcr = last(seriesFor(cust, months, [DEFENDER_SL2], [TOTAL_TOKEN], LEVEL_SERVICE_TOTAL));
      const eligibleWorkloadAcr = last(seriesFor(cust, months, eligibleSl2, null, LEVEL_SERVICE_TOTAL));

      const svcLatest = cust.filter((r) => r.level === LEVEL_SERVICE_TOTAL && r.month === latest);
      let azureWorkloadAcr = 0;
      for (const r of svcLatest) {
        if (!nonAzure.has(r.sl2) && r.sl2 !== DEFENDER_SL2) azureWorkloadAcr += r.acr;
      }

      const attachRatio = eligibleWorkloadAcr > 0 ? dfcAcr / eligibleWorkloadAcr : null;

      const dossier = {
        customer,
        customerTotalAcr,
        azureWorkloadAcr,
        eligibleWorkloadAcr,
        dfcAcr,
        attachRatio,
        opportunities: [],
        foundational: [],
        topSpend: [],
        presentEligibleCount: 0,
        uncoveredEligibleCount: 0,
        totalGapDollars: 0.0,
        breadthScore: 0.0,
        customerScore: 0.0,
        reconciliationOk: reconByCustomer.has(customer) ? reconByCustomer.get(customer) : true,
      };

      let presentEligible = 0;
      let uncoveredEligible = 0;
      for (const plan of WORKLOAD_PLANS) {
        const workloadNow = last(seriesFor(cust, months, plan.workloadSl2, null, LEVEL_SERVICE_TOTAL));
        if (workloadNow > 0) {
          presentEligible += 1;
          const defenderNow = last(seriesFor(cust, months, [DEFENDER_SL2], plan.defenderSl4, LEVEL_LEAF));
          if (defenderNow <= config.attachThreshold) uncoveredEligible += 1;
        }
        const ratio = Object.prototype.hasOwnProperty.call(cohort, plan.planLabel)
          ? cohort[plan.planLabel] : ratioFor(config, plan.planLabel);
        const opp = buildOpportunity(plan, cust, months, config, ratio);
        if (opp !== null) {
          opp.opener = opener(customer, opp);
          dossier.opportunities.push(opp);
          allOpps.push(opp);
        }
      }

      dossier.presentEligibleCount = presentEligible;
      dossier.uncoveredEligibleCount = uncoveredEligible;
      dossier.totalGapDollars = dossier.opportunities.reduce((acc, o) => acc + o.gapDollars, 0.0);

      for (const planName of FOUNDATIONAL_PLANS) {
        const actual = last(seriesFor(cust, months, [DEFENDER_SL2], [planName], LEVEL_LEAF));
        dossier.foundational.push({
          planLabel: planName,
          actual,
          present: actual > config.attachThreshold,
        });
      }

      // Top Azure spend categories.
      const spendBySl2 = new Map();
      for (const r of svcLatest) {
        if (r.sl2 === DEFENDER_SL2 || nonAzure.has(r.sl2) || r.sl2 === TOTAL_TOKEN) continue;
        spendBySl2.set(r.sl2, (spendBySl2.get(r.sl2) || 0) + r.acr);
      }
      const spendEntries = Array.from(spendBySl2.entries());
      spendEntries.sort((a, b) => (b[1] - a[1]) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
      dossier.topSpend = spendEntries.slice(0, 8).map(([sl2, acr]) => ({ sl2, acr }));

      dossiers.push(dossier);
    }

    score(dossiers, allOpps, config);

    let totalElig = 0;
    let totalDfc = 0;
    let totalGap = 0;
    for (const d of dossiers) {
      totalElig += d.eligibleWorkloadAcr;
      totalDfc += d.dfcAcr;
      totalGap += d.totalGapDollars;
    }

    const sorted = dossiers.slice().sort((a, b) => b.customerScore - a.customerScore);
    const bookAttachRatio = totalElig <= 0 ? null : totalDfc / totalElig;

    return {
      dossiers: sorted,
      months,
      latestMonth: latest,
      config,
      cohortRatios: cohort,
      sourceName: parsed.sourceName,
      reconciliation: parsed.reconciliation,
      totalEligibleWorkloadAcr: totalElig,
      totalDfcAcr: totalDfc,
      totalGapDollars: totalGap,
      bookAttachRatio,
    };
  }

  function score(dossiers, allOpps, config) {
    if (!allOpps.length) return;

    const sizes = allOpps.map((o) => Math.log1p(Math.max(0.0, o.sizeValue)));
    const gapScores = percentileScores(sizes);
    const momentumScores = percentileScores(allOpps.map((o) => o.momentumRaw));

    const [wGap, wMom, wBreadth] = normalizedWeights(config);

    for (let i = 0; i < allOpps.length; i += 1) {
      const opp = allOpps[i];
      opp.gapScore = gapScores[i];
      if (!opp.hasDollarGap) opp.gapScore *= config.coverageSignalDiscount;
      opp.momentumScore = momentumScores[i];
    }

    const breadthRaw = dossiers.map((d) => d.uncoveredEligibleCount);
    const breadthScores = percentileScores(breadthRaw);
    for (let i = 0; i < dossiers.length; i += 1) dossiers[i].breadthScore = breadthScores[i];

    for (const d of dossiers) {
      for (const opp of d.opportunities) {
        opp.blendedScore = wGap * opp.gapScore + wMom * opp.momentumScore + wBreadth * d.breadthScore;
      }
    }

    const rawCustomer = dossiers.map((d) => {
      const oppValue = d.opportunities.reduce((acc, o) => acc + o.gapScore, 0.0);
      return 0.7 * oppValue + 0.3 * d.breadthScore;
    });
    const customerScores = percentileScores(rawCustomer);
    for (let i = 0; i < dossiers.length; i += 1) dossiers[i].customerScore = customerScores[i];
  }

  const api = {
    SIGNAL_ATTACH,
    SIGNAL_EXPAND,
    seriesFor,
    rollingGrowth,
    percentileScores,
    median,
    cohortRatios,
    buildOpportunity,
    buildModel,
    bankRound,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.SLEngine = api;
})();
