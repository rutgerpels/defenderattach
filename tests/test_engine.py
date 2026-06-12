"""Unit tests for the attach-gap scoring engine.

These build small synthetic ``ParsedData`` books (no Excel I/O) so the gap
math, signal classification, momentum, and scoring bounds are pinned exactly.

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

from defender_acr_dashboard.service_attach.mapping import (  # noqa: E402
    DEFENDER_SL2,
    TOTAL_TOKEN,
    AttachConfig,
)
from defender_acr_dashboard.service_attach import export  # noqa: E402
from defender_acr_dashboard.service_attach.parser import (  # noqa: E402
    LEVEL_CUSTOMER_TOTAL,
    LEVEL_LEAF,
    LEVEL_SERVICE_TOTAL,
    ParsedData,
)
from defender_acr_dashboard.service_attach.engine import (  # noqa: E402
    SIGNAL_ATTACH,
    SIGNAL_EXPAND,
    STORY_DEFENDER_REGRESSION,
    STORY_GROWTH_DIVERGENCE,
    STORY_NEW_WORKLOAD_NO_DEFENDER,
    _percentile_scores,
    _rolling_growth,
    build_model,
)

MONTHS = ["M1", "M2", "M3", "M4", "M5", "M6"]


def _const(value):
    return [value] * len(MONTHS)


class _Book:
    """Tiny builder for a tidy SL2/SL4 frame matching the parser schema."""

    def __init__(self):
        self._rows = []

    def add(self, customer, sl2, sl4, level, series):
        for month, acr in zip(MONTHS, series):
            self._rows.append((customer, sl2, sl4, level, month, float(acr)))
        return self

    def workload(self, customer, sl2, series):
        return self.add(customer, sl2, TOTAL_TOKEN, LEVEL_SERVICE_TOTAL, series)

    def defender_plan(self, customer, sl4, series):
        # DfC service subtotal is required for dossier dfc_acr; add the leaf too.
        return self.add(customer, DEFENDER_SL2, sl4, LEVEL_LEAF, series)

    def dfc_total(self, customer, series):
        return self.add(
            customer, DEFENDER_SL2, TOTAL_TOKEN, LEVEL_SERVICE_TOTAL, series
        )

    def customer_total(self, customer, series):
        return self.add(customer, TOTAL_TOKEN, "", LEVEL_CUSTOMER_TOTAL, series)

    def parsed(self):
        frame = pd.DataFrame.from_records(
            self._rows,
            columns=["customer", "sl2", "sl4", "level", "month", "acr"],
        )
        customers = sorted(frame["customer"].unique().tolist())
        return ParsedData(
            frame=frame,
            months=list(MONTHS),
            customers=customers,
            reconciliation=[],
            source_name="synthetic",
            row_count=len(self._rows),
        )


def _find_opp(dossier, plan_label):
    for opp in dossier.opportunities:
        if opp.plan_label == plan_label:
            return opp
    return None


def _find_story(dossier, story_type):
    for story in dossier.divergence_stories:
        if story.story_type == story_type:
            return story
    return None


# Disable cohort medians so benchmarks are the deterministic flat target_ratio.
CFG = AttachConfig(use_cohort_median=False, target_ratio=0.06)


class GapMathTests(unittest.TestCase):
    def test_attach_signal_with_full_dollar_gap(self):
        book = (
            _Book()
            .customer_total("AttachCo", _const(10_000))
            .workload("AttachCo", "SQL Database", _const(10_000))
            .dfc_total("AttachCo", _const(0))
            .defender_plan("AttachCo", "Microsoft Defender for SQL", _const(0))
            .parsed()
        )
        model = build_model(book, CFG)
        dossier = model.dossiers[0]
        opp = _find_opp(dossier, "Defender for SQL")
        self.assertIsNotNone(opp)
        self.assertEqual(opp.signal, SIGNAL_ATTACH)
        # expected = 10000 * 0.06 = 600; actual 0 -> gap 600.
        self.assertAlmostEqual(opp.expected, 600.0)
        self.assertAlmostEqual(opp.gap_dollars, 600.0)
        self.assertTrue(opp.has_dollar_gap)

    def test_expand_signal_when_below_benchmark(self):
        book = (
            _Book()
            .customer_total("ExpandCo", _const(10_000))
            .workload("ExpandCo", "SQL Database", _const(10_000))
            .dfc_total("ExpandCo", _const(200))
            .defender_plan("ExpandCo", "Microsoft Defender for SQL", _const(200))
            .parsed()
        )
        model = build_model(book, CFG)
        opp = _find_opp(model.dossiers[0], "Defender for SQL")
        self.assertIsNotNone(opp)
        self.assertEqual(opp.signal, SIGNAL_EXPAND)
        # gap = max(0, 600 - 200) = 400.
        self.assertAlmostEqual(opp.gap_dollars, 400.0)

    def test_covered_plan_yields_no_opportunity(self):
        book = (
            _Book()
            .customer_total("CoveredCo", _const(10_000))
            .workload("CoveredCo", "SQL Database", _const(10_000))
            .dfc_total("CoveredCo", _const(700))
            .defender_plan("CoveredCo", "Microsoft Defender for SQL", _const(700))
            .parsed()
        )
        model = build_model(book, CFG)
        self.assertIsNone(_find_opp(model.dossiers[0], "Defender for SQL"))

    def test_no_opportunity_when_workload_absent(self):
        book = (
            _Book()
            .customer_total("EmptyCo", _const(10_000))
            .workload("EmptyCo", "SQL Database", _const(0))
            .dfc_total("EmptyCo", _const(0))
            .parsed()
        )
        model = build_model(book, CFG)
        self.assertEqual(model.dossiers[0].opportunities, [])

    def test_unit_priced_plan_benchmarks_from_target_ratio(self):
        # Defender for Servers is unit-priced but now gap-eligible: it benchmarks
        # the VM workload against the flat target_ratio (cohort median disabled
        # in CFG), so a fully-unattached VM footprint surfaces a dollar gap.
        book = (
            _Book()
            .customer_total("VmCo", _const(50_000))
            .workload("VmCo", "Virtual Machines", _const(50_000))
            .dfc_total("VmCo", _const(0))
            .defender_plan("VmCo", "Microsoft Defender for Servers", _const(0))
            .parsed()
        )
        model = build_model(book, CFG)
        opp = _find_opp(model.dossiers[0], "Defender for Servers")
        self.assertIsNotNone(opp)
        self.assertTrue(opp.eligible_for_gap)
        self.assertTrue(opp.has_dollar_gap)
        self.assertAlmostEqual(opp.benchmark_ratio, 0.06)
        # expected = 50000 * 0.06 = 3000; actual 0 -> gap 3000; sized by the gap.
        self.assertAlmostEqual(opp.expected, 3_000.0)
        self.assertAlmostEqual(opp.gap_dollars, 3_000.0)
        self.assertAlmostEqual(opp.size_value, 3_000.0)
        self.assertEqual(opp.signal, SIGNAL_ATTACH)

    def test_small_workload_suppresses_dollar_gap(self):
        # expected = 1000 * 0.06 = 60 < min_denominator(100) -> no $ benchmark,
        # but the plan is unattached so it still surfaces as a coverage signal.
        book = (
            _Book()
            .customer_total("TinyCo", _const(1_000))
            .workload("TinyCo", "SQL Database", _const(1_000))
            .dfc_total("TinyCo", _const(0))
            .defender_plan("TinyCo", "Microsoft Defender for SQL", _const(0))
            .parsed()
        )
        model = build_model(book, CFG)
        opp = _find_opp(model.dossiers[0], "Defender for SQL")
        self.assertIsNotNone(opp)
        self.assertFalse(opp.has_dollar_gap)
        self.assertEqual(opp.gap_dollars, 0.0)


class AttachRatioTests(unittest.TestCase):
    def test_attach_ratio_uses_eligible_denominator(self):
        book = (
            _Book()
            .customer_total("RatioCo", _const(20_000))
            .workload("RatioCo", "SQL Database", _const(10_000))
            .dfc_total("RatioCo", _const(500))
            .defender_plan("RatioCo", "Microsoft Defender for SQL", _const(500))
            .parsed()
        )
        model = build_model(book, CFG)
        dossier = model.dossiers[0]
        # dfc 500 / eligible workload 10000 = 0.05.
        self.assertAlmostEqual(dossier.eligible_workload_acr, 10_000.0)
        self.assertAlmostEqual(dossier.dfc_acr, 500.0)
        self.assertAlmostEqual(dossier.attach_ratio, 0.05)


class RollingGrowthTests(unittest.TestCase):
    def test_zero_base_growth_returns_cap(self):
        growth, grew = _rolling_growth([0, 0, 0, 10, 20, 30], window=3, cap=1.0)
        self.assertEqual(growth, 1.0)
        self.assertTrue(grew)

    def test_flat_series_zero_growth(self):
        growth, grew = _rolling_growth([100] * 6, window=3, cap=1.0)
        self.assertEqual(growth, 0.0)
        self.assertFalse(grew)

    def test_growth_is_clipped_to_cap(self):
        growth, _ = _rolling_growth([10, 10, 10, 100, 100, 100], window=3, cap=1.0)
        self.assertEqual(growth, 1.0)

    def test_decline_is_negative(self):
        growth, grew = _rolling_growth([100, 100, 100, 80, 80, 80], window=3, cap=1.0)
        self.assertAlmostEqual(growth, -0.2)
        self.assertFalse(grew)

    def test_empty_series_is_safe(self):
        self.assertEqual(_rolling_growth([], window=3, cap=1.0), (0.0, False))


class PercentileScoreTests(unittest.TestCase):
    def test_scores_within_bounds(self):
        scores = _percentile_scores([1.0, 5.0, 9.0, 100.0])
        self.assertTrue(all(0.0 <= s <= 100.0 for s in scores))
        # Largest value gets the top percentile.
        self.assertEqual(max(scores), 100.0)

    def test_single_value_scores_100(self):
        self.assertEqual(_percentile_scores([42.0]), [100.0])

    def test_all_equal_scores_midpoint(self):
        self.assertEqual(_percentile_scores([7.0, 7.0, 7.0]), [50.0, 50.0, 50.0])

    def test_empty_returns_empty(self):
        self.assertEqual(_percentile_scores([]), [])


class ScoringBoundsTests(unittest.TestCase):
    def test_opportunity_scores_bounded(self):
        book = (
            _Book()
            .customer_total("A", _const(10_000))
            .workload("A", "SQL Database", _const(10_000))
            .dfc_total("A", _const(0))
            .defender_plan("A", "Microsoft Defender for SQL", _const(0))
            .customer_total("B", _const(40_000))
            .workload("B", "Azure App Service", _const(40_000))
            .dfc_total("B", _const(0))
            .defender_plan("B", "Microsoft Defender for App Service", _const(0))
            .parsed()
        )
        model = build_model(book, CFG)
        for dossier in model.dossiers:
            for opp in dossier.opportunities:
                self.assertGreaterEqual(opp.gap_score, 0.0)
                self.assertLessEqual(opp.gap_score, 100.0)
                self.assertGreaterEqual(opp.blended_score, 0.0)
                self.assertLessEqual(opp.blended_score, 100.0)


class DivergenceStoryTests(unittest.TestCase):
    def test_growth_divergence_story_for_workload_outpacing_defender(self):
        book = (
            _Book()
            .customer_total("DivergeCo", [10_000, 10_000, 10_000, 20_000, 20_000, 20_000])
            .workload("DivergeCo", "SQL Database", [10_000, 10_000, 10_000, 20_000, 20_000, 20_000])
            .dfc_total("DivergeCo", _const(100))
            .defender_plan("DivergeCo", "Microsoft Defender for SQL", _const(100))
            .parsed()
        )
        model = build_model(book, CFG)
        dossier = model.dossiers[0]
        story = _find_story(dossier, STORY_GROWTH_DIVERGENCE)

        self.assertIsNotNone(story)
        self.assertEqual(story.customer, "DivergeCo")
        self.assertEqual(story.plan_label, "Defender for SQL")
        self.assertEqual(story.severity, "High")
        self.assertEqual(story.workload_sl2_categories, ["SQL Database"])
        self.assertEqual(story.compared_months, MONTHS)
        self.assertAlmostEqual(story.workload_start_value, 10_000.0)
        self.assertAlmostEqual(story.workload_end_value, 20_000.0)
        self.assertAlmostEqual(story.defender_start_value, 100.0)
        self.assertAlmostEqual(story.defender_end_value, 100.0)
        self.assertAlmostEqual(story.workload_pct_change, 1.0)
        self.assertIn("Directional signal", story.caveat_text)
        self.assertEqual(model.divergence_stories[0], story)

    def test_defender_regression_story_when_defender_declines(self):
        book = (
            _Book()
            .customer_total("RegressCo", _const(10_000))
            .workload("RegressCo", "SQL Database", _const(10_000))
            .dfc_total("RegressCo", [300, 300, 300, 200, 200, 200])
            .defender_plan(
                "RegressCo",
                "Microsoft Defender for SQL",
                [300, 300, 300, 200, 200, 200],
            )
            .parsed()
        )
        model = build_model(book, CFG)
        story = _find_story(model.dossiers[0], STORY_DEFENDER_REGRESSION)

        self.assertIsNotNone(story)
        self.assertEqual(story.severity, "High")
        self.assertLess(story.defender_delta, 0)
        self.assertAlmostEqual(story.defender_pct_change, -1 / 3)
        self.assertIn("declining", story.headline)

    def test_covered_plan_can_still_emit_defender_regression_story(self):
        book = (
            _Book()
            .customer_total("CoveredRegressionCo", [11_000, 11_000, 11_000, 11_650, 11_650, 11_650])
            .workload("CoveredRegressionCo", "SQL Database", [10_000, 10_000, 10_000, 10_650, 10_650, 10_650])
            .dfc_total("CoveredRegressionCo", [1_000, 1_000, 1_000, 834, 834, 834])
            .defender_plan(
                "CoveredRegressionCo",
                "Microsoft Defender for SQL",
                [1_000, 1_000, 1_000, 834, 834, 834],
            )
            .parsed()
        )
        model = build_model(book, CFG)
        dossier = model.dossiers[0]
        story = _find_story(dossier, STORY_DEFENDER_REGRESSION)

        self.assertIsNone(_find_opp(dossier, "Defender for SQL"))
        self.assertIsNotNone(story)
        self.assertEqual(story.severity, "Medium")
        self.assertAlmostEqual(story.workload_pct_change, 0.065)
        self.assertAlmostEqual(story.defender_pct_change, -0.166)
        self.assertTrue(story.has_dollar_gap)
        self.assertEqual(story.gap_dollars, 0.0)

    def test_covered_plan_with_healthy_defender_tracking_suppresses_story(self):
        book = (
            _Book()
            .customer_total("CoveredHealthyCo", [11_000, 11_000, 11_000, 11_650, 11_650, 11_650])
            .workload("CoveredHealthyCo", "SQL Database", [10_000, 10_000, 10_000, 10_650, 10_650, 10_650])
            .dfc_total("CoveredHealthyCo", [1_000, 1_000, 1_000, 1_065, 1_065, 1_065])
            .defender_plan(
                "CoveredHealthyCo",
                "Microsoft Defender for SQL",
                [1_000, 1_000, 1_000, 1_065, 1_065, 1_065],
            )
            .parsed()
        )
        model = build_model(book, CFG)
        dossier = model.dossiers[0]

        self.assertIsNone(_find_opp(dossier, "Defender for SQL"))
        self.assertEqual(dossier.divergence_stories, [])

    def test_new_workload_no_defender_story(self):
        book = (
            _Book()
            .customer_total("NewCo", [0, 0, 0, 2_000, 2_000, 2_000])
            .workload("NewCo", "SQL Database", [0, 0, 0, 2_000, 2_000, 2_000])
            .dfc_total("NewCo", _const(0))
            .defender_plan("NewCo", "Microsoft Defender for SQL", _const(0))
            .parsed()
        )
        model = build_model(book, CFG)
        story = _find_story(model.dossiers[0], STORY_NEW_WORKLOAD_NO_DEFENDER)

        self.assertIsNotNone(story)
        self.assertEqual(story.severity, "High")
        self.assertIsNone(story.workload_pct_change)
        self.assertEqual(story.latest_defender_acr, 0.0)
        self.assertIn("new", story.headline)

    def test_tracking_defender_growth_suppresses_story(self):
        book = (
            _Book()
            .customer_total("TrackCo", [10_100, 10_100, 10_100, 12_120, 12_120, 12_120])
            .workload("TrackCo", "SQL Database", [10_000, 10_000, 10_000, 12_000, 12_000, 12_000])
            .dfc_total("TrackCo", [100, 100, 100, 120, 120, 120])
            .defender_plan("TrackCo", "Microsoft Defender for SQL", [100, 100, 100, 120, 120, 120])
            .parsed()
        )
        model = build_model(book, CFG)

        self.assertEqual(model.dossiers[0].divergence_stories, [])
        self.assertEqual(model.divergence_stories, [])

    def test_low_workload_suppresses_story(self):
        book = (
            _Book()
            .customer_total("SmallCo", [100, 100, 100, 500, 500, 500])
            .workload("SmallCo", "SQL Database", [100, 100, 100, 500, 500, 500])
            .dfc_total("SmallCo", _const(0))
            .defender_plan("SmallCo", "Microsoft Defender for SQL", _const(0))
            .parsed()
        )
        model = build_model(book, CFG)

        self.assertEqual(model.dossiers[0].divergence_stories, [])

    def test_flat_defender_without_material_lag_suppresses_story(self):
        book = (
            _Book()
            .customer_total("MarginalCo", [10_100, 10_100, 10_100, 11_100, 11_100, 11_100])
            .workload("MarginalCo", "SQL Database", [10_000, 10_000, 10_000, 11_000, 11_000, 11_000])
            .dfc_total("MarginalCo", _const(100))
            .defender_plan("MarginalCo", "Microsoft Defender for SQL", _const(100))
            .parsed()
        )
        model = build_model(book, CFG)

        self.assertEqual(model.dossiers[0].divergence_stories, [])

    def test_tiny_prior_baseline_with_existing_defender_suppresses_growth_story(self):
        book = (
            _Book()
            .customer_total("TinyBaseCo", [50, 50, 50, 2_050, 2_050, 2_050])
            .workload("TinyBaseCo", "SQL Database", [0, 0, 0, 2_000, 2_000, 2_000])
            .dfc_total("TinyBaseCo", _const(50))
            .defender_plan("TinyBaseCo", "Microsoft Defender for SQL", _const(50))
            .parsed()
        )
        model = build_model(book, CFG)

        self.assertEqual(model.dossiers[0].divergence_stories, [])

    def test_export_includes_divergence_stories(self):
        book = (
            _Book()
            .customer_total("ExportCo", [10_000, 10_000, 10_000, 20_000, 20_000, 20_000])
            .workload("ExportCo", "SQL Database", [10_000, 10_000, 10_000, 20_000, 20_000, 20_000])
            .dfc_total("ExportCo", _const(100))
            .defender_plan("ExportCo", "Microsoft Defender for SQL", _const(100))
            .parsed()
        )
        payload = export.build_json(build_model(book, CFG))

        self.assertEqual(payload["meta"]["divergence_story_count"], 1)
        self.assertEqual(len(payload["divergence_stories"]), 1)
        book_story = payload["divergence_stories"][0]
        customer_story = payload["customers"][0]["divergence_stories"][0]
        self.assertEqual(book_story, customer_story)
        required_fields = {
            "customer",
            "plan_label",
            "workload_sl2_categories",
            "workload_categories",
            "story_type",
            "severity",
            "confidence",
            "pricing_driver",
            "latest_workload_acr",
            "latest_defender_acr",
            "compared_months",
            "workload_start_value",
            "workload_end_value",
            "defender_start_value",
            "defender_end_value",
            "workload_delta",
            "defender_delta",
            "workload_pct_change",
            "defender_pct_change",
            "momentum_spread",
            "has_dollar_gap",
            "gap_dollars",
            "headline",
            "evidence_bullets",
            "recommended_action",
            "caveat",
            "caveat_text",
        }
        self.assertTrue(required_fields.issubset(customer_story))
        self.assertEqual(customer_story["customer"], "ExportCo")
        self.assertEqual(customer_story["story_type"], STORY_GROWTH_DIVERGENCE)
        self.assertEqual(customer_story["workload_sl2_categories"], ["SQL Database"])
        self.assertEqual(customer_story["workload_categories"], ["SQL Database"])
        self.assertEqual(customer_story["compared_months"], MONTHS)
        self.assertAlmostEqual(customer_story["workload_pct_change"], 1.0)
        self.assertAlmostEqual(customer_story["defender_pct_change"], 0.0)
        self.assertGreater(customer_story["momentum_spread"], 0)
        self.assertTrue(customer_story["evidence_bullets"])
        self.assertIn("Directional signal", customer_story["caveat"])
        self.assertEqual(customer_story["caveat"], customer_story["caveat_text"])


if __name__ == "__main__":
    unittest.main()
