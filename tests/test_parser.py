"""Unit tests for the SL2/SL4 parser helpers and reconciliation.

Run with:  python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd  # noqa: E402

from defender_acr_dashboard.service_attach import parser  # noqa: E402
from defender_acr_dashboard.service_attach.parser import (  # noqa: E402
    LEVEL_CUSTOMER_TOTAL,
    LEVEL_LEAF,
    LEVEL_SERVICE_TOTAL,
    ReconciliationIssue,
    _classify_level,
    _coerce_float,
    _month_columns,
    _reconcile,
)


class ClassifyLevelTests(unittest.TestCase):
    def test_customer_total(self):
        level, sl2, sl4 = _classify_level("Total", None)
        self.assertEqual(level, LEVEL_CUSTOMER_TOTAL)
        self.assertEqual(sl2, "Total")
        self.assertEqual(sl4, "")

    def test_service_subtotal(self):
        level, sl2, sl4 = _classify_level("SQL Database", "Total")
        self.assertEqual(level, LEVEL_SERVICE_TOTAL)
        self.assertEqual(sl2, "SQL Database")
        self.assertEqual(sl4, "Total")

    def test_leaf_with_explicit_sl4(self):
        level, sl2, sl4 = _classify_level(
            "Microsoft Defender for Cloud", "Microsoft Defender for SQL"
        )
        self.assertEqual(level, LEVEL_LEAF)
        self.assertEqual(sl4, "Microsoft Defender for SQL")

    def test_leaf_blank_sl4_falls_back_to_sl2(self):
        level, sl2, sl4 = _classify_level("Key Vault", None)
        self.assertEqual(level, LEVEL_LEAF)
        self.assertEqual(sl4, "Key Vault")

    def test_whitespace_is_stripped(self):
        level, sl2, sl4 = _classify_level("  SQL Database  ", "  Total  ")
        self.assertEqual(sl2, "SQL Database")
        self.assertEqual(sl4, "Total")


class CoerceFloatTests(unittest.TestCase):
    def test_none_is_zero(self):
        self.assertEqual(_coerce_float(None), 0.0)

    def test_nan_is_zero(self):
        self.assertEqual(_coerce_float(float("nan")), 0.0)

    def test_garbage_is_zero(self):
        self.assertEqual(_coerce_float("not-a-number"), 0.0)

    def test_numeric_string(self):
        self.assertEqual(_coerce_float("1234.5"), 1234.5)


class MonthColumnsTests(unittest.TestCase):
    def test_excludes_total_group_and_non_acr_measures(self):
        # Row 1 (groups) carry the label only on the first column of each group.
        top = [None, None, None, "FY26-Jul", None, "Total", None]
        bottom = [
            "TPAccountName",
            "ServiceLevel2",
            "ServiceLevel4",
            "$ ACR",
            "$ ACR MoM",
            "$ ACR",
            "$ ACR MoM",
        ]
        cols = _month_columns(top, bottom)
        # Only the FY26-Jul "$ ACR" column at index 3 should survive.
        self.assertEqual(cols, [("FY26-Jul", 3)])


class ReconciliationTests(unittest.TestCase):
    def _frame(self, rows):
        return pd.DataFrame.from_records(
            rows, columns=["customer", "sl2", "sl4", "level", "month", "acr"]
        )

    def test_clean_book_has_no_subtotal_issue(self):
        frame = self._frame(
            [
                ("C", "Total", "", LEVEL_CUSTOMER_TOTAL, "M1", 100.0),
                ("C", "SQL Database", "Total", LEVEL_SERVICE_TOTAL, "M1", 100.0),
                ("C", "SQL Database", "SQL Database", LEVEL_LEAF, "M1", 100.0),
            ]
        )
        issues = _reconcile(frame, ["M1"])
        # One info-level customer-total issue may exist but the leaf subtotal
        # must reconcile exactly (no >1% service issue).
        service_issues = [i for i in issues if i.scope.startswith("service_subtotal")]
        self.assertEqual(service_issues, [])

    def test_leaf_mismatch_is_flagged(self):
        frame = self._frame(
            [
                ("C", "SQL Database", "Total", LEVEL_SERVICE_TOTAL, "M1", 100.0),
                ("C", "SQL Database", "SQL Database", LEVEL_LEAF, "M1", 50.0),
            ]
        )
        issues = _reconcile(frame, ["M1"])
        service_issues = [i for i in issues if i.scope.startswith("service_subtotal")]
        self.assertEqual(len(service_issues), 1)
        self.assertGreater(service_issues[0].rel_diff, 0.01)


class ReconciliationIssueMathTests(unittest.TestCase):
    def test_rel_diff_uses_expected_base(self):
        issue = ReconciliationIssue("C", "scope", expected=200.0, actual=180.0)
        self.assertAlmostEqual(issue.abs_diff, 20.0)
        self.assertAlmostEqual(issue.rel_diff, 0.1)

    def test_rel_diff_guards_against_tiny_base(self):
        issue = ReconciliationIssue("C", "scope", expected=0.0, actual=5.0)
        # Base floors at 1.0 to avoid divide-by-zero blow-ups.
        self.assertAlmostEqual(issue.rel_diff, 5.0)


if __name__ == "__main__":
    unittest.main()
