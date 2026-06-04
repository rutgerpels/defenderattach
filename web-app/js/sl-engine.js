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
  const SIGNAL_COVERED = 'covered';
  const STORY_GROWTH_DIVERGENCE = 'growth_divergence';
  const STORY_DEFENDER_REGRESSION = 'defender_regression';
  const STORY_NEW_WORKLOAD_NO_DEFENDER = 'new_workload_no_defender';
  const DIVERGENCE_STORY_CAVEAT = 'Directional signal based on ACR trend comparison. Defender for Cloud pricing '
    + 'can be vCore, resource, transaction, or unit based rather than a fixed percentage of workload ACR; '
    + 'validate usage, plan scope, and entitlement before treating this as a commercial forecast.';

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

  function classifyPriority(opp, config) {
    const eps = config.priorityMomentumEps != null ? config.priorityMomentumEps : 0.02;
    const covMed = config.priorityCoverageMedium != null ? config.priorityCoverageMedium : 0.5;
    const growing = opp.workloadGrowth > 0;
    const divergent = opp.defenderZeroWithWorkloadGrowth || opp.momentumRaw > eps;
    const severeCoverage = opp.signal === SIGNAL_ATTACH ||
      (opp.coveragePct != null && opp.coveragePct < covMed);

    if (growing && divergent) {
      const reason = opp.defenderZeroWithWorkloadGrowth
        ? 'Workload growing with little or no Defender spend'
        : 'Workload growth is outpacing Defender attach';
      return { priority: 'High', priorityReason: reason, priorityRank: 0 };
    }
    if (severeCoverage) {
      let reason;
      if (opp.signal === SIGNAL_ATTACH) {
        reason = opp.hasDollarGap
          ? 'Active workload with no Defender coverage'
          : 'Defender not detected for an active workload';
      } else {
        reason = 'Defender spend well below the benchmark attach ratio';
      }
      return { priority: 'Medium', priorityReason: reason, priorityRank: 1 };
    }
    return {
      priority: 'Low',
      priorityReason: 'Defender roughly tracking the benchmark; minor top-up',
      priorityRank: 2,
    };
  }

  function buildOpportunity(plan, frame, months, config, benchmarkRatio, includeCovered = false) {
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
    else if (includeCovered) signal = SIGNAL_COVERED;
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

    const opp = {
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
    const tier = classifyPriority(opp, config);
    opp.priority = tier.priority;
    opp.priorityReason = tier.priorityReason;
    opp.priorityRank = tier.priorityRank;
    return opp;
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

  function comparisonWindow(series, months, window) {
    if (!series.length) return [[], 0.0, 0.0];
    const safeWindow = Math.max(1, Math.min(window, series.length));
    let startValues;
    let endValues;
    let compared;
    if (series.length >= 2 * safeWindow) {
      startValues = series.slice(series.length - 2 * safeWindow, series.length - safeWindow);
      endValues = series.slice(series.length - safeWindow);
      compared = months.length ? months.slice(months.length - 2 * safeWindow) : [];
    } else {
      startValues = [series[0]];
      endValues = [series[series.length - 1]];
      compared = months.length > 1 ? [months[0], months[months.length - 1]] : months.slice();
    }
    const avg = (values) => values.reduce((acc, v) => acc + v, 0.0) / values.length;
    return [compared, avg(startValues), avg(endValues)];
  }

  function safePctChange(start, end) {
    return start <= 0 ? null : (end - start) / start;
  }

  function formatPct(value) {
    return value === null || value === undefined ? 'n/a' : `${(value * 100).toFixed(1)}%`;
  }

  function storySeverity(storyType, opp) {
    if (storyType === STORY_NEW_WORKLOAD_NO_DEFENDER) return 'High';
    if (storyType === STORY_DEFENDER_REGRESSION && opp.defenderGrowth <= -0.20) return 'High';
    if (opp.defenderZeroWithWorkloadGrowth || opp.momentumRaw >= 0.30) return 'High';
    return 'Medium';
  }

  function storyHeadline(customer, storyType, opp) {
    const workload = opp.workloadSl2Present.length ? opp.workloadSl2Present.join(', ') : 'mapped workload';
    if (storyType === STORY_NEW_WORKLOAD_NO_DEFENDER) {
      return `${customer} has material new ${workload} spend with no detected ${opp.planLabel} attach.`;
    }
    if (storyType === STORY_DEFENDER_REGRESSION) {
      return `${customer}'s ${opp.planLabel} ACR is declining while ${workload} is stable or growing.`;
    }
    return `${customer}'s ${workload} growth is outpacing ${opp.planLabel} attach.`;
  }

  function recommendedAction(storyType, opp) {
    const workload = opp.workloadSl2Present.length ? opp.workloadSl2Present.join(', ') : 'the workload';
    if (storyType === STORY_NEW_WORKLOAD_NO_DEFENDER) {
      return `Confirm ownership of ${workload}, validate Defender plan eligibility, `
        + `and position ${opp.planLabel} enablement for the newly material workload.`;
    }
    if (storyType === STORY_DEFENDER_REGRESSION) {
      return `Review whether ${opp.planLabel} coverage was removed, scoped down, `
        + 'or displaced by a billing change while workload consumption continued.';
    }
    return `Use the workload momentum in ${workload} to discuss whether `
      + `${opp.planLabel} coverage is keeping pace with deployment growth.`;
  }

  function detectDivergenceStories(customer, opportunities, months, config) {
    const stories = [];
    const window = Math.max(1, config.momentumWindow);
    if (months.length < 2 * window) return stories;

    for (const opp of opportunities) {
      if (opp.workloadAcr < config.divergenceStoryMinWorkloadAcr) continue;

      const [compared, workloadStart, workloadEnd] = comparisonWindow(opp.workloadSeries, months, window);
      const [, defenderStart, defenderEnd] = comparisonWindow(opp.defenderSeries, months, window);

      let storyType = null;
      const workloadMaterial = workloadEnd >= config.divergenceStoryMinWorkloadAcr;
      const defenderBelowAttach = (
        defenderEnd <= config.attachThreshold && opp.defenderActual <= config.attachThreshold
      );
      const workloadNew = (
        workloadStart <= config.divergenceStoryNewWorkloadMaxStartAcr && workloadMaterial
      );
      const workloadHasStableBaseline = workloadStart >= config.divergenceStoryMinStartWorkloadAcr;
      const workloadStableOrGrowing = opp.workloadGrowth >= 0;
      const defenderLagIsMaterial = opp.momentumRaw >= config.divergenceStoryMaterialLag;

      if (workloadNew && defenderBelowAttach) {
        storyType = STORY_NEW_WORKLOAD_NO_DEFENDER;
      } else if (
        workloadHasStableBaseline &&
        opp.defenderGrowth <= config.divergenceStoryDefenderRegression &&
        workloadStableOrGrowing
      ) {
        storyType = STORY_DEFENDER_REGRESSION;
      } else if (
        workloadHasStableBaseline &&
        opp.workloadGrowth >= config.divergenceStoryMinWorkloadGrowth &&
        defenderLagIsMaterial &&
        (
          opp.defenderGrowth <= config.divergenceStoryFlatDefenderGrowth ||
          opp.defenderGrowth < opp.workloadGrowth ||
          opp.defenderZeroWithWorkloadGrowth
        )
      ) {
        storyType = STORY_GROWTH_DIVERGENCE;
      }

      if (storyType === null) continue;

      const workloadDelta = workloadEnd - workloadStart;
      const defenderDelta = defenderEnd - defenderStart;
      const workloadPct = safePctChange(workloadStart, workloadEnd);
      const defenderPct = safePctChange(defenderStart, defenderEnd);
      const gapNote = opp.hasDollarGap
        ? `Estimated benchmark gap: $${fmtInt(opp.gapDollars)}/mo.`
        : 'No fixed dollar benchmark is used for this plan.';
      const evidence = [
        `Workload ACR moved from $${fmtInt(workloadStart)} to $${fmtInt(workloadEnd)} (${formatPct(workloadPct)}).`,
        `Defender ACR moved from $${fmtInt(defenderStart)} to $${fmtInt(defenderEnd)} (${formatPct(defenderPct)}).`,
        `Momentum spread is ${formatPct(opp.momentumRaw)}.`,
        gapNote,
      ];

      stories.push({
        customer,
        planLabel: opp.planLabel,
        workloadSl2Categories: opp.workloadSl2Present.slice(),
        storyType,
        severity: storySeverity(storyType, opp),
        confidence: opp.confidence,
        pricingDriver: opp.pricingDriver,
        latestWorkloadAcr: opp.workloadAcr,
        latestDefenderAcr: opp.defenderActual,
        comparedMonths: compared.slice(),
        workloadStartValue: workloadStart,
        workloadEndValue: workloadEnd,
        defenderStartValue: defenderStart,
        defenderEndValue: defenderEnd,
        workloadDelta,
        defenderDelta,
        workloadPctChange: workloadPct,
        defenderPctChange: defenderPct,
        momentumSpread: opp.momentumRaw,
        hasDollarGap: opp.hasDollarGap,
        gapDollars: opp.hasDollarGap ? opp.gapDollars : 0.0,
        headline: storyHeadline(customer, storyType, opp),
        evidenceBullets: evidence,
        recommendedAction: recommendedAction(storyType, opp),
        caveatText: DIVERGENCE_STORY_CAVEAT,
      });
    }

    const severityRank = { High: 0, Medium: 1 };
    return stories.sort((a, b) =>
      ((severityRank[a.severity] ?? 9) - (severityRank[b.severity] ?? 9)) ||
      (b.gapDollars - a.gapDollars) ||
      (b.latestWorkloadAcr - a.latestWorkloadAcr) ||
      (a.planLabel < b.planLabel ? -1 : a.planLabel > b.planLabel ? 1 : 0));
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
    const divergenceCandidatesByCustomer = new Map();

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
        divergenceStories: [],
        catalog: [],
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
      const divergenceCandidates = [];
      for (const plan of WORKLOAD_PLANS) {
        const workloadNow = last(seriesFor(cust, months, plan.workloadSl2, null, LEVEL_SERVICE_TOTAL));
        const defenderNow = last(seriesFor(cust, months, [DEFENDER_SL2], plan.defenderSl4, LEVEL_LEAF));
        if (workloadNow > 0) {
          presentEligible += 1;
          if (defenderNow <= config.attachThreshold) uncoveredEligible += 1;
        }
        const ratio = Object.prototype.hasOwnProperty.call(cohort, plan.planLabel)
          ? cohort[plan.planLabel] : ratioFor(config, plan.planLabel);
        const opp = buildOpportunity(plan, cust, months, config, ratio);
        if (opp !== null) {
          opp.opener = opener(customer, opp);
          dossier.opportunities.push(opp);
          allOpps.push(opp);
          divergenceCandidates.push(opp);
        } else {
          const coveredCandidate = buildOpportunity(plan, cust, months, config, ratio, true);
          if (coveredCandidate !== null) divergenceCandidates.push(coveredCandidate);
        }

        // Full-catalog entry for the all-services scorecard. Renderer-only:
        // this field is NOT read by sl-export.js, so golden parity is preserved.
        let workloadName = '';
        if (opp !== null && Array.isArray(opp.workloadSl2Present)) {
          workloadName = opp.workloadSl2Present.join(', ');
        } else if (workloadNow > 0) {
          const present = [];
          for (const sl2 of plan.workloadSl2) {
            if (last(seriesFor(cust, months, [sl2], null, LEVEL_SERVICE_TOTAL)) > 0) present.push(sl2);
          }
          workloadName = present.sort().join(', ');
        }
        let status;
        if (workloadNow <= 0) status = 'not_deployed';
        else if (opp !== null) status = 'below_threshold';
        else status = 'on_track';
        dossier.catalog.push({
          planLabel: plan.planLabel,
          eligibleForGap: plan.eligibleForGap,
          pricingDriver: plan.pricingDriver,
          workloadName,
          workloadAcr: workloadNow,
          defenderActual: defenderNow,
          status,
          signal: opp !== null ? opp.signal : null,
          hasDollarGap: opp !== null ? opp.hasDollarGap : false,
          gapDollars: opp !== null ? opp.gapDollars : 0.0,
          expected: opp !== null ? opp.expected : null,
          coveragePct: opp !== null ? opp.coveragePct : null,
        });
      }

      divergenceCandidatesByCustomer.set(customer, divergenceCandidates);
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

    const allStories = [];
    for (const dossier of dossiers) {
      dossier.divergenceStories = detectDivergenceStories(
        dossier.customer, divergenceCandidatesByCustomer.get(dossier.customer) || dossier.opportunities, months, config,
      );
      allStories.push(...dossier.divergenceStories);
    }

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
      divergenceStories: allStories.sort((a, b) => {
        const severityRank = { High: 0, Medium: 1 };
        return ((severityRank[a.severity] ?? 9) - (severityRank[b.severity] ?? 9)) ||
          (b.gapDollars - a.gapDollars) ||
          (b.latestWorkloadAcr - a.latestWorkloadAcr) ||
          (a.customer < b.customer ? -1 : a.customer > b.customer ? 1 : 0) ||
          (a.planLabel < b.planLabel ? -1 : a.planLabel > b.planLabel ? 1 : 0);
      }),
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
    STORY_GROWTH_DIVERGENCE,
    STORY_DEFENDER_REGRESSION,
    STORY_NEW_WORKLOAD_NO_DEFENDER,
    DIVERGENCE_STORY_CAVEAT,
    seriesFor,
    rollingGrowth,
    percentileScores,
    median,
    cohortRatios,
    buildOpportunity,
    detectDivergenceStories,
    buildModel,
    bankRound,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.SLEngine = api;
})();
