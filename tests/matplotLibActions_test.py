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


class TestDrawBurst:
    def test_burst_renders_red_lines(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (40, 40), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        matplotLibActions._draw_burst(draw, 20, 20, 5)
        # 4 lines × variable lengths should produce at least 20 red pixels
        assert _count_red_pixels(img) >= 20
