import datetime
import os
import pickle
from zoneinfo import ZoneInfo

from pydexcom import Dexcom, Region

from config import (
    checkDataBeforeRefresh,
    checkFile,
    dexcom_password,
    dexcom_region,
    dexcom_timezone_name,
    dexcom_username,
    nightscoutDataPoints,
)

_LOCAL_TZ = ZoneInfo(dexcom_timezone_name)


def checkIfNeedsToRun(lastEntry):
    myTime = datetime.datetime.now()
    if os.path.isfile(checkFile):
        myTime = pickle.load(open(checkFile, "rb"))

    if lastEntry == myTime:
        print("The Same, nothing changed, exiting...")
        exit(1)
    else:
        pickle.dump(lastEntry, open(checkFile, "wb"))


def _shift(dt):
    # pydexcom returns a timezone-aware datetime, so converting to the
    # configured zone yields the correct local wall-clock time, including DST.
    return dt.astimezone(_LOCAL_TZ)


def _client():
    return Dexcom(
        username=dexcom_username,
        password=dexcom_password,
        region=Region(dexcom_region),
    )


def getRecentReadings(minutes=1440, max_count=288):
    """Readings from the last `minutes`, chronological, as dicts.

    1440 minutes / 288 readings is everything Dexcom Share holds — it serves a
    rolling 24-hour window and nothing older, which is why the collector stores
    a copy and why a missed day can never be recovered.
    """
    entries = _client().get_glucose_readings(minutes=minutes, max_count=max_count)
    return [
        {"value": e.value, "timestamp": _shift(e.datetime)}
        for e in sorted(entries, key=lambda e: e.datetime)
    ]


def getDataFromNightscout():
    dexcom = _client()

    if checkDataBeforeRefresh:
        checkIfNeedsToRun(dexcom.get_glucose_readings(max_count=1)[0].datetime)

    entries = dexcom.get_glucose_readings(max_count=nightscoutDataPoints)
    if not entries:
        raise RuntimeError("No glucose readings returned from Dexcom")

    latest = entries[0]
    delta = entries[0].value - entries[1].value if len(entries) > 1 else 0

    glucose_history = [
        {"value": e.value, "timestamp": _shift(e.datetime)}
        for e in reversed(entries)
    ]

    current_glucose = {
        "value": latest.value,
        "trend": latest.trend_arrow,
        "trend_direction": latest.trend_direction,
        "delta": delta,
        "timestamp": _shift(latest.datetime),
    }

    return {
        "current_glucose": current_glucose,
        "glucose_history": glucose_history,
    }


def getTodayData(max_count=288):
    """Fetch today's readings (chronological). Used by the suspend-screen flow."""
    today = datetime.datetime.now(tz=_LOCAL_TZ).date()
    return [
        entry for entry in getRecentReadings(max_count=max_count)
        if entry["timestamp"].date() == today
    ]


def timeInRangeStats(history, target_low, target_high):
    if not history:
        return None
    total = len(history)
    in_range = sum(1 for h in history if target_low <= h["value"] <= target_high)
    below = sum(1 for h in history if h["value"] < target_low)
    above = sum(1 for h in history if h["value"] > target_high)
    avg = sum(h["value"] for h in history) / total
    return {
        "tir_pct": round(100 * in_range / total),
        "low_pct": round(100 * below / total),
        "high_pct": round(100 * above / total),
        "avg": round(avg),
        "count": total,
    }
