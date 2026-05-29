from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .config import DEFENDER_SERVICE, TOTAL_SERVICE


def build_dashboard_model(records: pd.DataFrame) -> dict[str, Any]:
    periods = (
        records[["period_start", "fiscal_month"]]
        .drop_duplicates()
        .sort_values("period_start")
        .reset_index(drop=True)
    )
    months = periods["fiscal_month"].tolist()
    month_labels = [month.split("-", 1)[1] if "-" in month else month for month in months]
    customers = sorted(records["customer"].dropna().unique().tolist())
    products = sorted(
        service for service in records["service_group"].dropna().unique().tolist() if service != TOTAL_SERVICE
    )

    pivot = records.pivot_table(
        index=["customer", "service_group"],
        columns="fiscal_month",
        values="acr",
        aggfunc="sum",
        fill_value=0.0,
    )
    pivot = pivot.reindex(columns=months, fill_value=0.0)

    def series(customer: str, product: str) -> list[float]:
        if (customer, product) not in pivot.index:
            return [0.0 for _ in months]
        return [_round_money(value) for value in pivot.loc[(customer, product)].tolist()]

    latest_idx = len(months) - 1
    prior_idx = max(0, latest_idx - 1)
    base_3m_idx = max(0, latest_idx - 2)
    latest_fy = months[latest_idx].split("-", 1)[0] if months else ""
    fytd_indices = [
        index
        for index, month in enumerate(months)
        if month.split("-", 1)[0] == latest_fy and index <= latest_idx
    ]
    opportunity: list[dict[str, Any]] = []
    customer_data: dict[str, Any] = {}

    for customer in customers:
        dfc = series(customer, DEFENDER_SERVICE)
        total = series(customer, TOTAL_SERVICE)
        other = [_round_money(total_value - dfc[index]) for index, total_value in enumerate(total)]

        dfc_current = dfc[latest_idx]
        total_current = total[latest_idx]
        other_current = other[latest_idx]
        dfc_fytd = sum(dfc[index] for index in fytd_indices)
        total_fytd = sum(total[index] for index in fytd_indices)
        other_fytd = sum(other[index] for index in fytd_indices)
        dfc_mom = _pct_change(dfc[prior_idx], dfc[latest_idx])
        other_mom = _pct_change(other[prior_idx], other[latest_idx])
        total_mom = _pct_change(total[prior_idx], total[latest_idx])
        dfc_3m = _pct_change(dfc[base_3m_idx], dfc[latest_idx])
        other_3m = _pct_change(other[base_3m_idx], other[latest_idx])
        total_3m = _pct_change(total[base_3m_idx], total[latest_idx])
        dfc_3m_delta = dfc[latest_idx] - dfc[base_3m_idx]
        other_3m_delta = other[latest_idx] - other[base_3m_idx]
        total_3m_delta = total[latest_idx] - total[base_3m_idx]
        dfc_ratio = dfc_current / total_current if total_current > 0 else 0.0
        dfc_fytd_ratio = dfc_fytd / total_fytd if total_fytd > 0 else 0.0

        breakdown = []
        for product in products:
            product_series = series(customer, product)
            current = product_series[latest_idx]
            if current < 1 and max(product_series or [0]) < 1:
                continue
            breakdown.append(
                {
                    "product": product,
                    "current": _round_money(current),
                    "mom": _pct_change(product_series[prior_idx], product_series[latest_idx]),
                    "three_m": _pct_change(product_series[base_3m_idx], product_series[latest_idx]),
                    "series": product_series,
                }
            )
        breakdown.sort(key=lambda row: row["current"], reverse=True)

        priority, notes = _classify_opportunity(
            dfc_current=dfc_current,
            total_current=total_current,
            dfc_ratio=dfc_ratio,
            dfc_3m=dfc_3m,
            other_3m=other_3m,
        )
        opportunity.append(
            {
                "customer": customer,
                "opportunity": priority,
                "notes": notes,
                "dfc_current": _round_money(dfc_current),
                "other_current": _round_money(other_current),
                "total_current": _round_money(total_current),
                "dfc_monthly_current": _round_money(dfc_current),
                "other_monthly_current": _round_money(other_current),
                "total_monthly_current": _round_money(total_current),
                "dfc_fytd": _round_money(dfc_fytd),
                "other_fytd": _round_money(other_fytd),
                "total_fytd": _round_money(total_fytd),
                "dfc_ratio": round(dfc_ratio * 100, 2),
                "dfc_fytd_ratio": round(dfc_fytd_ratio * 100, 2),
                "dfc_mom": dfc_mom,
                "other_mom": other_mom,
                "total_mom": total_mom,
                "dfc_3m": dfc_3m,
                "other_3m": other_3m,
                "total_3m": total_3m,
                "dfc_3m_delta": _round_money(dfc_3m_delta),
                "other_3m_delta": _round_money(other_3m_delta),
                "total_3m_delta": _round_money(total_3m_delta),
                "growth_gap": _round_money(other_3m_delta - dfc_3m_delta),
            }
        )
        customer_data[customer] = {
            "dfc_series": dfc,
            "other_series": other,
            "total_series": total,
            "products": breakdown,
        }

    product_monthly: dict[str, list[float]] = {}
    for product in [*products, TOTAL_SERVICE]:
        product_rows = records[records["service_group"] == product]
        monthly = (
            product_rows.groupby("fiscal_month")["acr"]
            .sum()
            .reindex(months, fill_value=0.0)
            .tolist()
        )
        product_monthly[product] = [_round_money(value) for value in monthly]

    priority_order = {"High": 0, "Medium": 1, "Low": 2, "Too small": 3}
    opportunity.sort(key=lambda row: (priority_order[row["opportunity"]], -row["total_current"]))

    return _json_safe(
        {
            "months": months,
            "month_labels": month_labels,
            "partial_month_idx": -1,
            "last_full_month": months[-1] if months else "",
            "prior_month": months[prior_idx] if months else "",
            "current_fiscal_year": latest_fy,
            "fytd_months": [months[index] for index in fytd_indices],
            "customers": customers,
            "products": products,
            "opportunity": opportunity,
            "customer_data": customer_data,
            "product_monthly": product_monthly,
            "dfc_total_monthly": product_monthly.get(DEFENDER_SERVICE, [0.0 for _ in months]),
            "counts": {
                "high": sum(1 for row in opportunity if row["opportunity"] == "High"),
                "medium": sum(1 for row in opportunity if row["opportunity"] == "Medium"),
                "low": sum(1 for row in opportunity if row["opportunity"] == "Low"),
                "too_small": sum(1 for row in opportunity if row["opportunity"] == "Too small"),
                "total": len(customers),
            },
        }
    )


