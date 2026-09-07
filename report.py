"""Cron entrypoint: write the weekly Markdown report.

Reads the stored history, runs the deterministic evaluations in analysis.py and
writes reports/report-YYYY-MM-DD.md plus its charts. No inference, no model —
every number is an integral or a median over recorded events, and the report
says how many days each one rests on.

Usage:
    python report.py                # last analysis_window_days
    python report.py --window 7     # shorter window, e.g. right after setup
    python report.py --no-purge     # keep raw rows past the retention limit
"""

import argparse
import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo

import analysis
import config
import db
import reportCharts


TZ = ZoneInfo(getattr(config, "dexcom_timezone_name", "Europe/Berlin"))
TARGET_LOW = getattr(config, "target_low", 70)
TARGET_HIGH = getattr(config, "target_high", 180)
WINDOW_DAYS = getattr(config, "analysis_window_days", 28)
AGP_DAYS = getattr(config, "agp_window_days", 14)
RETENTION_DAYS = getattr(config, "db_raw_retention_days", 120)
REPORT_DIR = getattr(
    config, "report_dir",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports"),
)

MIN_DAYS = 7          # clean days an hour needs before it may be flagged
DEVIATION = 0.20      # 20% median deviation
AGREEMENT = 0.70      # ...and 70% of days on the same side

DISCLAIMER = """> **Diskussionsgrundlage, keine Dosierungsempfehlung.**
> Alle Zahlen sind Mediane und Integrale über aufgezeichnete Pumpen- und
> Sensordaten — keine Vorhersage und keine Therapieanweisung. Änderungen an
> Basalrate, Korrekturfaktor oder KH-Faktor gehören besprochen mit deinem
> Diabetes-Team. Prüfe insbesondere den Abschnitt *Datenqualität*, bevor du
> einer Auffälligkeit Gewicht gibst."""


def _fmt(value, digits=2, dash="—"):
    return dash if value is None else f"{value:.{digits}f}"


def _pct(value, dash="—"):
    return dash if value is None else f"{value:.0f}%"


def _insulin_duration(conn):
    stored = db.get_meta(conn, "insulin_duration_min")
    return int(stored) if stored else 180


def _profile_summary(conn):
    """The programmed basal schedule from the most recent snapshot.

    basalRate arrives in milliunits per hour and startTime in minutes from
    midnight (tconnectsync's PumpProfileSegment).
    """
    day, payload = db.latest_profile(conn)
    if not payload:
        return None, None
    try:
        profile = json.loads(payload)
        segments = []
        for segment in profile.get("timeDependentSegments", []):
            segments.append({
                "start_min": int(segment.get("startTime", 0)),
                "basal_u_h": int(segment.get("basalRate", 0)) / 1000.0,
                "isf": segment.get("isf"),
                "carb_ratio": int(segment.get("carbRatio", 0)) / 1000.0
                if segment.get("carbRatio") else None,
                "target_bg": segment.get("targetBg"),
            })
        segments.sort(key=lambda s: s["start_min"])
        return day, {"name": profile.get("name"), "segments": segments}
    except (ValueError, TypeError, AttributeError):
        return day, None


def _basal_section(hours, insulin_duration):
    lines = [
        "## Control-IQ gegen Profil-Basalrate",
        "",
        f"Verglichen wird, was Control-IQ tatsächlich abgegeben hat, mit der in "
        f"deinem Profil programmierten Rate. Ausgewertet werden nur Stunden ohne "
        f"Bolus in der Stunde selbst und in den {insulin_duration} Minuten davor "
        f"— sonst misst man Mahlzeiten-Insulin statt Basal.",
        "",
        "Eine Stunde wird nur markiert, wenn drei Bedingungen zusammenkommen: "
        f"mindestens {MIN_DAYS} saubere Tage, mindestens "
        f"{DEVIATION * 100:.0f} % Abweichung im Median und mindestens "
        f"{AGREEMENT * 100:.0f} % der Tage auf derselben Seite. Die letzte "
        "Bedingung ist ein Vorzeichentest: sie verhindert, dass eine einzelne "
        "Nacht den Median über die Schwelle zieht.",
        "",
        "| Std | Tage | abgegeben | Profil | Abw. | gleiche Richtung | ø Glukose | Hypo-Werte | |",
        "|----:|-----:|----------:|-------:|-----:|-----------------:|----------:|-----------:|:--|",
    ]

    for hour in hours:
        if hour["ratio"] is not None:
            percent = (hour["ratio"] - 1) * 100
            # Rounded to zero before formatting, so a deviation of -0.3 %
            # prints as "±0 %" rather than the nonsensical "-0 %".
            deviation = "±0 %" if abs(percent) < 0.5 else f"{percent:+.0f} %"
        elif hour["diff_u"] is not None:
            deviation = f"{hour['diff_u']:+.2f} U"
        else:
            deviation = "—"

        mark = {"above": "▲ zu niedrig?", "below": "▼ zu hoch?"}.get(hour["flag"], "")
        lines.append(
            f"| {hour['hour']:02d} | {hour['n_days']} | "
            f"{_fmt(hour['delivered_u'])} | {_fmt(hour['profile_u'])} | "
            f"{deviation} | {_pct((hour['share_above'] or 0) * 100)} | "
            f"{_fmt(hour['cgm_median'], 0)} | {hour['hypo_n']} | {mark} |"
        )

    flagged = [h for h in hours if h["flag"]]
    lines.append("")
    if flagged:
        lines.append("**Auffällige Stunden**\n")
        for hour in flagged:
            direction = ("Control-IQ regelt hier systematisch **hoch** — die "
                         "programmierte Rate liegt womöglich zu niedrig."
                         if hour["flag"] == "above" else
                         "Control-IQ regelt hier systematisch **herunter** — die "
                         "programmierte Rate liegt womöglich zu hoch.")
            context = ""
            if hour["hypo_n"]:
                context = (f" In diesen Stunden liegen {hour['hypo_n']} Messwerte "
                           f"unter {TARGET_LOW} mg/dL — das gehört mit ins Gespräch.")
            lines.append(
                f"- **{hour['hour']:02d}:00–{(hour['hour'] + 1) % 24:02d}:00** "
                f"({hour['n_days']} saubere Tage): {direction}{context}"
            )
    else:
        enough = [h for h in hours if h["n_days"] >= MIN_DAYS]
        if enough:
            lines.append(
                "Keine Stunde erfüllt alle drei Bedingungen. Für die Stunden mit "
                f"genügend Daten ({len(enough)} von 24) deckt sich die Abgabe von "
                "Control-IQ also weitgehend mit deinem Profil."
            )
        else:
            lines.append(
                f"Noch keine Stunde hat {MIN_DAYS} saubere Tage beisammen. Das ist "
                "am Anfang normal — siehe *Datenqualität*."
            )
    return lines


