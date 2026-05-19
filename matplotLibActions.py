import io
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont


WIDTH = 212
HEIGHT = 104

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)

PLOT_WIDTH_WITH_PUMP = 130
PLOT_WIDTH_WITHOUT_PUMP = 158

_FONT_PATH = os.path.join(
    os.path.dirname(matplotlib.__file__),
    "mpl-data", "fonts", "ttf", "DejaVuSans-Bold.ttf",
)


def _font(size):
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except (OSError, IOError):
        return ImageFont.load_default()


def render(glucose, pump_data, target_low, target_high):
    plot_w = PLOT_WIDTH_WITH_PUMP if pump_data else PLOT_WIDTH_WITHOUT_PUMP

    canvas = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    plot_img = _render_plot(
        glucose["glucose_history"], target_low, target_high, plot_w, HEIGHT
    )
    canvas.paste(plot_img, (0, 0))

    panel_x = plot_w
    panel_w = WIDTH - plot_w

    if pump_data:
        half = HEIGHT // 2
        _draw_pump_panel(canvas, pump_data, panel_x, 0, panel_w, half)
        _draw_glucose_panel(
            canvas, glucose, target_low, target_high,
            panel_x, half, panel_w, HEIGHT - half, compact=True,
        )
    else:
        _draw_glucose_panel(
            canvas, glucose, target_low, target_high,
            panel_x, 0, panel_w, HEIGHT, compact=False,
        )

    return canvas


def _render_plot(history, target_low, target_high, width, height):
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes([0.13, 0.13, 0.85, 0.85])

    timestamps = [e["timestamp"] for e in history]
    values = [e["value"] for e in history]

    ax.set_ylim(40, 280)
    ax.set_yticks([target_low, target_high])
    ax.tick_params(axis="y", labelsize=6, length=0, pad=1)
    ax.tick_params(axis="x", labelsize=6, length=0, pad=1)

    ax.xaxis.set_major_locator(mdates.HourLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))

    ax.axhspan(target_low, target_high, facecolor="#DDDDDD", zorder=0)
    ax.axhline(target_low, color="red", linestyle="--", linewidth=0.6, zorder=1)
    ax.axhline(target_high, color="red", linestyle="--", linewidth=0.6, zorder=1)

    ax.plot(timestamps, values, color="black", linewidth=1.0, zorder=2)
    ax.plot(timestamps[-1], values[-1], "ko", markersize=3, zorder=3)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#888888")
    ax.spines["bottom"].set_color("#888888")
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color("#333333")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGB")
    if img.size != (width, height):
        img = img.resize((width, height))
    return img


