import pytest

import db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "test.db"))
    yield connection
    connection.close()


class TestInserts:
    def test_cgm_inserts_are_idempotent(self):
        """Overlapping collector runs re-fetch the same 24h window every three
        hours; a repeat must add nothing."""
        connection = db.connect(":memory:")
        rows = [(1000, 120), (1300, 125)]
        assert db.insert_cgm(connection, rows) == 2
        assert db.insert_cgm(connection, rows) == 0
        assert len(db.fetch_cgm(connection, 0, 9999)) == 2

    def test_basal_inserts_are_idempotent(self, conn):
        rows = [(1000, 0.8, 0.9, 0)]
        assert db.insert_basal(conn, rows) == 1
        assert db.insert_basal(conn, rows) == 0

    def test_bolus_backfills_missing_fields_without_erasing_known_ones(self, conn):
        """A later run may carry the carb count the first one lacked, but must
        never overwrite a stored value with NULL."""
        db.insert_bolus(conn, [(1000, 3.5, None, None, 0.4)])
        db.insert_bolus(conn, [(1000, 3.5, 40, 145, None)])
        ts, units, carbs, bg, iob = db.fetch_bolus(conn, 0, 9999)[0]
        assert (units, carbs, bg, iob) == (3.5, 40, 145, 0.4)

    def test_fetch_respects_the_half_open_window(self, conn):
        db.insert_cgm(conn, [(100, 1), (200, 2), (300, 3)])
        assert [v for _ts, v in db.fetch_cgm(conn, 100, 300)] == [1, 2]


class TestCoverage:
    def test_overlapping_windows_are_merged(self, conn):
        db.record_coverage(conn, 0, 1000)
        db.record_coverage(conn, 900, 2000)
        assert db.fetch_coverage(conn, 0, 5000) == [(0, 2000)]

    def test_distant_windows_stay_separate(self, conn):
        db.record_coverage(conn, 0, 1000)
        db.record_coverage(conn, 50000, 60000)
        assert len(db.fetch_coverage(conn, 0, 99999)) == 2

    def test_fetch_clips_to_the_requested_range(self, conn):
        db.record_coverage(conn, 0, 10000)
        assert db.fetch_coverage(conn, 2000, 3000) == [(2000, 3000)]

    def test_merge_windows_is_pure(self):
        assert db.merge_windows([(0, 5), (10, 15), (4, 11)]) == [(0, 15)]


class TestHourly:
    def _row(self, day="2026-06-01", hour=0, **overrides):
        row = {
            "day": day, "hour": hour, "cgm_n": 12, "cgm_mean": 120.0,
            "cgm_median": 118.0, "cgm_min": 100, "cgm_max": 140,
            "in_range_n": 12, "low_n": 0, "high_n": 0,
            "basal_covered_s": 3600, "basal_delivered_u": 0.9,
            "basal_profile_u": 0.8, "bolus_n": 0, "bolus_u": 0.0,
            "carbs_g": None,
        }
        row.update(overrides)
        return row

    def test_upsert_replaces_an_existing_hour(self, conn):
        """Rollups are recomputed for the last few days because the pump uploads
        late; the second write must replace, not duplicate."""
        db.upsert_hourly(conn, [self._row()])
        db.upsert_hourly(conn, [self._row(basal_delivered_u=1.4)])
        rows = db.fetch_hourly(conn, "2026-06-01", "2026-06-01")
        assert len(rows) == 1
        assert rows[0]["basal_delivered_u"] == 1.4

    def test_fetch_hourly_is_inclusive_on_both_days(self, conn):
        db.upsert_hourly(conn, [
            self._row(day="2026-05-31"), self._row(day="2026-06-01"),
            self._row(day="2026-06-02"),
        ])
        rows = db.fetch_hourly(conn, "2026-05-31", "2026-06-02")
        assert len(rows) == 3


class TestPurge:
    def test_purge_drops_raw_rows_but_keeps_the_aggregate(self, conn):
        """The size trade: fine-grained history for a few months, hourly
        history forever."""
        db.insert_cgm(conn, [(100, 120), (100000, 130)])
        db.upsert_hourly(conn, [TestHourly()._row()])
        db.purge_raw(conn, before_ts=50000)

        assert [v for _ts, v in db.fetch_cgm(conn, 0, 999999)] == [130]
        assert len(db.fetch_hourly(conn, "2026-06-01", "2026-06-01")) == 1

    def test_purge_trims_coverage_windows(self, conn):
        db.record_coverage(conn, 0, 100000)
        db.record_coverage(conn, 200, 300)
        db.purge_raw(conn, before_ts=50000)
        windows = db.fetch_coverage(conn, 0, 999999)
        assert windows == [(50000, 100000)]

    def test_purge_removes_windows_entirely_before_the_cutoff(self, conn):
        db.record_coverage(conn, 0, 1000)
        db.purge_raw(conn, before_ts=50000)
        assert db.fetch_coverage(conn, 0, 999999) == []


class TestMeta:
    def test_roundtrips_values_as_strings(self, conn):
        db.set_meta(conn, "insulin_duration_min", 180)
        assert db.get_meta(conn, "insulin_duration_min") == "180"
        assert db.get_meta(conn, "missing", "fallback") == "fallback"


class TestCounts:
    def test_reports_rows_and_span_per_table(self, conn):
        db.insert_cgm(conn, [(100, 120), (500, 130)])
        counts = db.counts(conn)
        assert counts["cgm"] == {"n": 2, "first": 100, "last": 500}
        assert counts["basal"]["n"] == 0
