import math
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageColor, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import renderer as renderer_module  # noqa: E402
from engine import calculate  # noqa: E402
from renderer import ELEMENT_STYLE, WuxingChartRenderer  # noqa: E402


def test_renderer_creates_ink_dark_png(tmp_path) -> None:
    renderer = WuxingChartRenderer()
    result = calculate("这次求职能否成功", "13254", "木")
    output = tmp_path / "wuxing.png"

    rendered = renderer.render(
        result,
        question="这次求职能否成功",
        matter_type="事业求职",
        symbolic_meanings=(
            "消息与机会起念",
            "能力持续生长",
            "行动进入显化",
            "资源逐步承接",
            "规则促成落定",
        ),
        symbolic_summary="五行顺势相生，机会由消息萌发，经行动与资源承接，最终进入规则确认。",
        output_path=output,
    )

    assert rendered == output.resolve()
    assert output.stat().st_size > 40_000
    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == (1440, 1900)


def test_watermarks_are_faint_and_have_no_white_background():
    renderer = WuxingChartRenderer()
    for element, style in ELEMENT_STYLE.items():
        canvas = Image.new("RGB", (320, 320), style["fill"])
        original = canvas.copy()
        renderer._watermark(canvas, (160, 160), element)
        difference = ImageChops.difference(original, canvas)
        assert difference.getbbox() is not None
        # A maximum 13% blend changes each channel by at most 34 levels.
        assert all(high <= 34 for low, high in difference.getextrema())
        assert renderer._icons[element].getchannel("A").getextrema() == (0, 255)
        assert canvas.getpixel((0, 0)) == original.getpixel((0, 0))


def test_long_chinese_text_fits_reserved_regions():
    renderer = WuxingChartRenderer()
    draw = ImageDraw.Draw(Image.new("RGB", (1440, 1900)))
    for text, width, count, maximum, minimum in (
        (
            "前期消息影响条件落实与能力发挥，最终需要明确确认资源安排。" * 8,
            1220,
            2,
            36,
            26,
        ),
        ("事业成长需要资源承接与规则确认" * 8, 970, 3, 25, 22),
        ("消息出现机会启动能力成长资源承接规则落定继续前进", 208, 2, 26, 20),
    ):
        lines, font = renderer._fit(draw, text, width, count, maximum, minimum)
        assert len(lines) <= count
        assert all(draw.textlength(line, font=font) <= width for line in lines)
        assert all(line[0] not in "，。；：" for line in lines)


def test_each_element_has_distinct_color_and_pattern() -> None:
    fills = {style["fill"] for style in ELEMENT_STYLE.values()}
    patterns = {style["pattern"] for style in ELEMENT_STYLE.values()}
    assert len(fills) == 5
    assert len(patterns) == 5


def test_renderer_rejects_incomplete_symbolism(tmp_path) -> None:
    renderer = WuxingChartRenderer()
    result = calculate("测试", "13254", "水")
    try:
        renderer.render(
            result,
            question="测试",
            matter_type="综合",
            symbolic_meanings=("只有一条",),
            symbolic_summary="不完整",
            output_path=tmp_path / "bad.png",
        )
    except renderer_module.ChartRenderError as exc:
        assert "五条" in str(exc)
    else:
        raise AssertionError("incomplete symbolism should be rejected")


def test_missing_icon_asset_still_renders(tmp_path, monkeypatch) -> None:
    def missing():
        raise FileNotFoundError("icon strip absent")

    monkeypatch.setattr(renderer_module, "load_icons", missing)
    output = WuxingChartRenderer().render(
        calculate("测试", "13254", "水"),
        question="测试",
        matter_type="综合",
        symbolic_meanings=("起因", "承接", "转折", "落实", "归结"),
        symbolic_summary="素材丢失时仍显示五行流转。",
        output_path=tmp_path / "fallback.png",
    )
    with Image.open(output) as image:
        assert image.size == (1440, 1900)


@pytest.mark.parametrize(
    "name,verdict,reason",
    [
        ("success", "成", ""),
        ("failure", "败", ""),
        ("dead", "死卦", "根气不现"),
        ("blocked", "死卦", "根气被截"),
        ("long", "死卦", "根气不现"),
    ],
)
def test_actual_text_and_digit_order_for_all_preview_cases(
    tmp_path, monkeypatch, name, verdict, reason
):
    from tools.preview import CASES, render_case

    drawn = []
    original = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        drawn.append((xy, text))
        bounds = self.textbbox(
            xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor")
        )
        assert 0 <= bounds[0] <= bounds[2] <= renderer_module.WIDTH
        assert 0 <= bounds[1] <= bounds[3] <= renderer_module.HEIGHT
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    render_case(WuxingChartRenderer(), name, tmp_path / f"{name}.png")
    texts = [text for _, text in drawn]
    case = CASES[name]
    result = calculate(case["question"], case["numbers"], case["root"])
    assert result.verdict == verdict
    assert result.dead_reason == reason
    assert "五行数字卦" in texts
    assert "五行气脉仪" not in texts
    assert verdict in texts
    assert Counter(
        text for text in texts if len(text) == 1 and text.isdigit()
    ) == Counter(case["numbers"])
    digits = [(xy, text) for xy, text in drawn if len(text) == 1 and text.isdigit()]
    for (xy, digit), (cx, cy), expected in zip(
        digits, renderer_module.CENTERS, case["numbers"]
    ):
        assert digit == expected
        assert xy == (cx, cy - 35)
    assert Counter(t.name for t in result.transitions) == Counter(
        text for text in texts if text in renderer_module.RELATION_STYLE
    )
    assert (
        f"{case['root']} · 阳" in texts
        or f"{case['root']} · 阴" in texts
        or reason == "根气不现"
    )
    assert "象意 · 演示象意 · 非实时模型" in texts
    if reason:
        assert reason in texts
    if name == "long":
        assert any(text.endswith("…") for text in texts)
        assert "阳 0  /  阴 5" in texts


