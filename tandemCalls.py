"""Tandem Source pump data — Phase B implementation.

Parsers grounded in real responses captured via probe_tandem.py. See
tandemcalls/*.json for reference samples.

Requires tconnectsync >= 3.0, which follows Tandem's move from the base64
binary event stream to the pre-decoded JSON BFF endpoints: get_pumper()
replaces pump_event_metadata(), get_pump_logs() replaces pump_events_raw() +
decode_raw_events(), and the event fields are camelCase (iob, insulinDelivered,
commandedBasalRate).

Sources of pump data:
  - get_pumper: device ID + scheduled basal/ISF profile snapshot
  - pump_events (event stream from the pump itself):
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
    "Fsl3": 336,  # FreeStyle Libre 3: 14 days
}

# tconnectsync event IDs for CGM session start / join / stop events.
_SESSION_EVENT_IDS = [212, 213, 214, 394, 404, 405, 406, 447, 477, 486]


def _select_pump(pumper):
    """Pick the active pump from get_pumper()['pumps'].

    An account can carry retired pumps (warranty replacements), so prefer the
    one that uploaded most recently. lastUploadDate is an ISO-8601 string and
    is absent/None for a pump that never uploaded, which sorts it last.
    """
    if not isinstance(pumper, dict):
        return None
    pumps = pumper.get("pumps") or []
    if not pumps:
        return None
    return max(pumps, key=lambda pump: pump.get("lastUploadDate") or "")


def _find_device_id(pump):
    """assignmentId (a UUID) is the device id the pump-logs endpoint expects."""
    if isinstance(pump, dict):
        return pump.get("assignmentId")
    return None


def _find_insulin_duration_minutes(pump):
    """Read insulinDuration from the active profile in settings.details."""
    try:
        profiles = pump["settings"]["details"]["profiles"]
        active_idp = profiles.get("activeIdp")
        for profile in profiles["profile"]:
            if profile.get("idp") == active_idp:
                return int(profile["insulinDuration"])
        return int(profiles["profile"][0]["insulinDuration"])
    except (KeyError, IndexError, TypeError):
        return _INSULIN_DURATION_DEFAULT_MINUTES


def _event_time(event):
    return event.raw.timestamp.datetime


def _parsed_events(events):
    """Keep only events tconnectsync could map to a known event class.

    An unknown event id yields a bare RawEvent instead of a wrapper carrying
    `.raw`. That is no longer an edge case: the pump-logs endpoint ignores the
    eventIds filter and returns everything in the window.
    """
    return [ev for ev in events if hasattr(getattr(ev, "raw", None), "timestampRaw")]


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
    if "Fsl3" in event_class_name:
        return "Fsl3"
    return None


def _fetch_sensor_session(ts, device_id, lookback_days=14):
    from tconnectsync.eventparser.generic import Events
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=lookback_days)).isoformat()
    end = today.isoformat()
    # The pump-logs endpoint caps a window at ~4 weeks, so a 14-day lookback
    # fits in a single request. The server ignores eventIds and returns the
    # whole window, hence the class-name filtering below.
    logs = ts.get_pump_logs(device_id, start, end, event_ids_filter=_SESSION_EVENT_IDS)
    events = _parsed_events(Events(logs.get("events") or []))
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

    pump = _select_pump(ts.get_pumper())
    device_id = _find_device_id(pump)
    if device_id is None:
        return None
    insulin_duration = _find_insulin_duration_minutes(pump)

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    events = _parsed_events(ts.pump_events(device_id, yesterday.isoformat(), today.isoformat()))
    if not events:
        return None

    events.sort(key=lambda e: e.raw.timestampRaw, reverse=True)
    now = datetime.datetime.now(tz=events[0].raw.timestamp.tzinfo)

    iob = None
    last_bolus = None
    current_basal = None

    for ev in events:
        cls = type(ev).__name__

        if iob is None and getattr(ev, "iob", None) is not None:
            when = _event_time(ev)
            iob = _decay_iob(float(ev.iob), when, now, insulin_duration)

        # Fields are None when the pump-logs payload omits them, so each value
        # is taken independently — a partial panel beats no panel at all.
        if (last_bolus is None and cls == "LidBolusCompleted"
                and ev.insulinDelivered is not None):
            when = _event_time(ev)
            mins_ago = int((now - when).total_seconds() / 60)
            last_bolus = {
                "units": float(ev.insulinDelivered),
                "minutes_ago": max(0, mins_ago),
            }

        if (current_basal is None and cls == "LidBasalRateChange"
                and ev.commandedBasalRate is not None):
            current_basal = float(ev.commandedBasalRate)

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
