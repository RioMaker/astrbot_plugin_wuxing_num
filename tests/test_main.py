from __future__ import annotations

import asyncio
import copy
import importlib
import sys
import types
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def _load_main_module():
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    event_module = types.ModuleType("astrbot.api.event")
    star_module = types.ModuleType("astrbot.api.star")

    class _Logger:
        def warning(self, *_args, **_kwargs):
            pass

        def exception(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    class AstrMessageEvent:
        pass

    class Context:
        pass

    class Star:
        def __init__(self, context):
            self.context = context
            if not hasattr(context, "_plugin_kv"):
                context._plugin_kv = {}

        async def get_kv_data(self, key, default=None):
            return copy.deepcopy(self.context._plugin_kv.get(key, default))

        async def put_kv_data(self, key, value):
            self.context._plugin_kv[key] = copy.deepcopy(value)

    def decorator(*_args, **_kwargs):
        return lambda func: func

    def register(*_args, **_kwargs):
        return lambda cls: cls

    api_module.logger = _Logger()
    api_module.message_components = types.SimpleNamespace(
        At=lambda *, qq: types.SimpleNamespace(qq=qq),
        Plain=lambda text: types.SimpleNamespace(text=text),
    )
    event_module.AstrMessageEvent = AstrMessageEvent
    event_module.filter = types.SimpleNamespace(
        command=decorator,
        llm_tool=decorator,
        on_llm_request=decorator,
    )
    star_module.Context = Context
    star_module.Star = Star
    star_module.register = register

    modules = {
        "astrbot": astrbot_module,
        "astrbot.api": api_module,
        "astrbot.api.event": event_module,
        "astrbot.api.star": star_module,
    }
    old_modules = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    sys.path.insert(0, str(REPO_ROOT))
    try:
        sys.modules.pop("astrbot_plugin_wuxing_num.main", None)
        return importlib.import_module("astrbot_plugin_wuxing_num.main")
    finally:
        sys.path.remove(str(REPO_ROOT))
        for name, old in old_modules.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


class _Context:
    pass


class _LlmContext:
    def __init__(self, *, provider_id="provider-1", error=None):
        self.provider_id = provider_id
        self.error = error
        self.calls = []

    async def get_current_chat_provider_id(self, *, umo):
        assert umo.startswith("group:")
        return self.provider_id

    async def llm_generate(
        self, *, chat_provider_id, prompt, contexts, tools, system_prompt
    ):
        assert chat_provider_id == self.provider_id
        assert "不得修改计算结论" in system_prompt
        assert contexts == [] and tools is None
        self.calls.append(prompt)
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        return types.SimpleNamespace(
            completion_text=(
                "从消息到能力、行动、资源与规则，五行顺序流通。建议落实面试安排。"
            )
        )


class _Event:
    def __init__(
        self,
        message_str="",
        *,
        sender_id="10001",
        group_id="100",
        platform_id="onebot-main",
        message_id=None,
    ):
        self.sent_sizes: list[int] = []
        self.message_str = message_str
        self.unified_msg_origin = f"group:{group_id}"
        self.sender_id = sender_id
        self.group_id = group_id
        self.platform_id = platform_id
        self.message_obj = types.SimpleNamespace(
            message_id=message_id if message_id is not None else uuid.uuid4().hex
        )
        self.extras = {}

    def get_sender_id(self):
        return self.sender_id

    def get_group_id(self):
        return self.group_id

    def get_platform_id(self):
        return self.platform_id

    def get_platform_name(self):
        return "aiocqhttp"

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value

    def image_result(self, path):
        return {"image": path}

    def plain_result(self, text):
        return {"text": text}

    def chain_result(self, chain):
        return {"chain": chain, "text": "".join(getattr(c, "text", "") for c in chain)}

    async def send(self, message):
        path = Path(message["image"])
        self.sent_sizes.append(path.stat().st_size)


def test_agent_tool_sends_chart_and_returns_fixed_verdict(
    tmp_path, monkeypatch
) -> None:
    module = _load_main_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "dead_streaks.json")
    plugin = module.WuxingNumberDivinationPlugin(_Context())
    event = _Event()

    response = asyncio.run(
        plugin.divine_wuxing_five_numbers(
            event,
            question="这次求职能否成功",
            five_numbers="13254",
            root_element="木",
            matter_type="事业求职",
            five_symbolic_meanings="消息出现｜能力生长｜行动显化｜资源承接｜规则落定",
            symbolic_summary="机会从消息萌发，经过能力、行动与资源承接，最终进入规则确认。",
        )
    )

    assert event.sent_sizes and event.sent_sizes[0] > 40_000
    assert "卦图已发送" in response
    assert "判定：成" in response
    assert "象意总览" in response


