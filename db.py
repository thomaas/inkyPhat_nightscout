"""SQLite history for glucose and pump data.

Neither data source can be back-filled indefinitely: Dexcom Share only serves
the last 24 hours, and the Tandem pump-log endpoint caps a request at roughly
four weeks. Every day that passes without a stored copy is a day permanently
lost to analysis, which is the whole reason this file exists.

Layering: this module is storage only — connect, insert, fetch, purge. All the
arithmetic lives in analysis.py, which imports no sqlite3. collector.py and
report.py wire the two together. Keeping the math free of I/O is what makes the
basal integration testable against hand-written event lists.

Timestamps are stored as integer Unix epoch seconds (UTC). Local-time bucketing
into day/hour happens in analysis.py, because therapy questions are asked in
wall-clock time ("what happens at 3 in the morning"), not in UTC.
"""

import os
import sqlite3

import config


DB_PATH = getattr(
    config, "db_path",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "nightscout.db"),
)

RAW_RETENTION_DAYS = getattr(config, "db_raw_retention_days", 120)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cgm (
    ts    INTEGER PRIMARY KEY,   -- epoch seconds, UTC
    value INTEGER NOT NULL       -- mg/dL
);

-- One row per LidBasalRateChange. `commanded` is what Control-IQ actually
-- delivers, `base` the rate programmed in the active profile — the pump
-- reports both in the same event, which is what makes the comparison possible
-- without reconstructing the profile segment timeline.
CREATE TABLE IF NOT EXISTS basal (
    ts          INTEGER PRIMARY KEY,
    commanded   REAL NOT NULL,   -- U/h
    base        REAL NOT NULL,   -- U/h
    change_type INTEGER          -- ChangetypeBitmask: suspend/resume/temp/segment
);

-- carbs/bg/iob come from LidBolusRequestedMsg1 and are NULL when the pump only
-- reported the completion event. Stored from day one even though the first
-- report ignores them: they cannot be fetched retroactively later.
CREATE TABLE IF NOT EXISTS bolus (
    ts    INTEGER PRIMARY KEY,
    units REAL NOT NULL,
    carbs INTEGER,
    bg    INTEGER,
    iob   REAL
);

CREATE TABLE IF NOT EXISTS profile_snapshot (
    day  TEXT PRIMARY KEY,       -- YYYY-MM-DD, local
    json TEXT NOT NULL           -- active IDP: segments + insulinDuration
);

-- Time windows the pump log was successfully fetched for, merged as they
-- accumulate. Without this, an hour holding no basal event is ambiguous: the
-- rate may simply not have changed, or nothing may ever have been downloaded
-- for that hour. Carrying the last known rate forward is only legitimate
-- inside a fetched window, and treating a quiet-but-fetched hour as missing
-- would throw away exactly the calm nights the analysis needs most.
CREATE TABLE IF NOT EXISTS pump_coverage (
    start_ts INTEGER PRIMARY KEY,
    end_ts   INTEGER NOT NULL
);

-- Aggregate, kept forever while the raw tables above are pruned. Deliberately
-- a fact table: it records what was measured, not whether an hour is fit for
-- analysis. That policy (bolus contamination, gap thresholds) lives in
-- analysis.py so it can change without invalidating stored history.
CREATE TABLE IF NOT EXISTS hourly (
    day               TEXT    NOT NULL,   -- local YYYY-MM-DD
    hour              INTEGER NOT NULL,   -- local 0..23
    cgm_n             INTEGER NOT NULL DEFAULT 0,
    cgm_mean          REAL,
    cgm_median        REAL,
    cgm_min           INTEGER,
    cgm_max           INTEGER,
    in_range_n        INTEGER NOT NULL DEFAULT 0,
    low_n             INTEGER NOT NULL DEFAULT 0,
    high_n            INTEGER NOT NULL DEFAULT 0,
    basal_covered_s   INTEGER NOT NULL DEFAULT 0,  -- seconds of the hour with real data
    basal_delivered_u REAL    NOT NULL DEFAULT 0,  -- time-weighted integral, units
    basal_profile_u   REAL    NOT NULL DEFAULT 0,  -- same for the programmed rate
    bolus_n           INTEGER NOT NULL DEFAULT 0,
    bolus_u           REAL    NOT NULL DEFAULT 0,
    carbs_g           INTEGER,
    PRIMARY KEY (day, hour)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path=None):
    """Open (and if needed create) the database.

    auto_vacuum has to be set before the first table is created, otherwise
    SQLite silently keeps the default and purged pages are never handed back to
    the filesystem — which on a Pi's SD card is the difference between a file
    that stays a few megabytes and one that only ever grows.
    """
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# --- writes ---------------------------------------------------------------
#
# Every insert is INSERT OR IGNORE keyed on the timestamp, so a collector run
# that overlaps the previous one is a no-op for data already stored. That is
# what lets the collector re-fetch a full 24h window every three hours and
# heal gaps left by an outage without producing duplicates.

