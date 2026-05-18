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

    return {
        "iob": iob,
        "last_bolus": last_bolus,
        "current_basal": current_basal,
    }
