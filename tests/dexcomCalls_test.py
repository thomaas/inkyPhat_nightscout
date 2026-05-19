import os
import unittest

import pytest

import dexcomCalls


def _has_real_credentials():
    from config import dexcom_username, dexcom_password
    placeholders = ("YOUR_DEXCOM_USERNAME", "your UserName", "")
    return (
        dexcom_username not in placeholders
        and dexcom_password not in placeholders
        and os.environ.get("SKIP_INTEGRATION_TESTS") != "1"
    )


class TimeInRangeStatsTest(unittest.TestCase):
    def test_empty_history_returns_none(self):
        self.assertIsNone(dexcomCalls.timeInRangeStats([], 70, 180))

    def test_all_in_range(self):
        history = [{"value": v, "timestamp": None} for v in [80, 100, 150, 170, 180]]
        stats = dexcomCalls.timeInRangeStats(history, 70, 180)
        self.assertEqual(stats["tir_pct"], 100)
        self.assertEqual(stats["low_pct"], 0)
        self.assertEqual(stats["high_pct"], 0)
        self.assertEqual(stats["count"], 5)
        self.assertEqual(stats["avg"], 136)

    def test_mixed_history(self):
        # 7 in-range, 2 low, 1 high → 70% / 20% / 10%
        values = [120, 130, 140, 150, 100, 80, 170, 60, 60, 200]
        history = [{"value": v, "timestamp": None} for v in values]
        stats = dexcomCalls.timeInRangeStats(history, 70, 180)
        self.assertEqual(stats["tir_pct"], 70)
        self.assertEqual(stats["low_pct"], 20)
        self.assertEqual(stats["high_pct"], 10)
        self.assertEqual(stats["count"], 10)

    def test_boundary_inclusivity(self):
        # Exactly at target_low and target_high should be in range
        history = [{"value": v, "timestamp": None} for v in [70, 180]]
        stats = dexcomCalls.timeInRangeStats(history, 70, 180)
        self.assertEqual(stats["tir_pct"], 100)

    def test_average_rounded(self):
        history = [{"value": v, "timestamp": None} for v in [100, 101, 102]]
        stats = dexcomCalls.timeInRangeStats(history, 70, 180)
        self.assertEqual(stats["avg"], 101)


@pytest.mark.integration
@pytest.mark.skipif(
    not _has_real_credentials(),
    reason="No real Dexcom credentials in config.py — set them and unset "
           "SKIP_INTEGRATION_TESTS to run these.",
)
class IntegrationTests(unittest.TestCase):
    def test_getDataFromDexcom_minimal(self):
        dexcomCalls.checkDataBeforeRefresh = False
        dexcomCalls.nightscoutDataPoints = 1
        data = dexcomCalls.getDataFromNightscout()
        self.assertIn("current_glucose", data)
        self.assertIn("glucose_history", data)
        self.assertEqual(len(data["glucose_history"]), 1)
        self.assertIsNotNone(data["current_glucose"]["value"])
        self.assertIsNotNone(data["current_glucose"]["trend"])

    def test_getDataFromDexcom_window(self):
        dexcomCalls.checkDataBeforeRefresh = False
        dexcomCalls.nightscoutDataPoints = 10
        data = dexcomCalls.getDataFromNightscout()
        self.assertEqual(len(data["glucose_history"]), 10)
        self.assertIsNotNone(data["current_glucose"]["delta"])
