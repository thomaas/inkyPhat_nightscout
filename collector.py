"""Cron entrypoint: append glucose and pump data to the SQLite history.

Runs every three hours, around the clock, deliberately decoupled from the
display cron in the README (`*/5 8-16 * * 1-5`), which only ever sees weekday
office hours. The fasting nights it never covers are exactly the hours a basal
rate analysis rests on.

Every run re-fetches a full 24-hour window and relies on INSERT OR IGNORE, so
overlapping runs are free and an outage heals itself: eight runs a day cover
the same Dexcom window, and the Pi can be off for most of a day without
punching a permanent hole in the history. That redundancy is the whole reason
for the three-hour cadence — Dexcom Share keeps nothing older than 24 hours,
so a single missed daily run would lose that day for good.

Usage:
    python collector.py                # normal cron run
    python collector.py --backfill 28  # one-off: pull weeks of pump events
    python collector.py --dry-run      # show what would be written
"""

import argparse
import datetime
import json
import sys
from zoneinfo import ZoneInfo

import analysis
import config
import db
import dexcomCalls


TZ = ZoneInfo(getattr(config, "dexcom_timezone_name", "Europe/Berlin"))
TARGET_LOW = getattr(config, "target_low", 70)
TARGET_HIGH = getattr(config, "target_high", 180)
MAX_CARRY_S = getattr(config, "max_carry_minutes", 360) * 60

# The pump-logs endpoint rejects windows much longer than a month.
BACKFILL_CHUNK_DAYS = 21

# Bolus data arrives split across two events with timestamps a few seconds
# apart: the request (carbs, BG) and the completion (units actually given).
# They are merged when they fall within this window of each other.
BOLUS_MERGE_WINDOW_S = 900


def _epoch(dt):
    return int(dt.timestamp())


def collect_cgm(conn, dry_run=False):
    readings = dexcomCalls.getRecentReadings()
    rows = [(_epoch(r["timestamp"]), r["value"]) for r in readings]
    if dry_run:
        print(f"  CGM: {len(rows)} readings fetched (nothing written)")
        return 0
    added = db.insert_cgm(conn, rows)
    print(f"  CGM: {len(rows)} fetched, {added} new")
    return added


def _basal_rows(events):
    rows = []
    for event in events:
        if type(event).__name__ != "LidBasalRateChange":
            continue
        if event.commandedBasalRate is None or event.baseBasalRate is None:
            continue
        rows.append((
            _epoch(event.raw.timestamp.datetime),
            float(event.commandedBasalRate),
            float(event.baseBasalRate),
            getattr(event, "changeTypeRaw", None),
        ))
    return rows


def _bolus_rows(events):
    """Merge LidBolusCompleted (units) with LidBolusRequestedMsg1 (carbs, BG).

    The two events describe the same bolus but carry different fields and
    slightly different timestamps, so they are matched by proximity. Carbs are
    stored even though the first report ignores them: they cannot be fetched
    retroactively once the pump's log window has moved on, and an insulin-to-
    carb analysis later is impossible without them.
    """
    completed, requested = [], []
    for event in events:
        name = type(event).__name__
        ts = _epoch(event.raw.timestamp.datetime)
        if name == "LidBolusCompleted" and event.insulinDelivered is not None:
            completed.append({
                "ts": ts,
                "units": float(event.insulinDelivered),
                "iob": float(event.iob) if event.iob is not None else None,
            })
        elif name == "LidBolusRequestedMsg1":
            requested.append({
                "ts": ts,
                "carbs": getattr(event, "carbAmount", None),
                "bg": getattr(event, "bg", None),
                "iob": float(event.iob) if getattr(event, "iob", None) is not None else None,
            })

    rows = []
    for entry in completed:
        match = None
        for candidate in requested:
            delta = entry["ts"] - candidate["ts"]
            if 0 <= delta <= BOLUS_MERGE_WINDOW_S:
                if match is None or candidate["ts"] > match["ts"]:
                    match = candidate
        carbs = match["carbs"] if match else None
        bg = match["bg"] if match else None
        rows.append((
            entry["ts"],
            entry["units"],
            int(carbs) if carbs else None,
            int(bg) if bg else None,
            entry["iob"] if entry["iob"] is not None else (match or {}).get("iob"),
        ))
    return rows


