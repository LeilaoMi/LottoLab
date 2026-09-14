"""注数/金额与部分奖级奖金计算（自 lottery-web worker/src/calc.js 迁入 trunk 的对等实现）。

方案B 融合：把“投注注数与金额、快乐8/数字型固定奖金”收敛为服务端单一实现，
与前端/JS 侧共用同一语义；奖级判定仍以 prize_golden.json 为唯一事实源（见 tests/test_prize_golden）。
"""

from __future__ import annotations

from typing import Any

PRICE = 2  # 每注 2 元


def comb(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    r = 1
    for i in range(1, k + 1):
        r = r * (n - i + 1) // i
    return round(r)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def calc_bet(kind: str, p: dict[str, Any]) -> dict[str, Any]:
    """复式/胆拖 → 注数与金额（含追号倍数）。对齐 worker/src/calc.js calcBet。"""
    dan, fdan = p.get("dan"), p.get("fdan")
    mode = "dantuo" if (dan or fdan) else "duplex"
    chase = _clamp(_as_int(p.get("chase", 1), 1), 1, 100)
    mults_raw = [x for x in str(p.get("mults", "")).split(",") if x]
    mults = [_clamp(_as_int(x, 1), 1, 999) for x in mults_raw]

    def mult(i: int) -> int:
        if not mults:
            return 1
        return mults[min(i, len(mults) - 1)] or 1

    bets = 0
    formula = ""
    if kind == "ssq":
        if mode == "dantuo":
            d = _clamp(_as_int(dan, 2), 1, 5)
            tuo = _clamp(_as_int(p.get("tuo", 8), 8), 7 - d, 32)
            blue = _clamp(_as_int(p.get("blue", 1), 1), 1, 16)
            bets = comb(tuo, 6 - d) * blue
            formula = f"C(拖{tuo},{6 - d}) × 蓝{blue}"
        else:
            red = _clamp(_as_int(p.get("red", 6), 6), 6, 33)
            blue = _clamp(_as_int(p.get("blue", 1), 1), 1, 16)
            bets = comb(red, 6) * blue
            formula = f"C(红{red},6) × 蓝{blue}"
    elif kind == "dlt":
        if mode == "dantuo":
            fd = _clamp(_as_int(fdan, 2), 1, 4)
            ft = _clamp(_as_int(p.get("ftuo", 8), 8), 5 - fd, 34)
            bd = _clamp(_as_int(p.get("bdan", 0), 0), 0, 1)
            bt = _clamp(_as_int(p.get("btuo", 2), 2), 2 - bd, 12)
            bets = comb(ft, 5 - fd) * comb(bt, 2 - bd)
            formula = f"C(前拖{ft},{5 - fd}) × C(后拖{bt},{2 - bd})"
        else:
            front = _clamp(_as_int(p.get("front", 5), 5), 5, 35)
            back = _clamp(_as_int(p.get("back", 2), 2), 2, 12)
            bets = comb(front, 5) * comb(back, 2)
            formula = f"C(前{front},5) × C(后{back},2)"
    elif kind == "qlc":
        if mode == "dantuo":
            d = _clamp(_as_int(dan, 2), 1, 6)
            tuo = _clamp(_as_int(p.get("tuo", 8), 8), 7 - d, 29)
            bets = comb(tuo, 7 - d)
            formula = f"C(拖{tuo},{7 - d})"
        else:
            main = _clamp(_as_int(p.get("main", 7), 7), 7, 30)
            bets = comb(main, 7)
            formula = f"C(基本{main},7)"
    elif kind == "kl8":
        pick = _clamp(_as_int(p.get("pick", 10), 10), 1, 10)
        nums = _clamp(_as_int(p.get("nums", pick), pick), pick, 80)
        bets = comb(nums, pick)
        formula = f"C({nums},{pick})"
    else:  # 数字型 fc3d/pl3/pl5/qxc
        pos = [_clamp(_as_int(x, 1), 1, 10) for x in str(p.get("pos", "")).split(",") if x]
        need = 5 if kind == "pl5" else (7 if kind == "qxc" else 3)
        arr = pos if len(pos) == need else [1] * need
        bets = 1
        for a in arr:
            bets *= a
        group = _as_int(p.get("group"), 0)
        if group == 3:
            bets = comb(max(arr), 2)
        elif group == 6:
            bets = comb(max(arr), 3)
        formula = " × ".join(map(str, arr))

    total_bets = 0
    plan: list[dict[str, int]] = []
    for i in range(chase):
        b = bets * mult(i)
        total_bets += b
        plan.append({"period": i + 1, "mult": mult(i), "bets": b, "amount": b * PRICE})
    return {
        "kind": kind,
        "mode": mode,
        "formula": formula,
        "bets": bets,
        "amount": bets * PRICE,
        "chase": {"periods": chase, "totalBets": total_bets, "totalAmount": total_bets * PRICE},
        "note": "金额按每注 2 元估算，实际以官方规则为准",
    }


KL8: dict[int, dict[int, int]] = {
    10: {10: 5000000, 9: 8000, 8: 720, 7: 80, 6: 5, 5: 3, 0: 2},
    9: {9: 250000, 8: 2000, 7: 225, 6: 22, 5: 5, 4: 3, 0: 2},
    8: {8: 50000, 7: 800, 6: 80, 5: 10, 4: 3, 0: 2},
    7: {7: 8500, 6: 300, 5: 30, 4: 4, 0: 2},
    6: {6: 2880, 5: 30, 4: 10, 3: 3},
    5: {5: 1000, 4: 20, 3: 3},
    4: {4: 93, 3: 5, 2: 3},
    3: {3: 52, 2: 3},
    2: {2: 19},
    1: {1: 4},
}


def kl8_prize(pick: int, hit: int) -> dict[str, Any]:
    table = KL8.get(pick)
    if table is None:
        return {"pick": pick, "hit": hit, "prize": "未中", "amount": 0, "note": "选几不在 1-10 范围"}
    amount = table.get(hit, 0)
    grade = "未中" if not amount else ("高等奖" if amount >= 10000 else "固定奖")
    return {"pick": pick, "hit": hit, "prize": grade, "amount": amount, "note": "金额以官方当期公告为准"}


def digit3_prize(bet: list[Any], draw: list[Any]) -> dict[str, Any]:
    b = [str(x) for x in bet]
    d = [str(x) for x in draw]
    if len(b) != 3 or len(d) != 3:
        return {"prize": "未中", "amount": 0, "note": "需 3 位号码"}
    if all(b[i] == d[i] for i in range(3)):
        return {"prize": "直选", "amount": 1040, "note": "顺序全中"}
    if sorted(b) != sorted(d):
        return {"prize": "未中", "amount": 0}
    uniq = len(set(d))
    if uniq == 2:
        return {"prize": "组三", "amount": 346, "note": "含一对，顺序不限"}
    return {"prize": "组六", "amount": 173, "note": "三位各异，顺序不限"}
