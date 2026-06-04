"""Workload -> Microsoft Defender plan mapping and scoring configuration.

This is the single source of truth for *which Azure workload pairs with which
Defender for Cloud plan*, how confident we are in a dollar-based gap for that
pair, and the default scoring knobs. Everything here is intentionally data
(not code branching) so it can be tuned without touching the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Tuple

# --- Row / dimension tokens used across the SL2/SL4 export ---------------------

DEFENDER_SL2 = "Microsoft Defender for Cloud"
SENTINEL_SL2 = "Sentinel"
TOTAL_TOKEN = "Total"

# Foundational Defender plans. These protect the whole environment rather than a
# single purchasable workload, so they are reported in a separate panel and are
# NEVER used to dilute per-workload gap scores.
FOUNDATIONAL_PLANS: Tuple[str, ...] = (
    "Microsoft Defender CSPM",
    "Microsoft Defender for Resource Manager",
    "Microsoft Defender for DNS",
    "Defender External Attack Surface Management",
)

# Service Level 2 buckets that are not Azure first-party workloads we attach
# Defender to. Used only to compute a cleaner "Azure workload ACR" context
# figure; never part of the eligible-workload denominator.
NON_AZURE_SL2: Tuple[str, ...] = (
    "Power BI",
    "Power BI Embedded",
    "Power Apps",
    "Power Automate",
    "Power Pages",
    "Microsoft Copilot Studio",
    "Dataverse",
    "GitHub",
    "MS Bing Services",
    "Microsoft Graph Services",
    "Microsoft Graph Data Connect",
    "Syntex",
    "UNKNOWN",
    "NONE",
)


@dataclass(frozen=True)
class WorkloadPlan:
    """A pairing between purchasable Azure workloads and a Defender plan.

    Attributes:
        plan_label: Friendly Defender plan name shown to sellers.
        workload_sl2: SL2 buckets whose spend signals demand for this plan.
        defender_sl4: SL4 plan names that count as *actual* Defender spend for
            this pairing (includes legacy plan names that were folded in).
        confidence: How reliable a percentage-of-ACR dollar benchmark is.
            high/medium -> we publish a $ benchmark gap.
            low -> unit-priced (per node/transaction); we only publish a binary
            *coverage* signal, never a fabricated dollar figure.
        pricing_driver: Plain-language note on how the plan is actually priced.
        eligible_for_gap: When True the pair gets a $ benchmark gap. When False
            it is a coverage-only signal (workload present, Defender absent/low).
    """

    plan_label: str
    workload_sl2: Tuple[str, ...]
    defender_sl4: Tuple[str, ...]
    confidence: str
    pricing_driver: str
    eligible_for_gap: bool


WORKLOAD_PLANS: Tuple[WorkloadPlan, ...] = (
    WorkloadPlan(
        plan_label="Defender for Containers",
        workload_sl2=(
            "Azure Kubernetes Service",
            "Container Instances",
            "Azure Container Apps",
            "Advanced Container Networking Services",
            "Container Registry",
        ),
        defender_sl4=(
            "Microsoft Defender for Containers",
            "Microsoft Defender for Kubernetes",
            "Microsoft Defender for Container Registries",
        ),
        confidence="medium",
        pricing_driver="Per vCPU/core of monitored container hosts",
        eligible_for_gap=True,
    ),
    WorkloadPlan(
        plan_label="Defender for SQL",
        workload_sl2=("SQL Database", "SQL Managed Instance"),
        defender_sl4=("Microsoft Defender for SQL",),
        confidence="medium",
        pricing_driver="Per vCore / protected database instance",
        eligible_for_gap=True,
    ),
    WorkloadPlan(
        plan_label="Defender for App Service",
        workload_sl2=("Azure App Service",),
        defender_sl4=("Microsoft Defender for App Service",),
        confidence="medium",
        pricing_driver="Per App Service instance",
        eligible_for_gap=True,
    ),
    WorkloadPlan(
        plan_label="Defender for Key Vault",
        workload_sl2=("Key Vault",),
        defender_sl4=("Microsoft Defender for Key Vault",),
        confidence="medium",
        pricing_driver="Per 10K Key Vault transactions",
        eligible_for_gap=True,
    ),
    WorkloadPlan(
        plan_label="Defender for PostgreSQL",
        workload_sl2=("Azure Database for PostgreSQL",),
        defender_sl4=("Microsoft Defender for PostgreSQL",),
        confidence="medium",
        pricing_driver="Per protected server instance",
        eligible_for_gap=True,
    ),
    WorkloadPlan(
        plan_label="Defender for MySQL",
        workload_sl2=("Azure Database for MySQL",),
        defender_sl4=("Microsoft Defender for MySQL",),
        confidence="medium",
        pricing_driver="Per protected server instance",
        eligible_for_gap=True,
    ),
    WorkloadPlan(
        plan_label="Defender for Azure Cosmos DB",
        workload_sl2=("Azure Cosmos DB",),
        defender_sl4=("Microsoft Defender for Azure Cosmos DB",),
        confidence="medium",
        pricing_driver="Per 100 RU/s provisioned",
        eligible_for_gap=True,
    ),
    WorkloadPlan(
        plan_label="Defender for APIs",
        workload_sl2=("API Management",),
        defender_sl4=("Defender for APIs",),
        confidence="medium",
        pricing_driver="Per API call / protected API",
        eligible_for_gap=True,
    ),
    WorkloadPlan(
        plan_label="Defender for AI Services",
        workload_sl2=("Foundry Models", "Foundry Tools", "Azure Machine Learning"),
        defender_sl4=("Microsoft Defender for AI Services",),
        confidence="medium",
        pricing_driver="Per AI resource / monitored model",
        eligible_for_gap=True,
    ),
    # --- Coverage-only (unit priced; no honest %-of-ACR benchmark) -----------
    WorkloadPlan(
        plan_label="Defender for Servers",
        workload_sl2=("Virtual Machines",),
        defender_sl4=("Microsoft Defender for Servers",),
        confidence="low",
        pricing_driver="Per server/node per hour (not a % of compute ACR)",
        eligible_for_gap=False,
    ),
    WorkloadPlan(
        plan_label="Defender for Storage",
        workload_sl2=("Storage",),
        defender_sl4=("Microsoft Defender for Storage",),
        confidence="low",
        pricing_driver="Per storage account + per million transactions",
        eligible_for_gap=False,
    ),
)


@dataclass
class AttachConfig:
    """Tunable scoring configuration (safe defaults, override from the UI)."""

    target_ratio: float = 0.06
    """Default Defender $/workload $ benchmark for gap-eligible plans."""

    plan_target_ratios: Dict[str, float] = field(default_factory=dict)
    """Optional per-plan override of ``target_ratio`` keyed by ``plan_label``."""

    weight_gap: float = 0.5
    weight_momentum: float = 0.3
    weight_breadth: float = 0.2

    coverage_signal_discount: float = 0.5
    """Coverage-only opportunities (no $ benchmark) get their size score scaled
    by this factor so quantified gaps of equal size outrank them."""

    min_denominator: float = 100.0
    """Suppress ratios/benchmarks when the workload base is below this ($)."""

    attach_threshold: float = 5.0
    """Defender actuals at or below this ($) are treated as 'not attached'."""

    use_cohort_median: bool = True
    """When True, derive each plan's benchmark from the median observed attach
    ratio of customers who already buy it (with a minimum-sample guardrail),
    falling back to ``target_ratio`` otherwise."""

    cohort_min_sample: int = 5

    momentum_window: int = 3
    """Months averaged on each side when computing rolling growth."""

    momentum_cap: float = 1.0
    """Growth is clipped to +/- this value to tame zero-base explosions."""

    priority_momentum_eps: float = 0.02
    """Minimum ``momentum_raw`` (workload minus Defender growth) for an
    opportunity to count as growth-divergent when assigning a priority tier."""

    priority_coverage_medium: float = 0.5
    """Coverage (fraction of benchmark) below which an ``expand`` opportunity is
    treated as a Medium-priority under-coverage gap."""

    divergence_story_min_workload_acr: float = 1_000.0
    """Minimum latest workload ACR required before emitting a trend story."""

    divergence_story_min_start_workload_acr: float = 1_000.0
    """Minimum prior-window workload ACR for non-new trend stories.

    This suppresses growth/regression narratives that are only large because the
    denominator was tiny or zero. New-workload stories use
    ``divergence_story_new_workload_max_start_acr`` instead.
    """

    divergence_story_new_workload_max_start_acr: float = 100.0
    """Maximum prior-window workload ACR for a new-workload/no-Defender story."""

    divergence_story_min_workload_growth: float = 0.10
    """Minimum workload growth for a growth-divergence story."""

    divergence_story_material_lag: float = 0.15
    """Minimum workload-minus-Defender growth spread for material lag."""

    divergence_story_flat_defender_growth: float = 0.02
    """Maximum Defender growth treated as flat while workload is growing."""

    divergence_story_defender_regression: float = -0.05
    """Defender growth at or below this value is treated as a regression."""

    def ratio_for(self, plan_label: str) -> float:
        return self.plan_target_ratios.get(plan_label, self.target_ratio)

    def normalized_weights(self) -> Tuple[float, float, float]:
        total = self.weight_gap + self.weight_momentum + self.weight_breadth
        if total <= 0:
            return (0.5, 0.3, 0.2)
        return (
            self.weight_gap / total,
            self.weight_momentum / total,
            self.weight_breadth / total,
        )

    def with_overrides(self, **kwargs) -> "AttachConfig":
        return replace(self, **kwargs)


def default_config() -> AttachConfig:
    return AttachConfig()


def workload_sl2_index() -> Dict[str, WorkloadPlan]:
    """Map every workload SL2 name to its owning plan for quick lookup."""

    index: Dict[str, WorkloadPlan] = {}
    for plan in WORKLOAD_PLANS:
        for sl2 in plan.workload_sl2:
            index[sl2] = plan
    return index


def all_mapped_workload_sl2() -> List[str]:
    names: List[str] = []
    for plan in WORKLOAD_PLANS:
        names.extend(plan.workload_sl2)
    return names
