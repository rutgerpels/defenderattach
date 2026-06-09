from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ATTACH_INPUT_DIR, DEFAULT_NEAR_TERM_DAYS, EXPORT_SHEET
from .excel_io import read_excel_sheet


MIGRATION_KIND = "migration"
DEFENDER_KIND = "defender"
TARGET_SALES_STAGE_KEYS = {"inspire and design", "listen and consult"}


@dataclass(frozen=True)
class MilestoneWorkbookBundle:
    migration_path: Path
    defender_path: Path
    migration_records: pd.DataFrame
    defender_records: pd.DataFrame


def load_milestone_gap_model(
    input_dir: Path = ATTACH_INPUT_DIR,
    near_term_days: int = DEFAULT_NEAR_TERM_DAYS,
    reference_date: date | None = None,
) -> dict[str, Any]:
    bundle = load_milestone_workbooks(input_dir)
    reference = reference_date or date.today()
    model = build_milestone_gap_model(
        bundle.migration_records,
        bundle.defender_records,
        near_term_days=near_term_days,
        reference_date=reference,
    )
    model["sources"] = {
        "migration": bundle.migration_path.name,
        "defender": bundle.defender_path.name,
    }
    model["near_term_days"] = near_term_days
    model["reference_date"] = reference.isoformat()
    return model


def load_milestone_workbooks(input_dir: Path = ATTACH_INPUT_DIR) -> MilestoneWorkbookBundle:
    migration_path, defender_path = find_milestone_workbooks(input_dir)
    migration_records = _load_milestone_records(migration_path, MIGRATION_KIND)
    defender_records = _load_milestone_records(defender_path, DEFENDER_KIND)
    return MilestoneWorkbookBundle(
        migration_path=migration_path,
        defender_path=defender_path,
        migration_records=migration_records,
        defender_records=defender_records,
    )


def find_milestone_workbooks(input_dir: Path = ATTACH_INPUT_DIR) -> tuple[Path, Path]:
    if not input_dir.exists():
        raise FileNotFoundError(f"Milestone input folder was not found: {input_dir}")
    files = [
        path
        for path in input_dir.glob("*.xls*")
        if path.is_file() and not path.name.startswith("~$")
    ]
    if not files:
        raise FileNotFoundError(f"No milestone Excel workbooks found in {input_dir}")

    migration_files = [path for path in files if "migration" in path.name.casefold()]
    defender_files = [path for path in files if "defender" in path.name.casefold()]
    if not migration_files:
        raise FileNotFoundError(f"No Migration milestones workbook found in {input_dir}")
    if not defender_files:
        raise FileNotFoundError(f"No Defender milestones workbook found in {input_dir}")

    return (
        max(migration_files, key=lambda path: path.stat().st_mtime),
        max(defender_files, key=lambda path: path.stat().st_mtime),
    )


def build_milestone_gap_model(
    migration_records: pd.DataFrame,
    defender_records: pd.DataFrame,
    *,
    near_term_days: int = DEFAULT_NEAR_TERM_DAYS,
    reference_date: date | None = None,
) -> dict[str, Any]:
    reference = reference_date or date.today()
    near_term_days = max(0, int(near_term_days))

    migration_accounts = set(migration_records["account_key"])
    defender_accounts = set(defender_records["account_key"])
    attached_accounts = migration_accounts & defender_accounts
    migration_only_accounts = migration_accounts - defender_accounts

    defender_opportunities = set(
        zip(defender_records["account_key"], defender_records["opportunity_key"], strict=False)
    )
    gap_frames: list[pd.DataFrame] = []

    account_gap_rows = migration_records[migration_records["account_key"].isin(migration_only_accounts)]
    if not account_gap_rows.empty:
        account_gap_rows = account_gap_rows.copy()
        account_gap_rows["gap_type"] = "Account-level gap"
        gap_frames.append(account_gap_rows)

    attached_migration_rows = migration_records[migration_records["account_key"].isin(attached_accounts)]
    if not attached_migration_rows.empty:
        opportunity_gap_mask = [
            (account_key, opportunity_key) not in defender_opportunities
            for account_key, opportunity_key in zip(
                attached_migration_rows["account_key"],
                attached_migration_rows["opportunity_key"],
                strict=False,
            )
        ]
        opportunity_gap_rows = attached_migration_rows[opportunity_gap_mask].copy()
        if not opportunity_gap_rows.empty:
            opportunity_gap_rows["gap_type"] = "Opportunity-level gap"
            gap_frames.append(opportunity_gap_rows)

    if gap_frames:
        gap_source = pd.concat(gap_frames, ignore_index=True)
        gaps = _aggregate_gap_rows(gap_source, reference, near_term_days)
    else:
        gaps = []

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    gaps.sort(
        key=lambda row: (
            priority_order[row["priority"]],
            row["estimated_date"] or "9999-12-31",
            -row["acr_pipeline"],
        )
    )

    account_gap_keys = {row["account_key"] for row in gaps}
    opportunity_gap_keys = {
        (row["account_key"], row["opportunity_id"] or "")
        for row in gaps
    }
    priority_counts = _count_by(gaps, "priority", ["HIGH", "MEDIUM", "LOW"])
    gap_type_counts = _count_by(gaps, "gap_type", ["Account-level gap", "Opportunity-level gap"])
    workload_counts = _top_workload_counts(gaps)

    return _json_safe(
        {
            "summary": {
                "migration_accounts": len(migration_accounts),
                "defender_accounts": len(defender_accounts),
                "attached_accounts": len(attached_accounts),
                "account_level_gap_accounts": len(migration_only_accounts),
                "total_accounts_with_gaps": len(account_gap_keys),
                "total_opportunities_with_gaps": len(opportunity_gap_keys),
                "account_level_gaps": gap_type_counts["Account-level gap"],
                "opportunity_level_gaps": gap_type_counts["Opportunity-level gap"],
                "total_gap_rows": len(gaps),
            },
            "priority_counts": priority_counts,
            "gap_type_counts": gap_type_counts,
            "workload_counts": workload_counts,
            "gaps": gaps,
            "top_gaps": gaps[:10],
            "data_quality": {
                "migration_rows": len(migration_records),
                "defender_rows": len(defender_records),
                "migration_invalid_dates": int(migration_records["due_date"].isna().sum()),
                "defender_invalid_dates": int(defender_records["due_date"].isna().sum()),
                "strict_opportunity_match": "Migration opportunities are compared to Defender milestones only when account and Opportunity ID both match.",
            },
        }
    )