def _quality_section(quality, insulin_duration, counts, window_days):
    lines = [
        "## Datenqualität",
        "",
        "Ohne diese Zahlen ist eine Abweichung nicht lesbar: „+34 %“ auf zwölf "
        "Nächten bedeutet etwas anderes als „+34 %“ auf einer. *Gespeichert* "
        "ist die Zahl vorhandener Stundenzeilen im Fenster, *sauber* die Zahl, die "
        "nach Lücken- und Bolusfilter übrig bleibt.",
        "",
        "| Std | gespeichert | sauber | verworfen: Lücke | verworfen: Bolus |",
        "|----:|------------:|-------:|-----------------:|-----------------:|",
    ]
    for row in quality:
        lines.append(
            f"| {row['hour']:02d} | {row['stored']} | {row['clean']} | "
            f"{row['dropped_gap']} | {row['dropped_bolus']} |"
        )

    lines += [
        "",
        f"Fenster: {window_days} Tage. Wirkdauer des Insulins laut Pumpe: "
        f"{insulin_duration} Minuten — so weit reicht der Bolusfilter zurück.",
        "",
        f"Gespeicherte Rohdaten: {counts['cgm']['n']} Glukosewerte, "
        f"{counts['basal']['n']} Basal-Events, {counts['bolus']['n']} Boli, "
        f"{counts['hourly']['n']} Stundenzeilen. "
        f"Datenbank: {db.file_size_bytes() / (1024 * 1024):.1f} MB.",
    ]
    return lines