def collect_pump(conn, start_date, end_date, dry_run=False):
    """Fetch pump events for [start_date, end_date] and store them.

    Returns the number of basal events seen, or None when the pump is
    unreachable — the collector treats that as a bad run and records no
    coverage, so the window is retried instead of being remembered as an hour
    with no insulin.
    """
    # Imported lazily: tconnectsync is a heavy dependency and is not installed
    # in every environment, so a CGM-only setup must not fail at import time.
    import tandemCalls

    ts, pump, device_id, insulin_duration = tandemCalls.connect()
    if device_id is None:
        print("  Pump: no usable pump on the account")
        return None

    events = tandemCalls.get_events_between(start_date, end_date, ts, device_id)
    basal = _basal_rows(events)
    bolus = _bolus_rows(events)

    profile = tandemCalls._find_active_profile(pump)
    today = datetime.datetime.now(tz=TZ).strftime("%Y-%m-%d")

    if dry_run:
        print(f"  Pump: {len(events)} events, {len(basal)} basal, "
              f"{len(bolus)} bolus (nothing written)")
        return len(basal)

    added_basal = db.insert_basal(conn, basal)
    db.insert_bolus(conn, bolus)
    if profile:
        db.save_profile_snapshot(conn, today, json.dumps(profile, default=str))
    db.set_meta(conn, "insulin_duration_min", insulin_duration)

    # Only now is the window known to have been downloaded. Recording it before
    # a successful fetch would let the analysis carry a stale rate across a gap
    # that was never actually retrieved.
    window_start, _ = _day_bounds(start_date)
    _, window_end = _day_bounds(end_date)
    db.record_coverage(conn, window_start, min(window_end, int(_now().timestamp())))

    print(f"  Pump: {len(events)} events, {added_basal} new basal, "
          f"{len(bolus)} bolus, insulin duration {insulin_duration} min")
    return len(basal)


def _now():
    return datetime.datetime.now(tz=TZ)


def _day_bounds(day):
    return analysis.day_bounds(day, TZ)


def rollup(conn, days_back=3, dry_run=False):
    """Recompute hourly aggregates for the last few days.

    Recomputed rather than appended because pump events arrive late: the pump
    uploads in batches, so yesterday's picture can still change today. Being
    idempotent makes that a non-issue.
    """
    today = _now().date()
    days = [
        (today - datetime.timedelta(days=offset)).isoformat()
        for offset in range(days_back, -1, -1)
    ]
    start_ts, _ = analysis.day_bounds(days[0], TZ)
    _, end_ts = analysis.day_bounds(days[-1], TZ)

    rows = analysis.rollup_rows(
        days, TZ,
        cgm_rows=db.fetch_cgm(conn, start_ts, end_ts),
        # Reach back before the window so the first hour inherits a rate.
        basal_events=db.fetch_basal(conn, start_ts - MAX_CARRY_S, end_ts),
        bolus_rows=db.fetch_bolus(conn, start_ts, end_ts),
        coverage=db.fetch_coverage(conn, start_ts, end_ts),
        target_low=TARGET_LOW,
        target_high=TARGET_HIGH,
        max_carry_s=MAX_CARRY_S,
    )
    if dry_run:
        print(f"  Rollup: {len(rows)} hourly rows would be written")
        return 0
    written = db.upsert_hourly(conn, rows)
    db.set_meta(conn, "tir_target_low", TARGET_LOW)
    db.set_meta(conn, "tir_target_high", TARGET_HIGH)
    print(f"  Rollup: {written} hourly rows")
    return written


def backfill(conn, days, dry_run=False):
    """One-off: pull as much pump history as the API still holds.

    Glucose cannot be backfilled at all — Dexcom Share serves 24 hours and
    nothing more — so this only deepens the pump side.
    """
    today = _now().date()
    remaining = days
    while remaining > 0:
        chunk = min(BACKFILL_CHUNK_DAYS, remaining)
        end = today - datetime.timedelta(days=remaining - chunk)
        start = end - datetime.timedelta(days=chunk)
        print(f"  backfill window {start} → {end}")
        try:
            collect_pump(conn, start, end, dry_run)
        except Exception as exc:
            print(f"  backfill window failed: {type(exc).__name__}: {exc}")
        remaining -= chunk

    if not dry_run:
        rollup(conn, days_back=days, dry_run=dry_run)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", type=int, metavar="DAYS",
                        help="one-off: fetch DAYS of pump history, then roll up")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and report, but write nothing")
    args = parser.parse_args(argv)

    print(f"collector {_now().isoformat(timespec='seconds')}  db={db.DB_PATH}")
    conn = db.connect()
    try:
        if args.backfill:
            backfill(conn, args.backfill, args.dry_run)
            return 0

        failures = 0
        try:
            collect_cgm(conn, args.dry_run)
        except Exception as exc:
            failures += 1
            print(f"  CGM failed: {type(exc).__name__}: {exc}")

        # A CGM outage must not stop the pump fetch, and the other way round —
        # each source is stored independently, and a partial history beats none.
        if getattr(config, "show_pump_data", False):
            today = _now().date()
            try:
                collect_pump(conn, today - datetime.timedelta(days=1), today,
                             args.dry_run)
            except Exception as exc:
                failures += 1
                print(f"  Pump failed: {type(exc).__name__}: {exc}")
        else:
            print("  Pump: skipped (show_pump_data is False)")

        rollup(conn, dry_run=args.dry_run)

        size_mb = db.file_size_bytes() / (1024 * 1024)
        print(f"  db size: {size_mb:.1f} MB")
        return 1 if failures else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
