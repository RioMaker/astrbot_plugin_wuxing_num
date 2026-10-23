from __future__ import annotations

import asyncio
import json
import types

import pytest
from test_ai_daily import agent, command, make_plugin
from test_main import ROOT, _Event, _LlmContext


def test_new_command_parsing_and_legacy_compatibility(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, monkeypatch)
    assert plugin._parse_command("/数字卦 13254 这次求职能否成功") == (
        "这次求职能否成功",
        "13254",
        None,
    )
    assert plugin._parse_command("数字卦 这次求职能否成功｜1 3 2 5 4｜木") == (
        "这次求职能否成功",
        "1 3 2 5 4",
        "木",
    )


@pytest.mark.parametrize(
    "message", ["/数字卦 12345", "/数字卦 1234", "/数字卦", "/数字卦 123456 具体问题"]
)
def test_incomplete_command_does_not_cast_or_charge(tmp_path, monkeypatch, message):
    context = _LlmContext()
    plugin, module = make_plugin(tmp_path, monkeypatch, context=context)

    async def run():
        replies = [item async for item in plugin.number_divination(_Event(message))]
        assert "问题" in replies[0]["text"]
        assert not module.STATE_FILE.exists()
        assert not context.calls and not context._plugin_kv

    asyncio.run(run())


def test_chart_precedes_one_isolated_request_and_mentions_original_sender(
    tmp_path, monkeypatch
):
    context = _LlmContext()
    plugin, module = make_plugin(tmp_path, monkeypatch, context=context)
    event = _Event("/数字卦 13254 这次求职能否成功", sender_id="123456")
    trace = []
    captured = []

    async def chart(*_args):
        assert module.STATE_FILE.exists()
        trace.append("chart")
        return "卦图已发送"

    async def llm(**kwargs):
        assert trace == ["chart"]
        trace.append("llm")
        captured.append(kwargs)
        return types.SimpleNamespace(completion_text="五行流通。建议按计划准备。")

    monkeypatch.setattr(plugin, "_render_and_send", chart)
    monkeypatch.setattr(context, "llm_generate", llm)

    # No conversation or persona APIs are provided by this context.
    async def run():
        replies = [item async for item in plugin.number_divination(event)]
        assert trace == ["chart", "llm"]
        assert len(captured) == 1
        req = captured[0]
        assert set(req) == {
            "chat_provider_id",
            "prompt",
            "contexts",
            "tools",
            "system_prompt",
        }
        assert req["contexts"] == [] and req["tools"] is None
        assert "这次求职能否成功" in req["prompt"]
        assert "判定：成" in req["prompt"] and "流转：" in req["prompt"]
        assert replies[0]["chain"][0].qq == "123456"
        assert "AI 解卦：" in replies[0]["text"]
        assert replies[0]["text"].endswith(
            "断语：成：根气有承有发，五行流转贯通，此事可成。"
        )

    asyncio.run(run())


def test_tool_switch_rejects_before_validation_and_state_changes(tmp_path, monkeypatch):
    context = _LlmContext()
    plugin, module = make_plugin(
        tmp_path, monkeypatch, context=context, config={"llm_tool_enabled": False}
    )

    async def run():
        assert "工具已关闭" in await agent(plugin, five_numbers="11111")
        assert not module.STATE_FILE.exists() and not context._plugin_kv
        assert "AI 解卦：" in await command(plugin)
        assert len(context.calls) == 1

    asyncio.run(run())


def test_request_tool_filter_preserves_other_tools_and_shared_registration(
    tmp_path, monkeypatch
):
    plugin, _ = make_plugin(tmp_path, monkeypatch, config={"llm_tool_enabled": False})

    class Tools:
        def __init__(self):
            self.tools = ["divine_wuxing_five_numbers", "cast_liuyao", "weather"]

        def remove_tool(self, name):
            self.tools = [tool for tool in self.tools if tool != name]

    original = Tools()
    req = types.SimpleNamespace(func_tool=original)

    async def run():
        await plugin.filter_agent_tools(_Event(), req)
        assert req.func_tool.tools == ["cast_liuyao", "weather"]
        assert original.tools == [
            "divine_wuxing_five_numbers",
            "cast_liuyao",
            "weather",
        ]
        plugin.config["llm_tool_enabled"] = True
        enabled = types.SimpleNamespace(func_tool=original)
        await plugin.filter_agent_tools(_Event(), enabled)
        assert enabled.func_tool is original
        plugin.config["llm_tool_enabled"] = False
        await plugin.filter_agent_tools(_Event(), types.SimpleNamespace(func_tool=None))

    asyncio.run(run())


