import datetime
from zoneinfo import ZoneInfo

import pytest

import analysis


TZ = ZoneInfo("Europe/Berlin")
HOUR = 3600


def ts(year=2026, month=6, day=1, hour=0, minute=0):
    """Epoch second for a local Berlin wall-clock time."""
    return int(datetime.datetime(year, month, day, hour, minute, tzinfo=TZ).timestamp())


def full_coverage(start, end):
    return [(start, end)]


class TestHourSlices:
    def test_splits_at_hour_boundaries(self):
        start = ts(hour=1, minute=30)
        slices = list(analysis.hour_slices(start, start + 2 * HOUR, TZ))
        assert [s[2] for s in slices] == [1800, 3600, 1800]
        assert [s[1] for s in slices] == [1, 2, 3]

    def test_single_slice_inside_one_hour(self):
        start = ts(hour=4, minute=10)
        slices = list(analysis.hour_slices(start, start + 600, TZ))
        assert slices == [("2026-06-01", 4, 600)]


class TestDayBounds:
    def test_normal_day_is_24_hours(self):
        start, end = analysis.day_bounds("2026-06-01", TZ)
        assert end - start == 24 * HOUR

    def test_dst_spring_forward_day_is_23_hours(self):
        # Last Sunday in March 2026: clocks jump 02:00 -> 03:00 local.
        start, end = analysis.day_bounds("2026-03-29", TZ)
        assert end - start == 23 * HOUR

    def test_dst_fall_back_day_is_25_hours(self):
        start, end = analysis.day_bounds("2026-10-25", TZ)
        assert end - start == 25 * HOUR


class TestIntegrateBasal:
    def test_weights_rates_by_duration_not_by_event_count(self):
        """A rate held for 55 minutes must not count the same as one held for 5.

        Averaging the two event values would give 1.05 U/h; the correct
        time-weighted answer is 0.1 * (55/60) + 2.0 * (5/60).
        """
        start = ts(hour=0)
        events = [
            (start, 0.1, 0.1, 0),
            (start + 55 * 60, 2.0, 0.1, 0),
        ]
        buckets = analysis.integrate_basal(
            events, full_coverage(start, start + HOUR), start, start + HOUR, TZ
        )
        bucket = buckets[("2026-06-01", 0)]
        assert bucket["delivered_u"] == pytest.approx(0.1 * 55 / 60 + 2.0 * 5 / 60)
        assert bucket["covered_s"] == HOUR

    def test_carries_rate_across_an_hour_boundary(self):
        start = ts(hour=2)
        events = [(start, 0.8, 0.8, 0)]
        buckets = analysis.integrate_basal(
            events, full_coverage(start, start + 2 * HOUR), start, start + 2 * HOUR, TZ
        )
        assert buckets[("2026-06-01", 2)]["delivered_u"] == pytest.approx(0.8)
        assert buckets[("2026-06-01", 3)]["delivered_u"] == pytest.approx(0.8)

    def test_gap_beyond_max_carry_is_not_credited(self):
        """A silent pump must not read as an hour of zero insulin."""
        start = ts(hour=0)
        events = [(start, 1.0, 1.0, 0)]
        end = start + 10 * HOUR
        buckets = analysis.integrate_basal(
            events, full_coverage(start, end), start, end, TZ,
            max_carry_s=2 * HOUR,
        )
        assert set(buckets) == {("2026-06-01", 0), ("2026-06-01", 1)}
        assert ("2026-06-01", 5) not in buckets

    def test_hours_outside_coverage_are_ignored(self):
        """Even with an event in range, an unfetched window stays unknown."""
        start = ts(hour=0)
        end = start + 4 * HOUR
        events = [(start, 1.0, 1.0, 0)]
        buckets = analysis.integrate_basal(
            events, [(start, start + 2 * HOUR)], start, end, TZ
        )
        assert set(buckets) == {("2026-06-01", 0), ("2026-06-01", 1)}

    def test_suspend_is_a_real_zero_not_a_gap(self):
        """commanded = 0 during a suspend is measured, so the hour stays covered."""
        start = ts(hour=0)
        events = [(start, 0.0, 0.9, 16)]  # 16 = PumpSuspended
        buckets = analysis.integrate_basal(
            events, full_coverage(start, start + HOUR), start, start + HOUR, TZ
        )
        bucket = buckets[("2026-06-01", 0)]
        assert bucket["covered_s"] == HOUR
        assert bucket["delivered_u"] == 0.0
        assert bucket["profile_u"] == pytest.approx(0.9)

    def test_no_events_yields_nothing(self):
        start = ts(hour=0)
        assert analysis.integrate_basal(
            [], full_coverage(start, start + HOUR), start, start + HOUR, TZ
        ) == {}


