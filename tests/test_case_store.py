import concurrent.futures
import json
from zipfile import ZipFile

import pytest

from case_store import CaseStore


def record(identity, *, user="u1", group="g1", source="command", platform="qq1"):
    return {
        "id": str(identity),
        "created_at": "2026-11-12T12:00:00+08:00",
        "source": source,
        "platform": platform,
        "user_id": user,
        "user_name": user,
        "group_id": group,
        "group_name": group,
        "kernel": "document_v2",
        "ai_used": False,
        "numbers": "01234",
        "question": "具体问题是否达成",
        "ai_interpretation": "",
    }


def test_concurrent_writes_dedupe_and_survive_reload(tmp_path):
    store = CaseStore(tmp_path / "cases.json")
    reloaded = CaseStore(store.path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(
            pool.map(
                lambda i: (store if i % 2 else reloaded).add(record(i % 40)), range(80)
            )
        )
    loaded = CaseStore(store.path)
    assert loaded.history()["total"] == 40
    assert len(json.loads(store.path.read_text("utf-8"))["records"]) == 40
    assert not list(tmp_path.glob("*.tmp"))


def test_rank_by_count_across_groups_isolate_platform_and_tests(tmp_path):
    store = CaseStore(tmp_path / "cases.json")
    for r in [
        record(1),
        record(2),
        record(3, group="g2"),
        record(4, user="u2", group="g2"),
        record(5, platform="qq2"),
        record(6, user="admin", group="", source="page_test"),
    ]:
        store.add(r)
    data = store.stats()
    assert data["total"] == 5 and data["test_total"] == 1
    assert data["users"][0]["id"] == "u1" and data["users"][0]["count"] == 3
    assert data["user_total"] == 3 and data["group_total"] == 3
    assert [r["count"] for r in data["groups"]] == [2, 2, 1]
    assert store.history(source="test")["total"] == 1
    assert store.stats(page=2, limit=1)["users"][0]["rank"] == 2


def test_export_contains_complete_storage_and_guide_not_just_current_page(tmp_path):
    store = CaseStore(tmp_path / "cases.json")
    for i in range(25):
        store.add(record(i, source="page_test" if i == 24 else "command"))
    assert len(store.history(limit=5)["records"]) == 5
    archive = store.export(tmp_path / "exports")
    with ZipFile(archive) as z:
        assert sorted(z.namelist()) == ["cases.json", "说明.md"]
        exported = json.loads(z.read("cases.json"))
        assert len(exported["records"]) == 25
        assert exported["records"][0]["numbers"] == "01234"
        assert "ai_interpretation" in z.read("说明.md").decode()
    assert exported == json.loads(store.path.read_text("utf-8"))


def test_corrupt_storage_is_never_overwritten(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text("{damaged", encoding="utf-8")
    with pytest.raises(OSError, match="损坏"):
        CaseStore(path).add(record(1))
    assert path.read_text("utf-8") == "{damaged"


def test_failed_atomic_replace_keeps_previous_records(tmp_path, monkeypatch):
    store = CaseStore(tmp_path / "cases.json")
    store.add(record(1))

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("case_store.os.replace", fail)
    with pytest.raises(OSError):
        store.add(record(2))
    assert store.history()["total"] == 1
    assert not list(tmp_path.glob("*.tmp"))