def test_explicit_provider_does_not_access_chat_provider_or_history(
    tmp_path, monkeypatch
):
    context = _LlmContext(provider_id="dedicated")
    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        context=context,
        config={"command_provider_id": "dedicated"},
    )

    async def forbidden(**_kwargs):
        raise AssertionError("Should not access the current chat provider")

    monkeypatch.setattr(context, "get_current_chat_provider_id", forbidden)

    async def run():
        assert "AI 解卦：" in await command(plugin)
        assert len(context.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("response", ["", "Output stopped.", "model error"])
def test_empty_or_error_model_response_preserves_cast_and_charges_attempt(
    tmp_path, monkeypatch, response
):
    context = _LlmContext()
    plugin, module = make_plugin(tmp_path, monkeypatch, context=context)
    calls = []

    async def llm(**kwargs):
        calls.append(kwargs)
        return types.SimpleNamespace(
            completion_text=response,
            role="err" if response == "model error" else "assistant",
        )

    monkeypatch.setattr(context, "llm_generate", llm)

    async def run():
        text = await command(plugin)
        assert "判定：成" in text and "解卦暂时失败" in text
        assert module.STATE_FILE.exists()
        assert "额度已用完" in await command(plugin)
        assert len(calls) == 1

    asyncio.run(run())


def test_private_reply_uses_plain_text(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=_LlmContext())
    event = _Event("/数字卦 13254 这次求职能否成功", group_id="")

    async def run():
        replies = [item async for item in plugin.number_divination(event)]
        assert "chain" not in replies[0]
        assert "AI 解卦：" in replies[0]["text"]

    asyncio.run(run())


def test_custom_prompt_cannot_drop_chart_and_does_not_interpolate_user_braces(
    tmp_path, monkeypatch
):
    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        config={
            "command_interpretation_prompt": "自定义 {question} {chart} {max_chars}"
        },
    )
    prompt = plugin._interpretation_prompt("合同中的 {chart} 如何处理", "真实卦例")
    assert "合同中的 {chart} 如何处理" in prompt
    assert "真实卦例" in prompt and "280" in prompt
    plugin.config["command_interpretation_prompt"] = "只给结论"
    assert "真实卦例" in plugin._interpretation_prompt("实际问题", "真实卦例")


def test_length_trimming_keeps_full_fixed_ruling(tmp_path, monkeypatch):
    plugin, module = make_plugin(
        tmp_path, monkeypatch, config={"command_reply_max_chars": 60}
    )
    result = module.calculate("这次求职能否成功", "13254", "木")
    response = "五行流通，应充分准备。" * 30 + "\n断语：模型擅自改变的判词"
    text = plugin._format_interpretation(response, result)
    assert len(text) <= 60
    assert text.endswith("断语：" + result.phrase)
    assert "擅自" not in text
    plugin.config["command_reply_trim"] = False
    assert len(plugin._format_interpretation(response, result)) > 60
    plugin.config.update(command_reply_trim=True, command_reply_max_chars=0)
    assert len(plugin._format_interpretation(response, result)) > 60


def test_unlimited_commands_and_bounded_settings(tmp_path, monkeypatch):
    context = _LlmContext()
    plugin, _ = make_plugin(
        tmp_path, monkeypatch, context=context, config={"ai_daily_limit": 0}
    )

    async def run():
        for _ in range(3):
            assert "AI 解卦：" in await command(plugin)
        assert len(context.calls) == 3

    asyncio.run(run())
    for value, expected in [(False, 60), (None, 60), (-1, 5), (9999, 180), ("bad", 60)]:
        plugin.config["command_analysis_timeout_seconds"] = value
        assert (
            plugin._bounded_config_int("command_analysis_timeout_seconds", 60, 5, 180)
            == expected
        )


def test_new_schema_defaults_and_provider_selector():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    assert schema["llm_tool_enabled"]["default"] is True
    assert schema["command_provider_id"]["_special"] == "select_provider"
    assert schema["command_analysis_timeout_seconds"]["default"] == 60
    assert schema["command_reply_max_chars"]["default"] == 280


def test_timeout_setting_is_used_and_attempt_remains_charged(tmp_path, monkeypatch):
    context = _LlmContext()
    plugin, module = make_plugin(
        tmp_path,
        monkeypatch,
        context=context,
        config={"command_analysis_timeout_seconds": 12},
    )
    timeouts = []

    async def timeout(coroutine, *, timeout):
        timeouts.append(timeout)
        coroutine.close()
        raise asyncio.TimeoutError  # noqa: UP041 - match Python 3.10 wait_for.

    monkeypatch.setattr(module.asyncio, "wait_for", timeout)

    async def run():
        text = await command(plugin)
        assert "AI 解卦超时" in text and "判定：成" in text
        assert timeouts == [12]
        assert "额度已用完" in await command(plugin)
        assert timeouts == [12]

    asyncio.run(run())


def test_cancelled_model_request_keeps_cast_and_one_charged_allowance(
    tmp_path, monkeypatch
):
    context = _LlmContext()
    plugin, module = make_plugin(tmp_path, monkeypatch, context=context)

    async def run():
        started = asyncio.Event()

        async def pending(**_kwargs):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(context, "llm_generate", pending)
        task = asyncio.create_task(command(plugin))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert module.STATE_FILE.exists()
        assert "额度已用完" in await command(plugin)
        for record in context._plugin_kv.values():
            for day in record["days"].values():
                assert all(
                    entry["used"] and not entry["holds"] for entry in day.values()
                )

    asyncio.run(run())


def test_image_send_failure_still_returns_interpretation_and_text_chart(
    tmp_path, monkeypatch
):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)
    image_path = tmp_path / "chart.png"

    def render(*_args, **_kwargs):
        image_path.write_bytes(b"simulated render output")
        return image_path

    plugin.renderer = types.SimpleNamespace(render=render)
    event = _Event("/数字卦 13254 这次求职能否成功")

    async def failed_send(_message):
        raise RuntimeError("simulated platform send failure")

    monkeypatch.setattr(event, "send", failed_send)

    async def run():
        replies = [item async for item in plugin.number_divination(event)]
        assert "已回退为文字卦象" in replies[0]["text"]
        assert "判定：成" in replies[0]["text"] and "AI 解卦：" in replies[0]["text"]
        assert not image_path.exists()
        assert len(context.calls) == 1

    asyncio.run(run())
