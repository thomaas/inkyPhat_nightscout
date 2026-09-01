import datetime
import os
from zoneinfo import ZoneInfo

import pytest


# tandemCalls imports tconnectsync at module load time. If tconnectsync isn't
# installed (e.g. simplified CI), skip the whole module rather than erroring.
tandemCalls = pytest.importorskip("tandemCalls")
generic = pytest.importorskip("tconnectsync.eventparser.generic")


# Minimal get_pumper() structure matching the tconnectsync 3.0 BFF response
# shape (pumps[] with a UUID assignmentId and a settings.details blob).
def _pump(assignment_id="8f0d1f6e-1c22-4a91-9a1e-9d2b1c3a4b5c",
          last_upload="2026-05-18T09:12:00Z", active_idp=0, duration=180):
    return {
        "assignmentId": assignment_id,
        "serialNumber": "1412470",
        "lastUploadDate": last_upload,
        "settings": {
            "details": {
                "profiles": {
                    "activeIdp": active_idp,
                    "profile": [
                        {"idp": 0, "insulinDuration": duration},
                        {"idp": 1, "insulinDuration": 300},
                    ],
                }
            }
        },
    }


SAMPLE_PUMPER = {"name": "Test User", "pumps": [_pump()]}


class TestSelectPump:
    def test_picks_single_pump(self):
        assert tandemCalls._select_pump(SAMPLE_PUMPER)["serialNumber"] == "1412470"

    def test_picks_most_recently_uploaded_pump(self):
        old = _pump("old-uuid", last_upload="2024-01-02T10:00:00Z")
        new = _pump("new-uuid", last_upload="2026-05-18T09:12:00Z")
        pumper = {"pumps": [old, new]}
        assert tandemCalls._select_pump(pumper)["assignmentId"] == "new-uuid"

    def test_pump_without_upload_date_sorts_last(self):
        never = _pump("never-uuid", last_upload=None)
        used = _pump("used-uuid", last_upload="2024-01-02T10:00:00Z")
        pumper = {"pumps": [never, used]}
        assert tandemCalls._select_pump(pumper)["assignmentId"] == "used-uuid"

    def test_returns_none_without_pumps(self):
        assert tandemCalls._select_pump({"pumps": []}) is None
        assert tandemCalls._select_pump({}) is None
        assert tandemCalls._select_pump(None) is None


class TestFindDeviceId:
    def test_extracts_assignment_id(self):
        pump = tandemCalls._select_pump(SAMPLE_PUMPER)
        assert tandemCalls._find_device_id(pump) == \
            "8f0d1f6e-1c22-4a91-9a1e-9d2b1c3a4b5c"

    def test_returns_none_for_non_dict(self):
        assert tandemCalls._find_device_id([]) is None
        assert tandemCalls._find_device_id(None) is None

    def test_returns_none_if_field_missing(self):
        assert tandemCalls._find_device_id({"serialNumber": "x"}) is None


class TestFindInsulinDuration:
    def test_extracts_from_active_profile(self):
        assert tandemCalls._find_insulin_duration_minutes(_pump()) == 180

    def test_follows_active_idp(self):
        pump = _pump(active_idp=1)
        assert tandemCalls._find_insulin_duration_minutes(pump) == 300

    def test_falls_back_to_first_profile_for_unknown_idp(self):
        pump = _pump(active_idp=7)
        assert tandemCalls._find_insulin_duration_minutes(pump) == 180

    def test_falls_back_to_default_without_settings(self):
        bare = {"assignmentId": "x", "settings": None}
        assert tandemCalls._find_insulin_duration_minutes(bare) == 180  # default

    def test_falls_back_on_empty_pump(self):
        assert tandemCalls._find_insulin_duration_minutes({}) == 180


class TestParsedEvents:
    class _Raw:
        timestampRaw = 12345

    class _Parsed:
        raw = None

    def test_keeps_events_with_raw_wrapper(self):
        parsed = self._Parsed()
        parsed.raw = self._Raw()
        assert tandemCalls._parsed_events([parsed]) == [parsed]

    def test_drops_unknown_events_without_raw_wrapper(self):
        # Unknown event ids come back as bare RawEvent objects whose `raw` is
        # the payload itself, not a wrapper with timestampRaw.
        class _BareRawEvent:
            raw = b""
            timestampRaw = 12345

        assert tandemCalls._parsed_events([_BareRawEvent()]) == []


