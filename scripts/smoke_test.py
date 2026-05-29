from defender_acr_dashboard.analytics import build_customer_metrics, customer_time_series, service_trends
from defender_acr_dashboard.config import (
    DEFAULT_DEFENDER_SHARE_THRESHOLD,
    DEFAULT_NON_DEFENDER_GROWTH_THRESHOLD,
)
from defender_acr_dashboard.data import load_records


def main() -> None:
    bundle = load_records()
    metrics = build_customer_metrics(
        bundle.records,
        DEFAULT_DEFENDER_SHARE_THRESHOLD,
        DEFAULT_NON_DEFENDER_GROWTH_THRESHOLD,
    )
    if bundle.records.empty:
        raise RuntimeError("No normalized records were loaded.")
    if metrics.empty:
        raise RuntimeError("No customer metrics were calculated.")
    customer = metrics.iloc[0]["customer"]
    if customer_time_series(bundle.records, customer).empty:
        raise RuntimeError("Customer time series is empty.")
    service_trends(bundle.records, customer)
    print(
        f"Loaded {len(bundle.records):,} records for {metrics['customer'].nunique():,} customers from {bundle.source_path.name}."
    )
    print(f"Flagged opportunities: {int(metrics['opportunity_flag'].sum()):,}")


if __name__ == "__main__":
    main()