def hourly_row(day, hour, delivered, profile, covered_s=3600, bolus_n=0,
               cgm_median=120, low_n=0, cgm_n=12):
    return {
        "day": day, "hour": hour,
        "cgm_n": cgm_n, "cgm_mean": cgm_median, "cgm_median": cgm_median,
        "cgm_min": cgm_median, "cgm_max": cgm_median,
        "in_range_n": cgm_n - low_n, "low_n": low_n, "high_n": 0,
        "basal_covered_s": covered_s,
        "basal_delivered_u": delivered, "basal_profile_u": profile,
        "bolus_n": bolus_n, "bolus_u": 0.0, "carbs_g": None,
    }


def days(n, start_day=1):
    return [f"2026-06-{start_day + i:02d}" for i in range(n)]


class TestCleanBasalHours:
    def test_bolus_two_hours_earlier_disqualifies_the_hour(self):
        rows = [
            hourly_row("2026-06-01", 1, 0.8, 0.8, bolus_n=1),
            hourly_row("2026-06-01", 2, 0.8, 0.8),
            hourly_row("2026-06-01", 3, 0.8, 0.8),
        ]
        clean = analysis.clean_basal_hours(rows, insulin_duration_min=180)
        assert clean == []

    def test_bolus_four_hours_earlier_leaves_the_hour_usable(self):
        rows = [hourly_row("2026-06-01", 0, 0.8, 0.8, bolus_n=1)]
        rows += [hourly_row("2026-06-01", h, 0.8, 0.8) for h in range(1, 6)]
        clean = analysis.clean_basal_hours(rows, insulin_duration_min=180)
        assert [r["hour"] for r in clean] == [4, 5]

    def test_missing_lookback_hour_counts_as_contaminated(self):
        """Not knowing whether a bolus happened is not the same as knowing none did."""
        rows = [hourly_row("2026-06-01", 5, 0.8, 0.8)]
        assert analysis.clean_basal_hours(rows, insulin_duration_min=180) == []

    def test_incomplete_basal_coverage_is_dropped(self):
        rows = [hourly_row("2026-06-01", h, 0.8, 0.8) for h in range(0, 5)]
        rows[4]["basal_covered_s"] = 1200
        clean = analysis.clean_basal_hours(rows, insulin_duration_min=180)
        assert 4 not in [r["hour"] for r in clean]


class TestBasalByHourOfDay:
    def _rows(self, delivered_per_day, profile=0.80, hour=3):
        """One clean hour per day, with the three preceding hours present and
        bolus-free so the look-back filter is satisfied."""
        rows = []
        for index, delivered in enumerate(delivered_per_day):
            day = f"2026-06-{index + 1:02d}"
            for back in range(hour - 3, hour):
                rows.append(hourly_row(day, back, profile, profile))
            rows.append(hourly_row(day, hour, delivered, profile))
        return rows

    def test_flags_a_consistent_upward_deviation(self):
        rows = self._rows([1.05] * 10)          # +31% every day
        result = analysis.basal_by_hour_of_day(rows, 180)
        hour = result[3]
        assert hour["n_days"] == 10
        assert hour["ratio"] == pytest.approx(1.3125)
        assert hour["share_above"] == 1.0
        assert hour["flag"] == "above"

    def test_flags_a_consistent_downward_deviation(self):
        rows = self._rows([0.50] * 10)          # -37% every day
        assert analysis.basal_by_hour_of_day(rows, 180)[3]["flag"] == "below"

    def test_too_few_days_is_never_flagged(self):
        rows = self._rows([1.05] * 6)
        result = analysis.basal_by_hour_of_day(rows, 180)[3]
        assert result["n_days"] == 6
        assert result["flag"] is None

    def test_one_wild_night_does_not_flag_the_hour(self):
        """The sign test is what stops a single outlier from carrying the median."""
        rows = self._rows([0.80] * 9 + [8.0])
        result = analysis.basal_by_hour_of_day(rows, 180)[3]
        assert result["share_above"] == pytest.approx(0.1)
        assert result["flag"] is None

    def test_deviation_without_agreement_is_not_flagged(self):
        # Half the days far above, half far below: the median deviates, but the
        # direction does not.
        rows = self._rows([1.60] * 5 + [0.30] * 5)
        assert analysis.basal_by_hour_of_day(rows, 180)[3]["flag"] is None

    def test_zero_profile_rate_reports_absolute_difference(self):
        rows = self._rows([0.35] * 10, profile=0.0)
        hour = analysis.basal_by_hour_of_day(rows, 180)[3]
        assert hour["ratio"] is None
        assert hour["diff_u"] == pytest.approx(0.35)
        assert hour["flag"] == "above"

    def test_matching_delivery_is_not_flagged(self):
        rows = self._rows([0.80] * 14)
        assert analysis.basal_by_hour_of_day(rows, 180)[3]["flag"] is None

    def test_reports_all_24_hours_even_without_data(self):
        result = analysis.basal_by_hour_of_day([], 180)
        assert [h["hour"] for h in result] == list(range(24))
        assert all(h["n_days"] == 0 for h in result)


