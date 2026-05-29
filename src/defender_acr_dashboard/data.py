from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import EXPORT_SHEET, INPUT_DIR
from .excel_io import read_excel_sheet


MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


@dataclass(frozen=True)
class DataBundle:
    source_path: Path
    records: pd.DataFrame


def find_latest_workbook(input_dir: Path = INPUT_DIR) -> Path:
    files = [
        path
        for path in input_dir.glob("*.xls*")
        if path.is_file() and not path.name.startswith("~$")
    ]
    if not files:
        raise FileNotFoundError(f"No Excel workbooks found in {input_dir}")
    return max(files, key=lambda path: path.stat().st_mtime)


def fiscal_month_to_period(value: str) -> pd.Timestamp:
    match = re.fullmatch(r"FY(?P<year>\d{2})-(?P<month>[A-Za-z]{3})", value.strip())
    if not match:
        raise ValueError(f"Unsupported fiscal month format: {value}")
    fiscal_year = 2000 + int(match.group("year"))
    month_name = match.group("month").title()
    month = MONTHS[month_name]
    calendar_year = fiscal_year - 1 if month >= 7 else fiscal_year
    return pd.Timestamp(year=calendar_year, month=month, day=1)


def load_records(path: Path | None = None, metric_name: str = "$ ACR") -> DataBundle:
    source_path = path or find_latest_workbook()
    raw = read_excel_sheet(source_path, sheet_name=EXPORT_SHEET, header=[0, 1])

    customer_col = _find_column(raw, "TPAccountName")
    service_col = _find_column(raw, "ServiceCompGrouping")
    metric_columns = [
        col
        for col in raw.columns
        if _clean_header_part(col[1]) == metric_name and _clean_header_part(col[0]).startswith("FY")
    ]
    if not metric_columns:
        raise ValueError(f"No monthly '{metric_name}' metric columns were found in the workbook.")

    frames: list[pd.DataFrame] = []
    for month_col in metric_columns:
        fiscal_month = _clean_header_part(month_col[0])
        frame = raw[[customer_col, service_col, month_col]].copy()
        frame.columns = ["customer", "service_group", "acr"]
        frame["fiscal_month"] = fiscal_month
        frame["period_start"] = fiscal_month_to_period(fiscal_month)
        frames.append(frame)

    records = pd.concat(frames, ignore_index=True)
    records["customer"] = records["customer"].astype("string").str.strip()
    records["service_group"] = records["service_group"].astype("string").str.strip()
    records["acr"] = pd.to_numeric(records["acr"], errors="coerce").fillna(0.0)
    records = records.dropna(subset=["customer", "service_group"])
    records = records[(records["customer"] != "") & (records["service_group"] != "")]
    records = records.sort_values(["customer", "service_group", "period_start"]).reset_index(drop=True)
    return DataBundle(source_path=source_path, records=records)


def _find_column(frame: pd.DataFrame, expected_name: str) -> tuple[str, str]:
    for col in frame.columns:
        if any(_clean_header_part(part) == expected_name for part in col):
            return col
    raise ValueError(f"Required column '{expected_name}' was not found.")


def _clean_header_part(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    return "" if text.startswith("Unnamed:") else text
