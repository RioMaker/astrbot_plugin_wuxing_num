"""The only command image includes the complete reading and local warnings."""

import asyncio
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw
from test_ai_daily import make_plugin
from test_main import _Event, _LlmContext

from engine import calculate
from renderer import ChartRenderError, WuxingChartRenderer
from tools.preview import render_case


def test_combined_chart_preserves_base_and_full_analysis(tmp_path, monkeypatch):
    renderer = WuxingChartRenderer()
    base = render_case(renderer, "success", tmp_path / "base.png")
    drawn = []
    original = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        bounds = self.textbbox(
            xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor")
        )
        assert 0 <= bounds[0] <= bounds[2] <= self._image.width
        assert 0 <= bounds[1] <= bounds[3] <= self._image.height
        if xy[1] >= 1930:
            drawn.append(text)
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    reading = "分析：水木承接，继续准备。" * 60 + "\n断语：必须完整保留。"
    warning = "警示：五行数字卦连续三次死卦，此事天机不可泄露。"
    from tools.preview import CASES

    values = CASES["success"].copy()
    result = calculate(values["question"], values.pop("numbers"), values.pop("root"))
    output = renderer.render(
        result,
        **values,
        analysis_text=reading,
        status_note=warning,
        output_path=tmp_path / "combined.png",
    )
    assert "".join(reading.splitlines()) + warning in "".join(drawn)
    with Image.open(base) as before, Image.open(output) as after:
        assert after.width == 1440 and after.height > 1900
        assert after.mode == "RGB"
        assert (
            ImageChops.difference(
                before.crop((0, 0, 1440, 1825)), after.crop((0, 0, 1440, 1825))
            ).getbbox()
            is None
        )


def test_oversize_reading_fails_without_truncating_or_creating_file(tmp_path):
    output = tmp_path / "oversize.png"
    with pytest.raises(ChartRenderError, match="超出单图容量"):
        WuxingChartRenderer().render(
            calculate("这次求职能否成功", "13254", "木"),
            question="这次求职能否成功",
            matter_type="事业求职",
            symbolic_meanings=("起因", "承接", "转折", "落实", "归结"),
            symbolic_summary="五行相生。",
            analysis_text="长正文需要完整显示。" * 900,
            output_path=output,
        )
    assert not output.exists()


@pytest.mark.parametrize("group", ["100", ""])
def test_command_sends_exactly_one_image_then_cleans_up(tmp_path, monkeypatch, group):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)
    renders, sent = [], []
    output = tmp_path / "combined.png"

    class Renderer:
        def render(self, result, **kwargs):
            renders.append(kwargs)
            output.write_bytes(b"simulated combined PNG")
            return output

    plugin.renderer = Renderer()
    event = _Event("/数字卦 13254 这次求职能否成功", group_id=group)

    async def send(message):
        assert output.is_file()  # Local file survives until the send completes.
        sent.append(message)

    monkeypatch.setattr(event, "send", send)

    async def run():
        assert [reply async for reply in plugin.number_divination(event)] == []

    asyncio.run(run())
    assert len(context.calls) == len(renders) == len(sent) == 1
    assert "程序解卦" in renders[0]["analysis_text"]
    assert "断语：" in renders[0]["analysis_text"]
    if group:
        assert sent[0]["chain"][0].qq == event.sender_id
        assert Path(sent[0]["chain"][1].image) == output
    else:
        assert sent[0] == {"image": str(output)}
    assert not output.exists()


def test_third_dead_warning_is_in_the_only_chart(tmp_path, monkeypatch):
    plugin, _ = make_plugin(
        tmp_path, monkeypatch, config={"command_ai_analysis_enabled": False}
    )
    captured = []

    async def render(*_args, **kwargs):
        captured.append(kwargs)
        return "卦图已发送"

    monkeypatch.setattr(plugin, "_render_and_send", render)

    async def run():
        for _ in range(3):
            event = _Event("/数字卦 这笔交易能谈成吗 | 12327 | 金")
            assert [reply async for reply in plugin.number_divination(event)] == []

    asyncio.run(run())
    assert "死卦次数：1/3" in captured[0]["status_note"]
    assert "连续三次死卦" in captured[2]["status_note"]
    assert "天机不可泄露" in captured[2]["status_note"]
    assert all("程序解卦" in item["analysis_text"] for item in captured)


def test_root_timeout_does_not_render_an_unconfirmed_chart(tmp_path, monkeypatch):
    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        context=_LlmContext(error=asyncio.TimeoutError()),  # noqa: UP041 - Python 3.10.
    )
    captured = []

    async def render(*_args, **kwargs):
        captured.append(kwargs)
        return "卦图已发送"

    monkeypatch.setattr(plugin, "_render_and_send", render)

    async def run():
        event = _Event("/数字卦 13254 这次求职能否成功")
        replies = [reply async for reply in plugin.number_divination(event)]
        assert "AI 取根气超时" in replies[0]["text"]

    asyncio.run(run())
    assert captured == []


def test_image_send_failure_returns_local_reading_and_cleans_file(
    tmp_path, monkeypatch
):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)
    output = tmp_path / "combined.png"

    class Renderer:
        def render(self, *_args, **_kwargs):
            output.write_bytes(b"simulated PNG")
            return output

    plugin.renderer = Renderer()
    event = _Event("/数字卦 13254 这次求职能否成功")

    async def failed_send(_message):
        raise RuntimeError("simulated platform failure")

    monkeypatch.setattr(event, "send", failed_send)

    async def run():
        replies = [item async for item in plugin.number_divination(event)]
        assert "已回退为文字卦象" in replies[0]["text"]
        assert "程序解卦" in replies[0]["text"] and "判定：成" in replies[0]["text"]

    asyncio.run(run())
    assert len(context.calls) == 1
    assert not output.exists()
