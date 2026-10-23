"""Explain the existing engine result with deterministic, auditable rules."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from .engine import DivinationResult, yin_yang_summary
except ImportError:
    from engine import DivinationResult, yin_yang_summary


@dataclass(frozen=True)
class Symbolism:
    matter_type: str
    meanings: tuple[str, str, str, str, str]
    summary: str


def build_symbolism(result: DivinationResult) -> Symbolism:
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


def build_reading(result: DivinationResult) -> str:
    """Describe actual positions and thresholds, without adding prediction rules."""
    roots = [i for i, element in enumerate(result.elements) if element == result.root]
    flowing = sum(item.flowing for item in result.transitions)
    blocks = sum(item.name == "受克阻断" for item in result.transitions)
    parts = ["程序解卦（本地规则）"]
    if roots:
        positions = "、".join(str(i + 1) for i in roots)
        parts.append(f"根气：{result.root}见于第{positions}位。")
        for i in roots:
            before, after = result.transitions[(i - 1) % 5], result.transitions[i]
            parts.append(
                f"第{i + 1}位根气两侧：{before.source}→{before.target}（{before.name}），"
                f"{after.source}→{after.target}（{after.name}）。"
            )
    else:
        parts.append(f"根气：{result.root}未出现在五个数字的五行中。")
    parts.append(
        "阴阳：" + yin_yang_summary(result.digits)[1] + "；仅作展示，不参与成败计分。"
    )
    parts.append(
        f"流转：五段中相生/同气{flowing}段，受克阻断{blocks}段，总分{result.score}。"
    )
    if result.is_dead:
        if result.dead_reason == "根气不现":
            reason = "所问根气不现，不能立卦。"
        else:
            reason = "各处根气的左右两侧均无流通边，按现有规则判为根气被截。"
        parts.append("依据：" + reason)
    elif result.verdict == "成":
        parts.append(
            "依据：根气至少一侧可通，且总分≥3、流通≥3段、受克≤1段，满足成局条件。"
        )
    else:
        failed = []
        if result.score < 3:
            failed.append("总分不足3")
        if flowing < 3:
            failed.append("流通不足3段")
        if blocks > 1:
            failed.append("受克超过1段")
        parts.append("依据：根气虽可立，但" + "、".join(failed) + "，未满足成局条件。")
    parts.append("断语：" + result.phrase)
    return "\n".join(parts)
