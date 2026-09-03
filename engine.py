"""五行数字卦的纯计算内核，不依赖 AstrBot，便于离线测试。"""

from __future__ import annotations

from dataclasses import dataclass
import re


ELEMENTS = ("水", "火", "木", "金", "土")
DIGIT_ELEMENT = {
    "1": "水", "6": "水",
    "2": "火", "7": "火",
    "3": "木", "8": "木",
    "4": "金", "9": "金",
    "5": "土", "0": "土",
}
DIGIT_YIN_YANG = {
    digit: ("阳" if int(digit) % 2 else "阴")
    for digit in "0123456789"
}
GENERATES = {"水": "木", "木": "火", "火": "土", "土": "金", "金": "水"}
CONTROLS = {"水": "火", "火": "金", "金": "木", "木": "土", "土": "水"}

ROOT_KEYWORDS = {
    "金": ("钱", "财", "收入", "工资", "合同", "签约", "官司", "诉讼", "决定", "交易", "投资"),
    "木": ("学业", "学习", "考试", "升学", "成长", "求职", "工作", "事业", "晋升", "计划"),
    "水": ("出行", "旅行", "搬迁", "物流", "消息", "沟通", "寻找", "远方", "流动"),
    "火": ("感情", "恋爱", "婚姻", "表白", "名气", "名声", "传播", "发布", "比赛"),
    "土": ("房", "家庭", "健康", "疾病", "稳定", "土地", "店铺", "居住", "安定"),
}


@dataclass(frozen=True)
class Transition:
    source: str
    target: str
    name: str
    score: int
    flowing: bool


@dataclass(frozen=True)
class DivinationResult:
    verdict: str
    phrase: str
    root: str
    digits: str
    elements: tuple[str, ...]
    transitions: tuple[Transition, ...]
    score: int
    dead_reason: str = ""

    @property
    def is_dead(self) -> bool:
        return self.verdict == "死卦"


def parse_five_digits(value: str) -> str:
    """接受连续数字或由空格、逗号分隔的五个个位数。"""
    text = str(value).strip()
    if re.fullmatch(r"[0-9]{5}", text):
        return text
    parts = [part for part in re.split(r"[\s,，、]+", text) if part]
    if len(parts) == 5 and all(re.fullmatch(r"[0-9]", part) for part in parts):
        return "".join(parts)
    raise ValueError("必须提供恰好五个数字，每个数字只能是 0 到 9。")


def yin_yang_summary(digits: str) -> tuple[tuple[str, ...], str]:
    """按奇数为阳、偶数（含 0）为阴，返回逐位阴阳和总体状态。"""
    values = tuple(DIGIT_YIN_YANG[digit] for digit in digits)
    yang = values.count("阳")
    yin = values.count("阴")
    if yang == 5:
        state = "纯阳"
    elif yin == 5:
        state = "纯阴"
    elif yang > yin:
        state = "阳盛阴弱"
    else:
        state = "阴盛阳弱"
    return values, f"阳{yang}、阴{yin}（{state}）"


def infer_root(question: str) -> str:
    """为命令模式提供稳定的根气归类；Agent 模式应显式给出根气。"""
    hits = {
        element: sum(question.count(keyword) for keyword in keywords)
        for element, keywords in ROOT_KEYWORDS.items()
    }
    best = max(hits.values(), default=0)
    if best == 0:
        # 无类别词时以问题文本字数取五行，避免随机和模糊回答。
        return ELEMENTS[len(question.strip()) % len(ELEMENTS)]
    return next(element for element in ELEMENTS if hits.get(element, 0) == best)


def relation(source: str, target: str) -> Transition:
    if source == target:
        return Transition(source, target, "同气", 1, True)
    if GENERATES[source] == target:
        return Transition(source, target, "相生", 2, True)
    if GENERATES[target] == source:
        return Transition(source, target, "逆生泄气", -1, False)
    if CONTROLS[source] == target:
        return Transition(source, target, "我克耗气", 0, False)
    return Transition(source, target, "受克阻断", -2, False)


def calculate(question: str, numbers: str, root_element: str | None = None) -> DivinationResult:
    digits = parse_five_digits(numbers)
    root = (root_element or infer_root(question)).strip()
    if root not in ELEMENTS:
        raise ValueError("根气必须是水、火、木、金、土之一。")

    elements = tuple(DIGIT_ELEMENT[digit] for digit in digits)
    transitions = tuple(
        relation(elements[index], elements[(index + 1) % len(elements)])
        for index in range(len(elements))
    )
    score = sum(item.score for item in transitions)
    root_indexes = [index for index, element in enumerate(elements) if element == root]
    flowing_edges = sum(item.flowing for item in transitions)
    hard_blocks = sum(item.name == "受克阻断" for item in transitions)

    if not root_indexes:
        return DivinationResult(
            "死卦", "死卦：所问根气不现，请重新起五个数字。", root, digits,
            elements, transitions, score, "根气不现",
        )

    root_open = any(
        transitions[index].flowing or transitions[(index - 1) % 5].flowing
        for index in root_indexes
    )
    if not root_open or (flowing_edges == 0 and hard_blocks >= 2):
        return DivinationResult(
            "死卦", "死卦：根气被截，五行不流通，请重新起五个数字。", root, digits,
            elements, transitions, score, "根气被截",
        )

    success = score >= 3 and flowing_edges >= 3 and hard_blocks <= 1
    if success:
        phrase = "成：根气有承有发，五行流转贯通，此事可成。"
        verdict = "成"
    else:
        phrase = "败：根气虽现但流转受阻，气不能成局，此事不成。"
        verdict = "败"
    return DivinationResult(
        verdict, phrase, root, digits, elements, transitions, score,
    )


def format_result(result: DivinationResult) -> str:
    yin_yang, yin_yang_state = yin_yang_summary(result.digits)
    paths = "；".join(
        f"{item.source}→{item.target}（{item.name}）" for item in result.transitions
    )
    return "\n".join((
        f"数字：{' '.join(result.digits)}",
        f"阴阳：{' → '.join(yin_yang)}；{yin_yang_state}",
        f"五行：{' → '.join(result.elements)} → {result.elements[0]}",
        f"根气：{result.root}",
        f"流转：{paths}",
        f"判定：{result.verdict}",
        f"断语：{result.phrase}",
    ))

