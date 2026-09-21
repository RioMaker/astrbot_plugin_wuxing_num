"""Regenerate the README preview using illustrative, not live-model, symbolism."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import calculate
from renderer import WuxingChartRenderer


def main():
    output = WuxingChartRenderer().render(
        calculate("这次求职能否成功", "13254", "木"),
        question="这次求职能否成功，能不能拿到理想公司的录用？",
        matter_type="事业求职",
        symbolic_meanings=(
            "消息出现，机会启动", "能力生长，获得认可", "行动显化，进入面试",
            "资源承接，条件落实", "规则落定，结果确认",
        ),
        symbolic_summary="木为事业根气，水木火土金依次承接；消息带来机会，能力与行动促进落实，最后进入条件确认。",
        symbolism_source="演示象意",
        output_path=ROOT / "docs" / "example_chart.png",
    )
    print(output)


if __name__ == "__main__":
    main()
