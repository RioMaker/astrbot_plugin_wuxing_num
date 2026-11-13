import asyncio
import concurrent.futures
import json
from types import SimpleNamespace as NS
from zipfile import ZipFile

import pytest
from test_ai_daily import agent, command, make_plugin
from test_case_store import record
from test_main import _Event, _LlmContext
from test_management import payload

from case_store import CaseStore
from token_usage import extract_usage, merge_usage, usage_snapshot


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (NS(usage=NS(input_other=80, input_cached=20, output=7)), (100, 7, 20, 107)),
        ({"usage": {"input_other": 0, "input_cached": 0, "output": 0}}, (0, 0, 0, 0)),
        (
            {
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 9,
                    "total_tokens": 109,
                    "prompt_tokens_details": {"cached_tokens": 40},
                }
            },
            (100, 9, 40, 109),
        ),
        (
            NS(
                raw_completion=NS(
                    usage=NS(
                        input_tokens=100,
                        output_tokens=9,
                        input_tokens_details=NS(cached_tokens=40),
                    )
                )
            ),
            (100, 9, 40, 109),
        ),
        (
            {
                "raw_completion": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 7,
                        "cache_read_input_tokens": 20,
                        "cache_creation_input_tokens": 5,
                    }
                }
            },
            (35, 7, 20, 42),
        ),
        (
            {
                "raw_completion": {
                    "usageMetadata": {
                        "promptTokenCount": 30,
                        "candidatesTokenCount": 4,
                        "thoughtsTokenCount": 6,
                        "totalTokenCount": 40,
                        "cachedContentTokenCount": 12,
                    }
                }
            },
            (30, 10, 12, 40),
        ),
        (
            {
                "raw_completion": {
                    "usage_metadata": {
                        "prompt_token_count": 30,
                        "candidates_token_count": 4,
                        "thoughts_token_count": 6,
                        "total_token_count": 40,
                    }
                }
            },
            (30, 10, None, 40),
        ),
        ({"usage": {"total_tokens": 123}}, (None, None, None, 123)),
        ({"usage": {"input_other": 20, "output": 2}}, (None, 2, None, None)),
        (
            {
                "usage": {
                    "input_tokens": True,
                    "output_tokens": -1,
                    "total_tokens": "20",
                }
            },
            (None, None, None, None),
        ),
        (
            {"usage": {"input_tokens": 1.5, "output_tokens": 2**64}},
            (None, None, None, None),
        ),
        (
            NS(
                usage=NS(input_other=0, input_cached=0, output=0),
                raw_completion=NS(usage=None),
            ),
            (None, None, None, None),
        ),
        (NS(completion_text="很长的解读" * 1000), (None, None, None, None)),
    ],
)
def test_reported_usage_and_unknown_are_not_confused(response, expected):
    result = extract_usage(response)
    assert tuple(result.values()) == expected


def measured(total=107):
    return usage_snapshot(
        scope="root_selection",
        provider_id="existing-provider",
        response=NS(usage=NS(input_other=80, input_cached=20, output=total - 100)),
    )


def test_snapshots_exclude_raw_responses_and_preserve_partial_fields():
    usage = usage_snapshot(
        scope="page_interpretation",
        response={
            "usage": {"total_tokens": 123},
            "completion_text": "secret",
            "raw_completion": {"api_key": "secret"},
        },
    )
    assert usage["status"] == "partial" and usage["input_tokens"] is None
    assert usage["total_tokens"] == 123
    assert "secret" not in json.dumps(usage)
    assert usage_snapshot()["total_tokens"] == 0
    assert usage_snapshot(scope="agent_context")["status"] == "external"


@pytest.mark.parametrize(
    "raw_usage", [None, {}, {"input_tokens": 40, "output_tokens": 5}]
)
def test_zero_adapter_placeholder_uses_raw_usage(raw_usage):
    result = extract_usage(
        NS(
            usage=NS(input_other=0, input_cached=0, output=0),
            raw_completion={"usage": raw_usage},
        )
    )
    assert result["total_tokens"] == (45 if raw_usage else None)


def test_merge_deduplicates_measurements_and_does_not_hide_unknown_costs():
    first = measured()
    assert merge_usage(first, first) == first
    assert merge_usage(first, measured())["total_tokens"] == 214
    partial = merge_usage(first, usage_snapshot(scope="page_interpretation"))
    assert partial["status"] == "partial" and partial["total_tokens"] is None
    assert partial["calls"][0]["total_tokens"] == 107


def test_repeated_case_cost_is_persisted_exported_without_inflating_rank(tmp_path):
    store = CaseStore(tmp_path / "cases.json")
    first = {**record(1), "token_usage": measured()}
    store.add(first)
    store.add(first)
    second = {**record(1), "token_usage": measured(110)}
    store.add(second)
    reloaded = CaseStore(store.path)
    assert reloaded.stats()["total"] == 1
    usage = reloaded.get("1")["token_usage"]
    assert usage["total_tokens"] == 217 and len(usage["calls"]) == 2
    with ZipFile(reloaded.export(tmp_path / "export")) as z:
        assert json.loads(z.read("cases.json"))["records"][0]["token_usage"] == usage
        assert "token_usage.calls[].scope" in z.read("说明.md").decode()


