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

# Info (glucose value + pump data) lives on the left, the graph on the right.
INFO_WIDTH = 116
GRAPH_WIDTH = WIDTH - INFO_WIDTH

_FONT_PATH = os.path.join(
    os.path.dirname(matplotlib.__file__),
    "mpl-data", "fonts", "ttf", "DejaVuSans-Bold.ttf",
)


def _font(size):
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except (OSError, IOError):
        return ImageFont.load_default()


def render(glucose, pump_data, target_low, target_high, sensor_warning_days=3):
    canvas = Image.new("RGB", (WIDTH, HEIGHT), WHITE)

    graph_x = INFO_WIDTH

    # Easter egg: a perfect 100 earns a unicorn in place of the graph. 🦄
    if glucose["current_glucose"]["value"] == 100:
        _draw_unicorn(canvas, graph_x, 0, GRAPH_WIDTH, HEIGHT)
    else:
        plot_img = _render_plot(
            glucose["glucose_history"], target_low, target_high, GRAPH_WIDTH, HEIGHT
        )
        canvas.paste(plot_img, (graph_x, 0))

        if pump_data:
            _draw_sensor_badge(
                canvas, pump_data.get("sensor"), graph_x, GRAPH_WIDTH, sensor_warning_days
            )

    _draw_info_panel(
        canvas, glucose, pump_data, target_low, target_high,
        0, 0, INFO_WIDTH, HEIGHT,
    )

    return canvas


def _draw_sensor_badge(canvas, sensor, graph_x, graph_w, threshold_days):
    if not sensor:
        return
    hours = sensor.get("remaining_hours")
    if hours is None or hours / 24 > threshold_days:
        return

    # Always show exact hours in the warning zone — avoids floor-rounding
    # surprises like "S 2d" for what's actually 70 hours / nearly 3 days.
    text = f"S {int(round(hours))}h"

    draw = ImageDraw.Draw(canvas)
    font = _font(9)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 2, 1
    box_x = graph_x + graph_w - tw - 2 * pad_x - 2
    box_y = 2
    draw.rectangle(
        (box_x, box_y, box_x + tw + 2 * pad_x, box_y + th + 2 * pad_y),
        fill=RED,
    )
    draw.text((box_x + pad_x, box_y + pad_y - 1), text, fill=WHITE, font=font)


def _draw_unicorn(canvas, x, y, w, h):
    """A little cartoon unicorn: black silhouette with a red horn, mane and tail.

    Drawn from relative coordinates so it scales to whatever box it's given.
    Shown as a treat when glucose lands on a perfect 100.
    """
    draw = ImageDraw.Draw(canvas)

    def P(fx, fy):
        return (x + fx * w, y + fy * h)

    def box(fx0, fy0, fx1, fy1):
        return [P(fx0, fy0), P(fx1, fy1)]

    # Body and head.
    draw.ellipse(box(0.30, 0.42, 0.82, 0.74), fill=BLACK)
    draw.ellipse(box(0.08, 0.30, 0.36, 0.52), fill=BLACK)
    # Neck joining head to body.
    draw.polygon([P(0.18, 0.40), P(0.40, 0.38), P(0.56, 0.66), P(0.30, 0.70)], fill=BLACK)
    # Snout poking forward-left.
    draw.ellipse(box(0.04, 0.40, 0.18, 0.52), fill=BLACK)

    # Legs.
    leg_w = 0.055 * w
    for fx in (0.36, 0.48, 0.62, 0.74):
        lx = x + fx * w
        draw.rectangle([lx, y + 0.66 * h, lx + leg_w, y + 0.96 * h], fill=BLACK)

    # Flowing tail, pointed horn and a mane down the neck — all in red.
    draw.polygon(
        [P(0.79, 0.44), P(0.93, 0.36), P(0.99, 0.58), P(0.88, 0.82), P(0.80, 0.62)],
        fill=RED,
    )
    draw.polygon([P(0.17, 0.30), P(0.25, 0.30), P(0.12, 0.02)], fill=RED)
    draw.polygon(
        [P(0.27, 0.26), P(0.39, 0.32), P(0.50, 0.56), P(0.40, 0.54), P(0.30, 0.40)],
        fill=RED,
    )

    # Pointy ear and an eye.
    draw.polygon([P(0.27, 0.30), P(0.35, 0.30), P(0.31, 0.14)], fill=BLACK)
    draw.ellipse(box(0.15, 0.37, 0.20, 0.43), fill=WHITE)


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


def _draw_info_panel(canvas, glucose, pump, target_low, target_high, x, y, w, h):
    draw = ImageDraw.Draw(canvas)
    current = glucose["current_glucose"]
    value = current["value"]
    value_color = BLACK if target_low <= value <= target_high else RED

    big = _font(42)
    arrow_font = _font(22)
    medium = _font(15)
    pump_font = _font(13)

    value_str = str(value)
    arrow = current["trend"]
    delta = current["delta"]
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    time_str = current["timestamp"].strftime("%H:%M")

    pad = 3

    def textsize(text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Big glucose value, top-left — nudged up a touch to give it more room.
    vw, vh = textsize(value_str, big)
    vy = y + 1
    draw.text((x + pad, vy), value_str, fill=value_color, font=big)

    # Trend arrow to the right of the value, vertically centered on it.
    _, ah = textsize(arrow, arrow_font)
    ay = vy + (vh - ah) // 2
    draw.text((x + pad + vw + 5, ay), arrow, fill=RED, font=arrow_font)

    # Delta change + time of reading on the next line, with a little breathing room.
    line_y = vy + vh + 8
    dw, dh = textsize(delta_str, medium)
    draw.text((x + pad, line_y), delta_str, fill=BLACK, font=medium)
    draw.text((x + pad + dw + 10, line_y), time_str, fill=BLACK, font=medium)

    if not pump:
        return

    # Pump details stacked underneath.
    py = line_y + dh + 6
    plh = 16

    iob = pump.get("iob")
    bolus = pump.get("last_bolus")
    basal = pump.get("current_basal")

    draw.text(
        (x + pad, py),
        f"IOB {iob:.1f}U" if iob is not None else "IOB —",
        fill=BLACK, font=pump_font,
    )
    if bolus is not None:
        mins = bolus.get("minutes_ago", 0)
        when = f"{mins}m" if mins < 60 else f"{mins // 60}h"
        bol_text = f"Bol {bolus['units']:.1f}U {when}"
    else:
        bol_text = "Bol —"
    draw.text((x + pad, py + plh), bol_text, fill=BLACK, font=pump_font)
    draw.text(
        (x + pad, py + 2 * plh),
        f"Bas {basal:.2f}" if basal is not None else "Bas —",
        fill=BLACK, font=pump_font,
    )
