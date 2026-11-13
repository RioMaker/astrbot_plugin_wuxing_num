"""Compact, atomic JSON case library. No images, prompts or chat history stored."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

if __package__:
    from .token_usage import merge_usage
else:
    from token_usage import merge_usage

BEIJING = timezone(timedelta(hours=8))
_STORE_LOCKS: dict[str, threading.RLock] = {}
_REGISTRY_LOCK = threading.Lock()


def now_iso():
    return datetime.now(BEIJING).isoformat(timespec="seconds")


EXPORT_GUIDE = """# 五行数字卦卦例库说明

cases.json 是可独立读取的 UTF-8 JSON 存储文件。ZIP 不包含图片、API 密钥、聊天历史或模型提示词。
导出包含全部正式卦例和后台测试记录，不受页面筛选或分页限制。

## 顶层字段

| 字段 | 含义 |
| --- | --- |
| schema_version | 存储格式版本，目前为 1 |
| started_at | 此卦例库首次创建时间，ISO 8601，北京时间 +08:00 |
| records | 全部记录的数组，按写入顺序保存 |

## 记录字段

| 字段 | 含义 |
| --- | --- |
| id | 记录标识；同一消息的相同卦例去重，后台测试按请求标识去重 |
| created_at | 起卦时间，ISO 8601，+08:00 |
| source | command 指令、agent 工具、page_test 后台测试 |
| platform | 平台实例标识；后台为 dashboard |
| user_id / user_name | 问卦人账号及当时昵称；后台使用已登录管理员身份 |
| group_id / group_name | 群号及当时群名；私聊、后台为空。群名取不到时为空 |
| question | 本次具体问题 |
| numbers | 五位原始数字字符串，保留前导 0 |
| root | 经典内核的根气；资料内核的事项五行 |
| root_source | 手动指定、AI 按问题选取或 Agent 按问题选取 |
| kernel / kernel_version | 计算内核标识及规则版本；legacy_v1 或 document_v2 |
| result | 当时结果快照，包含 verdict、phrase、dead_reason、final、combined、notices、timing（不适用字段可缺省） |
| result.verdict | 成、败、死卦、待定；v2 的败指短期难实现，待定不累计死卦 |
| result.phrase | 当时程序断语 |
| result.dead_reason | 经典内核的死卦原因，正常结果为空 |
| result.final / combined | v2 余象及结合事项后的有序阴阳五行字符串数组 |
| result.notices | 资料不完整或使用补充约定的说明 |
| result.timing | 可为空；案例补数信息，不是经过验证的日期预测 |
| result.timing.basis / note / unit | 补数依据、解释、单位；默认未定 |
| result.timing.supplements | [阴阳五行,数值] 数组；应期阴土取 10，不是输入数字 0 |
| result.timing.start / completion | 开始、达成的数值；单位需结合事情确认 |
| reading | 保存当时的程序解卦和推演过程，避免内核更新后失去原解释 |
| ai_used | 是否使用 AI（含命令取根气、Agent 选根气、后台 AI 解读） |
| ai_status | not_requested 未请求解读、success 解读成功、failed 解读失败；取根气不等于解读 |
| ai_interpretation | AI 解读原文；没有则为空，不伪造解读 |
| ai_error | 解读失败的简短状态，不保存模型密钥或请求体 |
| token_usage | 可选 Token 用量对象；旧记录缺省表示未记录，不能当作 0 |
| token_usage.status | reported 已返回输入/输出/总量；partial 仅有部分用量；unknown 未知；external 外部 Agent 无法归属；not_used 未请求模型 |
| token_usage.input_tokens | 输入 Token，包含缓存输入；未知为 null |
| token_usage.output_tokens | 输出 Token，包含接口已报告的思考 Token；未知为 null |
| token_usage.cached_tokens | 缓存命中的输入 Token，是 input_tokens 的子集，不再加到总量；未报告为 null |
| token_usage.total_tokens | 总 Token；优先保留接口报告，缺省时仅由已知输入与输出相加；未知为 null |
| token_usage.calls | 精简计量明细；同一卦例重复触发真实模型请求时保留各次用量。无模型调用时为空数组 |
| token_usage.calls[].id | 计量标识，重复保存相同计量不重复累加 |
| token_usage.calls[].scope | root_selection 指令取根气；page_interpretation 后台 AI 解读；agent_context 外部 Agent 无法归属；historical 同一旧卦例原有用量未记录 |
| token_usage.calls[].provider_id | 可选，已配置模型提供商 ID；不保存密钥或配置对象 |
| token_usage.calls[].status / input_tokens / output_tokens / cached_tokens / total_tokens | 本条明细的状态与用量，含义同上；agent_context 和 historical 只是未知占位，不代表观测到一次 API 请求 |

## Token 口径

从模型响应的 usage 读取实际报告值，不按字数估算。纯本地起卦为 0；旧记录、接口未报告或请求超时不能补成 0。
后台解读失败但模型已返回 usage 时仍保存用量；未配置模型、未发起请求为 0。
Agent 在插件外选择根气，工具内没有模型请求；外部对话可能包含其他任务，不能把整段对话 Token 算在此卦，故标为 external。
目前统计插件直接请求模型的输入与输出，不包括主 Agent 其他轮次、平台重试或供应商未返回的消耗，也不是金额账单。
多条明细汇总时，只要任一条某项未知，该汇总项即为 null；已知部分仍可在 calls 中查看。
同一消息的相同卦例仍只算一次起卦，实际重复的模型请求用量则累计；查看、预览和导出不会增加用量。

