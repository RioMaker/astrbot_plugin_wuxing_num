from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import calculate  # noqa: E402
from renderer import ELEMENT_STYLE, WuxingChartRenderer  # noqa: E402
import renderer as renderer_module  # noqa: E402


def test_renderer_creates_modern_png(tmp_path) -> None:
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
        ("前期消息影响条件落实与能力发挥，最终需要明确确认资源安排。" * 8, 1120, 2, 28, 22),
        ("事业成长需要资源承接与规则确认" * 8, 1252, 3, 26, 22),
        ("消息出现机会启动能力成长资源承接规则落定继续前进", 224, 2, 21, 15),
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
    except Exception as exc:
        assert "五条" in str(exc)
    else:
        raise AssertionError("incomplete symbolism should be rejected")


def test_missing_icon_asset_still_renders(tmp_path, monkeypatch) -> None:
    def missing():
        raise FileNotFoundError("icon strip absent")

    monkeypatch.setattr(renderer_module, "load_icons", missing)
    output = WuxingChartRenderer().render(
        calculate("测试", "13254", "水"),
        question="测试", matter_type="综合",
        symbolic_meanings=("起因", "承接", "转折", "落实", "归结"),
        symbolic_summary="素材丢失时仍显示五行流转。",
        output_path=tmp_path / "fallback.png",
    )
    with Image.open(output) as image:
        assert image.size == (1440, 1900)