def render_suspend(history, stats, target_low, target_high):
    canvas = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    plot_h = 80
    plot_img = _render_day_plot(history, target_low, target_high, WIDTH, plot_h)
    canvas.paste(plot_img, (0, 0))

    draw = ImageDraw.Draw(canvas)
    body_font = _font(10)

    if not stats:
        bbox = draw.textbbox((0, 0), "No data today", font=body_font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((WIDTH - tw) // 2,
                   plot_h + (HEIGHT - plot_h - th) // 2),
                  "No data today", fill=BLACK, font=body_font)
        return canvas

    _draw_fireworks(draw, stats["tir_pct"])

    stars = _stars_for_tir(stats["tir_pct"])
    body = f"TIR {stats['tir_pct']}%  ø {stats['avg']}  ↓ {stats['low_pct']}%  ↑ {stats['high_pct']}%"

    body_bbox = draw.textbbox((0, 0), body, font=body_font)
    body_w = body_bbox[2] - body_bbox[0]
    body_h = body_bbox[3] - body_bbox[1]

    if stars:
        star_font = _font(14)
        prefix = f"{stars} "
        sbbox = draw.textbbox((0, 0), prefix, font=star_font)
        prefix_w = sbbox[2] - sbbox[0]
        prefix_h = sbbox[3] - sbbox[1]
        total_w = prefix_w + body_w
        x = (WIDTH - total_w) // 2
        # Baseline-align: heights differ, but a common baseline keeps it tidy.
        star_ascent = star_font.getmetrics()[0]
        body_ascent = body_font.getmetrics()[0]
        y_stars = plot_h + (HEIGHT - plot_h - prefix_h) // 2
        y_body = y_stars + (star_ascent - body_ascent)
        draw.text((x, y_stars), prefix, fill=RED, font=star_font)
        draw.text((x + prefix_w, y_body), body, fill=BLACK, font=body_font)
    else:
        x = (WIDTH - body_w) // 2
        y = plot_h + (HEIGHT - plot_h - body_h) // 2
        draw.text((x, y), body, fill=BLACK, font=body_font)

    return canvas


def _stars_for_tir(tir_pct):
    if tir_pct >= 90:
        return "★★★"
    if tir_pct >= 80:
        return "★★"
    if tir_pct >= 70:
        return "★"
    return ""


def _draw_burst(draw, cx, cy, radius, color=RED):
    r = radius
    draw.line([(cx - r, cy), (cx + r, cy)], fill=color)
    draw.line([(cx, cy - r), (cx, cy + r)], fill=color)
    d = max(1, int(r * 0.65))
    draw.line([(cx - d, cy - d), (cx + d, cy + d)], fill=color)
    draw.line([(cx - d, cy + d), (cx + d, cy - d)], fill=color)


def _draw_fireworks(draw, tir_pct):
    if tir_pct >= 90:
        bursts = [
            (16, 7, 5), (46, 16, 3), (90, 5, 5), (130, 13, 3),
            (175, 6, 4), (200, 17, 3), (10, 72, 3), (202, 72, 3),
        ]
    elif tir_pct >= 80:
        bursts = [
            (20, 8, 4), (90, 5, 4), (180, 8, 4), (45, 18, 3),
        ]
    elif tir_pct >= 70:
        bursts = [
            (16, 8, 3), (196, 8, 3),
        ]
    else:
        return
    for cx, cy, size in bursts:
        _draw_burst(draw, cx, cy, size)


def _render_day_plot(history, target_low, target_high, width, height):
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes([0.08, 0.13, 0.90, 0.85])

    timestamps = [e["timestamp"] for e in history]
    values = [e["value"] for e in history]

    ax.set_ylim(40, 280)
    ax.set_yticks([target_low, target_high])
    ax.tick_params(axis="y", labelsize=6, length=0, pad=1)
    ax.tick_params(axis="x", labelsize=6, length=0, pad=1)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))

    ax.axhspan(target_low, target_high, facecolor="#DDDDDD", zorder=0)
    ax.axhline(target_low, color="red", linestyle="--", linewidth=0.6, zorder=1)
    ax.axhline(target_high, color="red", linestyle="--", linewidth=0.6, zorder=1)

    ax.plot(timestamps, values, color="black", linewidth=1.0, zorder=2)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#888888")
    ax.spines["bottom"].set_color("#888888")
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color("#333333")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGB")
    if img.size != (width, height):
        img = img.resize((width, height))
    return img


def _draw_pump_panel(canvas, pump, x, y, w, h):
    draw = ImageDraw.Draw(canvas)
    font = _font(11)
    line_h = h // 3
    pad = 2

    def line(idx, label, value):
        draw.text(
            (x + pad, y + idx * line_h),
            f"{label}: {value}", fill=BLACK, font=font,
        )

    iob = pump.get("iob")
    bolus = pump.get("last_bolus")
    basal = pump.get("current_basal")

    line(0, "IOB", f"{iob:.1f}U" if iob is not None else "—")
    if bolus is not None:
        mins = bolus.get("minutes_ago", 0)
        when = f"{mins}m" if mins < 60 else f"{mins // 60}h"
        line(1, "Bol", f"{bolus['units']:.1f}U {when}")
    else:
        line(1, "Bol", "—")
    line(2, "Bas", f"{basal:.2f}" if basal is not None else "—")


def _draw_glucose_panel(canvas, glucose, target_low, target_high, x, y, w, h, compact):
    draw = ImageDraw.Draw(canvas)
    current = glucose["current_glucose"]
    value = current["value"]
    value_color = BLACK if target_low <= value <= target_high else RED

    big = _font(20 if compact else 28)
    medium = _font(13 if compact else 16)
    small = _font(10)

    value_str = str(value)
    arrow = current["trend"]
    delta = current["delta"]
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    time_str = current["timestamp"].strftime("%H:%M")

    pad = 2
    bottom_pad = 4
    cx = x + w // 2

    def textsize(text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    vw, vh = textsize(value_str, big)
    draw.text((cx - vw // 2, y + pad), value_str, fill=value_color, font=big)

    middle_y = y + pad + vh + 1
    aw, ah = textsize(arrow, medium)
    dw, dh = textsize(delta_str, medium)
    gap = 3
    total_w = aw + gap + dw
    start_x = cx - total_w // 2
    draw.text((start_x, middle_y), arrow, fill=RED, font=medium)
    draw.text((start_x + aw + gap, middle_y), delta_str, fill=BLACK, font=medium)

    tw, th = textsize(time_str, small)
    bottom_y = y + h - th - bottom_pad
    draw.text((cx - tw // 2, bottom_y), time_str, fill=BLACK, font=small)