def test_old_records_are_readable_and_never_backfilled_as_zero(tmp_path):
    store = CaseStore(tmp_path / "cases.json")
    store.add(record(1))
    assert "token_usage" not in store.history()["records"][0]
    store.add({**record(1), "token_usage": measured()})
    usage = store.get("1")["token_usage"]
    assert usage["status"] == "partial" and usage["total_tokens"] is None
    assert usage["calls"][0]["scope"] == "historical"


def test_concurrent_usage_merges_and_failed_write_preserve_data(tmp_path, monkeypatch):
    store = CaseStore(tmp_path / "cases.json")
    store.add({**record(1), "token_usage": usage_snapshot()})
    updates = [{**record(1), "token_usage": measured()} for _ in range(12)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(store.add, updates))
    assert store.get("1")["token_usage"]["total_tokens"] == 12 * 107
    before = store.path.read_bytes()

    def fail(*_args):
        raise OSError("disk full")

    monkeypatch.setattr("case_store.os.replace", fail)
    with pytest.raises(OSError):
        store.add({**record(1), "token_usage": measured()})
    assert store.path.read_bytes() == before


def test_export_refreshes_guide_even_when_cases_have_not_changed(tmp_path, monkeypatch):
    import case_store

    store = CaseStore(tmp_path / "cases.json")
    store.add(record(1))
    before = store.export(tmp_path / "exports")
    monkeypatch.setattr(
        case_store, "EXPORT_GUIDE", case_store.EXPORT_GUIDE + "\n新增字段说明\n"
    )
    after = store.export(tmp_path / "exports")
    assert before != after
    with ZipFile(after) as z:
        assert "新增字段说明" in z.read("说明.md").decode()


def test_command_and_agent_save_correct_usage_and_keep_quota(tmp_path, monkeypatch):
    context = _LlmContext()
    plugin, _ = make_plugin(tmp_path, monkeypatch, context=context)

    async def llm(**kwargs):
        return NS(
            completion_text="木", usage=NS(input_other=80, input_cached=20, output=7)
        )

    monkeypatch.setattr(context, "llm_generate", llm)

    async def run():
        event = _Event(message_id="repeat-real-call")
        await command(plugin, event)
        await command(plugin, event)
        history = plugin._get_case_store().history()
        assert history["total"] == 1
        usage = history["records"][0]["token_usage"]
        assert usage["total_tokens"] == 214 and len(usage["calls"]) == 2
        assert "额度已用完" in await command(plugin)
        await command(plugin, manual=True)
        await agent(plugin, _Event(sender_id="another-user"))
        rows = plugin._get_case_store().history()["records"]
        assert (
            next(r for r in rows if r["root_source"] == "手动指定")["token_usage"][
                "total_tokens"
            ]
            == 0
        )
        external = next(r for r in rows if r["source"] == "agent")["token_usage"]
        assert external["status"] == "external" and external["total_tokens"] is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode",
    ["local", "missing_provider", "reported", "unknown", "timeout", "invalid_response"],
)
def test_page_usage_on_success_failure_preview_and_duplicate_request(
    tmp_path, monkeypatch, mode
):
    class Context(_LlmContext):
        async def llm_generate(self, **kwargs):
            self.calls.append(kwargs)
            if mode == "timeout":
                raise asyncio.TimeoutError()  # noqa: UP041 - Python 3.10 timeout compatibility.
            return NS(
                completion_text=""
                if mode == "invalid_response"
                else "根据程序结果继续推进。",
                usage=None
                if mode == "unknown"
                else NS(input_other=30, input_cached=10, output=8),
            )

    context = Context()
    plugin, _ = make_plugin(
        tmp_path,
        monkeypatch,
        context=context,
        config={
            "page_provider_id": "" if mode == "missing_provider" else "configured-model"
        },
    )

    async def run():
        request = payload(with_ai=mode != "local")
        data = await plugin.page_test(request, username="admin")
        usage = data["record"]["token_usage"]
        if mode in ("local", "missing_provider"):
            assert usage["status"] == "not_used" and usage["total_tokens"] == 0
            assert not context.calls
        elif mode in ("reported", "invalid_response"):
            assert usage["total_tokens"] == 48 and usage["cached_tokens"] == 10
        else:
            assert usage["status"] == "unknown" and usage["total_tokens"] is None
        if mode == "invalid_response":
            assert data["record"]["ai_status"] == "failed"
        before = len(context.calls)
        assert (await plugin.page_test(request, username="admin"))["record"][
            "token_usage"
        ] == usage
        assert (await plugin.page_preview({}, record_id=data["record"]["id"]))[
            "record"
        ]["token_usage"] == usage
        assert len(context.calls) == before
        assert context._plugin_kv == {}

    asyncio.run(run())
