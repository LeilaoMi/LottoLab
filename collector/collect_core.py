"""
collect_core.py —— 方案B「唯一采集器」的纯逻辑核（标准库、无网络、可单测）。
职责：多源 → 逐期交叉校验（不一致即拒绝，绝不静默择一）→ 产出瘦快照 → 新鲜度保险丝。
重算（回测/模型/MC）不在此，归离线 science 作业（Vercel Hobby 约束）。
"""
from __future__ import annotations
from datetime import date, datetime
from contract import canonicalize, key, ContractError

MIN_SOURCES_FOR_TRUST = 1  # 单源彩种=1，双源=2；由配置决定，校验“至少1个成功源”


def ingest(kind: str, records_by_source: dict[str, list[dict]], today: str | None = None):
    """records_by_source: {source_name: [ {issue,main,special,draw_date}, ... ]}
    返回：
      accepted: {issue: canonical_rec}      多源一致（或唯一源）且合规
      rejected: {issue: {reason, variants}} 冲突/越界/缺源，一律不落库
      per_source_errors: {source: [issues]} 某源解析失败的期
    """
    accepted, rejected = {}, {}
    # 逐期聚合各源 canonical
    by_issue: dict[str, dict[str, dict]] = {}
    for src, recs in records_by_source.items():
        for raw in recs:
            try:
                c = canonicalize(kind, raw["issue"], raw.get("main", []), raw.get("special", []), raw.get("draw_date", ""))
                for k in ("sales", "pool", "prizes"):          # 透传富字段（不影响号码一致性比较）
                    if raw.get(k) is not None:
                        c[k] = raw[k]
                c["src"] = src                                  # 记录来源
            except ContractError as e:
                by_issue.setdefault(str(raw.get("issue")), {}).setdefault(src, None)
                rejected.setdefault(str(raw.get("issue")), {"reason": [], "variants": {}})
                rejected[str(raw.get("issue"))]["reason"].append(f"{src}: 契约违例 {e}")
                continue
            by_issue.setdefault(c["issue"], {})[src] = c

    for issue, srcmap in by_issue.items():
        good = {s: c for s, c in srcmap.items() if c is not None}
        if not good:
            continue  # 全源都违例，已在上面登记
        fp = {s: key(c) for s, c in good.items()}
        if len(set(fp.values())) > 1:
            rejected.setdefault(issue, {"reason": ["多源不一致，拒绝落库"], "variants": {s: list(v) for s, v in fp.items()}})
        else:
            accepted[issue] = next(iter(good.values()))
    return {"accepted": accepted, "rejected": rejected, "per_source": {s: len(r) for s, r in records_by_source.items()}}


def build_slim_snapshot(accepted_by_kind: dict[str, dict]) -> dict:
    """只保留边缘读所需的瘦字段，按 issue 升序，供灌 D1 / R2。"""
    snap = {}
    for kind, accepted in accepted_by_kind.items():
        snap[kind] = sorted(
            [{"issue": r["issue"], "draw_date": r["draw_date"], "main": r["main"], "special": r["special"]}
             for r in accepted.values()], key=lambda x: x["issue"])
    return snap


def days_since(d: str, today: str) -> int:
    if not d:
        return 10_000
    return (datetime.strptime(today, "%Y-%m-%d").date() - datetime.strptime(d[:10], "%Y-%m-%d").date()).days


def freshness(snapshot: dict, today: str, max_age_days: int):
    """返回各彩种最新期距今天数；任一超阈值即整体 stale=True（供保险丝告警）。"""
    rep, stale = {}, False
    for kind, rows in snapshot.items():
        latest = max((r["draw_date"] for r in rows), default=None)
        age = days_since(latest, today)
        rep[kind] = {"latest_issue": (rows[-1]["issue"] if rows else None), "latest_date": latest, "age_days": age, "ok": age <= max_age_days}
        if not rows or age > max_age_days:
            stale = True
    return {"stale": stale, "per_kind": rep}
