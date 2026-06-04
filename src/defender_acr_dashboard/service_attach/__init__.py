"""Service-level (SL2/SL4) Defender attach motion.

Builds a per-service "you buy X, you don't protect X" sales motion from the
combined Service Level 2 / Service Level 4 ACR export.
"""

from .mapping import (
    DEFENDER_SL2,
    FOUNDATIONAL_PLANS,
    SENTINEL_SL2,
    TOTAL_TOKEN,
    WORKLOAD_PLANS,
    WorkloadPlan,
    default_config,
)

__all__ = [
    "DEFENDER_SL2",
    "SENTINEL_SL2",
    "TOTAL_TOKEN",
    "FOUNDATIONAL_PLANS",
    "WORKLOAD_PLANS",
    "WorkloadPlan",
    "default_config",
]