def build(conn, window_days, agp_days, out_dir, today=None):
    today = today or datetime.datetime.now(tz=TZ).date()
    start_day = today - datetime.timedelta(days=window_days - 1)
    insulin_duration = _insulin_duration(conn)

    hourly = db.fetch_hourly(conn, start_day.isoformat(), today.isoformat())
    hours = analysis.basal_by_hour_of_day(
        hourly, insulin_duration, MIN_DAYS, DEVIATION, AGREEMENT
    )
    quality = analysis.data_quality(hourly, insulin_duration)
    tir = analysis.tir_summary(hourly)
    hypo = analysis.hypo_by_hour(hourly)
    tdd = analysis.tdd_by_day(hourly)

    agp_start = today - datetime.timedelta(days=agp_days - 1)
    agp_start_ts, _ = analysis.day_bounds(agp_start, TZ)
    _, agp_end_ts = analysis.day_bounds(today, TZ)
    agp_rows = analysis.agp(db.fetch_cgm(conn, agp_start_ts, agp_end_ts), TZ)

    stamp = today.isoformat()
    base = os.path.join(out_dir, f"report-{stamp}")
    charts = {
        "agp": reportCharts.agp_chart(
            agp_rows, TARGET_LOW, TARGET_HIGH, f"{base}-agp.png",
            title=f"Glukose-Tagesprofil, {agp_days} Tage"),
        "basal": reportCharts.basal_chart(
            hours, f"{base}-basal.png",
            title=f"Basalrate je Tagesstunde, {window_days} Tage"),
        "hypo": reportCharts.hypo_chart(
            hypo, f"{base}-hypo.png", TARGET_LOW,
            title="Unterzuckerungen nach Uhrzeit"),
    }

    lines = [
        f"# Auswertung {start_day.strftime('%d.%m.')} – {today.strftime('%d.%m.%Y')}",
        "",
        DISCLAIMER,
        "",
        "## Kennzahlen",
        "",
    ]

    overall = tir["overall"]
    if overall:
        lines += [
            f"| Kennzahl | Wert |",
            f"|---|---|",
            f"| Zeit im Zielbereich ({TARGET_LOW}–{TARGET_HIGH}) | **{overall['tir_pct']} %** |",
            f"| Mittlere Glukose | {overall['avg']} mg/dL |",
            f"| Unter Zielbereich | {overall['low_pct']} % |",
            f"| Über Zielbereich | {overall['high_pct']} % |",
            f"| Messwerte | {overall['n']} |",
            "",
            "| Tagesabschnitt | TIR | ø | unter | über |",
            "|---|---:|---:|---:|---:|",
        ]
        for name, segment in tir["segments"]:
            if segment:
                lines.append(
                    f"| {name} | {segment['tir_pct']} % | {segment['avg']} | "
                    f"{segment['low_pct']} % | {segment['high_pct']} % |"
                )
            else:
                lines.append(f"| {name} | — | — | — | — |")
    else:
        lines.append("Noch keine Glukosedaten im Fenster gespeichert.")

    lines += [
        "",
        "## Glukose-Tagesprofil",
        "",
        f"![Tagesprofil]({os.path.basename(charts['agp'])})",
        "",
        f"Median und Perzentilbänder über {agp_days} Tage, alle Tage übereinander "
        "gelegt. Ein breites Band heißt: zu dieser Tageszeit läuft es von Tag zu "
        "Tag sehr unterschiedlich.",
        "",
    ]

    lines += _basal_section(hours, insulin_duration)
    lines += [
        "",
        f"![Basalrate]({os.path.basename(charts['basal'])})",
        "",
        "## Unterzuckerungen nach Uhrzeit",
        "",
        f"![Hypos]({os.path.basename(charts['hypo'])})",
        "",
    ]

    if tdd:
        recent = tdd[-14:]
        avg_tdd = analysis.median([d["tdd_u"] for d in recent])
        avg_basal_pct = analysis.median(
            [d["basal_pct"] for d in recent if d["basal_pct"] is not None]
        )
        lines += [
            "## Tagesdosis",
            "",
            f"Median über {len(recent)} vollständige Tage: "
            f"**{_fmt(avg_tdd, 1)} U** pro Tag, davon "
            f"{_pct(avg_basal_pct)} Basal. Nur Tage mit nahezu lückenloser "
            "Basal-Abdeckung zählen — ein halb erfasster Tag sähe sonst aus wie "
            "ein Tag mit weniger Insulin.",
            "",
        ]

    lines += _quality_section(quality, insulin_duration, db.counts(conn), window_days)

    day, profile = _profile_summary(conn)
    if profile and profile["segments"]:
        lines += [
            "",
            f"## Programmiertes Profil (Stand {day})",
            "",
            "| ab | Basal U/h | ISF | KH-Faktor g/U | Ziel mg/dL |",
            "|---|---:|---:|---:|---:|",
        ]
        for segment in profile["segments"]:
            start = f"{segment['start_min'] // 60:02d}:{segment['start_min'] % 60:02d}"
            lines.append(
                f"| {start} | {segment['basal_u_h']:.3f} | "
                f"{segment['isf'] if segment['isf'] is not None else '—'} | "
                f"{_fmt(segment['carb_ratio'], 1)} | "
                f"{segment['target_bg'] if segment['target_bg'] is not None else '—'} |"
            )

    lines += [
        "",
        "---",
        "",
        f"Erzeugt am {datetime.datetime.now(tz=TZ).strftime('%d.%m.%Y %H:%M')} "
        f"von `report.py`. Die Kohlenhydrat-Angaben aus der Pumpe werden seit "
        "Beginn mitgespeichert, aber noch nicht ausgewertet — eine belastbare "
        "KH-Faktor-Analyse braucht saubere Mahlzeitenfenster und mehr Historie.",
        "",
    ]

    path = f"{base}.md"
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, default=WINDOW_DAYS,
                        help=f"analysis window in days (default {WINDOW_DAYS})")
    parser.add_argument("--agp-window", type=int, default=AGP_DAYS,
                        help=f"AGP window in days (default {AGP_DAYS})")
    parser.add_argument("--out", default=REPORT_DIR, help="output directory")
    parser.add_argument("--no-purge", action="store_true",
                        help="keep raw rows older than the retention limit")
    args = parser.parse_args(argv)

    conn = db.connect()
    try:
        path = build(conn, args.window, args.agp_window, args.out)
        print(f"report written: {path}")

        if not args.no_purge:
            cutoff = datetime.datetime.now(tz=TZ) - datetime.timedelta(days=RETENTION_DAYS)
            deleted = db.purge_raw(conn, int(cutoff.timestamp()))
            if deleted:
                print(f"purged {deleted} raw rows older than {RETENTION_DAYS} days")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
