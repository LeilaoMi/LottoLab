"""predict 确定性核心的单测（结构分/分区/AC/二项显著性）。"""

import pytest
from lottolab.predict import ac_value, binom_p, recommend, structure, zones_of


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


SSQ_DRAWS = [
    {"red": [6, 11, 13, 14, 22, 30], "blue": 14},
    {"red": [2, 4, 13, 14, 15, 30], "blue": 8},
    {"red": [11, 12, 13, 19, 20, 31], "blue": 3},
    {"red": [6, 11, 13, 14, 22, 30], "blue": 14},
]


def test_recommend_pool_ssq_valid_and_deterministic():
    a = recommend("ssq", SSQ_DRAWS, seed=7)
    b = recommend("ssq", SSQ_DRAWS, seed=7)
    assert a == b  # 同 seed 确定
    assert len(a["main"]) == 6 and len(set(a["main"])) == 6
    assert all(1 <= int(x) <= 33 for x in a["main"])
    assert len(a["aux"]) == 1 and 1 <= int(a["aux"][0]) <= 16


def test_recommend_covers_all_eight_kinds():
    draws = {
        "dlt": [{"front": [1, 6, 14, 15, 26], "back": [8, 9]}] * 3,
        "qlc": [{"main": [8, 19, 20, 21, 23, 27, 30]}] * 3,
        "kl8": [{"nums": list(range(1, 21))}] * 3,
        "fc3d": [{"digits": [9, 8, 2]}] * 3,
        "pl3": [{"digits": [2, 8, 6]}] * 3,
        "pl5": [{"digits": [2, 8, 6, 6, 5]}] * 3,
        "qxc": [{"digits": [5, 1, 9, 5, 8, 5, 11]}] * 3,
    }
    expect = {
        "dlt": (5, 2),
        "qlc": (7, 0),
        "kl8": (10, 0),
        "fc3d": (3, 0),
        "pl3": (3, 0),
        "pl5": (5, 0),
        "qxc": (7, 0),
    }
    for kind, d in draws.items():
        r = recommend(kind, d, seed=3)
        m, x = expect[kind]
        assert len(r["main"]) == m and len(r["aux"]) == x, kind
    assert 0 <= int(recommend("qxc", draws["qxc"], seed=3)["main"][-1]) <= 14  # 末位号池 0..14


def test_recommend_rejects_unknown():
    with pytest.raises(ValueError):
        recommend("xxx", [], seed=1)
