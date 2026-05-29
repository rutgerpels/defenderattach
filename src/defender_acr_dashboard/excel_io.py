from __future__ import annotations

from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import pandas as pd

try:
    from xlrd.biffh import XLRDError
except ImportError:  # pragma: no cover - only used when xlrd is absent.
    XLRDError = None


OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ENCRYPTED_PACKAGE_MARKER = "EncryptedPackage".encode("utf-16le")
DRM_MARKER = "DRMEncrypted".encode("utf-16le")


def read_excel_sheet(path: Path, **kwargs: Any) -> pd.DataFrame:
    engine = _engine_for_workbook(path)
    try:
        return pd.read_excel(path, engine=engine, **kwargs)
    except BadZipFile as exc:
        raise ValueError(
            f"{path.name} is not a valid XLSX workbook. Open the export in Excel and save it as an unprotected .xlsx file."
        ) from exc
    except ImportError as exc:
        raise ValueError(f"Reading {path.name} requires the '{engine}' Excel engine to be installed.") from exc
    except _xlrd_errors() as exc:
        raise ValueError(
            f"{path.name} could not be read as a legacy Excel workbook. Save it as an unprotected .xlsx file and retry."
        ) from exc


def _engine_for_workbook(path: Path) -> str:
    signature = path.read_bytes()[:8]
    if signature == OLE_SIGNATURE:
        _raise_if_protected_office_file(path)
        return "xlrd"
    return "openpyxl"


def _raise_if_protected_office_file(path: Path) -> None:
    content = path.read_bytes()
    if ENCRYPTED_PACKAGE_MARKER in content or DRM_MARKER in content:
        raise ValueError(
            f"{path.name} is encrypted or sensitivity-label protected and cannot be read by the dashboard. "
            "Remove the protection or export/save a normal .xlsx copy, then refresh the page."
        )


def _xlrd_errors() -> tuple[type[Exception], ...]:
    return () if XLRDError is None else (XLRDError,)
