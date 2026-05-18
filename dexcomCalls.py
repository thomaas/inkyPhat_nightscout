import datetime
import os
import pickle

from pydexcom import Dexcom, Region

from config import (
    checkDataBeforeRefresh,
    checkFile,
    dexcom_password,
    dexcom_region,
    dexcom_timezone_offset_hours,
    dexcom_username,
    nightscoutDataPoints,
)


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
    return dt + datetime.timedelta(hours=dexcom_timezone_offset_hours)


def getDataFromNightscout():
    dexcom = Dexcom(
        username=dexcom_username,
        password=dexcom_password,
        region=Region(dexcom_region),
    )

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
    dexcom = Dexcom(
        username=dexcom_username,
        password=dexcom_password,
        region=Region(dexcom_region),
    )
    entries = dexcom.get_glucose_readings(max_count=max_count)
    today = datetime.datetime.now().date()
    today_entries = [e for e in entries if _shift(e.datetime).date() == today]
    today_entries.sort(key=lambda e: e.datetime)
    return [
        {"value": e.value, "timestamp": _shift(e.datetime)}
        for e in today_entries
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
