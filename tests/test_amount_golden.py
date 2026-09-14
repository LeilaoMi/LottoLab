"""固定奖金诚实性闸门：calc/verify 的金额常量必须等于 prize_golden.json 的 amounts 规范。"""

import json
from pathlib import Path

from lottolab.calc import KL8, digit3_prize, kl8_prize
from lottolab.verify import SSQ_FIXED

AMOUNTS = json.loads((Path(__file__).parent / "fixtures" / "prize_golden.json").read_text(encoding="utf-8"))[
    "amounts"
]


def test_kl8_table_matches_official():
    golden = {int(pick): {int(hit): amt for hit, amt in row.items()} for pick, row in AMOUNTS["kl8"].items()}
    assert KL8 == golden


def test_kl8_prize_amounts_sample():
    for pick, row in AMOUNTS["kl8"].items():
        for hit, amt in row.items():
            assert kl8_prize(int(pick), int(hit))["amount"] == amt, f"kl8 选{pick}中{hit}"


def test_ssq_fixed_amounts_match_and_float_excluded():
    golden = {int(k): v for k, v in AMOUNTS["ssq_fixed"].items()}
    assert SSQ_FIXED == golden
    for tier in AMOUNTS["ssq_float_tiers"]:  # 一二等浮动 → 不在固定表
        assert int(tier) not in SSQ_FIXED


def test_digit3_amounts_match_official():
    assert digit3_prize(["1", "2", "3"], ["1", "2", "3"])["amount"] == AMOUNTS["digit3"]["直选"]
    assert digit3_prize(["1", "1", "2"], ["1", "2", "1"])["amount"] == AMOUNTS["digit3"]["组三"]
    assert digit3_prize(["1", "2", "3"], ["3", "2", "1"])["amount"] == AMOUNTS["digit3"]["组六"]
