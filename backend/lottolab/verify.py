"""验奖引擎：把一注票解析并对照某期开奖，给出奖级/命中/金额（自 lottery-web verify-batch.js 迁入 trunk）。

单一判定：奖级 tier 全部复用 domain.ssq/dlt/qlc_prize_tier；固定奖金复用同侧常量，与 prize_golden.json 一致。
金额纪律沿用 lottery-web：只给有把握的固定奖（ssq 三~六等），浮动/换规则/未校验一律 None，绝不猜。
"""

from __future__ import annotations

import re
from typing import Any

from lottolab.calc import digit3_prize, kl8_prize
from lottolab.domain import dlt_prize_tier, qlc_prize_tier, ssq_prize_tier

# 主/辅区规格：POOL=(主区数, 上限) / DIGIT=(位数, 每位上限)。qxc 第 7 位另限 0..14。
SPEC: dict[str, dict[str, Any]] = {
    "ssq": {"main": 6, "max": 33, "aux": 1, "aux_max": 16, "digit": False},
    "dlt": {"main": 5, "max": 35, "aux": 2, "aux_max": 12, "digit": False},
    "qlc": {"main": 7, "max": 30, "aux": 1, "aux_max": 30, "digit": False, "no_dup_with_main": True},
    "kl8": {"main": None, "max": 80, "aux": 0, "aux_max": 0, "digit": False},
    "fc3d": {"main": 3, "max": 9, "aux": 0, "aux_max": 0, "digit": True},
    "pl3": {"main": 3, "max": 9, "aux": 0, "aux_max": 0, "digit": True},
    "pl5": {"main": 5, "max": 9, "aux": 0, "aux_max": 0, "digit": True},
    "qxc": {"main": 7, "max": 9, "aux": 0, "aux_max": 0, "digit": True, "last_hi": 14},
}

GRADE_CN = {
    1: "一等奖",
    2: "二等奖",
    3: "三等奖",
    4: "四等奖",
    5: "五等奖",
    6: "六等奖",
    7: "七等奖",
    8: "八等奖",
    9: "九等奖",
}
# 双色球恒定固定奖（2014 起）；一二等浮动→金额 None。其余彩种金额未逐字段校验→None。
SSQ_FIXED = {3: 3000, 4: 200, 5: 10, 6: 5}


def parse_ticket(kind: str, line: str) -> dict[str, Any]:
    """一行票 → {main:[str], aux:[str]} 或 {error}。POOL 补零、去重；DIGIT 保序、可重。"""
    sp = SPEC.get(kind)
    if not sp:
        return {"error": f"未知彩种 {kind}"}
    raw = (line or "").strip()
    if not raw:
        return {"error": "空行"}
    if "+" in raw:
        main_raw, aux_raw = raw.split("+", 1)
    else:
        main_raw, aux_raw = raw, ""
    main = re.findall(r"\d+", main_raw)
    aux = re.findall(r"\d+", aux_raw)
    if sp["digit"] and len(main) == 1 and len(main[0]) == sp["main"]:
        main = list(main[0])  # 数字彩允许连写「922」→9 2 2
    if sp["digit"]:
        main = [str(int(x)) for x in main]
        aux = [str(int(x)) for x in aux]
    else:
        main = [f"{int(x):02d}" for x in main]
        aux = [f"{int(x):02d}" for x in aux]

    need = sp["main"]
    if need is not None and len(main) != need:
        return {"error": f"主区需 {need} 个，实得 {len(main)}"}
    if need is None and not (1 <= len(main) <= 10):
        return {"error": "快乐8 每注选 1..10 个号"}
    if not sp["digit"] and len(set(main)) != len(main):
        return {"error": "同一注内有重复号"}
    if sp["digit"]:
        for i, v in enumerate(main):
            cap = sp.get("last_hi", sp["max"]) if (i == len(main) - 1 and "last_hi" in sp) else sp["max"]
            if not (0 <= int(v) <= cap):
                return {"error": f"第 {i + 1} 位须在 0-{cap}"}
    elif any(not (1 <= int(v) <= sp["max"]) for v in main):
        return {"error": f"主区号需在 1-{sp['max']}"}
    if len(aux) != sp["aux"]:
        return {
            "error": f"辅区需 {sp['aux']} 个，实得 {len(aux)}"
            if sp["aux"]
            else "该彩种无辅区，去掉 + 后的号码"
        }
    if sp["aux"] and any(not (1 <= int(v) <= sp["aux_max"]) for v in aux):
        return {"error": f"辅区号需在 1-{sp['aux_max']}"}
    if sp.get("no_dup_with_main") and set(aux) & set(main):
        return {"error": "特别号不得与基本号重复"}
    return {"main": main, "aux": aux}


def score_ticket(kind: str, ticket: dict[str, Any], draw: dict[str, Any]) -> dict[str, Any]:
    """一注 × 一期开奖 → 命中/奖级/金额。金额无把握为 None。"""
    sp = SPEC[kind]
    main = ticket["main"]
    if kind == "ssq":
        red = {f"{int(x):02d}" for x in draw["red"]}
        hm = sum(1 for x in main if x in red)
        blue_won = f"{int(draw['blue']):02d}" if draw.get("blue") not in (None, "") else ""
        hb = 1 if blue_won and blue_won in set(ticket["aux"]) else 0
        tier = ssq_prize_tier(hm, hb)
        grade = "未中" if tier is None else GRADE_CN[int(tier)]
        amount = 0 if tier is None else (SSQ_FIXED.get(int(tier)) if int(tier) >= 3 else None)
        return {"hit_main": hm, "hit_aux": hb, "tier": tier, "grade": grade, "amount": amount}
    if kind == "dlt":
        front = {f"{int(x):02d}" for x in draw["front"]}
        back = {f"{int(x):02d}" for x in draw["back"]}
        hm = sum(1 for x in main if x in front)
        ha = sum(1 for x in ticket["aux"] if x in back)
        tier = dlt_prize_tier(hm, ha)
        return {
            "hit_main": hm,
            "hit_aux": ha,
            "tier": tier,
            "grade": "未中" if tier is None else GRADE_CN[int(tier)],
            "amount": None,
            "note": "大乐透固定奖金额随规则版本变化，只给奖级",
        }
    if kind == "qlc":
        base = {f"{int(x):02d}" for x in draw["main"]}
        hs = 1 if f"{int(draw['special']):02d}" in main else 0
        hm = sum(1 for x in main if x in base)
        tier = qlc_prize_tier(hm, hs)
        return {
            "hit_main": hm,
            "hit_special": hs,
            "tier": tier,
            "grade": "未中" if tier is None else GRADE_CN[int(tier)],
            "amount": None,
        }
    if kind == "kl8":
        winning = {f"{int(x):02d}" for x in draw["nums"]}
        hit = sum(1 for x in main if x in winning)
        r = kl8_prize(len(main), hit)
        return {"pick": len(main), "hit": hit, "grade": r["prize"], "amount": r["amount"]}
    # 数字型
    digits = [str(int(x)) for x in draw.get("digits", [])]
    if kind in ("fc3d", "pl3"):
        r = digit3_prize(main, digits)
        return {"grade": r["prize"], "amount": r["amount"]}
    pos = sum(1 for i, v in enumerate(main) if i < len(digits) and v == digits[i])
    exact = pos == sp["main"] and len(digits) == sp["main"]
    grade = "全中" if exact else (f"中{pos}位" if pos else "未中")
    return {"hit_pos": pos, "total": sp["main"], "grade": grade, "amount": None}
