import asyncio
from types import SimpleNamespace as NS

import pytest
from test_ai_daily import make_plugin
from test_case_store import record

from case_store import CaseStore
from token_usage import case_token_summary, merge_usage, usage_snapshot


def measured(total):
    return usage_snapshot(
        scope="root_selection",
        response=NS(usage=NS(input_other=total - 3, input_cached=2, output=1)),
    )


def add(store, identity, total=None, *, usage=None, **kwargs):
    row = record(identity, **kwargs)
    if total is not None:
        row["token_usage"] = measured(total) if total else usage_snapshot()
    elif usage is not None:
        row["token_usage"] = usage
    store.add(row)
    return row


def test_rankings_change_order_globally_before_pagination(tmp_path):
    store = CaseStore(tmp_path / "cases.json")
    for i in range(3):
        add(store, f"frequent-{i}", 10, user="frequent", group="frequent")
    add(store, "expensive", 1000, user="expensive", group="expensive")
    add(store, "second-group", 50, user="expensive", group="frequent")
    by_count = store.stats(limit=1)
    assert by_count["sort"] == "count"
    assert by_count["groups"][0]["id"] == "frequent"
    assert by_count["users"][0]["id"] == "frequent"
    by_tokens = store.stats(sort="tokens", limit=1)
    assert by_tokens["groups"][0]["id"] == "expensive"
    assert by_tokens["users"][0]["id"] == "expensive"
    assert by_tokens["users"][0]["total_tokens"] == 1050
    second = store.stats(sort="tokens", limit=1, page=2)
    assert second["groups"][0]["id"] == "frequent"
    assert second["groups"][0]["total_tokens"] == 80
    assert second["users"][0]["rank"] == 2
    assert store.stats(page=3, limit=1, sort="tokens")["users"] == []


def test_partial_cases_keep_known_calls_without_double_counting_cache_or_repeats(
    tmp_path,
):
    store = CaseStore(tmp_path / "cases.json")
    first = add(store, "repeat", 100)
    store.add(first)
    add(store, "repeat", 200)
    partial = merge_usage(measured(30), usage_snapshot(scope="root_selection"))
    partial["calls"].append(
        partial["calls"][0]
    )  # malformed duplicate cannot inflate totals
    add(store, "partial", usage=partial)
    add(store, "local", 0)
    add(store, "old")
    before = store.path.read_bytes()
    row = CaseStore(store.path).stats(sort="tokens")["users"][0]
    assert row["count"] == 4
    assert row["total_tokens"] == 330  # no extra cached tokens or aggregate + calls
    assert row["token_known_cases"] == 3
    assert row["token_unknown_cases"] == 1
    assert row["token_unrecorded_cases"] == 1
    assert store.path.read_bytes() == before


def test_platform_private_and_test_boundaries_and_unknown_last(tmp_path):
    store = CaseStore(tmp_path / "cases.json")
    add(store, "qq1", 20, user="same", group="same")
    add(store, "qq2", 30, user="same", group="same", platform="qq2")
    add(store, "private", 40, user="same", group="")
    add(store, "test", 9999, user="admin", source="page_test")
    add(store, "zero", 0, user="zero", group="zero")
    add(
        store,
        "unknown",
        usage=usage_snapshot(scope="agent_context"),
        user="unknown",
        group="unknown",
    )
    for i in range(5):
        add(store, f"old-{i}", user="old", group="old")
    data = store.stats(sort="tokens")
    assert data["total"] == 10 and data["test_total"] == 1
    assert [(r["id"], r["platform"], r["total_tokens"]) for r in data["users"][:3]] == [
        ("same", "qq1", 60),
        ("same", "qq2", 30),
        ("zero", "qq1", 0),
    ]
    assert data["groups"][0]["platform"] == "qq2"
    assert (
        data["users"][-2]["id"] == "old"
        and data["users"][-2]["token_unrecorded_cases"] == 5
    )
    assert (
        data["users"][-1]["id"] == "unknown"
        and data["users"][-1]["token_unknown_cases"] == 1
    )
    assert data["users"][-1]["token_known_cases"] == 0
    assert data["users"][2]["token_known_cases"] == 1
    assert sum(r["total_tokens"] for r in data["groups"]) == 50
    assert sum(r["total_tokens"] for r in data["users"]) == 90


def test_token_ties_are_stable_and_prioritize_call_count(tmp_path):
    store = CaseStore(tmp_path / "cases.json")
    add(store, "b", 100, user="b")
    add(store, "a", 100, user="a")
    add(store, "c1", 50, user="c")
    add(store, "c2", 50, user="c")
    assert [r["id"] for r in store.stats(sort="tokens")["users"]] == ["c", "a", "b"]


@pytest.mark.parametrize("total", [None, True, -1, 1.5, "123"])
def test_unknown_or_invalid_total_is_not_a_measured_zero(total):
    result = case_token_summary({"token_usage": {"total_tokens": total, "calls": None}})
    assert result["token_known_cases"] == 0 and result["token_unknown_cases"] == 1


def test_reported_total_needs_no_input_output_estimation():
    result = case_token_summary(
        {"token_usage": {"total_tokens": 123, "status": "partial"}}
    )
    assert result["total_tokens"] == 123 and result["token_known_cases"] == 1
    assert result["token_unknown_cases"] == 0


def test_empty_rankings_remain_available(tmp_path):
    data = CaseStore(tmp_path / "cases.json").stats(sort="tokens")
    assert data["sort"] == "tokens" and data["groups"] == [] and data["users"] == []


def test_management_passes_sort_and_pagination_to_both_rankings(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, monkeypatch)
    store = plugin._get_case_store()
    add(store, "small", 10, user="small", group="small")
    add(store, "large", 100, user="large", group="large")
    data = asyncio.run(plugin.page_stats({"sort": "tokens", "limit": "1", "page": "1"}))
    assert data["sort"] == "tokens" and data["groups"][0]["id"] == "large"
    assert data["users"][0]["total_tokens"] == 100
    assert plugin.context._plugin_kv == {}


@pytest.mark.parametrize("sort", ["bad", None, True, ["tokens"], {"sort": "tokens"}])
def test_management_rejects_invalid_sort(tmp_path, monkeypatch, sort):
    plugin, _ = make_plugin(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="排序"):
        asyncio.run(plugin.page_stats({"sort": sort}))
