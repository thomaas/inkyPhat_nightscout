import datetime
import os

import pytest

import analysis
import db
import report
import reportCharts


TODAY = datetime.date(2026, 9, 7)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "report.db"))
    yield connection
    connection.close()


def _seed(connection, days=14, hour_delivered=1.05, hour_profile=0.80):
    rows = []
    for offset in range(days):
        day = (TODAY - datetime.timedelta(days=offset)).isoformat()
        for hour in range(24):
            delivered = hour_delivered if hour == 3 else hour_profile
            rows.append({
                "day": day, "hour": hour,
                "cgm_n": 12, "cgm_mean": 130.0, "cgm_median": 128.0,
                "cgm_min": 90, "cgm_max": 190,
                "in_range_n": 10, "low_n": 1, "high_n": 1,
                "basal_covered_s": 3600,
                "basal_delivered_u": delivered, "basal_profile_u": hour_profile,
                "bolus_n": 0, "bolus_u": 0.0, "carbs_g": None,
            })
    db.upsert_hourly(connection, rows)
    db.set_meta(connection, "insulin_duration_min", 180)


class TestBuild:
    def test_empty_database_still_produces_a_report(self, conn, tmp_path):
        """The state every fresh install starts in — it must not crash, and it
        must say plainly that there is nothing yet."""
        out = str(tmp_path / "reports")
        path = report.build(conn, 28, 14, out, today=TODAY)

        assert os.path.exists(path)
        text = open(path, encoding="utf-8").read()
        assert "Noch keine Glukosedaten" in text
        assert "Datenqualität" in text
        for suffix in ("agp", "basal", "hypo"):
            assert os.path.exists(os.path.join(out, f"report-{TODAY}-{suffix}.png"))

    def test_report_names_the_flagged_hour(self, conn, tmp_path):
        _seed(conn)
        path = report.build(conn, 28, 14, str(tmp_path / "reports"), today=TODAY)
        text = open(path, encoding="utf-8").read()

        assert "**03:00–04:00**" in text
        assert "zu niedrig" in text

    def test_report_always_carries_the_disclaimer(self, conn, tmp_path):
        _seed(conn)
        path = report.build(conn, 28, 14, str(tmp_path / "reports"), today=TODAY)
        text = open(path, encoding="utf-8").read()
        assert "keine Dosierungsempfehlung" in text

    def test_matching_delivery_produces_no_finding(self, conn, tmp_path):
        _seed(conn, hour_delivered=0.80)
        path = report.build(conn, 28, 14, str(tmp_path / "reports"), today=TODAY)
        text = open(path, encoding="utf-8").read()
        assert "zu niedrig" not in text
        assert "deckt sich die Abgabe" in text


class TestCharts:
    def test_hypo_chart_survives_a_week_without_hypos(self, tmp_path):
        """No hypos is the good case, not an error state."""
        rows = [{"hour": h, "n": 100, "low_n": 0, "low_pct": 0.0} for h in range(24)]
        path = reportCharts.hypo_chart(rows, str(tmp_path / "hypo.png"))
        assert os.path.getsize(path) > 0

    def test_charts_render_without_any_data(self, tmp_path):
        assert os.path.getsize(
            reportCharts.agp_chart([], 70, 180, str(tmp_path / "agp.png"))) > 0
        assert os.path.getsize(reportCharts.basal_chart(
            analysis.basal_by_hour_of_day([], 180), str(tmp_path / "b.png"))) > 0
        assert os.path.getsize(
            reportCharts.hypo_chart([], str(tmp_path / "h.png"))) > 0
