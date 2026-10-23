import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import calculate
from reading import build_reading, build_symbolism


@pytest.mark.parametrize(
    "numbers,root,verdict,reason",
    [
        ("13254", "木", "成", "满足成局条件"),
        ("41235", "金", "败", "未满足成局条件"),
        ("12327", "金", "死卦", "所问根气不现"),
        ("34925", "木", "死卦", "根气被截"),
    ],
)
def test_local_reading_matches_engine_without_inventing_rules(
    numbers, root, verdict, reason
):
    result = calculate("这次计划能实现吗", numbers, root)
    text = build_reading(result)
    assert result.verdict == verdict
    assert reason in text
    assert f"总分{result.score}" in text
    assert text.endswith("断语：" + result.phrase)
    assert "不参与成败计分" in text
    assert "AI 解卦" not in text
    assert text == build_reading(result)
    symbols = build_symbolism(result)
    assert len(symbols.meanings) == 5
    assert symbols.summary.endswith(result.phrase)


def test_repeated_roots_keep_every_position_and_real_adjacent_edges():
    result = calculate("这次出行能否顺利", "11111", "水")
    text = build_reading(result)
    assert "第1、2、3、4、5位" in text
    for i in range(1, 6):
        assert f"第{i}位根气两侧：水→水（同气），水→水（同气）" in text
    assert "流转：五段中相生/同气5段，受克阻断0段，总分5" in text
