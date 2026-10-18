from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from test_main import ROOT, _Context, _Event, _LlmContext, _load_main_module


def make_plugin(tmp_path, monkeypatch, *, config=None, context=None):
    module = _load_main_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "dead_streaks.json")
    plugin = module.WuxingNumberDivinationPlugin(
        context if context is not None else _Context(), config
    )
    plugin.renderer = None
    return plugin, module


async def command(plugin, event=None):
    event = event if event is not None else _Event()
    event.message_str = "/数字卦 这次求职能否成功 | 13254 | 木"
    replies = [item async for item in plugin.number_divination(event)]
    return replies[0]["text"]


async def agent(plugin, event=None, **overrides):
    args = {
        "question": "这次求职能否成功",
        "five_numbers": "13254",
        "root_element": "木",
        "matter_type": "事业求职",
        "five_symbolic_meanings": "消息出现｜能力生长｜行动显化｜资源承接｜规则落定",
        "symbolic_summary": "机会逐步落实",
        **overrides,
    }
    return await plugin.divine_wuxing_five_numbers(
        event if event is not None else _Event(), **args
    )


def test_command_ai_defaults_on_and_exhaustion_keeps_local_chart(tmp_path, monkeypatch):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)

    async def run():
        first = await command(plugin)
        second = await command(plugin)
        assert "判定：成" in first and "判定：成" in second
        assert "每日" in second or "每天" in second
        assert len(context.calls) == 1
        assert "本次未进行新的" in await agent(plugin)

    asyncio.run(run())


def test_disabled_command_ai_never_calls_model_or_consumes_quota(tmp_path, monkeypatch):
    context = _LlmContext()
    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        context=context,
        config={"command_ai_analysis_enabled": False},
    )

    async def run():
        for _ in range(3):
            assert "判定：成" in await command(plugin)
        assert context.calls == []
        assert "判定：成" in await agent(plugin)
        assert "本次未进行新的" in await agent(plugin)

    asyncio.run(run())


def test_agent_quota_denial_does_not_change_dead_streaks(tmp_path, monkeypatch):
    plugin, module = make_plugin(tmp_path, monkeypatch)

    async def run():
        assert "判定：成" in await agent(plugin)
        key = plugin._question_key(_Event(), "这次求职能否成功")
        plugin._dead_streaks[key] = 2
        plugin._save_state()
        before = module.STATE_FILE.read_bytes()
        rejected = await agent(plugin, five_numbers="11111")
        assert "本次未进行新的" in rejected
        assert plugin._dead_streaks[key] == 2
        assert module.STATE_FILE.read_bytes() == before

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad_args",
    [
        {"question": "随便看看"},
        {"five_numbers": "1234"},
        {"root_element": "雷"},
        {"matter_type": ""},
        {"five_symbolic_meanings": "只有一条"},
        {"symbolic_summary": ""},
    ],
)
def test_invalid_agent_requests_do_not_consume_quota(tmp_path, monkeypatch, bad_args):
    plugin, module = make_plugin(tmp_path, monkeypatch)

    async def run():
        rejected = await agent(plugin, **bad_args)
        assert "调用失败" in rejected or "无事不卜" in rejected
        assert plugin._dead_streaks == {}
        assert not module.STATE_FILE.exists()
        assert "判定：成" in await agent(plugin)

    asyncio.run(run())


def test_dead_streak_stop_does_not_consume_ai_quota(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, monkeypatch)
    for _ in range(3):
        plugin._run(_Event(), "这次求职能否成功", "11111", "木")

    async def run():
        assert "天机不可泄露" in await agent(plugin)
        assert "判定：成" in await agent(plugin, question="下周面试能否通过")

    asyncio.run(run())


def test_command_and_agent_share_one_real_message_allowance(tmp_path, monkeypatch):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)

    async def run():
        assert "判定：成" in await command(plugin, _Event(message_id="one"))
        assert "判定：成" in await agent(plugin, _Event(message_id="one"))
        assert "本次未进行新的" in await agent(plugin, _Event(message_id="two"))
        assert len(context.calls) == 1

    asyncio.run(run())


