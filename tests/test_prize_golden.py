"""奖级判定一致性闸门：domain 的实现必须等于官方规范 prize_golden.json（单一事实源）。

任何人改动 lottolab.domain 的 ssq_prize_tier / dlt_prize_tier 使判定偏离官方规范，
此测试即在 CI 变红——守住方案B「单一判定实现」红线；lottery-web 引擎并主干后读同一 golden。
"""

import json
from pathlib import Path

from lottolab.domain import dlt_prize_tier, qlc_prize_tier, ssq_prize_tier

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "prize_golden.json").read_text(encoding="utf-8"))


def _tier_or_none(table: dict[str, str], main: int, special: int) -> str | None:
    return table.get(f"{main},{special}")


def test_ssq_matches_official_tiers():
    for main in range(7):
        for special in range(2):
            assert ssq_prize_tier(main, special) == _tier_or_none(GOLDEN["ssq"], main, special), (
                f"ssq ({main},{special})"
            )


def test_dlt_matches_official_tiers():
    for main in range(6):
        for special in range(3):
            assert dlt_prize_tier(main, special) == _tier_or_none(GOLDEN["dlt"], main, special), (
                f"dlt ({main},{special})"
            )


def test_qlc_matches_official_tiers():
    for main in range(8):
        for special in range(2):
            assert qlc_prize_tier(main, special) == _tier_or_none(GOLDEN["qlc"], main, special), (
                f"qlc ({main},{special})"
            )


def test_golden_covers_every_prize_tier():
    for tier in ("1", "2", "3", "4", "5", "6"):
        assert tier in GOLDEN["ssq"].values(), f"ssq 缺少奖级 {tier} 的用例"
    for tier in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
        assert tier in GOLDEN["dlt"].values(), f"dlt 缺少奖级 {tier} 的用例"
    for tier in ("1", "2", "3", "4", "5", "6", "7"):
        assert tier in GOLDEN["qlc"].values(), f"qlc 缺少奖级 {tier} 的用例"
