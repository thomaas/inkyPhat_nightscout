"""Statistics over the stored history. Pure functions, no database access.

Everything here takes plain lists of tuples or dicts and returns plain data, so
the arithmetic can be tested against hand-written event sequences without a
database or a network. db.py does the storage, collector.py and report.py wire
the two together.

The central question this module answers: over the last few weeks, where does
Control-IQ systematically deviate from the programmed profile basal rate? Every
LidBasalRateChange event carries both the commanded rate and the profile's base
rate, so the comparison is a matter of integrating two step functions over the
same interval — no model, no fitting, no inference.

Three details carry most of the correctness weight, and each has a test:

1. Basal events are step changes, not samples. A rate that held for 55 minutes
   and one that held for 5 must not count equally, so everything is integrated
   as rate x duration.
2. An hour with no data must never be scored as an hour with zero insulin.
   Delivery is only credited inside a window the pump log was actually fetched
   for, and only within max_carry_s of a real event.
3. An hour touched by a bolus (in it, or within the insulin duration before it)
   measures meal insulin, not basal, and is excluded.
"""

import datetime
from zoneinfo import ZoneInfo


HOUR_S = 3600
DAY_S = 86400

# How long the last known rate may be carried forward past its event before the
# data is treated as missing. Generous on purpose: with a quiet profile and
# Control-IQ not modulating, the pump only logs a rate change when a timed
# segment advances, which can be hours apart. The pump_coverage window is the
# primary guard against inventing data; this is the backstop for the case where
# the collector fetched a window but the pump itself had uploaded nothing.
DEFAULT_MAX_CARRY_S = 6 * HOUR_S

# An hour needs near-complete basal data to be comparable across days.
MIN_COVERED_S = 3540  # 59 of 60 minutes


# --- small numeric helpers ------------------------------------------------

