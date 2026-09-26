from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .element_icons import ICON_EXPLANATION
from .engine import ELEMENTS, DivinationResult, calculate, format_result
from .question_policy import question_error
from .renderer import ChartRenderError, WuxingChartRenderer

PLUGIN_NAME = "wuxing_num"
DATA_DIR = Path("data") / "plugin_data" / PLUGIN_NAME
STATE_FILE = DATA_DIR / "dead_streaks.json"
METHOD_SCOPE_NOTICE = (
    "术数范围：仅五行数字卦。本结果、次数、死卦及停问提示均不影响六爻；"
    "同一事项仍可独立请求六爻，按六爻自身记录判断准入，勿将本结果当作六爻原卦复用。"
)


@dataclass(frozen=True)
class Symbolism:
    matter_type: str
    meanings: tuple[str, str, str, str, str]
    summary: str


@register(
    PLUGIN_NAME,
    "haxif",
    "以五个数字判断五行流转并生成山水光效象意卦图；只响应专用命令或专用 Agent 工具。",
    "1.4.2",
)
class WuxingNumberDivinationPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self._dead_streaks = self._load_state()
        try:
            self.renderer: WuxingChartRenderer | None = WuxingChartRenderer()
        except ChartRenderError as exc:
            self.renderer = None
            logger.warning(f"wuxing_num：图片渲染器不可用：{exc}")

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
            raise ValueError(
                "格式：/数字卦 你要问的事 | 五个数字；可选在末尾加 | 根气五行。"
            )
        parts[0] = re.sub(r"^/?数字卦\s*", "", parts[0]).strip()
        if not parts[0]:
            raise ValueError("请在 /数字卦 后写明你要问的具体事情。")
        root = parts[2] if len(parts) == 3 and parts[2] else None
        return parts[0], parts[1], root

    def _resolve(
        self,
        event: AstrMessageEvent,
        question: str,
        numbers: str,
        root: str | None,
    ) -> tuple[DivinationResult | None, str]:
        error = question_error(question)
        if error:
            return None, f"{error}\n{METHOD_SCOPE_NOTICE}"
        key = self._question_key(event, question)
        if self._dead_streaks.get(key, 0) >= 3:
            return (
                None,
                "判定：死卦\n断语：五行数字卦连续三次死卦，此事天机不可泄露；请停止对此事继续使用五行数字卦。\n"
                + METHOD_SCOPE_NOTICE,
            )

        result = calculate(question, numbers, root)
        streak = self._apply_dead_streak(key, result.is_dead)
        if result.is_dead and streak >= 3:
            return result, (
                f"{format_result(result)}\n"
                "警示：五行数字卦连续三次死卦，此事天机不可泄露；请停止对此事继续使用五行数字卦。\n"
                + METHOD_SCOPE_NOTICE
            )
        suffix = f"\n死卦次数：{streak}/3" if result.is_dead else ""
        return result, format_result(result) + suffix + "\n" + METHOD_SCOPE_NOTICE

    def _run(
        self, event: AstrMessageEvent, question: str, numbers: str, root: str | None
    ) -> str:
        """Compatibility wrapper retained for existing callers and tests."""
        return self._resolve(event, question, numbers, root)[1]

    @staticmethod
    def _parse_symbolic_meanings(value: str) -> tuple[str, str, str, str, str]:
        parts = [
            " ".join(part.split())[:28]
            for part in re.split(r"[|｜;；\n]+", str(value or ""))
            if part.strip()
        ]
        if len(parts) != 5 or any(not part for part in parts):
            raise ValueError("五位象意必须恰好五条，并按数字顺序用｜分隔。")
        return tuple(parts)  # type: ignore[return-value]

    @staticmethod
    def _fallback_symbolism(result, question: str) -> Symbolism:
        types = {
            "水": "流动消息",
            "火": "情感名望",
            "木": "事业成长",
            "金": "财务决断",
            "土": "家庭根基",
        }
        bases = {
            "水": "消息、流动与远方",
            "火": "显现、热情与名声",
            "木": "成长、计划与进展",
            "金": "规则、财货与决断",
            "土": "承载、资源与稳定",
        }
        roles = ("起因", "承接", "转折", "落实", "归结")
        meanings = tuple(
            f"{roles[index]}：{bases[element]}"[:28]
            for index, element in enumerate(result.elements)
        )
        summary = (
            f"所问以{result.root}为根，五位依次呈现"
            f"{'、'.join(result.elements)}之象；{result.phrase}"
        )
        return Symbolism(types[result.root], meanings, summary)  # type: ignore[arg-type]

    async def _analyze_symbolism(
        self, event, result, question: str
    ) -> tuple[Symbolism, str]:
        fallback = self._fallback_symbolism(result, question)
        get_provider_id = getattr(self.context, "get_current_chat_provider_id", None)
        llm_generate = getattr(self.context, "llm_generate", None)
        if not callable(get_provider_id) or not callable(llm_generate):
            return fallback, "本地规则回退"

        relations = "；".join(
            f"{item.source}→{item.target}（{item.name}）" for item in result.transitions
        )
        prompt = f"""你是五行数字卦的象意标注器，只分析象意，不得修改计算结论。
用户问题：{question}
五个数字：{" ".join(result.digits)}
五行顺序：{" → ".join(result.elements)}
阴阳与流转：{relations}
根气：{result.root}
固定结论：{result.verdict}；固定断语：{result.phrase}
配图说明：{ICON_EXPLANATION}

请只返回 JSON，不要 Markdown：
{{"matter_type":"2至8个汉字的事物类型","meanings":["第1位象意，不超过16字","第2位象意，不超过16字","第3位象意，不超过16字","第4位象意，不超过16字","第5位象意，不超过16字"],"summary":"结合问题、根气和流转的明确总象，不超过70字"}}
五条 meanings 必须按五个数字的原顺序逐位解释，禁止改判成败，禁止使用模糊的两面话。"""
        try:
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            provider_id = await get_provider_id(umo=umo)
            response = await asyncio.wait_for(
                llm_generate(chat_provider_id=provider_id, prompt=prompt),
                timeout=45,
            )
            raw = str(getattr(response, "completion_text", response) or "")
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("模型未返回 JSON 对象")
            payload = json.loads(raw[start : end + 1])
            meanings_raw = payload.get("meanings")
            if not isinstance(meanings_raw, list):
                raise ValueError("meanings 不是数组")
            meanings = self._parse_symbolic_meanings(
                "｜".join(str(item) for item in meanings_raw)
            )
            matter_type = " ".join(str(payload.get("matter_type") or "").split())[:10]
            summary = " ".join(str(payload.get("summary") or "").split())[:120]
            if not matter_type or not summary:
                raise ValueError("事类或总象为空")
            return Symbolism(matter_type, meanings, summary), "当前会话模型"
        except asyncio.TimeoutError:
            logger.warning("wuxing_num：LLM 象意分析超时，使用本地回退")
        except Exception as exc:
            logger.warning(f"wuxing_num：LLM 象意分析失败，使用本地回退：{exc}")
        return fallback, "本地规则回退"

    async def _render_and_send(
        self, event, result, question: str, symbolism: Symbolism, source: str
    ) -> str:
        if self.renderer is None:
            return "图片渲染器不可用，已回退为文字卦象"
        image_path: Path | None = None
        try:
            image_path = await asyncio.to_thread(
                self.renderer.render,
                result,
                question=question,
                matter_type=symbolism.matter_type,
                symbolic_meanings=symbolism.meanings,
                symbolic_summary=symbolism.summary,
                symbolism_source=source,
            )
            if not image_path.is_file() or image_path.stat().st_size <= 0:
                raise ChartRenderError("渲染器没有生成有效 PNG 文件")
            await event.send(event.image_result(str(image_path.absolute())))
            return f"卦图已发送；象意来源：{source}"
        except Exception as exc:
            logger.exception(f"wuxing_num：图片生成或发送失败：{exc}")
            return f"卦图生成失败（{type(exc).__name__}），已回退为文字卦象"
        finally:
            if image_path is not None:
                try:
                    image_path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning(f"wuxing_num：清理临时卦图失败：{exc}")

    @filter.command("数字卦")
    async def number_divination(self, event: AstrMessageEvent):
        """五行数字卦。格式：/数字卦 问题 | 12345 | 可选根气"""
        try:
            question, numbers, root = self._parse_command(event.message_str)
            result, text = self._resolve(event, question, numbers, root)
            if result is None:
                yield event.plain_result(text)
                return
            symbolism, source = await self._analyze_symbolism(event, result, question)
            chart_status = await self._render_and_send(
                event, result, question, symbolism, source
            )
            yield event.plain_result(f"{chart_status}\n\n{text}")
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
        matter_type: str = "",
        five_symbolic_meanings: str = "",
        symbolic_summary: str = "",
    ) -> str:
        """仅在用户明确要求五行数字卦并给出恰好五个数字时调用。

        无事不卜：必须有真实具体的事情，随便看看、消遣、测试或没有具体事情时拒绝调用，
        请用户说明所问，不得编造问题。五行数字不设每小时起卦次数限制，保留三次死卦规则。

        五行数字与六爻完全独立，不读取或修改六爻的记录、额度和判重状态。
        五行数字的结果及三次死卦停问提示仅适用于五行数字，不能阻止同一事项另起六爻卦；
        六爻已测、重复起卦或额度用尽也不能阻止用户明确请求五行数字卦。
        仅按用户当前明确选择的术数路由；历史提及六爻不代表当前请求六爻。
        当前明确要求六爻时不要调用本工具，也不要用五行结果替代六爻原卦。
        先根据问题本质在
        水火木金土中选择唯一根气，再把该字作为 root_element 传入；不得含糊。
        卦图使用专为五行生成的水纹、火焰、枝叶、金属刃面和山岩徽记。
        金为金属而非雷；象意、生克按五行解释，不引入游戏元素反应。

        Args:
            question(string): 用户实际所问之事。
            five_numbers(string): 用户或 AI 给出的恰好五个 0-9 数字。
            root_element(string): AI 判断的唯一根气，只能是水火木金土之一。
            matter_type(string): 明确事类，例如事业求职、财务交易或感情婚姻。
            five_symbolic_meanings(string): 按原序写五条象意，以｜分隔，每条最多16字。
            symbolic_summary(string): 结合问题、根气与流转的总象，最多70字，不改判成败。
        """
        if root_element not in ELEMENTS:
            return "调用失败：root_element 必须明确为水、火、木、金、土之一。"
        try:
            meanings = self._parse_symbolic_meanings(five_symbolic_meanings)
            clean_type = " ".join(str(matter_type or "").split())[:10]
            clean_summary = " ".join(str(symbolic_summary or "").split())[:120]
            if not clean_type or not clean_summary:
                return "调用失败：Agent 必须明确提供事类、五位象意和总象。"
            result, text = self._resolve(event, question, five_numbers, root_element)
            if result is None:
                return text
            symbolism = Symbolism(clean_type, meanings, clean_summary)
            chart_status = await self._render_and_send(
                event,
                result,
                question,
                symbolism,
                "调用此工具的 Agent",
            )
            return (
                f"{chart_status}\n\n{text}\n象意总览：{clean_summary}\n"
                f"配图说明：{ICON_EXPLANATION}"
            )
        except ValueError as exc:
            return f"调用失败：{exc}"
        except OSError:
            logger.exception("保存五行数字卦状态失败")
            return "调用失败：状态保存失败，本次未起卦。"

    async def terminate(self):
        return None
