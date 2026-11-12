import pytest
from PIL import Image, ImageDraw

from engine_v2 import calculate_v2
from reading import build_reading, build_symbolism
from renderer import WuxingChartRenderer


@pytest.mark.parametrize(
    "numbers,root,verdict",
    [
        ("15997", "水", "成"),
        ("55287", "金", "待定"),
        ("12759", "水", "败"),
        ("34852", "木", "成"),
    ],
)
def test_new_kernel_chart_contains_trace_without_legacy_scoring(
    tmp_path, monkeypatch, numbers, root, verdict
):
    drawn = []
    original = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        box = self.textbbox(
            xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor")
        )
        assert 0 <= box[0] <= box[2] <= self._image.width
        assert 0 <= box[1] <= box[3] <= self._image.height
        drawn.append(text)
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    result = calculate_v2("这次计划能否达成", numbers, root)
    assert result.verdict == verdict
    symbols = build_symbolism(result)
    renderer = WuxingChartRenderer()

    def forbid_legacy_edges(*args):
        pytest.fail("v2 must not draw legacy score arrows")

    monkeypatch.setattr(renderer, "_relation", forbid_legacy_edges)
    path = renderer.render(
        result,
        question="这次计划能否达成",
        matter_type=symbols.matter_type,
        symbolic_meanings=symbols.meanings,
        symbolic_summary=symbols.summary,
        analysis_text=build_reading(result),
        output_path=tmp_path / "new.png",
    )
    text = "".join(drawn)
    assert "根气" not in text and "总分" not in text and "成局不足" not in text
    assert "原始数字映射" in text and "资料推演" in text
    with Image.open(path) as image:
        assert image.width == 1440 and 1900 < image.height <= 10000