def _classify_opportunity(
    *,
    dfc_current: float,
    total_current: float,
    dfc_ratio: float,
    dfc_3m: float | None,
    other_3m: float | None,
) -> tuple[str, str]:
    priority = "Low"
    notes: list[str] = []
    if total_current < 1500:
        return "Too small", "Customer ACR under $1,500/month - sales priority low"
    if dfc_current < 15 and total_current > 3000:
        return "High", "No Defender for Cloud spend at all"
    if other_3m is not None and other_3m > 0.05:
        if dfc_3m is None or dfc_3m < -0.05:
            priority = "High"
            notes.append(f"Other Azure +{other_3m * 100:.0f}% over 3 months while DfC declining")
        elif dfc_3m < 0.02 and dfc_ratio < 0.02:
            priority = "High"
            notes.append("Other Azure growing, DfC flat AND under 2% of total ACR")
        elif dfc_ratio < 0.015:
            priority = "Medium"
            notes.append(f"DfC penetration only {dfc_ratio * 100:.1f}% - undersold")
        elif dfc_3m < other_3m - 0.05:
            priority = "Medium"
            notes.append("DfC growing slower than rest of Azure")
    elif dfc_ratio < 0.005 and total_current > 6000:
        priority = "Medium"
        notes.append("Very low DfC penetration")

    if dfc_3m is not None and dfc_3m > 0.10 and (other_3m is None or dfc_3m > other_3m):
        if priority in {"Low", "Too small"}:
            notes.append(f"DfC growing healthily +{dfc_3m * 100:.0f}% over 3 months")

    return priority, "; ".join(notes) if notes else "-"


def _pct_change(start: float, end: float) -> float | None:
    if start is None or start == 0:
        return None
    return (end - start) / start


def _round_money(value: float) -> float:
    return round(float(value or 0.0), 2)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value
