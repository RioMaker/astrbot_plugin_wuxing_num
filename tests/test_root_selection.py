from __future__ import annotations

import asyncio
import inspect
import json
import types

import pytest
from test_ai_daily import agent, command, make_plugin
from test_main import ROOT, _Event, _LlmContext


def test_command_parsing_keeps_new_and_legacy_forms(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, monkeypatch)
    assert plugin._parse_command("/数字卦 13254 这次求职能否成功") == (
        "这次求职能否成功",
        "13254",
        None,
    )
    assert plugin._parse_command("数字卦 合同能否签下｜4 1 2 3 5｜金") == (
        "合同能否签下",
        "4 1 2 3 5",
        "金",
    )


@pytest.mark.parametrize(
    "message",
    [
        "/数字卦 12345",
        "/数字卦 1234",
        "/数字卦",
        "/数字卦 123456 具体问题",
        "/数字卦 随便看看 | 13254",
        "/数字卦 合同能否签下 | 1234",
        "/数字卦 合同能否签下 | 13254 | 雷",
    ],
)
def test_bad_inputs_never_call_model_or_mutate_state(tmp_path, monkeypatch, message):
    context = _LlmContext()
    plugin, module = make_plugin(tmp_path, monkeypatch, context=context)

    async def run():
        assert [item async for item in plugin.number_divination(_Event(message))]
        assert not context.calls and not context._plugin_kv
        assert not module.STATE_FILE.exists()

    asyncio.run(run())


def test_only_question_reaches_ai_then_selected_root_drives_calculation(
    tmp_path, monkeypatch
):
    context = _LlmContext()
    plugin, module = make_plugin(tmp_path, monkeypatch, context=context)
    trace = []

    async def llm(**kwargs):
        assert trace == []
        assert not module.STATE_FILE.exists()
        assert kwargs["contexts"] == [] and kwargs["tools"] is None
        assert "这次求职能否成功" in kwargs["prompt"]
        assert all(
            value not in kwargs["prompt"] for value in ("13254", "判定：", "流转：")
        )
        trace.append("root")
        # Intentionally differs from the old keyword inference (木).
        return types.SimpleNamespace(completion_text="金")

    async def chart(event, result, *args, **kwargs):
        assert trace == ["root"] and module.STATE_FILE.exists()
        assert result.root == "金"
        assert "程序解卦" in kwargs["analysis_text"]
        assert kwargs["analysis_text"].endswith("断语：" + result.phrase)
        assert kwargs["mention_sender"] is True
        assert "AI 按问题选取" in kwargs["status_note"]
        trace.append("image")
        return "卦图已发送"

    monkeypatch.setattr(context, "llm_generate", llm)
    monkeypatch.setattr(plugin, "_render_and_send", chart)

    async def run():
        event = _Event("/数字卦 13254 这次求职能否成功")
        assert [item async for item in plugin.number_divination(event)] == []
        assert trace == ["root", "image"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "response", ["", "木火", "木，因为事业属木", '{"root":"木"}', "Output stopped."]
)
def test_non_single_root_output_cannot_become_a_reading(
    tmp_path, monkeypatch, response
):
    context = _LlmContext()
    plugin, module = make_plugin(tmp_path, monkeypatch, context=context)

    async def llm(**_kwargs):
        return types.SimpleNamespace(completion_text=response)

    monkeypatch.setattr(context, "llm_generate", llm)

    async def run():
        text = await command(plugin)
        assert "取根气失败" in text and "手动指定根气" in text
        assert "判定：" not in text
        if response:
            assert response not in text
        assert not module.STATE_FILE.exists()
        assert "额度已用完" in await command(plugin)

    asyncio.run(run())


def test_provider_error_cannot_be_accepted_as_root(tmp_path, monkeypatch):
    plugin, module = make_plugin(tmp_path, monkeypatch, context=_LlmContext())

    async def llm(**_kwargs):
        return types.SimpleNamespace(completion_text="木", role="err")

    monkeypatch.setattr(plugin.context, "llm_generate", llm)
    asyncio.run(command(plugin))
    assert not module.STATE_FILE.exists()


def test_provider_lookup_failure_is_not_described_as_a_charged_request(
    tmp_path, monkeypatch
):
    context = _LlmContext()
    plugin, module = make_plugin(tmp_path, monkeypatch, context=context)

    async def failed_lookup(**_kwargs):
        raise RuntimeError("simulated provider lookup failure")

    monkeypatch.setattr(context, "get_current_chat_provider_id", failed_lookup)
    text = asyncio.run(command(plugin))
    assert "未发起模型请求" in text
    assert "计入今日额度" not in text
    assert not context.calls and not context._plugin_kv
    assert not module.STATE_FILE.exists()