def median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def percentile(values, p):
    """Linear-interpolated percentile, p in 0..100. Pure Python on purpose:
    keeps this module free of numpy so the tests stay trivial."""
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    if n == 1:
        return float(ordered[0])
    rank = (p / 100.0) * (n - 1)
    low = int(rank)
    high = min(low + 1, n - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _tz(tz):
    return ZoneInfo(tz) if isinstance(tz, str) else tz


def local_bucket(ts, tz):
    """Map an epoch second to its local (YYYY-MM-DD, hour)."""
    local = datetime.datetime.fromtimestamp(ts, tz=_tz(tz))
    return local.strftime("%Y-%m-%d"), local.hour


def day_bounds(day, tz, days=1):
    """UTC epoch bounds of `days` local days starting at local midnight of `day`.

    Going through the local calendar rather than adding 86400 seconds is what
    makes the DST days come out right: the last Sunday in March is 23 hours
    long, the one in October 25.
    """
    zone = _tz(tz)
    if isinstance(day, str):
        day = datetime.date.fromisoformat(day)
    start = datetime.datetime.combine(day, datetime.time(0), tzinfo=zone)
    end = datetime.datetime.combine(
        day + datetime.timedelta(days=days), datetime.time(0), tzinfo=zone
    )
    return int(start.timestamp()), int(end.timestamp())


def hour_slices(start_ts, end_ts, tz):
    """Split [start_ts, end_ts) at hour boundaries.

    Yields (day, hour, seconds). Boundaries are UTC hour marks, which coincide
    with local ones for whole-hour offsets such as Europe/Berlin. In a zone
    offset by :30 or :45 the split points would be half an hour off; the bucket
    label itself always comes from converting the slice start to local time, so
    such a zone mis-assigns at most the edge of a slice rather than the bucket.
    """
    ts = int(start_ts)
    end_ts = int(end_ts)
    while ts < end_ts:
        boundary = min(((ts // HOUR_S) + 1) * HOUR_S, end_ts)
        day, hour = local_bucket(ts, tz)
        yield day, hour, boundary - ts
        ts = boundary


def _clip(intervals, start_ts, end_ts):
    out = []
    for s, e in intervals:
        s, e = max(s, start_ts), min(e, end_ts)
        if e > s:
            out.append((s, e))
    return out


def _intersect(a, b):
    """Intersection of two sorted, non-overlapping interval lists."""
    out = []
    i = j = 0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if end > start:
            out.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


# --- basal integration ----------------------------------------------------

def integrate_basal(events, coverage, start_ts, end_ts, tz,
                    max_carry_s=DEFAULT_MAX_CARRY_S):
    """Integrate the commanded and profile basal rates into hourly buckets.

    events:   (ts, commanded, base, change_type), sorted, ideally reaching back
              before start_ts so the first hour has a rate to carry in.
    coverage: (start, end) windows the pump log was fetched for.

    Returns {(day, hour): {"delivered_u", "profile_u", "covered_s"}}.

    A pump suspend is not a gap: Control-IQ reports commanded = 0 and that zero
    is a real measurement, so the hour stays fully covered and simply gets no
    insulin credited. A missing upload is the opposite and must not be scored
    as zero delivery, which is what the coverage windows and max_carry_s guard
    against.
    """
    buckets = {}
    if not events:
        return buckets

    known = _clip(coverage, start_ts, end_ts)
    if not known:
        return buckets

    for index, (ts, commanded, base, _change) in enumerate(events):
        next_ts = events[index + 1][0] if index + 1 < len(events) else end_ts
        # The rate holds until the next event, but only counts as known for as
        # long as the backstop allows.
        segment = _clip([(ts, min(next_ts, ts + max_carry_s))], start_ts, end_ts)
        for seg_start, seg_end in _intersect(segment, known):
            for day, hour, seconds in hour_slices(seg_start, seg_end, tz):
                bucket = buckets.setdefault(
                    (day, hour),
                    {"delivered_u": 0.0, "profile_u": 0.0, "covered_s": 0},
                )
                hours = seconds / HOUR_S
                bucket["delivered_u"] += commanded * hours
                bucket["profile_u"] += base * hours
                bucket["covered_s"] += seconds

    return buckets


# --- rollup ---------------------------------------------------------------

def rollup_rows(days, tz, cgm_rows, basal_events, bolus_rows, coverage,
                target_low, target_high, max_carry_s=DEFAULT_MAX_CARRY_S):
    """Build hourly aggregate rows for the given local days.

    days: list of YYYY-MM-DD strings. The caller is expected to have fetched
    basal events from before the first day so a rate can be carried in.
    """
    if not days:
        return []

    days = sorted(days)
    start_ts, _ = day_bounds(days[0], tz)
    _, end_ts = day_bounds(days[-1], tz)

    basal = integrate_basal(
        basal_events, coverage, start_ts, end_ts, tz, max_carry_s
    )

    cgm = {}
    for ts, value in cgm_rows:
        if start_ts <= ts < end_ts:
            cgm.setdefault(local_bucket(ts, tz), []).append(value)

    bolus = {}
    for row in bolus_rows:
        ts, units = row[0], row[1]
        carbs = row[2] if len(row) > 2 else None
        if not (start_ts <= ts < end_ts):
            continue
        entry = bolus.setdefault(
            local_bucket(ts, tz), {"n": 0, "units": 0.0, "carbs": None}
        )
        entry["n"] += 1
        entry["units"] += units or 0.0
        if carbs is not None:
            entry["carbs"] = (entry["carbs"] or 0) + carbs

    rows = []
    for key in sorted(set(cgm) | set(basal) | set(bolus)):
        day, hour = key
        values = cgm.get(key, [])
        b = basal.get(key, {})
        bol = bolus.get(key, {})
        rows.append({
            "day": day,
            "hour": hour,
            "cgm_n": len(values),
            "cgm_mean": (sum(values) / len(values)) if values else None,
            "cgm_median": median(values),
            "cgm_min": min(values) if values else None,
            "cgm_max": max(values) if values else None,
            "in_range_n": sum(1 for v in values if target_low <= v <= target_high),
            "low_n": sum(1 for v in values if v < target_low),
            "high_n": sum(1 for v in values if v > target_high),
            "basal_covered_s": int(b.get("covered_s", 0)),
            "basal_delivered_u": round(b.get("delivered_u", 0.0), 5),
            "basal_profile_u": round(b.get("profile_u", 0.0), 5),
            "bolus_n": bol.get("n", 0),
            "bolus_u": round(bol.get("units", 0.0), 3),
            "carbs_g": bol.get("carbs"),
        })
    return rows


# --- the core evaluation --------------------------------------------------

def _hour_ordinal(day, hour):
    return datetime.date.fromisoformat(day).toordinal() * 24 + hour


def clean_basal_hours(hourly_rows, insulin_duration_min,
                      min_covered_s=MIN_COVERED_S):
    """Hours usable for judging the basal rate.

    An hour qualifies when it has near-complete basal data and neither it nor
    any hour within the insulin duration before it saw a bolus. That is the
    logic of a classic basal-rate test, applied automatically across every day
    in the window instead of one fasting night at a time.

    A look-back hour that is simply absent from the table counts as
    disqualifying: not knowing whether a bolus happened is not the same as
    knowing none did.
    """
    by_ordinal = {_hour_ordinal(r["day"], r["hour"]): r for r in hourly_rows}
    lookback = max(1, -(-insulin_duration_min // 60))  # ceil to whole hours

    clean = []
    for ordinal, row in sorted(by_ordinal.items()):
        if row["basal_covered_s"] < min_covered_s:
            continue
        if row["bolus_n"]:
            continue
        contaminated = False
        for back in range(1, lookback + 1):
            prior = by_ordinal.get(ordinal - back)
            if prior is None or prior["bolus_n"]:
                contaminated = True
                break
        if not contaminated:
            clean.append(row)
    return clean


def basal_by_hour_of_day(hourly_rows, insulin_duration_min, min_days=7,
                         deviation=0.20, agreement=0.70,
                         min_covered_s=MIN_COVERED_S):
    """Compare delivered against programmed basal, per hour of day.

    An hour is only flagged when three conditions hold together: enough clean
    days behind it, a median deviation of at least `deviation`, and at least
    `agreement` of those days deviating in the same direction. The last one is
    the important one — it is a sign test, and it stops a single wild night
    from dragging the median across the threshold. A genuine trend has many
    days pointing the same way.
    """
    clean = clean_basal_hours(hourly_rows, insulin_duration_min, min_covered_s)

    grouped = {}
    for row in clean:
        grouped.setdefault(row["hour"], []).append(row)

    out = []
    for hour in range(24):
        rows = grouped.get(hour, [])
        n_days = len(rows)
        entry = {
            "hour": hour,
            "n_days": n_days,
            "delivered_u": None,
            "profile_u": None,
            "ratio": None,
            "diff_u": None,
            "share_above": None,
            "cgm_median": None,
            "hypo_n": 0,
            "flag": None,
        }
        if n_days:
            delivered = [r["basal_delivered_u"] for r in rows]
            profile = [r["basal_profile_u"] for r in rows]
            entry["delivered_u"] = median(delivered)
            entry["profile_u"] = median(profile)
            entry["diff_u"] = entry["delivered_u"] - entry["profile_u"]
            entry["share_above"] = sum(
                1 for d, p in zip(delivered, profile) if d > p
            ) / n_days
            cgm_medians = [r["cgm_median"] for r in rows if r["cgm_median"] is not None]
            entry["cgm_median"] = median(cgm_medians)
            entry["hypo_n"] = sum(r["low_n"] for r in rows)

            if entry["profile_u"] > 0:
                entry["ratio"] = entry["delivered_u"] / entry["profile_u"]

            entry["flag"] = _flag(entry, min_days, deviation, agreement)
        out.append(entry)
    return out


def _flag(entry, min_days, deviation, agreement):
    if entry["n_days"] < min_days:
        return None
    ratio, share = entry["ratio"], entry["share_above"]

    if ratio is None:
        # A zero profile rate makes the ratio undefined, so fall back to the
        # absolute difference: any sustained delivery against a programmed zero
        # is itself the finding.
        if entry["diff_u"] >= 0.1 and share >= agreement:
            return "above"
        return None

    if ratio >= 1 + deviation and share >= agreement:
        return "above"
    if ratio <= 1 - deviation and (1 - share) >= agreement:
        return "below"
    return None


# --- supporting views -----------------------------------------------------

DAY_SEGMENTS = [
    ("Nacht", 0, 6),
    ("Vormittag", 6, 12),
    ("Nachmittag", 12, 18),
    ("Abend", 18, 24),
]


def tir_summary(hourly_rows):
    """Time in range overall and per part of day, weighted by reading count."""
    def summarise(rows):
        total = sum(r["cgm_n"] for r in rows)
        if not total:
            return None
        weighted = sum((r["cgm_mean"] or 0) * r["cgm_n"] for r in rows)
        return {
            "n": total,
            "avg": round(weighted / total),
            "tir_pct": round(100 * sum(r["in_range_n"] for r in rows) / total),
            "low_pct": round(100 * sum(r["low_n"] for r in rows) / total),
            "high_pct": round(100 * sum(r["high_n"] for r in rows) / total),
        }

    return {
        "overall": summarise(hourly_rows),
        "segments": [
            (name, summarise([r for r in hourly_rows if start <= r["hour"] < end]))
            for name, start, end in DAY_SEGMENTS
        ],
    }


def agp(cgm_rows, tz, bucket_minutes=30):
    """Ambulatory glucose profile: percentiles per time-of-day bucket."""
    buckets = {}
    for ts, value in cgm_rows:
        local = datetime.datetime.fromtimestamp(ts, tz=_tz(tz))
        index = (local.hour * 60 + local.minute) // bucket_minutes
        buckets.setdefault(index, []).append(value)

    out = []
    for index in sorted(buckets):
        values = buckets[index]
        out.append({
            "minute": index * bucket_minutes,
            "n": len(values),
            "p10": percentile(values, 10),
            "p25": percentile(values, 25),
            "p50": percentile(values, 50),
            "p75": percentile(values, 75),
            "p90": percentile(values, 90),
        })
    return out


def hypo_by_hour(hourly_rows):
    """Share of readings below target per hour of day."""
    out = []
    for hour in range(24):
        rows = [r for r in hourly_rows if r["hour"] == hour]
        total = sum(r["cgm_n"] for r in rows)
        low = sum(r["low_n"] for r in rows)
        out.append({
            "hour": hour,
            "n": total,
            "low_n": low,
            "low_pct": round(100 * low / total, 1) if total else None,
        })
    return out


def tdd_by_day(hourly_rows, min_covered_hours=20):
    """Basal against bolus share per day.

    Days without near-complete basal coverage are dropped rather than reported
    low: a partial day looks like a day with less insulin, which would read as
    a trend that never happened.
    """
    by_day = {}
    for row in hourly_rows:
        entry = by_day.setdefault(
            row["day"], {"basal_u": 0.0, "bolus_u": 0.0, "covered_h": 0.0}
        )
        entry["basal_u"] += row["basal_delivered_u"]
        entry["bolus_u"] += row["bolus_u"]
        entry["covered_h"] += row["basal_covered_s"] / HOUR_S

    out = []
    for day in sorted(by_day):
        entry = by_day[day]
        if entry["covered_h"] < min_covered_hours:
            continue
        total = entry["basal_u"] + entry["bolus_u"]
        out.append({
            "day": day,
            "basal_u": round(entry["basal_u"], 2),
            "bolus_u": round(entry["bolus_u"], 2),
            "tdd_u": round(total, 2),
            "basal_pct": round(100 * entry["basal_u"] / total) if total else None,
        })
    return out


def data_quality(hourly_rows, insulin_duration_min, min_covered_s=MIN_COVERED_S):
    """Per hour of day: how many hours were stored, and how many survived the
    coverage and bolus filters.

    Without this the headline numbers are unreadable — a deviation of "+34%"
    means something entirely different resting on twelve nights than on one.
    """
    clean = clean_basal_hours(hourly_rows, insulin_duration_min, min_covered_s)
    clean_by_hour = {}
    for row in clean:
        clean_by_hour[row["hour"]] = clean_by_hour.get(row["hour"], 0) + 1

    out = []
    for hour in range(24):
        rows = [r for r in hourly_rows if r["hour"] == hour]
        covered = sum(1 for r in rows if r["basal_covered_s"] >= min_covered_s)
        out.append({
            "hour": hour,
            "stored": len(rows),
            "basal_covered": covered,
            "clean": clean_by_hour.get(hour, 0),
            "dropped_gap": len(rows) - covered,
            "dropped_bolus": covered - clean_by_hour.get(hour, 0),
        })
    return out
