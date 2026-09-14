"""predict 确定性核心的单测（结构分/分区/AC/二项显著性）。"""

import pytest
from lottolab.predict import ac_value, binom_p, structure, zones_of


def test_zones_of_ssq():
    assert zones_of(1, 33) == [
        {"from": 1, "to": 11, "i": 0},
        {"from": 12, "to": 22, "i": 1},
        {"from": 23, "to": 33, "i": 2},
    ]


def test_ac_value_known():
    assert ac_value([1, 2, 3, 4, 5, 6]) == 0  # 连号，差集仅 {1..5} → 5-5=0
    assert ac_value([1, 3, 6, 10, 15, 21]) == 8


def test_binom_p():
    assert binom_p(50, 100, 0.5) == 1.0  # 恰等于基线 → p≈1
    assert (binom_p(30, 100, 0.5) or 1) < 0.05  # 明显偏离 → 显著
    assert binom_p(10, 19, 0.5) is None  # 样本不足
    assert binom_p(200, 100, 0.5) is None  # 越界


def test_structure_ssq():
    s = structure("ssq", [6, 11, 13, 14, 22, 30])
    assert s["sum"] == 96 and s["odd"] == 2 and s["big"] == 2 and s["span"] == 24
    assert s["zone_dist"] == [2, 3, 1] and s["prime"] == 2
    assert s["ac"] == ac_value([6, 11, 13, 14, 22, 30])


def test_structure_rejects_digit_kind():
    with pytest.raises(ValueError):
        structure("fc3d", [1, 2, 3])