def test_limits_are_separate_for_users_groups_and_platforms(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, monkeypatch)

    async def run():
        assert "判定：成" in await agent(plugin)
        assert "判定：成" in await agent(plugin, _Event(group_id="200"))
        assert "判定：成" in await agent(plugin, _Event(sender_id="10002"))
        assert "判定：成" in await agent(plugin, _Event(platform_id="other-bot"))
        assert "本次未进行新的" in await agent(plugin)

    asyncio.run(run())


def test_group_override_replaces_default_limit(tmp_path, monkeypatch):
    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        config={
            "ai_daily_limit": 1,
            "ai_daily_group_limits": [{"group_id": "100", "limit": 2}],
        },
    )

    async def run():
        assert "判定：成" in await agent(plugin)
        assert "判定：成" in await agent(plugin)
        assert "本次未进行新的" in await agent(plugin)
        assert "判定：成" in await agent(plugin, _Event(group_id="200"))
        assert "本次未进行新的" in await agent(plugin, _Event(group_id="200"))

    asyncio.run(run())


def test_beijing_midnight_and_same_day_reload(tmp_path, monkeypatch):
    context = _Context()
    plugin, module = make_plugin(tmp_path, monkeypatch, context=context)
    before = datetime(2026, 10, 17, 15, 59, 59, tzinfo=timezone.utc)
    after = datetime(2026, 10, 17, 16, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(plugin, "_ai_daily_now", lambda: before)

    async def run():
        assert "判定：成" in await agent(plugin)
        reloaded = module.WuxingNumberDivinationPlugin(context)
        reloaded.renderer = None
        monkeypatch.setattr(reloaded, "_ai_daily_now", lambda: before)
        assert "本次未进行新的" in await agent(reloaded)
        monkeypatch.setattr(reloaded, "_ai_daily_now", lambda: after)
        assert "判定：成" in await agent(reloaded)

    asyncio.run(run())


def test_missing_provider_uses_local_result_without_ai_charge(tmp_path, monkeypatch):
    context = _LlmContext(provider_id=None)
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)

    async def run():
        assert "判定：成" in await command(plugin)
        assert context.calls == []
        context.provider_id = "provider-1"
        assert "判定：成" in await command(plugin)
        assert len(context.calls) == 1

    asyncio.run(run())


def test_failed_model_attempt_still_consumes_ai_allowance(tmp_path, monkeypatch):
    context = _LlmContext(error=TimeoutError())
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)

    async def run():
        assert "判定：成" in await command(plugin)
        assert "判定：成" in await command(plugin)
        assert len(context.calls) == 1
        assert "本次未进行新的" in await agent(plugin)

    asyncio.run(run())


def test_parallel_commands_only_start_one_model_request(tmp_path, monkeypatch):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)

    async def run():
        replies = await asyncio.gather(command(plugin), command(plugin))
        assert all("判定：成" in text for text in replies)
        assert len(context.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("numbers", ["13254", "11111"])
def test_state_save_failure_releases_agent_reservation(tmp_path, monkeypatch, numbers):
    plugin, _ = make_plugin(tmp_path, monkeypatch)
    original = plugin._save_state

    def fail():
        raise OSError("simulated disk failure")

    async def run():
        monkeypatch.setattr(plugin, "_save_state", fail)
        assert "状态保存失败" in await agent(plugin, five_numbers=numbers)
        assert plugin._dead_streaks == {}
        monkeypatch.setattr(plugin, "_save_state", original)
        assert "判定：" in await agent(plugin, five_numbers=numbers)

    asyncio.run(run())


def test_quota_storage_failure_never_calls_model_and_keeps_local_command(
    tmp_path, monkeypatch
):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)

    async def fail(*_args, **_kwargs):
        raise OSError("simulated quota storage failure")

    monkeypatch.setattr(plugin, "get_kv_data", fail)

    async def run():
        assert "判定：成" in await command(plugin)
        assert "次数记录读取或保存失败" in await agent(plugin)
        assert context.calls == []

    asyncio.run(run())


