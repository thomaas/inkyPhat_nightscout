"""Probe the Tandem Source API (source.tandemdiabetes.com) and dump responses.

Uses the new Tandem Source platform (api.tandemsource), which is replacing the
legacy t:connect API (api.controliq) per the tconnectsync README.

One-shot debugging tool to capture real responses for tandemCalls.py parser dev.

Usage on the Pi (assumes the project's .venv is active):

    pip install tconnectsync python-dotenv 'setuptools<81'

    # Option A — env vars:
    export TCONNECT_EMAIL=you@example.com
    export TCONNECT_PASSWORD='your_password'
    export TCONNECT_REGION=EU
    python probe_tandem.py

    # Option B — just run it, the script prompts:
    python probe_tandem.py

Outputs are written to ./tandem_probe_output/*.json. Inspect them, redact
anything sensitive (userGuid, email, etc.) and share them back.

If you see "certificate has expired" errors:
  Almost always caused by the Pi's system clock being in the past
  (no RTC + no NTP after a power cycle). Verify with `date`, then fix with:
      sudo timedatectl set-ntp true
      sudo systemctl restart systemd-timesyncd
  Re-check `date` after ~30s.

  As an absolute last resort (only after confirming the clock is correct):
      INSECURE_SSL=1 python probe_tandem.py
  This disables TLS verification — your credentials travel over a connection
  whose peer identity is not verified. Don't use it casually.
"""

import datetime
import getpass
import json
import os
import sys
import traceback
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if os.environ.get("INSECURE_SSL") == "1":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    import requests
    _orig_session_init = requests.Session.__init__
    def _patched_session_init(self, *args, **kwargs):
        _orig_session_init(self, *args, **kwargs)
        self.verify = False
    requests.Session.__init__ = _patched_session_init
    print("!!! WARNING: SSL certificate verification is DISABLED.")
    print("!!! Your Tandem credentials are about to be sent over an unverified TLS connection.")
    print("!!! Only proceed if you've already verified the Pi clock is correct.\n")

from tconnectsync.api import TConnectApi


OUTPUT_DIR = Path(__file__).parent / "tandem_probe_output"


def _credentials():
    email = os.environ.get("TCONNECT_EMAIL")
    password = os.environ.get("TCONNECT_PASSWORD")
    region = os.environ.get("TCONNECT_REGION")

    if not email:
        email = input("Tandem email: ").strip()
    if not password:
        password = getpass.getpass("Tandem password: ")
    if not region:
        region = input("Region [US/EU, default EU]: ").strip().upper() or "EU"
    return email, password, region


def _save(name, payload):
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{name}.json"
    with path.open("w") as f:
        if isinstance(payload, (dict, list)):
            json.dump(payload, f, indent=2, default=str)
        else:
            f.write(str(payload))
    size = path.stat().st_size
    print(f"  saved → {path.name} ({size} bytes)")


def _probe(label, func):
    print(f"\n→ {label}")
    try:
        result = func()
        _save(label, result)
        return result
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=3, file=sys.stderr)
        _save(f"{label}_ERROR", {"error": str(exc), "type": type(exc).__name__})
        return None


def _extract_device_id(pumper_info):
    if not isinstance(pumper_info, dict):
        return None
    for key in ("tconnectDeviceId", "tconnect_device_id", "deviceId", "device_id"):
        if pumper_info.get(key):
            return pumper_info[key]
    for container_key in ("devices", "pumpDevices", "pumps"):
        items = pumper_info.get(container_key)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            for key in ("tconnectDeviceId", "deviceId", "id"):
                if items[0].get(key):
                    return items[0][key]
    return None


def _serialize_events(events):
    out = []
    for event in events:
        attrs = {"__class__": type(event).__name__, "__repr__": repr(event)}
        try:
            attrs.update({k: v for k, v in vars(event).items()})
        except TypeError:
            for slot in getattr(event, "__slots__", ()) or ():
                attrs[slot] = getattr(event, slot, None)
        out.append(attrs)
    return out


def _ssl_diagnostic(exc):
    print(f"\nTLS/certificate error: {exc}")
    print()
    print("Most common cause on a Pi: the system clock is in the past, so")
    print("valid certificates appear expired. Check it now:")
    print()
    print(f"    Current Pi time: {datetime.datetime.now().isoformat()}")
    print()
    print("If that's wrong, fix it with:")
    print("    sudo timedatectl set-ntp true")
    print("    sudo systemctl restart systemd-timesyncd")
    print("    # wait ~30s, then verify with: date")
    print()
    print("If the clock is actually correct and you still need to proceed,")
    print("re-run with: INSECURE_SSL=1 python probe_tandem.py")


def main():
    print(f"System time: {datetime.datetime.now().isoformat()}")

    email, password, region = _credentials()

    print(f"\nLogging in to Tandem Source as {email} (region={region}) ...")
    try:
        api = TConnectApi(email, password, region)
        ts = api.tandemsource  # property access triggers OAuth login
    except Exception as exc:
        msg = str(exc).lower()
        if "certificate" in msg or "ssl" in msg or "tls" in msg:
            _ssl_diagnostic(exc)
            sys.exit(1)
        raise
    print(f"Logged in. pumperId: {ts.pumperId}")

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    start = yesterday.isoformat()
    end = today.isoformat()
    print(f"Date range: {start} → {end}")

    pumper_info = _probe(
        "tandemsource_pumper_info", lambda: ts.pumper_info()
    )
    _probe(
        "tandemsource_pump_event_metadata", lambda: ts.pump_event_metadata()
    )

    device_id = _extract_device_id(pumper_info)
    if device_id:
        print(f"\nExtracted device_id from pumper_info: {device_id}")
        _probe(
            "tandemsource_pump_events",
            lambda: _serialize_events(ts.pump_events(device_id, start, end)),
        )
    else:
        print("\nCould not auto-extract a device ID from pumper_info.")
        print("Look at tandem_probe_output/tandemsource_pumper_info.json,")
        print("identify the field that holds the device ID, and share it")
        print("back. I'll update the probe to use the right field.")

    print(f"\nDone. Files in: {OUTPUT_DIR}")
    print("Review each file, redact sensitive bits (userGuid, email, etc.)")
    print("if you want, then share them back.")


if __name__ == "__main__":
    main()
