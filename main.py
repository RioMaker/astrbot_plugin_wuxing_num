from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .engine import ELEMENTS, calculate, format_result, infer_root


PLUGIN_NAME = "wuxing_num"
DATA_DIR = Path("data") / "plugin_data" / PLUGIN_NAME
STATE_FILE = DATA_DIR / "dead_streaks.json"
LIUYAO_TERMS = ("六爻", "铜钱", "摇卦", "爻辞", "世爻", "应爻", "纳甲")


@register(
    PLUGIN_NAME,
    "haxif",
    "以五个数字判断五行流转的数字卦；只响应专用命令或专用 Agent 工具。",
    "1.0.0",
)
class WuxingNumberDivinationPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._dead_streaks = self._load_state()

    @staticmethod
    def _load_state() -> dict[str, int]:
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return {str(key): int(value) for key, value in raw.items()}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError):
            logger.warning("五行数字卦状态文件无效，将从空状态开始。")
            return {}

    def _save_state(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._dead_streaks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(STATE_FILE)

    @staticmethod
    def _question_key(event: AstrMessageEvent, question: str) -> str:
        sender = str(event.get_sender_id())
        normalized = re.sub(r"\s+", "", question).casefold()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
        return f"{sender}:{digest}"

    def _apply_dead_streak(self, key: str, is_dead: bool) -> int:
        if is_dead:
            self._dead_streaks[key] = self._dead_streaks.get(key, 0) + 1
        else:
            self._dead_streaks.pop(key, None)
        self._save_state()
        return self._dead_streaks.get(key, 0)

    @staticmethod
    def _parse_command(text: str) -> tuple[str, str, str | None]:
        parts = [part.strip() for part in re.split(r"[|｜]", text, maxsplit=2)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError("格式：/数字卦 你要问的事 | 五个数字；可选在末尾加 | 根气五行。")
        root = parts[2] if len(parts) == 3 and parts[2] else None
        return parts[0], parts[1], root

    def _run(self, event: AstrMessageEvent, question: str, numbers: str, root: str | None) -> str:
        key = self._question_key(event, question)
        if self._dead_streaks.get(key, 0) >= 3:
            return "判定：死卦\n断语：连续三次死卦，此事天机不可泄露，请更换问题或不要再继续询问此事。"

        result = calculate(question, numbers, root)
        streak = self._apply_dead_streak(key, result.is_dead)
        if result.is_dead and streak >= 3:
            return (
                f"{format_result(result)}\n"
                "警示：连续三次死卦，此事天机不可泄露，请更换问题或不要再继续询问此事。"
            )
        suffix = f"\n死卦次数：{streak}/3" if result.is_dead else ""
        return format_result(result) + suffix

    @filter.command("数字卦")
    async def number_divination(self, event: AstrMessageEvent):
        """五行数字卦。格式：/数字卦 问题 | 12345 | 可选根气"""
        try:
            question, numbers, root = self._parse_command(event.message_str)
            yield event.plain_result(self._run(event, question, numbers, root))
        except ValueError as exc:
            yield event.plain_result(str(exc))
        except OSError:
            logger.exception("保存五行数字卦状态失败")
            yield event.plain_result("数字卦状态保存失败，本次未起卦，请稍后重试。")

    @filter.llm_tool(name="divine_wuxing_five_numbers")
    async def divine_wuxing_five_numbers(
        self,
        event: AstrMessageEvent,
        question: str,
        five_numbers: str,
        root_element: str,
    ) -> str:
        """仅在用户明确要求五行数字卦并给出恰好五个数字时调用。

        禁止用于六爻、铜钱卦、摇卦、爻辞、纳甲等请求。先根据问题本质在
        水火木金土中选择唯一根气，再把该字作为 root_element 传入；不得含糊。

        Args:
            question(string): 用户实际所问之事。
            five_numbers(string): 用户或 AI 给出的恰好五个 0-9 数字。
            root_element(string): AI 判断的唯一根气，只能是水火木金土之一。
        """
        if any(term in question for term in LIUYAO_TERMS):
            return "拒绝调用：这是六爻类请求，应交由六爻插件处理。"
        if root_element not in ELEMENTS:
            return "调用失败：root_element 必须明确为水、火、木、金、土之一。"
        try:
            return self._run(event, question, five_numbers, root_element)
        except ValueError as exc:
            return f"调用失败：{exc}"
        except OSError:
            logger.exception("保存五行数字卦状态失败")
            return "调用失败：状态保存失败，本次未起卦。"

    async def terminate(self):
        return None

