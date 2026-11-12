import itertools

import pytest

from engine import DIGIT_ELEMENT
from engine import calculate as legacy
from engine_v2 import calculate_v2
from kernels import calculate
from reading import build_reading, build_symbolism


def test_complete_document_example_15997():
    result = calculate_v2("这次销售交易能否达成", "15997", "水")
    assert result.verdict == "成"
    assert result.details["missing"] == ["木"]
    assert [step["state"] for step in result.details["steps"]][2:7] == [
        ["阳水", "阴土", "阳金", "阳金", "阳火", "阳木"],
        ["阴水", "阳金", "阳金", "阳火", "阳木"],
        ["阳金", "阳金", "阴火", "阳木"],
        ["阴金", "阳金", "阳木"],
        ["阳金", "阴木"],
    ]
    assert result.details["combined"] == ["阳金", "阳水", "阴木"]
    timing = result.details["timing"]
    assert (timing["start"], timing["completion"], timing["unit"]) == (22, 32, "未定")
    assert timing["supplements"] == [
        ["阴木", 8],
        ["阳火", 7],
        ["阴火", 2],
        ["阳土", 5],
        ["阴土", 10],
    ]
    assert legacy("这次交易能否达成", "15997", "水").verdict == "死卦"
    assert "总分" not in build_reading(result)
    assert "单位未定" in build_reading(result)


@pytest.mark.parametrize(
    "digits,final",
    [
        ("75319", ["阴金", "阳木"]),
        ("34852", ["阳木", "阴火"]),
        ("34289", ["阴金", "阳木"]),
        ("12759", ["阴水", "阳火"]),
        ("65637", ["阴土", "阴水"]),
        ("37182", ["阴木", "阴火"]),
        ("25876", ["阳土", "阴金"]),
    ],
)
def test_unambiguous_short_example_final_symbols(digits, final):
    assert calculate_v2("此事能否达成", digits, final[0][1]).details["final"] == final


@pytest.mark.parametrize("digits", ["59789", "55287"])
def test_unresolved_short_examples_are_not_fabricated(digits):
    result = calculate_v2("此事能否达成", digits, "金")
    assert result.verdict == "待定"
    assert result.is_dead is False
    assert result.details["timing"] is None


def test_generation_convention_is_visible_and_polarity_matters():
    result = calculate_v2("这次考试能否通过", "34852", "木")
    assert result.verdict == "成"
    assert result.details["notices"]
    assert any("补充约定" in step["action"] for step in result.details["steps"])
    assert calculate_v2("这次考试能否通过", "37182", "木").details["final"] == [
        "阴木",
        "阴火",
    ]
    assert (
        calculate_v2("此事能否达成", "15997", "水").details
        != calculate_v2("此事能否达成", "60442", "水").details
    )


def test_all_single_element_and_all_polarity_patterns_terminate():
    for digits in [d * 5 for d in "0123456789"] + [
        "".join(d) for d in itertools.product(*["16", "27", "38", "49", "50"])
    ]:
        result = calculate_v2("具体事项是否达成", digits, "水")
        assert result.verdict in {"成", "败", "待定"}
        assert result.elements == tuple(DIGIT_ELEMENT[d] for d in digits)
        assert len(result.details["steps"]) <= 12
        assert len(build_symbolism(result).meanings) == 5
        assert result.transitions == ()  # No fictional five-position score arrows.


def test_router_preserves_default_and_rejects_unknown_kernel():
    assert calculate("求职能否成功", "13254", "木") == legacy(
        "求职能否成功", "13254", "木"
    )
    with pytest.raises(ValueError, match="未知"):
        calculate("求职能否成功", "13254", "木", kernel_id="unknown")
