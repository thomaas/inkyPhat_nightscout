"""Charts for the weekly report.

Kept separate from matplotLibActions.py, which is hard-wired to the 212x104
InkyPHAT (six-point type, two ink colours, no room for a legend). Nothing here
is reusable there and nothing there is reusable here, so the two stay apart.

Rendered on a light surface only. A report read on a Mac may sit in a dark
viewer, but a second dark-mode set of PNGs is real work for a personal report,
and a light figure stays legible on a dark page while the reverse is not true.
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


# Validated categorical slots 1 and 2 (blue / orange) on the light surface:
# all-pairs CVD Delta-E 24.7, normal-vision 33.6, both clear of the floors.
SERIES_DELIVERED = "#2a78d6"
SERIES_PROFILE = "#eb6834"

BAND_INNER = "#9ec5f4"   # sequential blue 200 — the 25-75 band
BAND_OUTER = "#cde2fb"   # sequential blue 100 — the 10-90 band

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
TARGET_BAND = "#f0efec"
CRITICAL = "#d03b3b"

FIGSIZE = (9.0, 3.4)
DPI = 130


def _style(ax, ylabel=None):
    """Hairline, recessive chrome: solid gridlines one shade off the surface,
    no top/right spines, muted tick labels."""
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8, linestyle="-", zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=INK_MUTED, labelsize=8, length=0, pad=4)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK_MUTED, fontsize=8)


def _hour_axis(ax, every=2):
    ax.set_xlim(-0.6, 23.6)
    ax.set_xticks(range(0, 24, every))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, every)],
                       fontsize=7 if every == 1 else 8)
    ax.set_xlabel("Uhrzeit", color=INK_MUTED, fontsize=8)


def _legend(ax, handles=None, ncol=3):
    """Placed above the plot rather than inside it: an in-axes legend collides
    with whichever bar happens to be tallest that week."""
    kwargs = {"loc": "lower left", "bbox_to_anchor": (0, 1.0), "frameon": False,
              "fontsize": 8, "ncol": ncol, "borderaxespad": 0.0,
              "handlelength": 1.4, "columnspacing": 1.6}
    legend = ax.legend(handles=handles, **kwargs) if handles else ax.legend(**kwargs)
    for text in legend.get_texts():
        text.set_color(INK_MUTED)
    return legend


def _no_data(ax, text="Noch keine Daten für diesen Zeitraum"):
    """The first weeks on a fresh install are mostly empty. An empty frame with
    a note is honest; an empty frame alone looks like a broken chart."""
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center",
            color=INK_MUTED, fontsize=9)


def _save(fig, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


def agp_chart(rows, target_low, target_high, path, title=None):
    """Percentile bands over the time of day — the standard AGP view.

    One entity (glucose) at nested magnitudes, so it is a single-hue sequential
    ramp rather than categorical colours: the darker the mark, the closer to
    the median.
    """
    fig, ax = plt.subplots(figsize=FIGSIZE)
    _style(ax, "mg/dL")

    if rows:
        x = [r["minute"] / 60.0 for r in rows]
        ax.fill_between(x, [r["p10"] for r in rows], [r["p90"] for r in rows],
                        color=BAND_OUTER, linewidth=0, zorder=2,
                        label="10.–90. Perzentil")
        ax.fill_between(x, [r["p25"] for r in rows], [r["p75"] for r in rows],
                        color=BAND_INNER, linewidth=0, zorder=3,
                        label="25.–75. Perzentil")
        ax.plot(x, [r["p50"] for r in rows], color=SERIES_DELIVERED,
                linewidth=2.0, zorder=4, label="Median")

    ax.axhspan(target_low, target_high, facecolor=TARGET_BAND, zorder=1)
    for bound in (target_low, target_high):
        ax.axhline(bound, color=CRITICAL, linewidth=0.8, zorder=2)

    ax.set_ylim(40, 300)
    _hour_axis(ax)
    if title:
        ax.set_title(title, color=INK_PRIMARY, fontsize=10, loc="left", pad=24)
    if rows:
        _legend(ax)
    else:
        _no_data(ax)
    return _save(fig, path)


def basal_chart(hours, path, title=None):
    """Delivered against programmed basal per hour of day.

    Both series share one axis in the same unit — units of insulin per hour —
    so they belong in one chart. Grouped bars rather than a deviation chart on
    purpose: a 40% deviation on 0.05 U/h and one on 1.2 U/h are the same
    percentage and very different findings, and only the absolute heights show
    that difference.

    Flagged hours are marked with a triangle and a bold tick label, never by
    recolouring the bar: colour belongs to the series, not to the verdict.

    Hours with no evaluable day are shaded rather than left blank. An empty
    column would read as "no insulin here", which is the same lie the gap
    handling in analysis.py exists to prevent — the truth is "nothing
    comparable was measured here", almost always because a meal bolus sits
    inside the insulin-duration window.
    """
    fig, ax = plt.subplots(figsize=FIGSIZE)
    _style(ax, "Einheiten pro Stunde")

    width = 0.38          # leaves a ~2px surface gap between the paired bars
    positions = range(24)
    delivered = [h["delivered_u"] or 0 for h in hours]
    profile = [h["profile_u"] or 0 for h in hours]

    for hour in hours:
        if not hour["n_days"]:
            ax.axvspan(hour["hour"] - 0.5, hour["hour"] + 0.5,
                       facecolor=TARGET_BAND, zorder=1)

    ax.bar([p - width / 2 - 0.01 for p in positions], delivered, width,
           color=SERIES_DELIVERED, zorder=3, label="Control-IQ abgegeben")
    ax.bar([p + width / 2 + 0.01 for p in positions], profile, width,
           color=SERIES_PROFILE, zorder=3, label="Profil programmiert")

    headroom = max(delivered + profile + [0.1]) * 1.15
    ax.set_ylim(0, headroom)

    for hour in hours:
        if not hour["flag"]:
            continue
        peak = max(hour["delivered_u"] or 0, hour["profile_u"] or 0)
        ax.annotate("▲", (hour["hour"], peak + headroom * 0.02),
                    ha="center", va="bottom", fontsize=7, color=INK_PRIMARY,
                    zorder=4)

    _hour_axis(ax, every=1)
    flagged = {h["hour"] for h in hours if h["flag"]}
    for label in ax.get_xticklabels():
        if int(label.get_text()) in flagged:
            label.set_color(INK_PRIMARY)
            label.set_fontweight("bold")

    if title:
        ax.set_title(title, color=INK_PRIMARY, fontsize=10, loc="left", pad=24)

    handles = list(ax.containers)
    if any(not h["n_days"] for h in hours):
        handles.append(Patch(facecolor=TARGET_BAND,
                             label="keine auswertbaren Tage"))
    _legend(ax, handles=handles, ncol=len(handles))
    if not any(h["n_days"] for h in hours):
        _no_data(ax, "Noch keine auswertbaren Stunden — siehe Datenqualität")
    return _save(fig, path)


def hypo_chart(rows, path, target_low=70, title=None):
    """Share of readings below target, per hour of day. One series, one hue."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    _style(ax, f"Anteil < {target_low} mg/dL (%)")

    values = [r["low_pct"] or 0 for r in rows if r] or [0] * 24
    ax.bar(range(24), values, 0.6, color=SERIES_DELIVERED, zorder=3)

    # A day with no hypos at all is the good case, not an error: keep a
    # sensible axis and skip the annotation rather than indexing for a peak
    # that does not exist.
    peak = max(values)
    ax.set_ylim(0, max(peak * 1.2, 1.0))

    # Direct-label the worst hour only; the axis carries the rest.
    if peak > 0:
        worst = values.index(peak)
        ax.annotate(f"{peak:.1f}%", (worst, peak), ha="center", va="bottom",
                    fontsize=8, color=INK_PRIMARY,
                    xytext=(0, 3), textcoords="offset points")

    _hour_axis(ax)
    if title:
        ax.set_title(title, color=INK_PRIMARY, fontsize=10, loc="left", pad=8)
    # Single series: the title names it, so no legend box.
    return _save(fig, path)
