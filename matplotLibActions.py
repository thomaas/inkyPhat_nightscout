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
PLOT_WIDTH_WITHOUT_PUMP = 170

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
    ax.tick_params(axis="y", labelsize=5, length=0, pad=1)
    ax.tick_params(axis="x", labelsize=5, length=0, pad=1)

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
    font = _font(11)

    if not stats:
        bbox = draw.textbbox((0, 0), "No data today", font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((WIDTH - tw) // 2,
                   plot_h + (HEIGHT - plot_h - th) // 2),
                  "No data today", fill=BLACK, font=font)
        return canvas

    stars = _stars_for_tir(stats["tir_pct"])
    body = f"TIR {stats['tir_pct']}%   ø {stats['avg']}   ↓ {stats['low_pct']}%   ↑ {stats['high_pct']}%"

    body_bbox = draw.textbbox((0, 0), body, font=font)
    body_w = body_bbox[2] - body_bbox[0]
    body_h = body_bbox[3] - body_bbox[1]

    if stars:
        prefix = f"{stars} "
        prefix_bbox = draw.textbbox((0, 0), prefix, font=font)
        prefix_w = prefix_bbox[2] - prefix_bbox[0]
        total_w = prefix_w + body_w
        x = (WIDTH - total_w) // 2
        y = plot_h + (HEIGHT - plot_h - body_h) // 2
        draw.text((x, y), prefix, fill=RED, font=font)
        draw.text((x + prefix_w, y), body, fill=BLACK, font=font)
    else:
        x = (WIDTH - body_w) // 2
        y = plot_h + (HEIGHT - plot_h - body_h) // 2
        draw.text((x, y), body, fill=BLACK, font=font)

    return canvas


def _stars_for_tir(tir_pct):
    if tir_pct >= 90:
        return "★★★"
    if tir_pct >= 80:
        return "★★"
    if tir_pct >= 70:
        return "★"
    return ""


def _render_day_plot(history, target_low, target_high, width, height):
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes([0.08, 0.13, 0.90, 0.85])

    timestamps = [e["timestamp"] for e in history]
    values = [e["value"] for e in history]

    ax.set_ylim(40, 280)
    ax.set_yticks([target_low, target_high])
    ax.tick_params(axis="y", labelsize=5, length=0, pad=1)
    ax.tick_params(axis="x", labelsize=5, length=0, pad=1)

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
    font = _font(9)
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
        line(1, "Bolus", f"{bolus['units']:.1f}U {when}")
    else:
        line(1, "Bolus", "—")
    line(2, "Basal", f"{basal:.2f}" if basal is not None else "—")


def _draw_glucose_panel(canvas, glucose, target_low, target_high, x, y, w, h, compact):
    draw = ImageDraw.Draw(canvas)
    current = glucose["current_glucose"]
    value = current["value"]
    value_color = BLACK if target_low <= value <= target_high else RED

    big = _font(18 if compact else 24)
    medium = _font(11 if compact else 14)
    small = _font(8)

    value_str = str(value)
    arrow = current["trend"]
    delta = current["delta"]
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    time_str = current["timestamp"].strftime("%H:%M")

    pad = 2
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
    bottom_y = y + h - th - pad
    draw.text((cx - tw // 2, bottom_y), time_str, fill=BLACK, font=small)