class TestSensorTypeFor:
    @pytest.mark.parametrize("cls_name, expected", [
        ("LidCgmJoinSessionG7", "G7"),
        ("LidCgmStartSessionG7", "G7"),
        ("LidCgmStartSessionGx", "Gx"),
        ("LidCgmJoinSessionGx", "Gx"),
        ("LidCgmStartSessionFsl2", "Fsl2"),
        ("LidCgmJoinSessionFsl2", "Fsl2"),
        ("LidCgmJoinSessionFsl3", "Fsl3"),
        ("LidBolusCompleted", None),
        ("LidCgmStopSessionG7", "G7"),  # name still contains "G7"
    ])
    def test_classification(self, cls_name, expected):
        assert tandemCalls._sensor_type_for(cls_name) == expected


class TestGetPumpData:
    """End-to-end run of get_pump_data() against the real tconnectsync 3.0
    parser, with the network API replaced by canned pump-logs JSON."""

    @staticmethod
    def _json_event(code, props, minutes_ago, seq):
        # pumpDateTime is naive pump wall-clock time in the configured timezone.
        tz = ZoneInfo(os.environ["TIMEZONE_NAME"])
        when = datetime.datetime.now(tz) - datetime.timedelta(minutes=minutes_ago)
        return {
            "deviceAssignmentId": "uuid",
            "eventCode": code,
            "sequenceGroup": 1,
            "sequenceNumber": seq,
            "pumpDateTime": when.strftime("%Y-%m-%dT%H:%M:%S"),
            "estimatedDateTime": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "eventProperties": props,
        }

    @pytest.fixture
    def fake_api(self, monkeypatch):
        events = [
            # LID_BOLUS_COMPLETED, 30 min ago: 3.2 U delivered, 4.0 U IOB left
            self._json_event(20, {
                "completionStatus": 3, "bolusId": 1,
                "insulinDelivered": 3.2, "insulinRequested": 3.2, "iob": 4.0,
            }, minutes_ago=30, seq=2),
            # LID_BASAL_RATE_CHANGE, 10 min ago
            self._json_event(3, {
                "commandedBasalRate": 0.85, "baseBasalRate": 0.8,
                "maxBasalRate": 3.0, "idp": 0, "changeType": [0],
            }, minutes_ago=10, seq=3),
            # An event id tconnectsync doesn't know — must not blow up the sort
            self._json_event(9999, {"whatever": 1}, minutes_ago=5, seq=4),
        ]
        session_events = [
            # LID_CGM_JOIN_SESSION_G7, started 3 days ago
            self._json_event(394, {}, minutes_ago=3 * 24 * 60, seq=1),
        ]

        class FakeTandemSource:
            def get_pumper(self):
                return SAMPLE_PUMPER

            def pump_events(self, device_id, min_date=None, max_date=None):
                assert device_id == SAMPLE_PUMPER["pumps"][0]["assignmentId"]
                return generic.Events(events)

            def get_pump_logs(self, device_id, min_date=None, max_date=None,
                              event_ids_filter=None):
                return {"events": session_events, "clockChanges": []}

        class FakeTConnectApi:
            def __init__(self, *args, **kwargs):
                self.tandemsource = FakeTandemSource()

        monkeypatch.setattr(tandemCalls, "TConnectApi", FakeTConnectApi)
        return FakeTConnectApi

    def test_returns_iob_bolus_basal_and_sensor(self, fake_api):
        data = tandemCalls.get_pump_data()

        # 30 of 180 min elapsed → 4.0 U decayed to ~3.33 U
        assert data["iob"] == pytest.approx(4.0 * (1 - 30 / 180), abs=0.05)
        assert data["last_bolus"]["units"] == pytest.approx(3.2)
        assert data["last_bolus"]["minutes_ago"] in (29, 30)
        assert data["current_basal"] == pytest.approx(0.85)
        assert data["sensor"]["type"] == "G7"
        # G7 runs 240 h, 72 h used
        assert data["sensor"]["remaining_hours"] == pytest.approx(168, abs=1)


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
