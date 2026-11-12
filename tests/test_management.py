import asyncio
import json
import sys
import types

import pytest
from test_ai_daily import agent, command, make_plugin
from test_main import _Context, _Event


def payload(**changes):
    return {
        "question": "这次销售交易能否达到预期",
        "numbers": "15997",
        "root": "水",
        "kernel": "document_v2",
        "with_ai": False,
        "request_id": "test_request_123456",
        **changes,
    }


class Config(dict):
    def save_config(self, values):
        self.clear()
        self.update(values)


def test_save_persists_switch_keeps_unrelated_config_and_detects_stale_edit(
    tmp_path, monkeypatch
):
    config = Config(ai_daily_group_limits=[{"group_id": "1", "limit": 8}])
    plugin, _ = make_plugin(tmp_path, monkeypatch, config=config)

    async def run():
        old = await plugin.page_settings({})
        saved = await plugin.page_save_settings(
            {"revision": old["revision"], "values": {"kernel_id": "document_v2"}}
        )
        assert saved["values"]["kernel_id"] == "document_v2"
        assert config["ai_daily_group_limits"][0]["limit"] == 8
        with pytest.raises(ValueError, match="配置已变化"):
            await plugin.page_save_settings(
                {"revision": old["revision"], "values": {"kernel_id": "legacy_v1"}}
            )

    asyncio.run(run())


def test_failed_config_save_rolls_back(tmp_path, monkeypatch):
    class BrokenConfig(Config):
        def save_config(self, values):
            super().save_config(values)
            raise OSError("disk full")

    plugin, _ = make_plugin(
        tmp_path, monkeypatch, config=BrokenConfig(kernel_id="legacy_v1")
    )

    async def run():
        with pytest.raises(OSError):
            await plugin.page_save_settings(
                {
                    "revision": plugin._config_revision(),
                    "values": {"kernel_id": "document_v2"},
                }
            )
        assert plugin._kernel_id() == "legacy_v1"

    asyncio.run(run())


@pytest.mark.parametrize(
    "values",
    [
        {"kernel_id": "bad"},
        {"ai_daily_limit": True},
        {"ai_daily_limit": -1},
        {"llm_tool_enabled": "false"},
        {"anything": "evil"},
    ],
)
def test_invalid_settings_rejected(tmp_path, monkeypatch, values):
    plugin, _ = make_plugin(tmp_path, monkeypatch, config=Config())
    with pytest.raises(ValueError):
        asyncio.run(
            plugin.page_save_settings(
                {"revision": plugin._config_revision(), "values": values}
            )
        )


def test_local_test_does_not_call_ai_or_change_real_kernel_quota_or_dead_streak(
    tmp_path, monkeypatch
):
    plugin, module = make_plugin(
        tmp_path, monkeypatch, config={"kernel_id": "legacy_v1"}
    )

    async def run():
        data = await plugin.page_test(payload(), username="admin")
        assert data["record"]["result"]["verdict"] == "成"
        assert data["record"]["ai_interpretation"] == ""
        assert data["record"]["source"] == "page_test"
        assert data["record"]["user_id"] == "admin"
        assert not module.STATE_FILE.exists()
        assert plugin._kernel_id() == "legacy_v1" and plugin._dead_streaks == {}
        assert plugin.context._plugin_kv == {}
        stats = await plugin.page_stats({})
        assert stats["total"] == 0 and stats["test_total"] == 1
        repeated = await plugin.page_test(payload(), username="admin")
        assert repeated["record"]["id"] == data["record"]["id"]
        assert (await plugin.page_history({}))["total"] == 1

    asyncio.run(run())


def test_ai_interpretation_stores_output_without_overwriting_program(
    tmp_path, monkeypatch
):
    class AI(_Context):
        calls = 0

        async def llm_generate(self, **kwargs):
            self.calls += 1
            assert kwargs["contexts"] == [] and kwargs["tools"] is None
            assert json.loads(kwargs["prompt"])["verdict"] == "成"
            return types.SimpleNamespace(
                completion_text="根据程序生相，需要继续推进。", role="assistant"
            )

    ctx = AI()
    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        context=ctx,
        config={"page_provider_id": "existing-model"},
    )

    async def run():
        first, second = await asyncio.gather(
            *[
                plugin.page_test(payload(with_ai=True), username="admin")
                for _ in range(2)
            ]
        )
        assert ctx.calls == 1
        assert first["record"]["id"] == second["record"]["id"]
        assert first["record"]["ai_status"] == "success"
        assert first["record"]["result"]["verdict"] == "成"
        assert first["record"]["ai_interpretation"].startswith("根据程序")
        await plugin.page_preview({}, record_id=first["record"]["id"])
        assert ctx.calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["missing", "timeout", "empty", "error"])
