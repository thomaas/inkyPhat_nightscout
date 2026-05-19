import datetime

import pytest


# tandemCalls imports tconnectsync at module load time. If tconnectsync isn't
# installed (e.g. simplified CI), skip the whole module rather than erroring.
tandemCalls = pytest.importorskip("tandemCalls")


# Minimal metadata structure matching the real Tandem Source response shape
# (top-level is a list of pumps, one entry per pump).
SAMPLE_METADATA = [
    {
        "tconnectDeviceId": 72811,
        "serialNumber": "1412470",
        "lastUpload": {
            "settings": {
                "profiles": {
                    "profile": [
                        {"insulinDuration": 180}
                    ]
                }
            }
        }
    }
]


class TestFindDeviceId:
    def test_extracts_from_first_entry(self):
        assert tandemCalls._find_device_id(SAMPLE_METADATA) == 72811

    def test_returns_none_for_empty_list(self):
        assert tandemCalls._find_device_id([]) is None

    def test_returns_none_for_non_list(self):
        assert tandemCalls._find_device_id({}) is None
        assert tandemCalls._find_device_id(None) is None

    def test_returns_none_if_field_missing(self):
        assert tandemCalls._find_device_id([{"serialNumber": "x"}]) is None


class TestFindInsulinDuration:
    def test_extracts_from_metadata(self):
        assert tandemCalls._find_insulin_duration_minutes(SAMPLE_METADATA) == 180

    def test_falls_back_to_default_on_missing_field(self):
        bare = [{"tconnectDeviceId": 1}]
        assert tandemCalls._find_insulin_duration_minutes(bare) == 180  # default

    def test_falls_back_on_empty_metadata(self):
        assert tandemCalls._find_insulin_duration_minutes([]) == 180


class TestDecayIob:
    def test_no_time_elapsed_returns_full_iob(self):
        now = datetime.datetime(2026, 5, 18, 12, 0, tzinfo=datetime.timezone.utc)
        result = tandemCalls._decay_iob(5.0, now, now, 180)
        assert result == pytest.approx(5.0)

    def test_half_duration_elapsed_yields_half_iob(self):
        now = datetime.datetime(2026, 5, 18, 12, 0, tzinfo=datetime.timezone.utc)
        # 90 min ago, duration 180 → 0.5 remaining
        when = now - datetime.timedelta(minutes=90)
        result = tandemCalls._decay_iob(10.0, when, now, 180)
        assert result == pytest.approx(5.0)

    def test_past_duration_clamps_to_zero(self):
        now = datetime.datetime(2026, 5, 18, 12, 0, tzinfo=datetime.timezone.utc)
        when = now - datetime.timedelta(minutes=240)
        result = tandemCalls._decay_iob(10.0, when, now, 180)
        assert result == 0.0

    def test_quarter_elapsed_yields_three_quarters(self):
        now = datetime.datetime(2026, 5, 18, 12, 0, tzinfo=datetime.timezone.utc)
        when = now - datetime.timedelta(minutes=45)
        result = tandemCalls._decay_iob(8.0, when, now, 180)
        assert result == pytest.approx(6.0)
