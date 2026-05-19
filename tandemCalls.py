"""Tandem Source pump data — Phase B implementation.

Parsers grounded in real responses captured via probe_tandem.py. See
tandemcalls/*.json for reference samples.

Sources of pump data:
  - pump_event_metadata: device ID + scheduled basal/ISF profile snapshot
  - pump_events (binary-decoded event stream from the pump itself):
      LidBolusCompleted     → last bolus + post-bolus IOB
      LidBolusActivated     → IOB at bolus activation (fallback)
      LidBolusRequestedMsg1 → pre-bolus IOB (further fallback)
      LidBasalRateChange    → live Control-IQ basal rate

IOB only updates when a bolus event fires, so we apply linear decay against
the pump's configured insulinDuration (180 min on this user's pump).
"""

import datetime
import os

from config import (
    tconnect_email,
    tconnect_password,
    tconnect_region,
    tconnect_timezone_name,
)

os.environ.setdefault("TIMEZONE_NAME", tconnect_timezone_name)

if os.environ.get("INSECURE_SSL") == "1":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    import requests
    _orig_session_init = requests.Session.__init__
    def _patched_session_init(self, *args, **kwargs):
        _orig_session_init(self, *args, **kwargs)
        self.verify = False
    requests.Session.__init__ = _patched_session_init

from tconnectsync.api import TConnectApi


_INSULIN_DURATION_DEFAULT_MINUTES = 180

# Manufacturer session durations (used to compute remaining sensor time).
_SESSION_DURATION_HOURS = {
    "G7": 240,    # Dexcom G7: 10 days
    "Gx": 240,    # Dexcom G6 / earlier Gx assumed 10 days
    "Fsl2": 336,  # FreeStyle Libre 2: 14 days
}

# tconnectsync event IDs for CGM session start / join / stop events.
_SESSION_EVENT_IDS = [212, 213, 214, 394, 404, 405, 406, 447]


def _find_device_id(metadata):
    if isinstance(metadata, list) and metadata:
        return metadata[0].get("tconnectDeviceId")
    return None


def _find_insulin_duration_minutes(metadata):
    try:
        return int(
            metadata[0]["lastUpload"]["settings"]["profiles"]["profile"][0]
            ["insulinDuration"]
        )
    except (KeyError, IndexError, TypeError):
        return _INSULIN_DURATION_DEFAULT_MINUTES


def _event_time(event):
    return event.raw.timestamp.datetime


def _decay_iob(iob_at, when, now, duration_minutes):
    elapsed_minutes = (now - when).total_seconds() / 60.0
    fraction_remaining = max(0.0, 1.0 - elapsed_minutes / duration_minutes)
    return iob_at * fraction_remaining


def _sensor_type_for(event_class_name):
    if "G7" in event_class_name:
        return "G7"
    if "Gx" in event_class_name:
        return "Gx"
    if "Fsl2" in event_class_name:
        return "Fsl2"
    return None


def _fetch_sensor_session(ts, device_id, lookback_days=14):
    from tconnectsync.eventparser.generic import Events, decode_raw_events
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=lookback_days)).isoformat()
    end = today.isoformat()
    raw = ts.pump_events_raw(device_id, start, end, event_ids_filter=_SESSION_EVENT_IDS)
    decoded = decode_raw_events(raw)
    events = list(Events(decoded))
    if not events:
        return None

    candidates = []
    for ev in events:
        cls = type(ev).__name__
        if "Start" in cls or "Join" in cls:
            sensor_type = _sensor_type_for(cls)
            if sensor_type:
                candidates.append((ev, sensor_type))
    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0].raw.timestampRaw, reverse=True)
    latest, sensor_type = candidates[0]
    started_at = _event_time(latest)
    now = datetime.datetime.now(tz=started_at.tzinfo)
    elapsed_hours = (now - started_at).total_seconds() / 3600.0
    total_hours = _SESSION_DURATION_HOURS.get(sensor_type, 240)
    remaining_hours = max(0.0, total_hours - elapsed_hours)
    return {
        "type": sensor_type,
        "started_at": started_at,
        "remaining_hours": remaining_hours,
    }


def get_pump_data():
    api = TConnectApi(tconnect_email, tconnect_password, tconnect_region)
    ts = api.tandemsource

    metadata = ts.pump_event_metadata()
    device_id = _find_device_id(metadata)
    if device_id is None:
        return None
    insulin_duration = _find_insulin_duration_minutes(metadata)

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    events = list(ts.pump_events(device_id, yesterday.isoformat(), today.isoformat()))
    if not events:
        return None

    events.sort(key=lambda e: e.raw.timestampRaw, reverse=True)
    now = datetime.datetime.now(tz=events[0].raw.timestamp.tzinfo)

    iob = None
    last_bolus = None
    current_basal = None

    for ev in events:
        cls = type(ev).__name__

        if iob is None and hasattr(ev, "IOB"):
            when = _event_time(ev)
            iob = _decay_iob(float(ev.IOB), when, now, insulin_duration)

        if last_bolus is None and cls == "LidBolusCompleted":
            when = _event_time(ev)
            mins_ago = int((now - when).total_seconds() / 60)
            last_bolus = {
                "units": float(ev.insulindelivered),
                "minutes_ago": max(0, mins_ago),
            }

        if current_basal is None and cls == "LidBasalRateChange":
            current_basal = float(ev.commandedbasalrate)

        if iob is not None and last_bolus is not None and current_basal is not None:
            break

    try:
        sensor = _fetch_sensor_session(ts, device_id)
    except Exception:
        sensor = None

    return {
        "iob": iob,
        "last_bolus": last_bolus,
        "current_basal": current_basal,
        "sensor": sensor,
    }