def test_quota_commit_and_release_failure_still_preserves_local_fallback(
    tmp_path, monkeypatch
):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)
    original = plugin.put_kv_data
    writes = 0

    async def fail_after_reservation(key, value):
        nonlocal writes
        writes += 1
        if writes >= 2:
            raise OSError("simulated confirmation/release failure")
        await original(key, value)

    monkeypatch.setattr(plugin, "put_kv_data", fail_after_reservation)

    async def run():
        result = await command(plugin)
        assert "判定：成" in result
        assert "额度记录暂不可用" in result
        assert context.calls == []

    asyncio.run(run())


@pytest.mark.parametrize("numbers", ["13254", "11111"])
def test_agent_quota_commit_failure_restores_prior_dead_streak(
    tmp_path, monkeypatch, numbers
):
    plugin, module = make_plugin(tmp_path, monkeypatch)
    key = plugin._question_key(_Event(), "这次求职能否成功")
    plugin._dead_streaks[key] = 2
    plugin._save_state()
    before = module.STATE_FILE.read_bytes()
    original = plugin.put_kv_data
    writes = 0

    async def fail_confirmation(key, value):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated confirmation failure")
        await original(key, value)

    monkeypatch.setattr(plugin, "put_kv_data", fail_confirmation)

    async def run():
        rejected = await agent(plugin, five_numbers=numbers)
        assert "额度记录暂不可用" in rejected
        assert plugin._dead_streaks[key] == 2
        assert module.STATE_FILE.read_bytes() == before
        assert "判定：成" in await agent(plugin)

    asyncio.run(run())


def test_agent_failure_rollback_does_not_overwrite_concurrent_local_command(
    tmp_path, monkeypatch
):
    plugin, module = make_plugin(
        tmp_path, monkeypatch, config={"command_ai_analysis_enabled": False}
    )
    key = plugin._question_key(_Event(), "这次求职能否成功")
    plugin._dead_streaks[key] = 2
    plugin._save_state()
    original = plugin.put_kv_data
    writes = 0

    async def run():
        confirming, resume = asyncio.Event(), asyncio.Event()

        async def delayed_failure(key, value):
            nonlocal writes
            writes += 1
            if writes == 2:
                confirming.set()
                await resume.wait()
                raise OSError("simulated confirmation failure")
            await original(key, value)

        monkeypatch.setattr(plugin, "put_kv_data", delayed_failure)
        ai_task = asyncio.create_task(agent(plugin, five_numbers="11111"))
        await asyncio.wait_for(confirming.wait(), timeout=1)
        local_task = asyncio.create_task(command(plugin))
        await asyncio.sleep(0)
        assert not local_task.done()
        resume.set()
        rejected, local = await asyncio.gather(ai_task, local_task)
        assert "额度记录暂不可用" in rejected
        assert "判定：成" in local
        assert plugin._dead_streaks == {}
        assert json.loads(module.STATE_FILE.read_text(encoding="utf-8")) == {}

    asyncio.run(run())


def test_concurrent_agent_waits_for_failed_cast_state_rollback(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, monkeypatch)
    key = plugin._question_key(_Event(), "这次求职能否成功")
    plugin._dead_streaks[key] = 2
    plugin._save_state()
    original = plugin.put_kv_data
    writes = 0

    async def run():
        confirming, resume = asyncio.Event(), asyncio.Event()

        async def delayed_failure(key, value):
            nonlocal writes
            writes += 1
            if writes == 2:
                confirming.set()
                await resume.wait()
                raise OSError("simulated confirmation failure")
            await original(key, value)

        monkeypatch.setattr(plugin, "put_kv_data", delayed_failure)
        first = asyncio.create_task(agent(plugin, five_numbers="11111"))
        await asyncio.wait_for(confirming.wait(), timeout=1)
        second = asyncio.create_task(agent(plugin, five_numbers="11111"))
        await asyncio.sleep(0)
        assert not second.done()
        resume.set()
        rejected, accepted = await asyncio.gather(first, second)
        assert "额度记录暂不可用" in rejected
        assert "判定：死卦" in accepted
        assert "象意总览" in accepted
        assert plugin._dead_streaks[key] == 3

    asyncio.run(run())


def test_ai_schema_defaults_match_runtime():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    assert schema["command_ai_analysis_enabled"]["default"] is True
    assert schema["ai_daily_limit"]["default"] == 1
    assert schema["ai_daily_group_limits"]["default"] == []