def test_explicit_root_skips_ai_even_when_disabled_or_unavailable(
    tmp_path, monkeypatch
):
    context = _LlmContext(error=AssertionError("No model call expected"))
    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        context=context,
        config={"command_ai_analysis_enabled": False},
    )

    async def run():
        assert "取根气已关闭" in await command(plugin)
        text = await command(plugin, manual=True)
        assert "判定：成" in text and "程序解卦" in text and "手动指定" in text
        assert not context.calls and not context._plugin_kv

    asyncio.run(run())


def test_explicit_provider_and_custom_root_prompt_never_reuse_old_reading_prompt(
    tmp_path, monkeypatch
):
    context = _LlmContext(provider_id="dedicated")
    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        context=context,
        config={
            "command_provider_id": "dedicated",
            "command_root_prompt": "补充归类规则",
            "command_interpretation_prompt": "旧版长篇解卦要求",
        },
    )

    async def forbidden(**_kwargs):
        raise AssertionError("Do not access chat provider or history")

    monkeypatch.setattr(context, "get_current_chat_provider_id", forbidden)
    prompt = plugin._root_prompt("合同中的 {question} 如何处理")
    assert "合同中的 {question} 如何处理" in prompt and "补充归类规则" in prompt
    assert "旧版长篇解卦要求" not in prompt
    assert "判定：成" in asyncio.run(command(plugin))
    assert len(context.calls) == 1


def test_timeout_charged_but_no_cast_or_dead_streak(tmp_path, monkeypatch):
    plugin, module = make_plugin(
        tmp_path,
        monkeypatch,
        context=_LlmContext(),
        config={"command_analysis_timeout_seconds": 12},
    )
    timeouts = []

    async def timeout(coroutine, *, timeout):
        timeouts.append(timeout)
        coroutine.close()
        raise asyncio.TimeoutError  # noqa: UP041 - Python 3.10.

    monkeypatch.setattr(module.asyncio, "wait_for", timeout)

    async def run():
        text = await command(plugin)
        assert "AI 取根气超时" in text and "判定：" not in text
        assert not module.STATE_FILE.exists() and plugin._dead_streaks == {}
        assert "额度已用完" in await command(plugin)
        assert timeouts == [12]

    asyncio.run(run())


def test_cancellation_leaves_no_cast_and_one_charged_allowance(tmp_path, monkeypatch):
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
        assert not module.STATE_FILE.exists()
        assert "额度已用完" in await command(plugin)
        for record in context._plugin_kv.values():
            for day in record["days"].values():
                assert all(
                    entry["used"] and not entry["holds"] for entry in day.values()
                )

    asyncio.run(run())


def test_stop_rule_precedes_root_request_and_is_rechecked_after_it(
    tmp_path, monkeypatch
):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)
    event = _Event()
    key = plugin._question_key(event, "这次求职能否成功")
    plugin._dead_streaks[key] = 3

    async def run():
        assert "天机不可泄露" in await command(plugin, event)
        assert not context.calls and not context._plugin_kv
        plugin._dead_streaks.clear()

        async def llm(**_kwargs):
            plugin._dead_streaks[key] = 3
            return types.SimpleNamespace(completion_text="木")

        monkeypatch.setattr(context, "llm_generate", llm)
        assert "天机不可泄露" in await command(plugin, event)
        assert plugin._dead_streaks[key] == 3

    asyncio.run(run())


def test_tool_switch_filter_preserves_other_tools_and_registration(
    tmp_path, monkeypatch
):
    plugin, module = make_plugin(
        tmp_path, monkeypatch, context=_LlmContext(), config={"llm_tool_enabled": False}
    )

    class Tools:
        def __init__(self):
            self.tools = ["divine_wuxing_five_numbers", "cast_liuyao"]

        def remove_tool(self, name):
            self.tools = [tool for tool in self.tools if tool != name]

    original = Tools()
    req = types.SimpleNamespace(func_tool=original)

    async def run():
        assert "工具已关闭" in await agent(plugin)
        assert not module.STATE_FILE.exists()
        await plugin.filter_agent_tools(_Event(), req)
        assert req.func_tool.tools == ["cast_liuyao"]
        assert len(original.tools) == 2
        assert "程序解卦" in await command(plugin)

    asyncio.run(run())


def test_agent_contract_only_accepts_question_numbers_and_root(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, monkeypatch)
    assert list(inspect.signature(plugin.divine_wuxing_five_numbers).parameters) == [
        "event",
        "question",
        "five_numbers",
        "root_element",
    ]
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    assert schema["command_provider_id"]["_special"] == "select_provider"
    assert "command_root_prompt" in schema
    assert "command_interpretation_prompt" not in schema
    assert "command_reply_max_chars" not in schema
