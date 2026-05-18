"""Probe the Tandem Source API and dump raw JSON responses to disk.

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
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=3, file=sys.stderr)
        _save(f"{label}_ERROR", {"error": str(exc), "type": type(exc).__name__})


def main():
    email, password, region = _credentials()

    print(f"\nLogging in as {email} (region={region}) ...")
    api = TConnectApi(email, password, region)
    print("Logged in.")

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    start = yesterday.isoformat()
    end = today.isoformat()
    print(f"Date range: {start} → {end}")

    _probe("controliq_therapy_timeline",
           lambda: api.controliq.therapy_timeline(start, end))
    _probe("controliq_dashboard_summary",
           lambda: api.controliq.dashboard_summary(start, end))
    _probe("controliq_therapy_events",
           lambda: api.controliq.therapy_events(start, end))
    _probe("controliq_pumpfeatures",
           lambda: api.controliq.pumpfeatures())

    print(f"\nDone. Files in: {OUTPUT_DIR}")
    print("Review each file, redact sensitive bits (userGuid, email, etc.)")
    print("if you want, then share them back.")


if __name__ == "__main__":
    main()
