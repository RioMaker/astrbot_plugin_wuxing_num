from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import calculate  # noqa: E402
from renderer import ELEMENT_STYLE, WuxingChartRenderer  # noqa: E402
import renderer as renderer_module  # noqa: E402


def test_renderer_creates_palace_style_png(tmp_path) -> None:
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
        # All five positions contain the white icon medallion, not an empty
        # flat-colour palace. This also covers glyph pasting on the PNG canvas.
        for cx, cy in [(720, 590), (1080, 785), (940, 1120), (500, 1120), (360, 785)]:
            assert image.getpixel((cx - 51, cy - 66)) == (255, 255, 255)


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
