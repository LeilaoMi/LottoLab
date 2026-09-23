"""预测复盘闭环：把推荐落台账，开奖后自动对账命中/奖级——用真实结果自证预测准不准。

诚实内核：对账结果会显示各策略的真实命中率（预期≈随机基线），不美化。
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Draw, PredictionLog
from .domain import RULES, Lottery, dlt_prize_tier_for, qlc_prize_tier, ssq_prize_tier
from .predict import recommend_multi

TIER = {"ssq": ssq_prize_tier, "qlc": qlc_prize_tier}


def log_predictions(
    session: Session, kind: str, target_issue: str, picks: list[dict[str, Any]], seed: int = 1
) -> int:
    """把一组推荐（[{strategy, main, aux}]）登记到台账，等待该期开奖后对账。"""
    n = 0
    for p in picks:
        session.add(
            PredictionLog(
                kind=kind,
                dataset_kind="real",
                target_issue=str(target_issue),
                seed=seed,
                strategy=str(p.get("strategy", p.get("name", "")))[:40],
                main_numbers=[int(x) for x in p.get("main", [])],
                special_numbers=[int(x) for x in p.get("aux", [])],
            )
        )
        n += 1
    session.commit()
    return n


def _score(kind: str, pred: PredictionLog, draw: Draw) -> tuple[int, int, str | None]:
    rule = RULES[cast("Lottery", kind)]
    if rule.family == "DIGIT":
        pm, dm = pred.main_numbers, draw.main_numbers
        hit = sum(1 for i in range(len(dm)) if i < len(pm) and pm[i] == dm[i])
        prize = "全中" if hit == len(dm) else (f"中{hit}位" if hit else None)
        return hit, 0, prize
    if kind == "qlc":
        # 票面 7 基本号；特别号 = 开奖第 8 号，命中 = 特别号 ∈ 票面（与 verify.score_ticket 一致）
        special = draw.special_numbers[0] if draw.special_numbers else None
        hit_special = 1 if special is not None and special in set(pred.main_numbers) else 0
        hit_main = len(set(pred.main_numbers) & set(draw.main_numbers))
        tier = qlc_prize_tier(hit_main, hit_special)
        return hit_main, hit_special, tier
    hit_main = len(set(pred.main_numbers) & set(draw.main_numbers))
    hit_special = len(set(pred.special_numbers) & set(draw.special_numbers))
    if kind == "kl8":
        prize = f"中{hit_main}" if hit_main else None
        return hit_main, hit_special, prize
    if kind == "dlt":  # 奖级映射按开奖日期选择规则版本（2019-02-20 为界）
        day = draw.draw_date.isoformat() if getattr(draw, "draw_date", None) else ""
        return hit_main, hit_special, dlt_prize_tier_for(day, hit_main, hit_special)
    tier_fn = TIER.get(kind)
    tier = tier_fn(hit_main, hit_special) if tier_fn else None
    return hit_main, hit_special, tier


def next_issue(latest: str) -> str | None:
    """池型 7 位期号 YYYYNNN → 序号 +1；非法格式返回 None（不猜）。"""
    if len(latest) == 7 and latest.isdigit():
        return f"{latest[:4]}{int(latest[4:]) + 1:03d}"
    return None


def snapshot_review(session: Session, kind: str, online: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    """用当前数据生成该彩种推荐并登记到台账，等目标期开奖后自动对账。

    online 为 predict.online_rows 格式。同一目标期已记则跳过，保证每日重跑幂等。
    """
    if not online:
        return {"kind": kind, "logged": 0, "skipped": "无可用开奖数据"}
    latest = max(str(r["code"]) for r in online)
    target = next_issue(latest)
    if not target:
        return {"kind": kind, "logged": 0, "skipped": f"最新期号 {latest} 无法推算下一期"}
    done = session.scalar(
        select(PredictionLog.id)
        .where(PredictionLog.kind == kind, PredictionLog.target_issue == target)
        .limit(1)
    )
    if done:
        return {"kind": kind, "target_issue": target, "logged": 0, "skipped": "该期已登记"}
    picks = recommend_multi(kind, online, seed, 7)["picks"]
    logged = log_predictions(
        session,
        kind,
        target,
        [{"strategy": p["name"], "main": p["main"], "aux": p["aux"]} for p in picks],
        seed,
    )
    return {"kind": kind, "target_issue": target, "based_on": latest, "seed": seed, "logged": logged}


def reconcile(session: Session, kind: str | None = None) -> int:
    """对账：把 target_issue 已开奖且未核对的预测，按真实开奖算命中/奖级并标记。返回对账条数。"""
    q = select(PredictionLog).where(PredictionLog.checked.is_(False))
    if kind:
        q = q.where(PredictionLog.kind == kind)
    updated = 0
    for pred in session.scalars(q).all():
        draw = session.scalar(
            select(Draw).where(
                Draw.lottery == pred.kind, Draw.issue == pred.target_issue, Draw.dataset_kind == "real"
            )
        )
        if not draw:
            continue
        hit_main, hit_special, prize = _score(pred.kind, pred, draw)
        pred.hit_main, pred.hit_special, pred.checked, pred.prize = hit_main, hit_special, True, prize
        updated += 1
    session.commit()
    return updated


def review_summary(session: Session, kind: str, limit: int = 50) -> dict[str, Any]:
    """返回该彩种台账：最近若干条 + 已对账部分的平均命中与中奖分布。"""
    rows = session.scalars(
        select(PredictionLog)
        .where(PredictionLog.kind == kind)
        .order_by(PredictionLog.created_at.desc())
        .limit(limit)
    ).all()
    checked = [r for r in rows if r.checked and r.hit_main is not None]
    rule = RULES[cast("Lottery", kind)]
    n = len(checked)
    avg_hit = round(sum(int(r.hit_main or 0) for r in checked) / n, 3) if n else None
    # 期望命中按**实际票面大小**计算：POOL 为 k*k/池；DIGIT 为各位均匀命中概率之和。
    sized = [len(r.main_numbers) for r in rows if r.main_numbers] or [rule.main_count]
    if rule.family == "POOL":
        # 期望 = 票面 k × 开奖球数 D / 池 N（双色球 k=D 时为 k²/N）
        expected = sum(k * rule.main_count for k in sized) / len(sized) / rule.main_max
    else:
        ranges = [
            rule.last_max if (rule.last_max is not None and i == rule.main_count - 1) else rule.main_max
            for i in range(rule.main_count)
        ]
        expected = sum(1.0 / (hi + 1) for hi in ranges)
    won = sum(1 for r in checked if r.prize)
    return {
        "kind": kind,
        "logged": len(rows),
        "checked": n,
        "avg_hit_main": avg_hit,
        "expected_hit": round(expected, 3),
        "won_count": won,
        "note": "对账用真实开奖计算命中；命中率应长期贴近随机期望——这是自证，不美化。",
        "rows": [r.public() for r in rows],
    }
