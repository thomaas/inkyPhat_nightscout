import numpy as np
import pytest

import matplotLibActions


def _count_red_pixels(img):
    arr = np.array(img)
    return int(((arr[:, :, 0] > 200) & (arr[:, :, 1] < 80) & (arr[:, :, 2] < 80)).sum())


class TestStarsForTir:
    @pytest.mark.parametrize("tir, expected", [
        (0, ""),
        (50, ""),
        (69, ""),
        (70, "★"),
        (75, "★"),
        (79, "★"),
        (80, "★★"),
        (89, "★★"),
        (90, "★★★"),
        (100, "★★★"),
    ])
    def test_thresholds(self, tir, expected):
        assert matplotLibActions._stars_for_tir(tir) == expected


class TestRender:
    def test_returns_correct_dimensions_without_pump(self, glucose_payload):
        img = matplotLibActions.render(glucose_payload, None, 70, 180)
        assert img.size == (matplotLibActions.WIDTH, matplotLibActions.HEIGHT)
        assert img.mode == "RGB"

    def test_returns_correct_dimensions_with_pump(self, glucose_payload, pump_payload):
        img = matplotLibActions.render(glucose_payload, pump_payload, 70, 180)
        assert img.size == (matplotLibActions.WIDTH, matplotLibActions.HEIGHT)
        assert img.mode == "RGB"

    def test_uses_red_pixels_for_out_of_range_value(self, glucose_payload):
        glucose_payload["current_glucose"]["value"] = 245
        img = matplotLibActions.render(glucose_payload, None, 70, 180)
        # The huge red "245" plus the dashed red target lines should yield
        # a substantial number of red-ish pixels.
        assert _count_red_pixels(img) > 50

    def test_partial_pump_data_does_not_crash(self, glucose_payload):
        partial = {"iob": None, "last_bolus": None, "current_basal": 0.85}
        img = matplotLibActions.render(glucose_payload, partial, 70, 180)
        assert img.size == (matplotLibActions.WIDTH, matplotLibActions.HEIGHT)


class TestRenderSuspend:
    def test_returns_correct_dimensions(self, history_in_range):
        import dexcomCalls
        stats = dexcomCalls.timeInRangeStats(history_in_range, 70, 180)
        img = matplotLibActions.render_suspend(history_in_range, stats, 70, 180)
        assert img.size == (matplotLibActions.WIDTH, matplotLibActions.HEIGHT)
        assert img.mode == "RGB"

    def test_no_data_message(self):
        img = matplotLibActions.render_suspend([], None, 70, 180)
        assert img.size == (matplotLibActions.WIDTH, matplotLibActions.HEIGHT)

    def test_fireworks_draw_red_pixels_for_high_tir(self, history_in_range):
        import dexcomCalls
        stats = dexcomCalls.timeInRangeStats(history_in_range, 70, 180)
        img = matplotLibActions.render_suspend(history_in_range, stats, 70, 180)
        # Top 20px hosts fireworks bursts and lies above the in-range data line
        top_strip = img.crop((0, 0, img.width, 20))
        assert _count_red_pixels(top_strip) > 10, "expected fireworks bursts in top strip"


class TestSensorBadge:
    def _make_pump(self, remaining_hours):
        return {
            "iob": 1.0,
            "last_bolus": None,
            "current_basal": 1.0,
            "sensor": {"type": "G7", "remaining_hours": remaining_hours},
        }

    def test_no_badge_when_no_pump_data(self, glucose_payload):
        img = matplotLibActions.render(glucose_payload, None, 70, 180, sensor_warning_days=3)
        top_strip = img.crop((100, 0, 212, 15))
        # No red badge area should appear in the top-right when there's no pump data
        assert _count_red_pixels(top_strip) < 30  # only the dashed target line crosses

    def test_no_badge_when_sensor_above_threshold(self, glucose_payload):
        pump = self._make_pump(remaining_hours=240)  # 10 days
        img = matplotLibActions.render(glucose_payload, pump, 70, 180, sensor_warning_days=3)
        # Without a badge, the corner (top-right of plot area) is plot background only.
        # Sample a tight rectangle that the badge would occupy.
        corner = img.crop((100, 0, 130, 14))
        assert _count_red_pixels(corner) == 0

    def test_badge_appears_when_sensor_at_two_days(self, glucose_payload):
        pump = self._make_pump(remaining_hours=48)
        img = matplotLibActions.render(glucose_payload, pump, 70, 180, sensor_warning_days=3)
        corner = img.crop((100, 0, 130, 14))
        # The badge is a small red rectangle — should produce a substantial red blob
        assert _count_red_pixels(corner) > 30

    def test_badge_uses_hours_below_one_day(self, glucose_payload):
        pump = self._make_pump(remaining_hours=18)
        img = matplotLibActions.render(glucose_payload, pump, 70, 180, sensor_warning_days=3)
        corner = img.crop((100, 0, 130, 14))
        assert _count_red_pixels(corner) > 30


class TestDrawBurst:
    def test_burst_renders_red_lines(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (40, 40), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        matplotLibActions._draw_burst(draw, 20, 20, 5)
        # 4 lines × variable lengths should produce at least 20 red pixels
        assert _count_red_pixels(img) >= 20