def insert_cgm(conn, rows):
    """rows: iterable of (ts, value). Returns the number of new rows."""
    cur = conn.executemany(
        "INSERT OR IGNORE INTO cgm (ts, value) VALUES (?, ?)", list(rows)
    )
    conn.commit()
    return cur.rowcount


def insert_basal(conn, rows):
    """rows: iterable of (ts, commanded, base, change_type)."""
    cur = conn.executemany(
        "INSERT OR IGNORE INTO basal (ts, commanded, base, change_type) "
        "VALUES (?, ?, ?, ?)", list(rows)
    )
    conn.commit()
    return cur.rowcount


def insert_bolus(conn, rows):
    """rows: iterable of (ts, units, carbs, bg, iob).

    A bolus surfaces in two events: LidBolusCompleted carries the delivered
    units, LidBolusRequestedMsg1 the carbs entered. They share a timestamp only
    approximately, so the collector merges them before calling this. Where a
    later run has richer data for a known timestamp, COALESCE fills the gaps
    without ever overwriting a value with NULL.
    """
    cur = conn.executemany(
        "INSERT INTO bolus (ts, units, carbs, bg, iob) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(ts) DO UPDATE SET "
        "  units = MAX(units, excluded.units), "
        "  carbs = COALESCE(carbs, excluded.carbs), "
        "  bg    = COALESCE(bg,    excluded.bg), "
        "  iob   = COALESCE(iob,   excluded.iob)",
        list(rows)
    )
    conn.commit()
    return cur.rowcount


def save_profile_snapshot(conn, day, payload_json):
    conn.execute(
        "INSERT OR REPLACE INTO profile_snapshot (day, json) VALUES (?, ?)",
        (day, payload_json),
    )
    conn.commit()


def upsert_hourly(conn, rows):
    """rows: iterable of dicts as produced by analysis.rollup_rows()."""
    rows = list(rows)
    if not rows:
        return 0
    columns = [
        "day", "hour", "cgm_n", "cgm_mean", "cgm_median", "cgm_min", "cgm_max",
        "in_range_n", "low_n", "high_n", "basal_covered_s",
        "basal_delivered_u", "basal_profile_u", "bolus_n", "bolus_u", "carbs_g",
    ]
    placeholders = ", ".join("?" * len(columns))
    conn.executemany(
        f"INSERT OR REPLACE INTO hourly ({', '.join(columns)}) "
        f"VALUES ({placeholders})",
        [tuple(row[c] for c in columns) for row in rows],
    )
    conn.commit()
    return len(rows)


def record_coverage(conn, start_ts, end_ts, merge_gap_s=300):
    """Add a fetched window and merge it with the ones already stored.

    Windows are merged when they overlap or sit within merge_gap_s of each
    other, so eight overlapping collector runs per day collapse into a single
    row rather than accumulating forever.
    """
    if end_ts <= start_ts:
        return
    windows = [(row["start_ts"], row["end_ts"]) for row in
               conn.execute("SELECT start_ts, end_ts FROM pump_coverage")]
    windows.append((int(start_ts), int(end_ts)))
    merged = merge_windows(windows, merge_gap_s)
    conn.execute("DELETE FROM pump_coverage")
    conn.executemany(
        "INSERT INTO pump_coverage (start_ts, end_ts) VALUES (?, ?)", merged
    )
    conn.commit()


