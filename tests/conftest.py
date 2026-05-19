import datetime
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("TIMEZONE_NAME", "Europe/Berlin")


import pytest


@pytest.fixture
def now():
    return datetime.datetime(2026, 5, 18, 14, 30, tzinfo=datetime.timezone.utc)


@pytest.fixture
def history_in_range():
    """36 readings, all inside 70–180, spread across 3 hours."""
    base = datetime.datetime(2026, 5, 18, 11, 30, tzinfo=datetime.timezone.utc)
    pattern = [120, 135, 148, 155, 160, 158, 150, 140, 128, 118,
               112, 108, 105, 110, 122, 138, 152, 168, 178, 170,
               160, 150, 140, 132, 125, 118, 112, 108, 105, 110,
               118, 128, 138, 148, 158, 168]
    return [
        {"value": pattern[i], "timestamp": base + datetime.timedelta(minutes=5 * i)}
        for i in range(len(pattern))
    ]


@pytest.fixture
def history_mixed():
    """Mix of in-range, low, and high readings — predictable counts."""
    base = datetime.datetime(2026, 5, 18, 11, 30, tzinfo=datetime.timezone.utc)
    values = (
        [120] * 7  # in range
        + [60] * 2  # low
        + [200] * 1  # high
    )
    return [
        {"value": v, "timestamp": base + datetime.timedelta(minutes=5 * i)}
        for i, v in enumerate(values)
    ]


@pytest.fixture
def glucose_payload(history_in_range):
    latest = history_in_range[-1]
    prev = history_in_range[-2]
    return {
        "current_glucose": {
            "value": latest["value"],
            "trend": "↗",
            "trend_direction": "FortyFiveUp",
            "delta": latest["value"] - prev["value"],
            "timestamp": latest["timestamp"],
        },
        "glucose_history": history_in_range,
    }


@pytest.fixture
def pump_payload():
    return {
        "iob": 2.4,
        "last_bolus": {"units": 3.2, "minutes_ago": 45},
        "current_basal": 0.85,
    }