class TestRollupRows:
    def test_combines_cgm_basal_and_bolus_into_hourly_rows(self):
        start = ts(hour=0)
        cgm = [(start + 300 * i, 100 + i) for i in range(12)]  # one hour of readings
        basal = [(start, 0.9, 0.9, 0)]
        bolus = [(start + 1800, 3.5, 40, 145, 0.2)]
        rows = analysis.rollup_rows(
            ["2026-06-01"], TZ, cgm, basal, bolus,
            full_coverage(start, start + 24 * HOUR),
            target_low=70, target_high=180,
        )
        first = next(r for r in rows if r["hour"] == 0)
        assert first["cgm_n"] == 12
        assert first["cgm_median"] == pytest.approx(105.5)
        assert first["in_range_n"] == 12
        assert first["basal_delivered_u"] == pytest.approx(0.9)
        assert first["bolus_n"] == 1
        assert first["bolus_u"] == pytest.approx(3.5)
        assert first["carbs_g"] == 40

    def test_counts_lows_and_highs_against_the_target_range(self):
        start = ts(hour=8)
        cgm = [(start, 55), (start + 300, 120), (start + 600, 250)]
        rows = analysis.rollup_rows(
            ["2026-06-01"], TZ, cgm, [], [], [], target_low=70, target_high=180
        )
        row = next(r for r in rows if r["hour"] == 8)
        assert (row["low_n"], row["in_range_n"], row["high_n"]) == (1, 1, 1)


class TestSupportingViews:
    def test_tir_summary_weights_by_reading_count(self):
        rows = [
            hourly_row("2026-06-01", 0, 0.8, 0.8, cgm_median=100, cgm_n=10),
            hourly_row("2026-06-01", 1, 0.8, 0.8, cgm_median=200, cgm_n=30),
        ]
        summary = analysis.tir_summary(rows)["overall"]
        assert summary["n"] == 40
        assert summary["avg"] == 175  # not 150

    def test_tdd_skips_days_without_full_coverage(self):
        full = [hourly_row("2026-06-01", h, 0.5, 0.5) for h in range(24)]
        partial = [hourly_row("2026-06-02", h, 0.5, 0.5) for h in range(6)]
        result = analysis.tdd_by_day(full + partial)
        assert [d["day"] for d in result] == ["2026-06-01"]
        assert result[0]["basal_u"] == pytest.approx(12.0)

    def test_agp_returns_percentiles_per_bucket(self):
        start = ts(hour=0)
        cgm = [(start + i * 86400, 100 + i * 10) for i in range(5)]
        rows = analysis.agp(cgm, TZ, bucket_minutes=30)
        assert len(rows) == 1
        assert rows[0]["p50"] == pytest.approx(120)
        assert rows[0]["n"] == 5

    def test_hypo_by_hour_reports_share_below_target(self):
        rows = [hourly_row("2026-06-01", 3, 0.8, 0.8, cgm_n=10, low_n=2)]
        result = analysis.hypo_by_hour(rows)
        assert result[3]["low_pct"] == pytest.approx(20.0)
        assert result[4]["low_pct"] is None


class TestPercentile:
    def test_interpolates_between_ranks(self):
        assert analysis.percentile([0, 10], 50) == pytest.approx(5)
        assert analysis.percentile([0, 10, 20, 30], 25) == pytest.approx(7.5)

    def test_handles_short_input(self):
        assert analysis.percentile([], 50) is None
        assert analysis.percentile([7], 90) == 7.0