## 计数口径与恢复

群、个人排行按已保存的正式卦例次数降序排列，包括死卦；不计拒绝的输入、未起卦的 AI 失败或后台测试。
个人按平台实例和账号合并各群次数；群按平台实例和群号汇总。后台测试单独显示。
只有启用本版本后生成的卦例才能入库，旧版每日额度不是历史卦例，不能还原旧排行。
同分按标识排序。页面查看和历史图片预览不计次，不调用 AI。

如需离线恢复：先停止插件，备份 data/plugin_data/wuxing_num/cases.json，
把本包 cases.json 放回同一路径后重载插件。不要在运行中手工编辑文件。
ai_daily_quota 和 dead_streaks 不在本包内，此包不用于恢复配额或三次死卦限制。
原始存储不自动截断，导出也不裁剪。图片按需生成，不长期存储。
资料内核的完整约定见插件 docs/kernel-v2.md，规则版本用于追溯，不代表资料已无歧义。
"""


class CaseStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        # Reloaded plugin instances in the same process may briefly overlap.
        # Share the write lock by canonical file path to avoid lost updates.
        with _REGISTRY_LOCK:
            key = os.path.normcase(str(self.path.resolve()))
            self._lock = _STORE_LOCKS.setdefault(key, threading.RLock())

    def _read(self):
        if not self.path.exists():
            return {"schema_version": 1, "started_at": now_iso(), "records": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or data.get("schema_version") != 1
                or not isinstance(data.get("records"), list)
                or any(
                    not isinstance(r, dict) or not r.get("id") for r in data["records"]
                )
            ):
                raise ValueError("invalid case schema")
            return data
        except (ValueError, TypeError) as exc:
            raise OSError(
                "卦例库损坏，已停止读写；请备份并检查 cases.json，原文件未覆盖。"
            ) from exc

    def add(self, record):
        with self._lock:
            data = self._read()
            for existing in data["records"]:
                if existing["id"] == record["id"]:
                    if record.get("token_usage") is not None:
                        combined = merge_usage(
                            existing.get("token_usage"), record["token_usage"]
                        )
                        if combined != existing.get("token_usage"):
                            existing["token_usage"] = combined
                            self._write(data)
                    return existing
            data["records"].append(record)
            self._write(data)
            return record

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(
            prefix="cases-", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(data, out, ensure_ascii=False, separators=(",", ":"))
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def get(self, record_id):
        with self._lock:
            return next(
                (r for r in self._read()["records"] if r["id"] == record_id), None
            )

    def history(self, *, page=1, limit=20, source="all"):
        with self._lock:
            rows = self._read()["records"]
            if source != "all":
                rows = [
                    r
                    for r in rows
                    if (r["source"] == "page_test") == (source == "test")
                ]
            rows = sorted(rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)
            start = (page - 1) * limit
            return {
                "total": len(rows),
                "page": page,
                "limit": limit,
                "records": rows[start : start + limit],
            }

    def stats(self, *, page=1, limit=50):
        with self._lock:
            data = self._read()
        groups, users = {}, {}
        kernels = defaultdict(int)
        official = [r for r in data["records"] if r["source"] != "page_test"]
        for r in official:
            kernels[r["kernel"]] += 1
            identities = [(users, (r["platform"], r["user_id"]), r["user_name"])]
            if r["group_id"]:
                identities.append(
                    (groups, (r["platform"], r["group_id"]), r["group_name"])
                )
            for target, key, name in identities:
                item = target.setdefault(
                    key,
                    {
                        "platform": key[0],
                        "id": key[1],
                        "name": name,
                        "count": 0,
                        "ai_count": 0,
                    },
                )
                item["count"] += 1
                item["ai_count"] += int(bool(r.get("ai_used")))
                if name:
                    item["name"] = name

        def ranked(mapping):
            rows = sorted(
                mapping.values(), key=lambda r: (-r["count"], r["platform"], r["id"])
            )
            for i, row in enumerate(rows, 1):
                row["rank"] = i
            return rows[(page - 1) * limit : page * limit]

        return {
            "started_at": data["started_at"] if data["records"] else None,
            "total": len(official),
            "test_total": len(data["records"]) - len(official),
            "ai_total": sum(bool(r.get("ai_used")) for r in official),
            "kernels": dict(kernels),
            "groups": ranked(groups),
            "users": ranked(users),
            "group_total": len(groups),
            "user_total": len(users),
            "page": page,
            "limit": limit,
        }

    def export(self, directory):
        with self._lock:
            data = self._read()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        digest = hashlib.sha256((content + EXPORT_GUIDE).encode()).hexdigest()[:16]
        target = directory / f"wuxing-cases-{digest}.zip"
        # Old downloads are disposable caches; the authoritative cases.json is
        # never pruned. Leave recent files alone while Dashboard may stream them.
        for old in directory.glob("wuxing-cases-*.zip"):
            try:
                if old != target and old.stat().st_mtime < time.time() - 172800:
                    old.unlink()
            except OSError:
                pass  # A download in use can be cleaned up on a later export.
        if target.exists():
            return target
        # Content-addressed exports remain stable while Dashboard streams them.
        fd, temporary = tempfile.mkstemp(prefix="export-", suffix=".tmp", dir=directory)
        os.close(fd)
        try:
            with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
                archive.writestr("cases.json", content)
                archive.writestr("说明.md", EXPORT_GUIDE)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return target
