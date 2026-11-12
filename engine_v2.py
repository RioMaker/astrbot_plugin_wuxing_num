"""Versioned, traceable implementation of 资料/0数字卦.docx.

The source is incomplete. Explicit implementation conventions are exposed with
every result; unsupported reductions return 待定, never an invented dead cast.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

try:
    from .engine import (
        CONTROLS,
        DIGIT_ELEMENT,
        ELEMENTS,
        GENERATES,
        DivinationResult,
        parse_five_digits,
    )
except ImportError:
    from engine import (
        CONTROLS,
        DIGIT_ELEMENT,
        ELEMENTS,
        GENERATES,
        DivinationResult,
        parse_five_digits,
    )

VERSION = "2.0.0"
CONVENTIONS = (
    "缺失五行按水、火、木、金、土顺序补阳，原位和重复元素保留。",
    "全阳时将第一个土转阴；补齐后必有土。",
    "每轮从左向右找可克阳的阴，目标取从左向右第一个；主克消去，被克转阴；余两项停止。",
    "无可执行的阴克阳时，从右向左找阴生阴：生者消去、受生者转阳。这是为简例补充的约定，待老师确认。",
    "两项优先按相生、否则按相克方向排列；只插入能接通两端的事项阳五行，其他合卦情况标为待定。",
)
YIN_MEANINGS = {"木": "思虑、精神状态", "火": "保守、思虑过多与内耗"}
YANG_MEANINGS = {"木": "身体健康与行动", "火": "情绪与冲动"}


@dataclass(frozen=True)
class Token:
    element: str
    yin: bool = False

    @property
    def label(self):
        return ("阴" if self.yin else "阳") + self.element


def labels(tokens):
    return [token.label for token in tokens]


def _ordered_pair(tokens):
    a, b = tokens
    for relation in (GENERATES, CONTROLS):
        if relation[a.element] == b.element:
            return [a, b]
        if relation[b.element] == a.element:
            return [b, a]
    return [a, b]


def _timing(combined):
    # The handout does not explain why supplementation ends at 土. Do not
    # generalize this one example into an unsupported calendar algorithm.
    if labels(combined) != ["阳金", "阳水", "阴木"]:
        return None
    return {
        "basis": "资料金水木案例的补数路径；其他路径未定义",
        "supplements": [
            ["阴木", 8],
            ["阳火", 7],
            ["阴火", 2],
            ["阳土", 5],
            ["阴土", 10],
        ],
        "start": 22,
        "completion": 32,
        "unit": "未定",
        "note": "单位须结合实际事项确定；资料销售例用天，程序不自动推断天/月/年。",
    }


def calculate_v2(question: str, numbers: str, root_element: str) -> DivinationResult:
    digits = parse_five_digits(numbers)
    root = str(root_element).strip()
    if root not in ELEMENTS:
        raise ValueError("事项五行必须是水、火、木、金、土之一。")
    original = [Token(DIGIT_ELEMENT[d], int(d) % 2 == 0) for d in digits]
    tokens = list(original)
    steps = [{"action": "原始数字映射", "state": labels(tokens)}]
    missing = [e for e in ELEMENTS if e not in {t.element for t in tokens}]
    if missing:
        tokens += [Token(e) for e in missing]
        steps.append(
            {
                "action": "补齐缺失五行：" + "、".join("阳" + e for e in missing),
                "state": labels(tokens),
            }
        )
    if all(not t.yin for t in tokens):
        i = next(i for i, t in enumerate(tokens) if t.element == "土")
        tokens[i] = Token("土", True)
        steps.append(
            {"action": "全阳，按约定将第一个阳土转阴", "state": labels(tokens)}
        )
    used_generation = False
    while len(tokens) > 2:
        pair = next(
            (
                (i, j)
                for i, a in enumerate(tokens)
                if a.yin
                for j, b in enumerate(tokens)
                if not b.yin and CONTROLS[a.element] == b.element
            ),
            None,
        )
        action = "克"
        if pair is None:
            pair = next(
                (
                    (i, j)
                    for i in range(len(tokens) - 1, -1, -1)
                    if tokens[i].yin
                    for j, b in enumerate(tokens)
                    if b.yin and GENERATES[tokens[i].element] == b.element
                ),
                None,
            )
            action = "生"
        if pair is None:
            break
        i, j = pair
        a, b = tokens[i], tokens[j]
        changed = Token(b.element, yin=action == "克")
        tokens[j] = changed
        tokens.pop(i)
        used_generation |= action == "生"
        steps.append(
            {
                "action": f"{a.label}{action}{b.label}，{a.label}消去、{b.label}转为{changed.label}"
                + ("（补充约定）" if action == "生" else ""),
                "state": labels(tokens),
            }
        )
    if len(tokens) == 2:
        tokens = _ordered_pair(tokens)
    combined = list(tokens)
    notices = []
    if used_generation:
        notices.append("本卦使用了资料未完整定义的阴生阴补充约定，请结合逐轮过程复核。")
    if len(tokens) != 2:
        notices.append("仍有多项余象，资料未给出下一步通用规则。")
    elif root not in {t.element for t in tokens}:
        a, b = tokens
        if GENERATES[a.element] == root and GENERATES[root] == b.element:
            combined = [a, Token(root), b]
            steps.append(
                {"action": f"将事项五行阳{root}接入相生链", "state": labels(combined)}
            )
        else:
            notices.append("事项五行不能直接接入余象，资料未给出这种情形的合卦规则。")
    valid = len(tokens) == 2 and root in {t.element for t in combined}
    if valid and all(GENERATES[a.element] == b.element for a, b in pairwise(combined)):
        verdict, phrase = "成", "成：结合事项形成生相，按资料可向达成发展。"
    elif (
        valid
        and len(combined) == 2
        and CONTROLS[combined[0].element] == combined[1].element
    ):
        verdict, phrase = (
            "败",
            "败：结合事项为克相，按资料短期难实现，并非永久不能实现。",
        )
    else:
        verdict, phrase = (
            "待定",
            "待定：现有资料不足以确定此种组合的成败，请复核推演过程。",
        )
    timing = _timing(combined) if verdict == "成" else None
    details = {
        "initial": labels(original),
        "missing": missing,
        "steps": steps,
        "final": labels(tokens),
        "combined": labels(combined),
        "conventions": list(CONVENTIONS),
        "notices": notices,
        "timing": timing,
    }
    return DivinationResult(
        verdict,
        phrase,
        root,
        digits,
        tuple(t.element for t in original),
        (),
        0,
        kernel_id="document_v2",
        kernel_version=VERSION,
        details=details,
    )