def test_ai_failures_preserve_local_result_and_history(tmp_path, monkeypatch, failure):
    class AI(_Context):
        async def llm_generate(self, **kwargs):
            if failure == "timeout":
                raise asyncio.TimeoutError()  # noqa: UP041 - test the Python 3.10 timeout class.
            if failure == "error":
                raise RuntimeError("secret should not escape")
            return types.SimpleNamespace(completion_text="", role="assistant")

    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        context=AI(),
        config={"page_provider_id": "" if failure == "missing" else "model"},
    )
    data = asyncio.run(plugin.page_test(payload(with_ai=True), username="admin"))
    assert data["record"]["ai_status"] == "failed"
    assert data["record"]["result"]["verdict"] == "成"
    assert "secret" not in data["record"]["ai_error"]
    assert plugin._get_case_store().history()["total"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"question": "随便看看"},
        {"root": ""},
        {"numbers": "123"},
        {"with_ai": "false"},
        {"kernel": "bad"},
        {"request_id": "../"},
    ],
)
def test_invalid_page_tests_never_write(tmp_path, monkeypatch, changes):
    plugin, _ = make_plugin(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(plugin.page_test(payload(**changes), username="admin"))
    assert not (tmp_path / "cases.json").exists()


def test_real_command_and_tool_record_identity_and_rank_but_reject_does_not(
    tmp_path, monkeypatch
):
    plugin, _ = make_plugin(tmp_path, monkeypatch, config={"kernel_id": "document_v2"})

    async def run():
        event = _Event(sender_id="200", group_id="300", message_id="same")
        await command(plugin, event, manual=True)
        await command(plugin, event, manual=True)
        await agent(plugin, _Event(sender_id="100", group_id="300"))
        await agent(plugin, _Event(sender_id="100", group_id="400"))
        stats = await plugin.page_stats({})
        assert stats["total"] == 3
        assert stats["users"][0]["id"] == "100" and stats["users"][0]["count"] == 2
        assert stats["groups"][0]["id"] == "300" and stats["groups"][0]["count"] == 2
        await agent(plugin, question="随便看看")
        assert (await plugin.page_stats({}))["total"] == 3

    asyncio.run(run())


def test_new_kernel_ignores_legacy_stop_without_erasing_it(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, monkeypatch, config={"kernel_id": "document_v2"})
    event = _Event()
    key = plugin._question_key(event, "这次求职能否成功")
    plugin._dead_streaks[key] = 3
    result, _ = plugin._resolve(event, "这次求职能否成功", "15997", "水")
    assert result.verdict == "成" and plugin._dead_streaks[key] == 3
    plugin.config["kernel_id"] = "legacy_v1"
    result, text = plugin._resolve(event, "这次求职能否成功", "15997", "水")
    assert result is None and "连续三次死卦" in text


def test_registered_routes_require_dashboard_identity(tmp_path, monkeypatch):
    routes = {}

    class Context(_Context):
        def register_web_api(self, route, handler, methods, description):
            routes[(route, methods[0])] = handler

    request = types.SimpleNamespace(username=None, query={})

    async def request_json(default=None):
        return payload()

    request.json = request_json
    web = types.ModuleType("astrbot.api.web")
    web.request = request
    web.error_response = lambda msg, status_code=400: {
        "error": msg,
        "code": status_code,
    }
    web.json_response = lambda data: data
    web.file_response = lambda *args, **kwargs: args[0]
    monkeypatch.setitem(sys.modules, "astrbot.api.web", web)
    _plugin, _ = make_plugin(tmp_path, monkeypatch, context=Context())
    assert len(routes) == 7

    async def run():
        for handler in routes.values():
            assert (await handler())["code"] == 403
        request.username = "admin"
        data = await routes[("/wuxing_num/test", "POST")]()
        assert data["record"]["user_id"] == "admin"
        assert (await routes[("/wuxing_num/stats", "GET")]())["test_total"] == 1

    asyncio.run(run())