def gaps_to_dataframe(model: dict[str, Any]) -> pd.DataFrame:
    rows = model.get("gaps", [])
    columns = [
        "account",
        "opportunity_id",
        "gap_type",
        "workload",
        "estimated_date",
        "priority",
        "commitment",
        "status",
        "sales_stage",
        "acr_pipeline",
        "owner_role",
        "owner",
        "milestone_count",
        "priority_reason",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(rows)
    return frame[[column for column in columns if column in frame.columns]]


def _load_milestone_records(path: Path, dataset_type: str) -> pd.DataFrame:
    raw = read_excel_sheet(path, sheet_name=EXPORT_SHEET)
    columns = _column_lookup(raw)
    required = {
        "account": ("Translated Account Name", "Account name"),
        "opportunity_id": ("Opportunity ID",),
        "milestone_id": ("Milestone ID",),
        "milestone_name": ("Milestone Name",),
        "milestone_workload": ("Milestone Workload",),
        "workload": ("Workload",),
        "acr_pipeline": ("ACR Pipeline $",),
        "status": ("Status",),
        "commitment": ("Commitment",),
        "due_date": ("Due Date", "Estimated date"),
        "category": ("Category",),
        "owner_role": ("Owner Role",),
        "owner": ("Owner",),
    }
    optional = {
        "sales_stage": ("SalesStageName", "Sales Stage Name", "Sales Stage"),
    }
    source_columns = {
        target: _find_source_column(columns, names, path)
        for target, names in required.items()
    }
    for target, names in optional.items():
        source = _find_optional_source_column(columns, names)
        if source:
            source_columns[target] = source

    frame = raw[list(source_columns.values())].copy()
    frame.columns = list(source_columns.keys())
    frame["dataset_type"] = dataset_type
    frame["source_file"] = path.name
    frame["source_row"] = frame.index + 2

    text_columns = [
        "account",
        "opportunity_id",
        "milestone_id",
        "milestone_name",
        "milestone_workload",
        "workload",
        "status",
        "commitment",
        "category",
        "owner_role",
        "owner",
        "sales_stage",
    ]
    for column in text_columns:
        if column not in frame.columns:
            frame[column] = ""
    for column in text_columns:
        frame[column] = frame[column].map(_clean_text)

    frame["account_key"] = frame["account"].map(_key)
    frame["opportunity_key"] = frame["opportunity_id"].map(_key)
    frame["due_date"] = frame["due_date"].map(_parse_date)
    frame["due_date_display"] = frame["due_date"].map(
        lambda value: value.date().isoformat() if pd.notna(value) else ""
    )
    frame["acr_pipeline"] = pd.to_numeric(frame["acr_pipeline"], errors="coerce").fillna(0.0)

    valid_account = (
        frame["account_key"].ne("")
        & frame["account_key"].ne("total")
        & ~frame["account_key"].str.startswith("applied filters:")
    )
    frame = frame[valid_account].copy()

    frame["dedupe_key"] = frame.apply(_dedupe_key, axis=1)
    frame = frame.drop_duplicates(subset=["dedupe_key"], keep="first")
    return frame.sort_values(["account", "opportunity_id", "milestone_id"]).reset_index(drop=True)


def _aggregate_gap_rows(
    rows: pd.DataFrame,
    reference_date: date,
    near_term_days: int,
) -> list[dict[str, Any]]:
    grouped = rows.groupby(["account_key", "opportunity_key", "gap_type"], dropna=False)
    gaps: list[dict[str, Any]] = []
    for (account_key, _opportunity_key, gap_type), group in grouped:
        display_account = _first_non_empty(group["account"])
        opportunity_id = _first_non_empty(group["opportunity_id"])
        workloads = _unique_text(group["workload"])
        milestone_workloads = _unique_text(group["milestone_workload"])
        commitments = _unique_text(group["commitment"])
        statuses = _unique_text(group["status"])
        sales_stages = _unique_text(group["sales_stage"])
        owners = _unique_text(group["owner"])
        owner_roles = _unique_text(group["owner_role"])
        due_dates = group["due_date"].dropna().sort_values()
        earliest_due_date = due_dates.iloc[0].date() if not due_dates.empty else None
        has_committed = any(_key(value) == "committed" for value in group["commitment"])
        has_valid_workload = any(_is_valid_workload(value) for value in workloads)
        priority, reason = _priority(
            sales_stages=sales_stages,
            has_valid_workload=has_valid_workload,
        )
        gaps.append(
            {
                "account_key": account_key,
                "account": display_account,
                "opportunity_id": opportunity_id,
                "gap_type": gap_type,
                "workload": "; ".join(workloads) if workloads else "Unclear workload",
                "milestone_workload": "; ".join(milestone_workloads),
                "estimated_date": earliest_due_date.isoformat() if earliest_due_date else "",
                "priority": priority,
                "commitment": "; ".join(commitments),
                "status": "; ".join(statuses),
                "sales_stage": "; ".join(sales_stages),
                "acr_pipeline": round(float(group["acr_pipeline"].sum()), 2),
                "owner_role": "; ".join(owner_roles),
                "owner": "; ".join(owners),
                "milestone_count": int(group["milestone_id"].nunique() or len(group)),
                "has_committed": has_committed,
                "priority_reason": reason,
                "milestones": _unique_text(group["milestone_name"])[:6],
            }
        )
    return gaps


def _priority(
    *,
    sales_stages: list[str],
    has_valid_workload: bool,
) -> tuple[str, str]:
    target_stage = next(
        (stage for stage in sales_stages if _sales_stage_key(stage) in TARGET_SALES_STAGE_KEYS),
        "",
    )
    if target_stage:
        return "HIGH", f"Target sales stage: {target_stage}"
    if sales_stages:
        return "MEDIUM", f"Other sales stage: {'; '.join(sales_stages)}"
    if has_valid_workload:
        return "MEDIUM", "No sales stage provided; valid workload"
    return "LOW", "No target sales stage and unclear workload"


def _sales_stage_key(value: object) -> str:
    return " ".join(_key(value).replace("&", " and ").split())


def _is_valid_workload(value: str) -> bool:
    key = _key(value)
    if not key:
        return False
    unclear_terms = ("unknown", "unclear", "tbd", "to be scoped", "placeholder", "other adjustment")
    return not any(term in key for term in unclear_terms)


def _top_workload_counts(gaps: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in gaps:
        for workload in [part.strip() for part in row["workload"].split(";") if part.strip()]:
            counts[workload] = counts.get(workload, 0) + 1
    return [
        {"workload": workload, "count": count}
        for workload, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _count_by(rows: list[dict[str, Any]], key: str, expected: list[str]) -> dict[str, int]:
    counts = {value: 0 for value in expected}
    for row in rows:
        value = row.get(key, "")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _column_lookup(frame: pd.DataFrame) -> dict[str, str]:
    return {_key(column): column for column in frame.columns}


def _find_source_column(columns: dict[str, str], names: tuple[str, ...], path: Path) -> str:
    for name in names:
        key = _key(name)
        if key in columns:
            return columns[key]
    expected = " or ".join(names)
    raise ValueError(f"Required column '{expected}' was not found in {path.name}")


def _find_optional_source_column(columns: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        key = _key(name)
        if key in columns:
            return columns[key]
    return None


def _dedupe_key(row: pd.Series) -> str:
    if row["milestone_id"]:
        return f"{row['dataset_type']}|milestone|{_key(row['milestone_id'])}"
    parts = [
        row["dataset_type"],
        row["account_key"],
        row["opportunity_key"],
        _key(row["milestone_name"]),
        _key(row["workload"]),
        row["due_date_display"],
    ]
    return "|".join(parts)


def _first_non_empty(values: pd.Series) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _unique_text(values: pd.Series) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = _clean_text(value)
        key = _key(text)
        if text and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).replace("\xa0", " ").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return " ".join(text.split())


def _key(value: object) -> str:
    return _clean_text(value).casefold()


def _parse_date(value: object) -> pd.Timestamp | pd.NaT:
    if pd.isna(value):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value.normalize()
    if isinstance(value, datetime):
        return pd.Timestamp(value.date())
    if isinstance(value, date):
        return pd.Timestamp(value)
    if isinstance(value, (int, float)) and not math.isnan(value):
        if 20_000 <= float(value) <= 80_000:
            return pd.to_datetime(value, unit="D", origin="1899-12-30", errors="coerce")
    return pd.to_datetime(value, errors="coerce")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value