def test_orbit_paths_are_clockwise_and_clear_of_nodes():
    renderer = WuxingChartRenderer()
    for index in range(5):
        points = renderer._arc_points(index)
        for point, node in (
            (points[0], renderer_module.CENTERS[index]),
            (points[-1], renderer_module.CENTERS[(index + 1) % 5]),
        ):
            assert math.dist(point, node) > renderer_module.NODE_RADIUS + 10
        for a, b in pairwise(points):
            rx, ry = (
                a[0] - renderer_module.ORBIT_CENTER[0],
                a[1] - renderer_module.ORBIT_CENTER[1],
            )
            # Positive cross product means clockwise in screen (downward-y) coordinates.
            assert rx * (b[1] - a[1]) - ry * (b[0] - a[0]) > 0


def test_full_relation_labels_never_cover_their_arrows():
    renderer = WuxingChartRenderer()
    draw = ImageDraw.Draw(
        Image.new("RGB", (renderer_module.WIDTH, renderer_module.HEIGHT))
    )
    for index, angle in enumerate(renderer_module.ANGLES):
        xy = renderer_module.orbit_point(angle + 36, renderer_module.ORBIT_RADIUS + 76)
        box = draw.textbbox(xy, "受克阻断", font=renderer._font(24), anchor="mm")
        for x, y in renderer._arc_points(index):
            assert not (box[0] - 6 <= x <= box[2] + 6 and box[1] - 6 <= y <= box[3] + 6)


def test_dark_text_palette_has_readable_contrast():
    def luminance(color):
        channels = [value / 255 for value in ImageColor.getrgb(color)]
        channels = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return sum(
            value * weight for value, weight in zip(channels, (0.2126, 0.7152, 0.0722))
        )

    # Lightest background field plus each dark element surface.
    backgrounds = ["#172D35", *(style["fill"] for style in ELEMENT_STYLE.values())]
    for background in backgrounds:
        for foreground in (renderer_module.INK, renderer_module.MUTED):
            assert (luminance(foreground) + 0.05) / (
                luminance(background) + 0.05
            ) >= 4.5


def test_bloom_is_visible_outside_the_stroke_and_scales_with_energy():
    from visual_effects import luminous_path

    values = []
    for energy in (0, 0.2, 1):
        canvas = Image.new("RGB", (320, 240), "#091219")
        luminous_path(
            canvas,
            [(60, 120), (260, 120)],
            "#8CCDE2",
            energy=energy,
            emission="#39B6F4",
        )
        values.append(sum(canvas.getpixel((160, 130))))
    assert values[0] < values[1] < values[2]
    assert values[2] - values[0] > 35  # Actual visible halo, not only a brighter core.


def test_blocked_dashed_stroke_does_not_emit_false_flow():
    from visual_effects import luminous_path

    canvas = Image.new("RGB", (320, 240), "#091219")
    luminous_path(
        canvas,
        [(60 + i * 2.5, 120) for i in range(81)],
        "#E69C9F",
        dashed=True,
        energy=0,
    )
    assert canvas.getpixel((160, 135)) == ImageColor.getrgb("#091219")


@pytest.mark.parametrize("corrupt", [False, True])
def test_background_asset_failure_has_a_local_fallback(tmp_path, monkeypatch, corrupt):
    asset = tmp_path / "missing.png"
    if corrupt:
        asset.write_bytes(b"invalid PNG fixture")
    monkeypatch.setattr(renderer_module, "BACKGROUND_PATH", asset)
    background = WuxingChartRenderer._background()
    assert background.size == (1440, 1900)
    assert background.mode == "RGB"


def test_packaged_background_is_loaded_not_flat_fallback(monkeypatch):
    assert renderer_module.BACKGROUND_PATH.is_file()

    def unexpected_fallback():
        raise AssertionError("packaged landscape was not loaded")

    monkeypatch.setattr(
        WuxingChartRenderer, "_fallback_background", unexpected_fallback
    )
    assert WuxingChartRenderer._background().size == (1440, 1900)
