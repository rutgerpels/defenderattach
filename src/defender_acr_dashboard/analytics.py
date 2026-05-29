from __future__ import annotations

import pandas as pd

from .config import DEFENDER_SERVICE, TOTAL_SERVICE


def build_customer_metrics(
    records: pd.DataFrame,
    defender_share_threshold: float,
    non_defender_growth_threshold: float,
) -> pd.DataFrame:
    periods = sorted(records["period_start"].dropna().unique())
    if not periods:
        raise ValueError("No periods are available in the normalized data.")

    latest_period = periods[-1]
    previous_period = periods[-2] if len(periods) > 1 else None

    latest_total = _service_acr(records, TOTAL_SERVICE, latest_period, "latest_total_acr")
    latest_defender = _service_acr(records, DEFENDER_SERVICE, latest_period, "latest_defender_acr")
    metrics = latest_total.merge(latest_defender, on="customer", how="left").fillna(0)

    if previous_period is not None:
        previous_total = _service_acr(records, TOTAL_SERVICE, previous_period, "previous_total_acr")
        previous_defender = _service_acr(records, DEFENDER_SERVICE, previous_period, "previous_defender_acr")
        metrics = metrics.merge(previous_total, on="customer", how="left")
        metrics = metrics.merge(previous_defender, on="customer", how="left")
    else:
        metrics["previous_total_acr"] = 0.0
        metrics["previous_defender_acr"] = 0.0

    metrics = metrics.fillna(0.0)
    metrics["latest_non_defender_acr"] = metrics["latest_total_acr"] - metrics["latest_defender_acr"]
    metrics["previous_non_defender_acr"] = metrics["previous_total_acr"] - metrics["previous_defender_acr"]
    metrics["defender_share"] = _safe_divide(metrics["latest_defender_acr"], metrics["latest_total_acr"])
    metrics["non_defender_growth_mom"] = _safe_growth(
        metrics["latest_non_defender_acr"],
        metrics["previous_non_defender_acr"],
    )
    metrics["opportunity_flag"] = (
        (metrics["defender_share"] < defender_share_threshold)
        & (metrics["non_defender_growth_mom"] > non_defender_growth_threshold)
        & (metrics["latest_total_acr"] > 0)
    )
    metrics["opportunity_score"] = (
        ((defender_share_threshold - metrics["defender_share"]).clip(lower=0) / defender_share_threshold)
        + metrics["non_defender_growth_mom"].clip(lower=0)
    ) * metrics["latest_total_acr"].clip(lower=0).pow(0.35)
    metrics["top_growing_services"] = metrics["customer"].map(
        lambda customer: summarize_top_growing_services(records, customer)
    )
    return metrics.sort_values(
        ["opportunity_flag", "opportunity_score", "latest_total_acr"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def customer_time_series(records: pd.DataFrame, customer: str) -> pd.DataFrame:
    subset = records[records["customer"] == customer]
    total = subset[subset["service_group"] == TOTAL_SERVICE][["period_start", "fiscal_month", "acr"]]
    defender = subset[subset["service_group"] == DEFENDER_SERVICE][["period_start", "acr"]]
    series = total.rename(columns={"acr": "total_acr"}).merge(
        defender.rename(columns={"acr": "defender_acr"}),
        on="period_start",
        how="left",
    )
    series["defender_acr"] = series["defender_acr"].fillna(0.0)
    series["defender_share"] = _safe_divide(series["defender_acr"], series["total_acr"])
    return series.sort_values("period_start")


def service_trends(records: pd.DataFrame, customer: str, top_n: int = 8) -> pd.DataFrame:
    subset = records[
        (records["customer"] == customer)
        & (~records["service_group"].isin([TOTAL_SERVICE, DEFENDER_SERVICE]))
    ].copy()
    latest_period = subset["period_start"].max()
    top_services = (
        subset[subset["period_start"] == latest_period]
        .sort_values("acr", ascending=False)
        .head(top_n)["service_group"]
    )
    return subset[subset["service_group"].isin(top_services)].sort_values(["service_group", "period_start"])


def summarize_top_growing_services(records: pd.DataFrame, customer: str, top_n: int = 3) -> str:
    subset = records[
        (records["customer"] == customer)
        & (~records["service_group"].isin([TOTAL_SERVICE, DEFENDER_SERVICE]))
    ]
    periods = sorted(subset["period_start"].dropna().unique())
    if len(periods) < 2:
        return ""
    previous_period, latest_period = periods[-2], periods[-1]
    pivot = (
        subset[subset["period_start"].isin([previous_period, latest_period])]
        .pivot_table(index="service_group", columns="period_start", values="acr", aggfunc="sum", fill_value=0)
    )
    if previous_period not in pivot or latest_period not in pivot:
        return ""
    pivot["delta"] = pivot[latest_period] - pivot[previous_period]
    pivot = pivot[pivot["delta"] > 0].sort_values("delta", ascending=False).head(top_n)
    return ", ".join(f"{service} (+${row['delta']:,.0f})" for service, row in pivot.iterrows())


def _service_acr(records: pd.DataFrame, service: str, period: pd.Timestamp, column_name: str) -> pd.DataFrame:
    return (
        records[(records["service_group"] == service) & (records["period_start"] == period)]
        .groupby("customer", as_index=False)["acr"]
        .sum()
        .rename(columns={"acr": column_name})
    )


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.where(denominator.ne(0))).fillna(0.0)


def _safe_growth(current: pd.Series, previous: pd.Series) -> pd.Series:
    return current.sub(previous).div(previous.where(previous.abs().gt(0))).fillna(0.0)
