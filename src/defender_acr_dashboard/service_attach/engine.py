"""Attach-gap scoring engine.

Turns the tidy SL2/SL4 parse into a ranked book of per-customer, per-plan
Defender attach opportunities with explainable score components, robust
momentum, and a trust layer (reconciliation + confidence).

Design notes:
* The eligible-workload denominator (mapped Azure workloads only) drives the
  headline attach ratio, NOT the raw customer total (which includes non-Azure
  XCR such as Power BI / GitHub).
* Unit-priced plans (Servers, Storage) never get a fabricated dollar benchmark;
  they surface as binary coverage signals and are demoted in ranking.
* All score components are normalized to a bounded 0-100 percentile and shown
  separately so a seller can see *why* an opportunity ranks where it does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from .mapping import (
    AttachConfig,
    DEFENDER_SL2,
    FOUNDATIONAL_PLANS,
    NON_AZURE_SL2,
    TOTAL_TOKEN,
    WORKLOAD_PLANS,
    WorkloadPlan,
    default_config,
)
from .parser import (
    LEVEL_CUSTOMER_TOTAL,
    LEVEL_LEAF,
    LEVEL_SERVICE_TOTAL,
    ParsedData,
    ReconciliationIssue,
)

SIGNAL_ATTACH = "attach"
SIGNAL_EXPAND = "expand"
SIGNAL_COVERED = "covered"

STORY_GROWTH_DIVERGENCE = "growth_divergence"
STORY_DEFENDER_REGRESSION = "defender_regression"
STORY_NEW_WORKLOAD_NO_DEFENDER = "new_workload_no_defender"

DIVERGENCE_STORY_CAVEAT = (
    "Directional signal based on ACR trend comparison. Defender for Cloud pricing "
    "can be vCore, resource, transaction, or unit based rather than a fixed "
    "percentage of workload ACR; validate usage, plan scope, and entitlement "
    "before treating this as a commercial forecast."
)


@dataclass
class Opportunity:
    plan_label: str
    confidence: str
    pricing_driver: str
    eligible_for_gap: bool
    signal: str

    workload_sl2_present: List[str]
    workload_acr: float
    defender_actual: float

    benchmark_ratio: Optional[float]
    expected: Optional[float]
    gap_dollars: float
    coverage_pct: Optional[float]
    has_dollar_gap: bool

    workload_series: List[float]
    defender_series: List[float]
    workload_growth: float
    defender_growth: float
    momentum_raw: float
    defender_zero_with_workload_growth: bool

    size_value: float

    gap_score: float = 0.0
    momentum_score: float = 0.0
    blended_score: float = 0.0
    opener: str = ""

    priority: str = ""
    priority_reason: str = ""
    priority_rank: int = 2


@dataclass
class FoundationalCoverage:
    plan_label: str
    actual: float
    present: bool


@dataclass
class DivergenceStory:
    customer: str
    plan_label: str
    workload_sl2_categories: List[str]
    story_type: str
    severity: str
    confidence: str
    pricing_driver: str

    latest_workload_acr: float
    latest_defender_acr: float
    compared_months: List[str]
    workload_start_value: float
    workload_end_value: float
    defender_start_value: float
    defender_end_value: float
    workload_delta: float
    defender_delta: float
    workload_pct_change: Optional[float]
    defender_pct_change: Optional[float]
    momentum_spread: float
    has_dollar_gap: bool
    gap_dollars: float

    headline: str
    evidence_bullets: List[str]
    recommended_action: str
    caveat_text: str


@dataclass
class SpendCategory:
    sl2: str
    acr: float


@dataclass
class CustomerDossier:
    customer: str
    customer_total_acr: float
    azure_workload_acr: float
    eligible_workload_acr: float
    dfc_acr: float
    attach_ratio: Optional[float]

    opportunities: List[Opportunity] = field(default_factory=list)
    divergence_stories: List[DivergenceStory] = field(default_factory=list)
    foundational: List[FoundationalCoverage] = field(default_factory=list)
    top_spend: List[SpendCategory] = field(default_factory=list)

    present_eligible_count: int = 0
    uncovered_eligible_count: int = 0
    total_gap_dollars: float = 0.0

    breadth_score: float = 0.0
    customer_score: float = 0.0
    reconciliation_ok: bool = True


@dataclass
class BookModel:
    dossiers: List[CustomerDossier]
    months: List[str]
    latest_month: Optional[str]
    config: AttachConfig
    cohort_ratios: Dict[str, float]
    source_name: str
    reconciliation: List[ReconciliationIssue]

    # Book-level roll-ups.
    total_eligible_workload_acr: float = 0.0
    total_dfc_acr: float = 0.0
    total_gap_dollars: float = 0.0
    divergence_stories: List[DivergenceStory] = field(default_factory=list)

    @property
    def book_attach_ratio(self) -> Optional[float]:
        if self.total_eligible_workload_acr <= 0:
            return None
        return self.total_dfc_acr / self.total_eligible_workload_acr


def _series_for(
    frame: pd.DataFrame, months: List[str], sl2_values, sl4_values, level: str
) -> List[float]:
    """Sum ACR by month for the matching rows, returned in month order."""

    mask = frame["level"] == level
    if sl2_values is not None:
        mask &= frame["sl2"].isin(sl2_values)
    if sl4_values is not None:
        mask &= frame["sl4"].isin(sl4_values)
    sub = frame[mask]
    if sub.empty:
        return [0.0] * len(months)
    grouped = sub.groupby("month")["acr"].sum()
    return [float(grouped.get(m, 0.0)) for m in months]


def _rolling_growth(series: List[float], window: int, cap: float) -> tuple[float, bool]:
    """Rolling-average growth with zero-base protection.

    Returns (growth, grew_from_zero). Growth is clipped to +/- ``cap``.
    """

    window = max(1, window)
    n = len(series)
    if n < 2 * window:
        # Not enough history for a stable two-window comparison.
        if not series:
            return 0.0, False
        recent = series[-1]
        prior = series[0]
    else:
        recent = sum(series[-window:]) / window
        prior = sum(series[-2 * window : -window]) / window

    if prior <= 0:
        grew_from_zero = recent > 0
        growth = cap if grew_from_zero else 0.0
        return growth, grew_from_zero

    growth = (recent - prior) / prior
    growth = max(-cap, min(cap, growth))
    return growth, False


def _percentile_scores(values: List[float]) -> List[float]:
    """Map raw values to a 0-100 percentile (ties share the mean rank)."""

    if not values:
        return []
    series = pd.Series(values)
    if series.nunique() <= 1:
        return [50.0 if len(values) > 1 else 100.0] * len(values)
    pct = series.rank(method="average", pct=True) * 100.0
    return [float(x) for x in pct]


def _cohort_ratios(
    frame: pd.DataFrame, latest: str, config: AttachConfig
) -> Dict[str, float]:
    """Median observed attach ratio per plan among customers who already buy it."""

    ratios: Dict[str, float] = {}
    if not config.use_cohort_median or latest is None:
        return ratios

    snap = frame[frame["month"] == latest]
    for plan in WORKLOAD_PLANS:
        if not plan.eligible_for_gap:
            continue
        observed: List[float] = []
        for customer, rows in snap.groupby("customer"):
            workload = rows[
                (rows["level"] == LEVEL_SERVICE_TOTAL)
                & (rows["sl2"].isin(plan.workload_sl2))
            ]["acr"].sum()
            defender = rows[
                (rows["level"] == LEVEL_LEAF)
                & (rows["sl4"].isin(plan.defender_sl4))
            ]["acr"].sum()
            if workload >= config.min_denominator and defender > config.attach_threshold:
                observed.append(defender / workload)
        if len(observed) >= config.cohort_min_sample:
            ratios[plan.plan_label] = float(pd.Series(observed).median())
    return ratios


def _build_plan_candidate(
    plan: WorkloadPlan,
    frame: pd.DataFrame,
    months: List[str],
    config: AttachConfig,
    benchmark_ratio: float,
    include_covered: bool = False,
) -> Optional[Opportunity]:
    workload_series = _series_for(
        frame, months, plan.workload_sl2, None, LEVEL_SERVICE_TOTAL
    )
    workload_acr = workload_series[-1] if workload_series else 0.0
    if workload_acr <= 0:
        return None  # Workload not present -> nothing to attach to.

    defender_series = _series_for(
        frame, months, [DEFENDER_SL2], plan.defender_sl4, LEVEL_LEAF
    )
    defender_actual = defender_series[-1] if defender_series else 0.0

    present_sl2 = sorted(
        {
            sl2
            for sl2 in plan.workload_sl2
            if _series_for(frame, months, [sl2], None, LEVEL_SERVICE_TOTAL)[-1] > 0
        }
    )

    attached = defender_actual > config.attach_threshold

    expected: Optional[float] = None
    coverage_pct: Optional[float] = None
    gap_dollars = 0.0
    has_dollar_gap = False

    if plan.eligible_for_gap:
        expected = workload_acr * benchmark_ratio
        has_dollar_gap = expected >= config.min_denominator
        if has_dollar_gap:
            gap_dollars = max(0.0, expected - defender_actual)
            coverage_pct = defender_actual / expected if expected > 0 else None

    # Decide whether this is a real opportunity and which signal it carries.
    if not attached:
        signal = SIGNAL_ATTACH
    elif has_dollar_gap and gap_dollars > 0:
        signal = SIGNAL_EXPAND
    elif include_covered:
        signal = SIGNAL_COVERED
    else:
        return None  # Attached and at/above benchmark -> covered.

    workload_growth, _ = _rolling_growth(
        workload_series, config.momentum_window, config.momentum_cap
    )
    defender_growth, _ = _rolling_growth(
        defender_series, config.momentum_window, config.momentum_cap
    )
    recent_defender = (
        sum(defender_series[-config.momentum_window :]) / config.momentum_window
        if len(defender_series) >= config.momentum_window
        else (defender_series[-1] if defender_series else 0.0)
    )
    zero_with_growth = recent_defender <= config.attach_threshold and workload_growth > 0
    momentum_raw = workload_growth - defender_growth

    if has_dollar_gap:
        size_value = gap_dollars
    else:
        # Coverage-only (unit priced or sub-threshold benchmark): size by the
        # workload footprint at risk, not a fabricated dollar gap.
        size_value = workload_acr

    opp = Opportunity(
        plan_label=plan.plan_label,
        confidence=plan.confidence,
        pricing_driver=plan.pricing_driver,
        eligible_for_gap=plan.eligible_for_gap,
        signal=signal,
        workload_sl2_present=present_sl2,
        workload_acr=workload_acr,
        defender_actual=defender_actual,
        benchmark_ratio=benchmark_ratio if plan.eligible_for_gap else None,
        expected=expected,
        gap_dollars=gap_dollars,
        coverage_pct=coverage_pct,
        has_dollar_gap=has_dollar_gap,
        workload_series=workload_series,
        defender_series=defender_series,
        workload_growth=workload_growth,
        defender_growth=defender_growth,
        momentum_raw=momentum_raw,
        defender_zero_with_workload_growth=zero_with_growth,
        size_value=size_value,
    )
    opp.priority, opp.priority_reason, opp.priority_rank = _classify_priority(opp, config)
    return opp


def _build_opportunity(
    plan: WorkloadPlan,
    frame: pd.DataFrame,
    months: List[str],
    config: AttachConfig,
    benchmark_ratio: float,
) -> Optional[Opportunity]:
    return _build_plan_candidate(plan, frame, months, config, benchmark_ratio)


def _classify_priority(opp: Opportunity, config: AttachConfig) -> tuple:
    """Assign a High/Medium/Low tier mirroring ``classifyPriority`` in sl-engine.js.

    High = workload growing while Defender is not keeping pace (momentum
    divergence). Medium = material current under-attachment / under-coverage.
    Low = roughly tracking the benchmark.
    """
    eps = config.priority_momentum_eps
    cov_med = config.priority_coverage_medium
    growing = opp.workload_growth > 0
    divergent = opp.defender_zero_with_workload_growth or opp.momentum_raw > eps
    severe_coverage = opp.signal == SIGNAL_ATTACH or (
        opp.coverage_pct is not None and opp.coverage_pct < cov_med
    )

    if growing and divergent:
        reason = (
            "Workload growing with little or no Defender spend"
            if opp.defender_zero_with_workload_growth
            else "Workload growth is outpacing Defender attach"
        )
        return "High", reason, 0
    if severe_coverage:
        if opp.signal == SIGNAL_ATTACH:
            reason = (
                "Active workload with no Defender coverage"
                if opp.has_dollar_gap
                else "Defender not detected for an active workload"
            )
        else:
            reason = "Defender spend well below the benchmark attach ratio"
        return "Medium", reason, 1
    return "Low", "Defender roughly tracking the benchmark; minor top-up", 2


def _opener(customer: str, opp: Opportunity) -> str:
    workload = ", ".join(opp.workload_sl2_present) or "this workload"
    if opp.has_dollar_gap:
        return (
            f"{customer} spends ${opp.workload_acr:,.0f}/mo on {workload} but only "
            f"${opp.defender_actual:,.0f} on {opp.plan_label} — roughly a "
            f"${opp.gap_dollars:,.0f}/mo attach gap."
        )
    return (
        f"{customer} runs {workload} (${opp.workload_acr:,.0f}/mo) with no "
        f"{opp.plan_label} coverage in place."
    )


def _comparison_window(
    series: List[float], months: List[str], window: int
) -> tuple[List[str], float, float]:
    if not series:
        return [], 0.0, 0.0
    safe_window = max(1, min(window, len(series)))
    if len(series) >= 2 * safe_window:
        start_values = series[-2 * safe_window : -safe_window]
        end_values = series[-safe_window:]
        compared = months[-2 * safe_window :] if months else []
    else:
        start_values = [series[0]]
        end_values = [series[-1]]
        compared = [months[0], months[-1]] if len(months) > 1 else list(months)
    start = sum(start_values) / len(start_values) if start_values else 0.0
    end = sum(end_values) / len(end_values) if end_values else 0.0
    return compared, start, end


def _safe_pct_change(start: float, end: float) -> Optional[float]:
    if start <= 0:
        return None
    return (end - start) / start


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _story_severity(story_type: str, opp: Opportunity) -> str:
    if story_type == STORY_NEW_WORKLOAD_NO_DEFENDER:
        return "High"
    if story_type == STORY_DEFENDER_REGRESSION and opp.defender_growth <= -0.20:
        return "High"
    if opp.defender_zero_with_workload_growth or opp.momentum_raw >= 0.30:
        return "High"
    return "Medium"


def _story_headline(customer: str, story_type: str, opp: Opportunity) -> str:
    workload = ", ".join(opp.workload_sl2_present) or "mapped workload"
    if story_type == STORY_NEW_WORKLOAD_NO_DEFENDER:
        return (
            f"{customer} has material new {workload} spend with no detected "
            f"{opp.plan_label} attach."
        )
    if story_type == STORY_DEFENDER_REGRESSION:
        return (
            f"{customer}'s {opp.plan_label} ACR is declining while {workload} "
            "is stable or growing."
        )
    return (
        f"{customer}'s {workload} growth is outpacing {opp.plan_label} attach."
    )


def _recommended_action(story_type: str, opp: Opportunity) -> str:
    workload = ", ".join(opp.workload_sl2_present) or "the workload"
    if story_type == STORY_NEW_WORKLOAD_NO_DEFENDER:
        return (
            f"Confirm ownership of {workload}, validate Defender plan eligibility, "
            f"and position {opp.plan_label} enablement for the newly material workload."
        )
    if story_type == STORY_DEFENDER_REGRESSION:
        return (
            f"Review whether {opp.plan_label} coverage was removed, scoped down, "
            "or displaced by a billing change while workload consumption continued."
        )
    return (
        f"Use the workload momentum in {workload} to discuss whether "
        f"{opp.plan_label} coverage is keeping pace with deployment growth."
    )


def detect_divergence_stories(
    customer: str, opportunities: List[Opportunity], months: List[str], config: AttachConfig
) -> List[DivergenceStory]:
    """Emit conservative trend stories from already-computed opportunities."""

    stories: List[DivergenceStory] = []
    window = max(1, config.momentum_window)
    full_history = len(months) >= 2 * window
    if not full_history:
        return stories

    for opp in opportunities:
        if opp.workload_acr < config.divergence_story_min_workload_acr:
            continue

        compared, workload_start, workload_end = _comparison_window(
            opp.workload_series, months, window
        )
        _, defender_start, defender_end = _comparison_window(
            opp.defender_series, months, window
        )

        story_type: Optional[str] = None
        workload_material = workload_end >= config.divergence_story_min_workload_acr
        defender_below_attach = (
            defender_end <= config.attach_threshold
            and opp.defender_actual <= config.attach_threshold
        )
        workload_new = (
            workload_start <= config.divergence_story_new_workload_max_start_acr
            and workload_material
        )
        workload_has_stable_baseline = (
            workload_start >= config.divergence_story_min_start_workload_acr
        )
        workload_stable_or_growing = opp.workload_growth >= 0
        defender_lag_is_material = (
            opp.momentum_raw >= config.divergence_story_material_lag
        )

        if workload_new and defender_below_attach:
            story_type = STORY_NEW_WORKLOAD_NO_DEFENDER
        elif (
            workload_has_stable_baseline
            and opp.defender_growth <= config.divergence_story_defender_regression
            and workload_stable_or_growing
        ):
            story_type = STORY_DEFENDER_REGRESSION
        elif (
            workload_has_stable_baseline
            and opp.workload_growth >= config.divergence_story_min_workload_growth
            and defender_lag_is_material
            and (
                opp.defender_growth <= config.divergence_story_flat_defender_growth
                or opp.defender_growth < opp.workload_growth
                or opp.defender_zero_with_workload_growth
            )
        ):
            story_type = STORY_GROWTH_DIVERGENCE

        if story_type is None:
            continue

        workload_delta = workload_end - workload_start
        defender_delta = defender_end - defender_start
        workload_pct = _safe_pct_change(workload_start, workload_end)
        defender_pct = _safe_pct_change(defender_start, defender_end)
        severity = _story_severity(story_type, opp)
        gap_note = (
            f"Estimated benchmark gap: ${opp.gap_dollars:,.0f}/mo."
            if opp.has_dollar_gap
            else "No fixed dollar benchmark is used for this plan."
        )
        evidence = [
            (
                f"Workload ACR moved from ${workload_start:,.0f} to "
                f"${workload_end:,.0f} ({_format_pct(workload_pct)})."
            ),
            (
                f"Defender ACR moved from ${defender_start:,.0f} to "
                f"${defender_end:,.0f} ({_format_pct(defender_pct)})."
            ),
            f"Momentum spread is {_format_pct(opp.momentum_raw)}.",
            gap_note,
        ]

        stories.append(
            DivergenceStory(
                customer=customer,
                plan_label=opp.plan_label,
                workload_sl2_categories=list(opp.workload_sl2_present),
                story_type=story_type,
                severity=severity,
                confidence=opp.confidence,
                pricing_driver=opp.pricing_driver,
                latest_workload_acr=opp.workload_acr,
                latest_defender_acr=opp.defender_actual,
                compared_months=list(compared),
                workload_start_value=workload_start,
                workload_end_value=workload_end,
                defender_start_value=defender_start,
                defender_end_value=defender_end,
                workload_delta=workload_delta,
                defender_delta=defender_delta,
                workload_pct_change=workload_pct,
                defender_pct_change=defender_pct,
                momentum_spread=opp.momentum_raw,
                has_dollar_gap=opp.has_dollar_gap,
                gap_dollars=opp.gap_dollars if opp.has_dollar_gap else 0.0,
                headline=_story_headline(customer, story_type, opp),
                evidence_bullets=evidence,
                recommended_action=_recommended_action(story_type, opp),
                caveat_text=DIVERGENCE_STORY_CAVEAT,
            )
        )

    severity_rank = {"High": 0, "Medium": 1}
    return sorted(
        stories,
        key=lambda s: (
            severity_rank.get(s.severity, 9),
            -s.gap_dollars,
            -s.latest_workload_acr,
            s.plan_label,
        ),
    )


def build_model(parsed: ParsedData, config: Optional[AttachConfig] = None) -> BookModel:
    config = config or default_config()
    frame = parsed.frame
    months = parsed.months
    latest = parsed.latest_month

    recon_by_customer: Dict[str, bool] = {}
    for issue in parsed.reconciliation:
        ok = issue.rel_diff <= 0.01
        recon_by_customer[issue.customer] = recon_by_customer.get(issue.customer, True) and ok

    cohort_ratios = _cohort_ratios(frame, latest, config)

    foundational_set = set(FOUNDATIONAL_PLANS)
    non_azure = set(NON_AZURE_SL2)

    dossiers: List[CustomerDossier] = []
    all_opps: List[Opportunity] = []
    divergence_candidates_by_customer: Dict[str, List[Opportunity]] = {}

    for customer in parsed.customers:
        cust = frame[frame["customer"] == customer]

        customer_total_acr = _series_for(
            cust, months, [TOTAL_TOKEN], None, LEVEL_CUSTOMER_TOTAL
        )[-1]
        dfc_acr = _series_for(
            cust, months, [DEFENDER_SL2], [TOTAL_TOKEN], LEVEL_SERVICE_TOTAL
        )[-1]

        # Eligible workload ACR = mapped workloads only.
        eligible_sl2 = [s for p in WORKLOAD_PLANS for s in p.workload_sl2]
        eligible_workload_acr = _series_for(
            cust, months, eligible_sl2, None, LEVEL_SERVICE_TOTAL
        )[-1]

        # Azure (non-XCR) workload context = service subtotals excluding DfC and
        # known non-Azure SL2 buckets.
        svc_latest = cust[
            (cust["level"] == LEVEL_SERVICE_TOTAL) & (cust["month"] == latest)
        ]
        azure_workload_acr = float(
            svc_latest[
                (~svc_latest["sl2"].isin(non_azure))
                & (svc_latest["sl2"] != DEFENDER_SL2)
            ]["acr"].sum()
        )

        attach_ratio = (
            dfc_acr / eligible_workload_acr if eligible_workload_acr > 0 else None
        )

        dossier = CustomerDossier(
            customer=customer,
            customer_total_acr=customer_total_acr,
            azure_workload_acr=azure_workload_acr,
            eligible_workload_acr=eligible_workload_acr,
            dfc_acr=dfc_acr,
            attach_ratio=attach_ratio,
            reconciliation_ok=recon_by_customer.get(customer, True),
        )

        present_eligible = 0
        uncovered_eligible = 0
        divergence_candidates: List[Opportunity] = []
        for plan in WORKLOAD_PLANS:
            workload_now = _series_for(
                cust, months, plan.workload_sl2, None, LEVEL_SERVICE_TOTAL
            )[-1]
            if workload_now > 0:
                present_eligible += 1
                defender_now = _series_for(
                    cust, months, [DEFENDER_SL2], plan.defender_sl4, LEVEL_LEAF
                )[-1]
                if defender_now <= config.attach_threshold:
                    uncovered_eligible += 1

            ratio = cohort_ratios.get(plan.plan_label, config.ratio_for(plan.plan_label))
            opp = _build_opportunity(plan, cust, months, config, ratio)
            if opp is not None:
                opp.opener = _opener(customer, opp)
                dossier.opportunities.append(opp)
                all_opps.append(opp)
                divergence_candidates.append(opp)
            else:
                covered_candidate = _build_plan_candidate(
                    plan, cust, months, config, ratio, include_covered=True
                )
                if covered_candidate is not None:
                    divergence_candidates.append(covered_candidate)

        dossier.present_eligible_count = present_eligible
        dossier.uncovered_eligible_count = uncovered_eligible
        dossier.total_gap_dollars = sum(o.gap_dollars for o in dossier.opportunities)

        # Foundational coverage panel.
        for plan_name in FOUNDATIONAL_PLANS:
            actual = _series_for(cust, months, [DEFENDER_SL2], [plan_name], LEVEL_LEAF)[-1]
            dossier.foundational.append(
                FoundationalCoverage(
                    plan_label=plan_name,
                    actual=actual,
                    present=actual > config.attach_threshold,
                )
            )

        # Top Azure spend categories for context. Deterministic tie-break by
        # sl2 name (ascending) so cross-language ports stay byte-stable.
        top = (
            svc_latest[
                (svc_latest["sl2"] != DEFENDER_SL2)
                & (~svc_latest["sl2"].isin(non_azure))
                & (svc_latest["sl2"] != TOTAL_TOKEN)
            ]
            .groupby("sl2")["acr"]
            .sum()
            .reset_index()
            .sort_values(["acr", "sl2"], ascending=[False, True], kind="mergesort")
            .head(8)
        )
        dossier.top_spend = [
            SpendCategory(sl2=r.sl2, acr=float(r.acr)) for r in top.itertuples(index=False)
        ]

        divergence_candidates_by_customer[customer] = divergence_candidates
        dossiers.append(dossier)

    _score(dossiers, all_opps, config)

    all_stories: List[DivergenceStory] = []
    for dossier in dossiers:
        dossier.divergence_stories = detect_divergence_stories(
            dossier.customer, divergence_candidates_by_customer[dossier.customer], months, config
        )
        all_stories.extend(dossier.divergence_stories)

    total_elig = sum(d.eligible_workload_acr for d in dossiers)
    total_dfc = sum(d.dfc_acr for d in dossiers)
    total_gap = sum(d.total_gap_dollars for d in dossiers)

    return BookModel(
        dossiers=sorted(dossiers, key=lambda d: d.customer_score, reverse=True),
        months=months,
        latest_month=latest,
        config=config,
        cohort_ratios=cohort_ratios,
        source_name=parsed.source_name,
        reconciliation=parsed.reconciliation,
        total_eligible_workload_acr=total_elig,
        total_dfc_acr=total_dfc,
        total_gap_dollars=total_gap,
        divergence_stories=sorted(
            all_stories,
            key=lambda s: (
                {"High": 0, "Medium": 1}.get(s.severity, 9),
                -s.gap_dollars,
                -s.latest_workload_acr,
                s.customer,
                s.plan_label,
            ),
        ),
    )


def _score(
    dossiers: List[CustomerDossier],
    all_opps: List[Opportunity],
    config: AttachConfig,
) -> None:
    if not all_opps:
        return

    # Gap score from log-compressed size, percentile-ranked across the book.
    sizes = [math.log1p(max(0.0, o.size_value)) for o in all_opps]
    gap_scores = _percentile_scores(sizes)
    momentum_scores = _percentile_scores([o.momentum_raw for o in all_opps])

    w_gap, w_mom, w_breadth = config.normalized_weights()

    for opp, g, m in zip(all_opps, gap_scores, momentum_scores):
        opp.gap_score = g
        if not opp.has_dollar_gap:
            opp.gap_score *= config.coverage_signal_discount
        opp.momentum_score = m

    # Breadth is a customer-level signal; normalize across customers.
    breadth_raw = [float(d.uncovered_eligible_count) for d in dossiers]
    breadth_scores = _percentile_scores(breadth_raw)
    for d, b in zip(dossiers, breadth_scores):
        d.breadth_score = b

    # Per-opportunity blended score (breadth folded in at customer level).
    for d in dossiers:
        for opp in d.opportunities:
            opp.blended_score = (
                w_gap * opp.gap_score
                + w_mom * opp.momentum_score
                + w_breadth * d.breadth_score
            )

    # Customer score: size of the prize (sum of opportunity size scores) blended
    # with breadth, then re-normalized to 0-100 for a clean leaderboard.
    raw_customer = []
    for d in dossiers:
        opp_value = sum(o.gap_score for o in d.opportunities)
        raw_customer.append(0.7 * opp_value + 0.3 * d.breadth_score)
    customer_scores = _percentile_scores(raw_customer)
    for d, s in zip(dossiers, customer_scores):
        d.customer_score = s
