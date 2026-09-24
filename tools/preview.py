"""Render real local charts with explicitly illustrative (not live LLM) symbolism."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import calculate  # noqa: E402
from renderer import WuxingChartRenderer  # noqa: E402

CASES = {
    "success": {
        "numbers": "13254",
        "root": "木",
        "question": "这次求职能成功吗？",
        "matter_type": "事业求职",
        "symbolic_meanings": (
            "消息渠道",
            "岗位机会",
            "面试表现",
            "落地承接",
            "资格凭证",
        ),
        "symbolic_summary": "木为事业根气，水生木，消息带来机会；后续火土金依次承接，流转条件满足成局。",
    },
    "failure": {
        "numbers": "41235",
        "root": "金",
        "question": "这次合同能顺利签下吗？",
        "matter_type": "合同签约",
        "symbolic_meanings": (
            "合同条款",
            "往来沟通",
            "公开表态",
            "合作计划",
            "执行资源",
        ),
        "symbolic_summary": "金为合同根气，虽有土生金承接，但中段两处我克耗气、一处逆生泄气，整体不足以成局。",
    },
    "dead": {
        "numbers": "12327",
        "root": "金",
        "question": "这笔交易能谈成吗？",
        "matter_type": "财务交易",
        "symbolic_meanings": (
            "消息往来",
            "交易热度",
            "合作意向",
            "公开承诺",
            "推进意愿",
        ),
        "symbolic_summary": "本卦有水火木，但所问金根未现。按当前规则不能立卦，需要重新提供五个数字。",
    },
    "blocked": {
        "numbers": "34925",
        "root": "木",
        "question": "这个事业计划能实现吗？",
        "matter_type": "事业计划",
        "symbolic_meanings": (
            "发展计划",
            "资格约束",
            "规则审查",
            "行动表现",
            "资源基础",
        ),
        "symbolic_summary": "木根虽现，但相邻两段未满足当前算法的流通条件，判为根气被截，需要重新起卦。",
    },
    "long": {
        "numbers": "66666",
        "root": "火",
        "question": "在现有工作尚未完成交接、对方还没有确认岗位职责与薪资条件的情况下，这次跨城市求职能否取得明确录用，并在约定时间内落实入职和居住安排？"
        * 2,
        "matter_type": "跨城市事业发展与条件确认",
        "symbolic_meanings": ("外部消息与往来渠道需要反复核实确认具体细节和变化",) * 5,
        "symbolic_summary": "此图用于检查长问题、重复数字、纯阴、缺失根气和长象意的区域边界；所有内容按原顺序显示，过长文本以省略号结束，不侵占固定断语。"
        * 3,
    },
}


def render_case(renderer, name, output):
    values = CASES[name].copy()
    result = calculate(values["question"], values.pop("numbers"), values.pop("root"))
    return renderer.render(
        result, **values, symbolism_source="演示象意 · 非实时模型", output_path=output
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, default="success")
    parser.add_argument(
        "--all", action="store_true", help="render all result and layout cases"
    )
    parser.add_argument("--output-dir", type=Path, help="optional preview directory")
    args = parser.parse_args()
    renderer = WuxingChartRenderer()
    for name in CASES if args.all else (args.case,):
        if args.output_dir:
            output = args.output_dir / f"{name}.png"
        elif name == "success":
            output = ROOT / "docs" / "example_chart.png"
        else:
            output = ROOT / "docs" / "previews" / f"{name}.png"
        print(render_case(renderer, name, output))


if __name__ == "__main__":
    main()