def test_agent_tool_requires_five_ordered_meanings(tmp_path, monkeypatch) -> None:
    module = _load_main_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "dead_streaks.json")
    plugin = module.WuxingNumberDivinationPlugin(_Context())

    response = asyncio.run(
        plugin.divine_wuxing_five_numbers(
            _Event(),
            question="测试",
            five_numbers="13254",
            root_element="水",
            matter_type="综合",
            five_symbolic_meanings="只有一条",
            symbolic_summary="测试总象",
        )
    )

    assert response == "调用失败：五位象意必须恰好五条，并按数字顺序用｜分隔。"


def test_command_uses_isolated_llm_interpretation_and_local_chart(
    tmp_path, monkeypatch
) -> None:
    module = _load_main_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "dead_streaks.json")
    plugin = module.WuxingNumberDivinationPlugin(_LlmContext())
    event = _Event("/数字卦 这次求职能否成功 | 13254 | 木")

    async def collect():
        return [item async for item in plugin.number_divination(event)]

    replies = asyncio.run(collect())

    assert event.sent_sizes and event.sent_sizes[0] > 40_000
    assert len(replies) == 1
    assert "象意来源：本地规则" in replies[0]["text"]
    assert "AI 解卦：" in replies[0]["text"]
    assert replies[0]["chain"][0].qq == event.get_sender_id()
    assert "判定：成" in replies[0]["text"]


def test_no_matter_rejected_by_command_and_agent_without_state(tmp_path, monkeypatch):
    module = _load_main_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "dead_streaks.json")
    plugin = module.WuxingNumberDivinationPlugin(_Context())

    async def check():
        for question in ["随便看看", "只是好奇，看看今天运势", "没什么事", "事业"]:
            event = _Event(f"/数字卦 {question} | 13254 | 木")
            replies = [item async for item in plugin.number_divination(event)]
            assert "无事不卜" in replies[0]["text"]
            result = await plugin.divine_wuxing_five_numbers(
                event,
                question,
                "13254",
                "木",
                "事业求职",
                "消息出现｜能力生长｜行动显化｜资源承接｜规则落定",
                "机会逐步落实",
            )
            assert "无事不卜" in result
            assert not event.sent_sizes
        assert "无事不卜" in plugin._run(_Event(), "", "13254", "木")

    asyncio.run(check())
    assert plugin._dead_streaks == {}
    assert not module.STATE_FILE.exists()


def test_valid_number_casts_have_no_hourly_or_repeat_limit(tmp_path, monkeypatch):
    module = _load_main_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "dead_streaks.json")
    plugin = module.WuxingNumberDivinationPlugin(_Context())
    for _ in range(6):
        assert "判定：成" in plugin._run(_Event(), "这次求职能否成功", "13254", "木")


def test_three_dead_casts_still_stop_same_question(tmp_path, monkeypatch):
    module = _load_main_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "dead_streaks.json")
    plugin = module.WuxingNumberDivinationPlugin(_Context())
    for _ in range(3):
        assert "死卦" in plugin._run(_Event(), "这次求职能否成功", "11111", "木")
    assert "天机不可泄露" in plugin._run(_Event(), "这次求职能否成功", "13254", "木")


def test_explicit_wuxing_request_can_mention_prior_liuyao(tmp_path, monkeypatch):
    module = _load_main_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "dead_streaks.json")
    plugin = module.WuxingNumberDivinationPlugin(_Context())
    plugin.renderer = None
    response = asyncio.run(
        plugin.divine_wuxing_five_numbers(
            _Event(),
            "这次求职能否成功，先前六爻已测，现在用五行数字测",
            "13254",
            "木",
            "事业求职",
            "消息出现｜能力生长｜行动显化｜资源承接｜规则落定",
            "机会逐步落实",
        )
    )
    assert "判定：成" in response
    assert "本结果、次数、死卦及停问提示均不影响六爻" in response


def test_dead_stop_notice_only_applies_to_wuxing(tmp_path, monkeypatch):
    module = _load_main_module()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "dead_streaks.json")
    plugin = module.WuxingNumberDivinationPlugin(_Context())
    for _ in range(4):
        response = plugin._run(_Event(), "这次求职能否成功", "11111", "木")
        assert "同一事项仍可独立请求六爻" in response
    assert "停止对此事继续使用五行数字卦" in response
    assert "不要再继续询问此事" not in response