def merge_windows(windows, merge_gap_s=0):
    """Merge overlapping/adjacent (start, end) pairs. Pure helper, no I/O."""
    merged = []
    for start, end in sorted(windows):
        if merged and start - merged[-1][1] <= merge_gap_s:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def fetch_coverage(conn, start_ts, end_ts):
    """Coverage windows clipped to [start_ts, end_ts)."""
    out = []
    for row in conn.execute(
        "SELECT start_ts, end_ts FROM pump_coverage "
        "WHERE end_ts > ? AND start_ts < ? ORDER BY start_ts",
        (start_ts, end_ts),
    ):
        out.append((max(row["start_ts"], start_ts), min(row["end_ts"], end_ts)))
    return out


def set_meta(conn, key, value):
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value))
    )
    conn.commit()


# --- reads ----------------------------------------------------------------

def fetch_cgm(conn, start_ts, end_ts):
    return [
        (row["ts"], row["value"])
        for row in conn.execute(
            "SELECT ts, value FROM cgm WHERE ts >= ? AND ts < ? ORDER BY ts",
            (start_ts, end_ts),
        )
    ]


def fetch_basal(conn, start_ts, end_ts):
    return [
        (row["ts"], row["commanded"], row["base"], row["change_type"])
        for row in conn.execute(
            "SELECT ts, commanded, base, change_type FROM basal "
            "WHERE ts >= ? AND ts < ? ORDER BY ts",
            (start_ts, end_ts),
        )
    ]


def fetch_bolus(conn, start_ts, end_ts):
    return [
        (row["ts"], row["units"], row["carbs"], row["bg"], row["iob"])
        for row in conn.execute(
            "SELECT ts, units, carbs, bg, iob FROM bolus "
            "WHERE ts >= ? AND ts < ? ORDER BY ts",
            (start_ts, end_ts),
        )
    ]


def fetch_hourly(conn, start_day, end_day):
    """Inclusive on both ends; days are local YYYY-MM-DD strings."""
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM hourly WHERE day >= ? AND day <= ? ORDER BY day, hour",
            (start_day, end_day),
        )
    ]


def latest_profile(conn):
    row = conn.execute(
        "SELECT day, json FROM profile_snapshot ORDER BY day DESC LIMIT 1"
    ).fetchone()
    return (row["day"], row["json"]) if row else (None, None)


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def counts(conn):
    """Row counts and time span per table — used by the report's data-quality
    section and by --dry-run to show what is already stored."""
    out = {}
    for table in ("cgm", "basal", "bolus"):
        row = conn.execute(
            f"SELECT count(*) AS n, min(ts) AS first, max(ts) AS last FROM {table}"
        ).fetchone()
        out[table] = {"n": row["n"], "first": row["first"], "last": row["last"]}
    row = conn.execute("SELECT count(*) AS n FROM hourly").fetchone()
    out["hourly"] = {"n": row["n"]}
    return out


# --- maintenance ----------------------------------------------------------

def purge_raw(conn, before_ts):
    """Drop raw rows older than before_ts; the hourly aggregate is untouched.

    This is the trade that keeps the file small: fine-grained history for a few
    months, hourly history forever. incremental_vacuum actually returns the
    freed pages to the filesystem — without it the file keeps its high-water
    mark and the purge buys nothing on disk.
    """
    deleted = 0
    for table in ("cgm", "basal", "bolus"):
        cur = conn.execute(f"DELETE FROM {table} WHERE ts < ?", (before_ts,))
        deleted += cur.rowcount
    conn.execute("DELETE FROM pump_coverage WHERE end_ts < ?", (before_ts,))
    conn.execute(
        "UPDATE pump_coverage SET start_ts = ? WHERE start_ts < ?",
        (before_ts, before_ts),
    )
    conn.commit()
    conn.execute("PRAGMA incremental_vacuum")
    conn.commit()
    return deleted


def file_size_bytes(path=None):
    """Total on-disk size, including the write-ahead log.

    In WAL mode recent writes live in the -wal sidecar until a checkpoint, so
    measuring only the main file while a connection is open reports a fraction
    of the real footprint.
    """
    target = path or DB_PATH
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(target + suffix)
        except OSError:
            pass
    return total
