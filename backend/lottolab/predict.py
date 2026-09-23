"""预测引擎 · 确定性核心（自 lottery-web worker/src/predict.js 迁入 trunk 的第一片）。

只含无随机、可精确断言的部分：分区、AC 值、二项显著性、结构分（和值/奇偶/大小/跨度/区分布/AC）。
带随机的 pickN/kill/dan/recommend 留待后续片（会引入可注入的 seed 以便复现测试）。
"""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np

from .coldness import coldness

PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79}

# pool 类彩种主区界（与 contract 对齐）：min, max, pick
POOL_SPEC: dict[str, tuple[int, int, int]] = {
    "ssq": (1, 33, 6),
    "dlt": (1, 35, 5),
    "qlc": (1, 30, 7),
    "kl8": (1, 80, 10),  # 推荐票面 10 注（开奖仍为 20/80；见 RULES["kl8"]）
}


def zones_of(lo: int, hi: int) -> list[dict[str, int]]:
    """三分区：区宽 = ceil(跨度/3)，从 lo 起等宽切分（对齐 JS zonesOf）。"""
    span = hi - lo + 1
    w = math.ceil(span / 3)
    out: list[dict[str, int]] = []
    start = lo
    for i in range(3):
        end = min(start + w - 1, hi)
        out.append({"from": start, "to": end, "i": i})
        start = end + 1
    return out


def zone_idx(zones: list[dict[str, int]], v: int) -> int:
    for z in zones:
        if z["from"] <= v <= z["to"]:
            return z["i"]
    return zones[-1]["i"]


def ac_value(nums: list[Any]) -> int:
    """AC 值 = 不同两两差个数 − (n−1)。"""
    arr = [int(x) for x in nums]
    diffs = {abs(arr[i] - arr[j]) for i in range(len(arr)) for j in range(i + 1, len(arr))}
    return len(diffs) - (len(arr) - 1)


def binom_p(hits: int, n: int, p0: float) -> float | None:
    """双侧二项检验近似 p 值（正态）。n<20 或参数越界 → None（样本不足不做显著宣称）。"""
    if not (n >= 20) or not (0 < p0 < 1) or not (0 <= hits <= n):
        return None
    se = math.sqrt(p0 * (1 - p0) / n)
    z = abs((hits / n - p0) / se)
    if not math.isfinite(z):
        return None
    t = 1 / (1 + 0.2316419 * z)
    poly = t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    tail = 0.3989423 * math.exp(-z * z / 2) * poly
    return round(min(1.0, max(0.0, 2 * tail)), 4)


def structure(kind: str, nums: list[Any]) -> dict[str, Any]:
    """一期号码的结构画像：和值/奇/大/跨度/分区分布/AC。仅 pool 类彩种。"""
    if kind not in POOL_SPEC:
        raise ValueError(f"structure 仅支持 pool 类彩种，收到 {kind}")
    lo, hi, _pick = POOL_SPEC[kind]
    n = sorted(int(x) for x in nums)
    zones = zones_of(lo, hi)
    mid = (lo + hi) / 2
    zcount = [0, 0, 0]
    for x in n:
        zcount[zone_idx(zones, x)] += 1
    return {
        "kind": kind,
        "sum": sum(n),
        "odd": sum(1 for x in n if x % 2),
        "big": sum(1 for x in n if x > mid),
        "span": (n[-1] - n[0]) if n else 0,
        "zone_dist": zcount,
        "ac": ac_value(n),
        "prime": sum(1 for x in n if x in PRIMES),
    }


# ---------- 把 ssq 的预测逻辑推广到全部 8 彩种：频率打分 + 可注入 seed 的 recommend ----------
# pool: main=(pick, hi), aux=(pick, hi), field=(主区字段, 辅区字段)；digit: 位置数 + 末位上限
PICK: dict[str, dict[str, Any]] = {
    "ssq": {"main": (6, 33), "aux": (1, 16), "field": ("red", "blue")},
    "dlt": {"main": (5, 35), "aux": (2, 12), "field": ("front", "back")},
    "qlc": {"main": (7, 30), "aux": (0, 0), "field": ("main", None)},
    "kl8": {"main": (10, 80), "aux": (0, 0), "field": ("nums", None)},  # 推荐给 10 个
    "fc3d": {"digit": 3, "field": ("digits", None)},
    "pl3": {"digit": 3, "field": ("digits", None)},
    "pl5": {"digit": 5, "field": ("digits", None)},
    "qxc": {"digit": 7, "last_hi": 14, "field": ("digits", None)},
}


def _rank_tokens(tokens: list[str], scores: dict[str, int], k: int, rng: random.Random) -> list[str]:
    """按频率(拉普拉斯+1)降序、seeded 抖动破平局，取 k 个。"""
    ranked = sorted((-(scores.get(t, 0) + 1), rng.random(), t) for t in tokens)
    return [r[2] for r in ranked[:k]]


def _freq_by_field(draws: list[dict[str, Any]], field: str) -> dict[str, int]:
    scores: dict[str, int] = {}
    for d in draws:
        val = d.get(field)
        if val is None:
            continue
        vals = val if isinstance(val, (list, tuple)) else [val]
        for x in vals:
            tk = f"{int(x):02d}"
            scores[tk] = scores.get(tk, 0) + 1
    return scores


def recommend(kind: str, draws: list[dict[str, Any]], seed: int = 1) -> dict[str, Any]:
    """8 彩种统一推荐：池型按各区频率选号；数字型按每位频率逐位选号。同 seed 结果确定。"""
    spec = PICK.get(kind)
    if not spec:
        raise ValueError(f"未知彩种 {kind}")
    rng = random.Random(seed)
    if "digit" in spec:
        pos = int(spec["digit"])
        last_hi = int(spec.get("last_hi", 9))
        field = spec["field"][0]
        main: list[str] = []
        for p in range(pos):
            hi = last_hi if (kind == "qxc" and p == pos - 1) else 9
            scores: dict[str, int] = {}
            for d in draws:
                dg = d.get(field) or []
                if p < len(dg):
                    tk = str(int(dg[p]))
                    scores[tk] = scores.get(tk, 0) + 1
            main.append(_rank_tokens([str(v) for v in range(0, hi + 1)], scores, 1, rng)[0])
        return {"kind": kind, "main": main, "aux": []}
    mfield, afield = spec["field"]
    m_pick, m_hi = spec["main"]
    a_pick, a_hi = spec["aux"]
    main = _rank_tokens([f"{v:02d}" for v in range(1, m_hi + 1)], _freq_by_field(draws, mfield), m_pick, rng)
    aux: list[str] = []
    if afield and a_pick:
        aux = _rank_tokens(
            [f"{v:02d}" for v in range(1, a_hi + 1)], _freq_by_field(draws, afield), a_pick, rng
        )
    return {"kind": kind, "main": sorted(main), "aux": sorted(aux)}


# ---------- 整合 lottery-web 多策略评分推荐 + LottoLab 分区/AC 结构分，seeded 可复现 ----------

AUX_SPEC: dict[str, tuple[int, int, int]] = {"ssq": (1, 16, 1), "dlt": (1, 12, 2)}  # lo, hi, count

DISCLAIMER_RECOMMEND = "结构化参考，随机游戏仅供娱乐；不改变任何一注的中奖概率，不构成购彩建议。"

# 撞号规避先验（Ziemba 式）：不改变中奖概率，只降低“中头奖要和多少人分摊”的期望风险。
LUCKY = {6, 8, 9, 16, 18, 19, 26, 28, 29, 36, 38, 39}
DIGIT_POP: dict[int, float] = {
    0: 0.45,
    1: 0.60,
    2: 0.55,
    3: 0.50,
    4: 0.32,
    5: 0.50,
    6: 0.72,
    7: 0.66,
    8: 0.78,
    9: 0.70,
}


def number_popularity(value: int) -> float:
    """某号码被大众选中的相对倾向 0..1（越大越易撞号）。纯结构先验，不依赖销量数据。"""
    p = 0.5
    if 1 <= value <= 31:
        p += 0.25  # 生日（日/月）
    if 1 <= value <= 12:
        p += 0.15  # 月份，更热
    if value % 10 == 0:
        p += 0.10  # 整十
    elif value % 5 == 0:
        p += 0.05
    if value in LUCKY:
        p += 0.10  # 吉利数
    if value == 4 or value % 10 == 4:
        p -= 0.18  # 忌“4”，反而冷门
    if value >= 32:
        p -= 0.22  # 生日覆盖不到，选的人少
    return max(0.0, min(1.0, p))


def _collision(kind: str, main: list[int], aux: list[int], pop: Any = None) -> int:
    """撞号指数 0–100，越低越可能独享奖金。数字型按每位数字先验（或实测逐位热度），
    池型按号码先验（或实测号码热度，含辅区）。pop：池型为 dict[号码,0..1]，数字型为 list[dict[数字,0..1]]。"""
    spec = PICK.get(kind, {})
    if "digit" in spec:
        if isinstance(pop, list):
            pops = [pop[i].get(int(v), 0.5) if i < len(pop) else 0.5 for i, v in enumerate(main)]
        else:
            pops = [DIGIT_POP.get(int(v), 0.5) for v in main]
    else:
        source = pop or {}
        pops = [source.get(int(v), number_popularity(int(v))) for v in list(main) + list(aux or [])]
    if not pops:
        return 0
    return round(sum(pops) / len(pops) * 100)


def _learn_popularity(kind: str, rows: list[dict[str, Any]]) -> Any:
    """从真实一等奖/直选注数回归号码相对热度（控制销量）。样本不足或退化返回 None。
    池型返回 dict[号码,0..1]；数字型返回 list[dict[数字,0..1]]（逐位）。"""
    spec = PICK.get(kind)
    if not spec:
        return None
    if "digit" in spec:
        return _learn_popularity_digit(kind, rows, spec)
    if kind not in POOL_SPEC:
        return None
    _lo, hi, _pick = POOL_SPEC[kind]
    field = spec["field"][0]
    X: list[list[float]] = []
    y: list[float] = []
    for r in rows:
        winners = r.get("winners")
        if winners is None:
            continue
        nums = {int(v) for v in (r.get(field) or [])}
        if not nums:
            continue
        vec = [1.0 if v in nums else 0.0 for v in range(1, hi + 1)]
        sales = r.get("sales")
        try:
            vec.append(math.log10(float(sales)) if sales else 0.0)
        except (TypeError, ValueError):
            vec.append(0.0)
        X.append(vec)
        y.append(math.log1p(float(winners)))
    if len(y) < 200:
        return None
    A = np.asarray(X)
    b = np.asarray(y)
    reg = A.T @ A + np.eye(A.shape[1])
    try:
        coef = np.linalg.solve(reg, A.T @ b)
    except np.linalg.LinAlgError:
        return None
    raw = coef[:hi]
    lo, mx = float(raw.min()), float(raw.max())
    if mx - lo < 1e-9:
        return None
    if not _oos_positive(A, b):
        return None
    return {v + 1: float((raw[v] - lo) / (mx - lo)) for v in range(hi)}


def _oos_positive(A: np.ndarray, b: np.ndarray) -> bool:
    """时序 70/30 样本外：验证段目标有方差且预测-残差相关为正才放行。"""
    split = max(50, int(len(b) * 0.7))
    if len(b) - split < 40:
        return True
    y_val = b[split:]
    if float(np.var(y_val)) < 1e-15:
        return True  # 验证段目标恒定，无法做相关检验
    try:
        coef = np.linalg.solve(A[:split].T @ A[:split] + np.eye(A.shape[1]), A[:split].T @ b[:split])
    except np.linalg.LinAlgError:
        return False
    pred = A[split:] @ coef
    pc = pred - pred.mean()
    yc = y_val - y_val.mean()
    denom = math.sqrt(float(np.dot(pc, pc)) * float(np.dot(yc, yc)))
    if denom <= 0:
        return True
    return float(np.dot(pc, yc)) / denom > 0


def _learn_popularity_digit(kind: str, rows: list[dict[str, Any]], spec: dict[str, Any]) -> Any:
    pos = int(spec["digit"])
    last_hi = int(spec.get("last_hi", 9))
    field = spec["field"][0]
    ranges = [last_hi if (kind == "qxc" and p == pos - 1) else 9 for p in range(pos)]
    cols: list[tuple[int, int]] = [(p, d) for p in range(pos) for d in range(0, ranges[p] + 1)]
    index = {c: i for i, c in enumerate(cols)}
    X: list[list[float]] = []
    y: list[float] = []
    for r in rows:
        winners = r.get("winners")
        if winners is None:
            continue
        dg = r.get(field) or []
        if len(dg) < pos:
            continue
        vec = [0.0] * (len(cols) + 1)
        for p in range(pos):
            d = int(dg[p])
            if 0 <= d <= ranges[p]:
                vec[index[(p, d)]] = 1.0
        sales = r.get("sales")
        try:
            vec[-1] = math.log10(float(sales)) if sales else 0.0
        except (TypeError, ValueError):
            vec[-1] = 0.0
        X.append(vec)
        y.append(math.log1p(float(winners)))
    if len(y) < 200:
        return None
    A = np.asarray(X)
    b = np.asarray(y)
    reg = A.T @ A + np.eye(A.shape[1])
    try:
        coef = np.linalg.solve(reg, A.T @ b)
    except np.linalg.LinAlgError:
        return None
    raw = coef[: len(cols)]
    lo, mx = float(raw.min()), float(raw.max())
    if mx - lo < 1e-9:
        return None
    if not _oos_positive(A, b):
        return None
    per_pos: list[dict[int, float]] = [{} for _ in range(pos)]
    for (p, d), val in zip(cols, raw, strict=True):
        per_pos[p][d] = float((val - lo) / (mx - lo))
    return per_pos


def _main_of(kind: str, row: dict[str, Any]) -> list[int]:
    field = PICK[kind]["field"][0]
    val = row.get(field) or []
    if not isinstance(val, (list, tuple)):
        val = [val]
    return [int(x) for x in val]


def _aux_of(kind: str, row: dict[str, Any]) -> list[int]:
    field = PICK[kind]["field"][1]
    if not field:
        return []
    val = row.get(field)
    if val is None:
        return []
    if not isinstance(val, (list, tuple)):
        val = [val]
    return [int(x) for x in val]


def online_rows(kind: str, draws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """公开开奖记录 → 在线引擎行（含销量与一等奖注数，供人气回归与冷门度使用）。

    唯一事实源：app 的推荐/验奖/回测与离线复盘快照共用，避免两份转换漂移。
    """
    out: list[dict[str, Any]] = []
    for r in draws:
        main = r["main_numbers"]
        spc = r["special_numbers"] or []
        base: dict[str, Any] = {"code": r["issue"], "date": str(r["draw_date"])}
        if kind == "ssq":
            base.update(red=main, blue=(spc[0] if spc else 0))
        elif kind == "dlt":
            base.update(front=main, back=spc)
        elif kind == "qlc":
            base.update(main=main, special=(spc[0] if spc else 0))
        elif kind == "kl8":
            base.update(nums=main)
        else:
            base.update(digits=main)
        prizes = r.get("prizes") or {}
        wc = prizes.get("winner_count_1")
        if wc is not None:
            try:
                base["winners"] = int(wc)
            except (TypeError, ValueError):
                pass
        if r.get("sales"):
            try:
                base["sales"] = float(r["sales"])
            except (TypeError, ValueError):
                pass
        out.append(base)
    return out


def _rank_pick(
    rng: random.Random, ordered: list[int], k: int, scores: dict[int, float] | None = None
) -> list[int]:
    """按优先级取前 k。提供 scores 时同分用 seeded rng 破平局；不提供时保持给定顺序但仍消费 rng。"""
    if scores is None:
        keyed = [(float(i), rng.random(), v) for i, v in enumerate(ordered)]
        keyed.sort(key=lambda t: (t[0], t[1]))
        return sorted(v for _, _, v in keyed[:k])
    keyed = [(-float(scores.get(v, 0.0)), rng.random(), v) for v in ordered]
    keyed.sort()
    return sorted(v for _, _, v in keyed[:k])


def analyze_pool(kind: str, draws: list[dict[str, Any]], window: int = 60) -> dict[str, Any]:
    lo, hi, pick = POOL_SPEC[kind]
    recent = draws[-window:]
    freq = {v: 0 for v in range(lo, hi + 1)}
    for d in recent:
        for x in _main_of(kind, d):
            if lo <= x <= hi:
                freq[x] += 1
    omission: dict[int, int] = {}
    for v in range(lo, hi + 1):
        gap = 0
        for d in reversed(draws):
            if v in _main_of(kind, d):
                break
            gap += 1
        omission[v] = gap
    hot = sorted(freq, key=lambda v: (-freq[v], v))
    cold = sorted(freq, key=lambda v: (freq[v], v))
    sums: list[int] = []
    acs: list[int] = []
    roads = [0, 0, 0]
    prime = 0
    total = 0
    for d in recent:
        n = sorted(_main_of(kind, d))
        if len(n) != pick:
            continue
        sums.append(sum(n))
        acs.append(ac_value(n))
        for x in n:
            roads[x % 3] += 1
            prime += 1 if x in PRIMES else 0
        total += len(n)
    avg = lambda a: round(sum(a) / len(a), 2) if a else None  # noqa: E731
    return {
        "kind": kind,
        "window": len(recent),
        "hot": hot[: pick * 2],
        "cold": cold[: pick * 2],
        "freq": freq,
        "omission": omission,
        "avg_sum": avg(sums),
        "avg_ac": avg(acs),
        "road012": roads,
        "prime_share": round(prime / total, 3) if total else None,
    }


def struct_score(kind: str, nums: list[Any]) -> int:
    """通用池型结构分（和值/奇偶/大小/三区/跨度/AC），0–12。整合 LottoLab 分区与 AC。"""
    if kind not in POOL_SPEC:
        raise ValueError(f"struct_score 仅支持 pool 类彩种，收到 {kind}")
    lo, hi, pick = POOL_SPEC[kind]
    n = sorted(int(x) for x in nums)
    if len(n) != pick:
        return 0
    min_sum = sum(range(lo, lo + pick))
    max_sum = sum(range(hi - pick + 1, hi + 1))
    span_lo, span_hi = min_sum + 0.25 * (max_sum - min_sum), min_sum + 0.75 * (max_sum - min_sum)
    s = 0
    if span_lo <= sum(n) <= span_hi:
        s += 3
    mid = (lo + hi) / 2
    if abs(sum(1 for x in n if x % 2) - pick / 2) <= 1:
        s += 2
    if abs(sum(1 for x in n if x > mid) - pick / 2) <= 1:
        s += 2
    zones = zones_of(lo, hi)
    zc = [0, 0, 0]
    for x in n:
        zc[zone_idx(zones, x)] += 1
    if all(c > 0 for c in zc):
        s += 2
    if 0.6 * (hi - lo) <= (n[-1] - n[0]) <= 0.95 * (hi - lo):
        s += 1
    if ac_value(n) >= pick:
        s += 1
    return s


def _zone_cover(rng: random.Random, kind: str, freq: dict[int, int]) -> list[int]:
    lo, hi, pick = POOL_SPEC[kind]
    zones = zones_of(lo, hi)
    buckets: dict[int, list[int]] = {i: [] for i in range(3)}
    for v in range(lo, hi + 1):
        buckets[zone_idx(zones, v)].append(v)
    jitter = {v: rng.random() for v in range(lo, hi + 1)}
    for i in buckets:
        buckets[i].sort(key=lambda v: (-freq[v], jitter[v], v))
    out: list[int] = []
    for i in range(min(3, pick)):
        if buckets[i]:
            out.append(buckets[i].pop(0))
    rest = [v for i in buckets for v in buckets[i]]
    rest.sort(key=lambda v: (-freq[v], jitter[v], v))
    for v in rest:
        if len(out) >= pick:
            break
        if v not in out:
            out.append(v)
    return sorted(out[:pick])


def _weighted_pick(rng: random.Random, tokens: list[int], weights: list[int], k: int) -> list[int]:
    pool = list(zip(tokens, weights, strict=True))
    out: list[int] = []
    while len(out) < k and pool:
        total = sum(w for _, w in pool)
        target = rng.uniform(0, total)
        acc = 0.0
        chosen = pool[-1][0]
        for tok, w in pool:
            acc += w
            if acc >= target:
                chosen = tok
                break
        out.append(chosen)
        pool = [(t, w) for t, w in pool if t != chosen]
    return sorted(out)


def _pick_aux(rng: random.Random, kind: str, draws: list[dict[str, Any]], offset: int = 0) -> list[int]:
    spec = AUX_SPEC.get(kind)
    if not spec:
        return []
    lo, hi, cnt = spec
    freq = {v: 0 for v in range(lo, hi + 1)}
    omission = {v: 0 for v in range(lo, hi + 1)}
    for d in draws:
        for x in _aux_of(kind, d):
            if lo <= x <= hi:
                freq[x] += 1
    for v in range(lo, hi + 1):
        gap = 0
        for d in reversed(draws):
            if v in _aux_of(kind, d):
                break
            gap += 1
        omission[v] = gap
    maxf = max(1, max(freq.values()))
    score = {v: (freq[v] / maxf) * 0.6 + min(1.0, omission[v] / 30) * 0.4 for v in range(lo, hi + 1)}
    jitter = {v: rng.random() for v in range(lo, hi + 1)}
    ranked = sorted(score, key=lambda v: (-score[v], jitter[v], v))
    start = offset % max(1, len(ranked) - cnt + 1)
    return sorted(ranked[start : start + cnt])


def _cold_aux(kind: str, draws: list[dict[str, Any]]) -> list[int]:
    spec = AUX_SPEC.get(kind)
    if not spec:
        return []
    lo, hi, cnt = spec
    omission = {v: 0 for v in range(lo, hi + 1)}
    for v in range(lo, hi + 1):
        gap = 0
        for d in reversed(draws):
            if v in _aux_of(kind, d):
                break
            gap += 1
        omission[v] = gap
    ranked = sorted(omission, key=lambda v: (-omission[v], v))
    return sorted(ranked[:cnt])


def _low_pop_aux(kind: str) -> list[int]:
    spec = AUX_SPEC.get(kind)
    if not spec:
        return []
    lo, hi, cnt = spec
    ranked = sorted(range(lo, hi + 1), key=lambda v: (number_popularity(v), v))
    return sorted(ranked[:cnt])


def recommend_multi(kind: str, draws: list[dict[str, Any]], seed: int = 1, groups: int = 6) -> dict[str, Any]:
    """多策略、带结构分的推荐（整合 lottery-web 的 6 组参考与遗漏/012 路/质合分析，
    并叠加 LottoLab 的分区与 AC 结构分）。全程 seeded 可复现。"""
    spec = PICK.get(kind)
    if not spec:
        raise ValueError(f"未知彩种 {kind}")
    rng = random.Random(seed)
    if "digit" in spec:
        return _recommend_multi_digit(kind, draws, rng, groups)
    if kind not in POOL_SPEC:
        raise ValueError(f"{kind} 暂不支持多策略推荐")
    an = analyze_pool(kind, draws)
    pop = _learn_popularity(kind, draws)
    lo, hi, pick = POOL_SPEC[kind]
    all_tokens = list(range(lo, hi + 1))
    freq = an["freq"]
    omission = an["omission"]
    hot = an["hot"] + [v for v in sorted(freq, key=lambda v: (-freq[v], v)) if v not in an["hot"]]
    by_omit = sorted(all_tokens, key=lambda v: (-omission[v], v))
    half = pick // 2
    balanced = hot[:half] + an["cold"][: pick - half]
    pop_key = (lambda v: (pop[v], v)) if pop else (lambda v: (number_popularity(v), v))
    by_pop = sorted(all_tokens, key=pop_key)
    # _rank_pick 的 scores 越大越优先；冷门避撞要低撞号先选 → 取负热度
    avoid_scores = {v: -float(pop_key(v)[0]) for v in all_tokens}
    strategies: list[tuple[str, list[int]]] = [
        ("稳健·热号", _rank_pick(rng, hot, pick, scores=freq)),
        ("进取·遗漏", _rank_pick(rng, by_omit, pick, scores=omission)),
        ("冷热均衡", _rank_pick(rng, balanced + hot, pick, scores=freq)),
        ("区间覆盖", _zone_cover(rng, kind, freq)),
        ("冷热加权", _weighted_pick(rng, all_tokens, [freq[v] + 1 for v in all_tokens], pick)),
        ("随机基准", sorted(rng.sample(all_tokens, pick))),
        ("冷门避撞", _rank_pick(rng, by_pop, pick, scores=avoid_scores)),
    ]
    picks: list[dict[str, Any]] = []
    for si, (name, main) in enumerate(strategies[: max(1, groups)]):
        main = sorted(set(main))[:pick]
        if len(main) < pick:
            main = sorted(set(main) | set(hot[:pick]))[:pick]
        if name == "冷门避撞":
            aux = _low_pop_aux(kind)
        elif name == "进取·遗漏":
            aux = _cold_aux(kind, draws)
        elif name == "随机基准":
            sa = AUX_SPEC.get(kind)
            aux = sorted(rng.sample(range(sa[0], sa[1] + 1), sa[2])) if sa else []
        else:
            aux = _pick_aux(rng, kind, draws, offset=si)
        picks.append(
            {
                "name": name,
                "main": [f"{v:02d}" for v in main],
                "aux": [f"{v:02d}" for v in aux],
                "score": struct_score(kind, main),
                "collision": _collision(kind, main, aux, pop),
                "coldness": coldness(kind, main, aux),
            }
        )
    analysis = {
        "window": an["window"],
        "hot": [f"{v:02d}" for v in an["hot"][:pick]],
        "cold": [f"{v:02d}" for v in an["cold"][:pick]],
        "avg_sum": an["avg_sum"],
        "avg_ac": an["avg_ac"],
        "road012": an["road012"],
        "prime_share": an["prime_share"],
    }
    return {
        "kind": kind,
        "family": "pool",
        "picks": picks,
        "analysis": analysis,
        "basis": "实测（一等奖注数回归，控销量）" if pop else "结构先验（生日/吉利/整数）",
        "disclaimer": DISCLAIMER_RECOMMEND,
    }


def _recommend_multi_digit(
    kind: str, draws: list[dict[str, Any]], rng: random.Random, groups: int
) -> dict[str, Any]:
    spec = PICK[kind]
    pos = int(spec["digit"])
    last_hi = int(spec.get("last_hi", 9))
    field = spec["field"][0]
    pop = _learn_popularity(kind, draws)

    def pos_scores(p: int) -> dict[int, int]:
        hi = last_hi if (kind == "qxc" and p == pos - 1) else 9
        counts = {v: 0 for v in range(0, hi + 1)}
        for d in draws:
            dg = d.get(field) or []
            if p < len(dg):
                v = int(dg[p])
                if v in counts:
                    counts[v] += 1
        return counts

    def build(mode: str) -> list[int]:
        out: list[int] = []
        for p in range(pos):
            counts = pos_scores(p)
            hi = max(counts) if counts else 9
            if mode == "hot":
                ranked = sorted(counts, key=lambda v: (-counts[v], v))
                out.append(ranked[0])
            elif mode == "cold":
                ranked = sorted(counts, key=lambda v: (counts[v], v))
                out.append(ranked[0])
            elif mode == "balanced":
                ranked = sorted(counts, key=lambda v: (-counts[v], v))
                out.append(ranked[min(1, len(ranked) - 1)])
            elif mode == "avoid":
                if isinstance(pop, list) and p < len(pop):
                    weights = pop[p]
                    out.append(min(range(0, hi + 1), key=lambda v: (weights.get(v, 0.5), v)))
                else:
                    out.append(
                        min(range(0, hi + 1), key=lambda v: (DIGIT_POP.get(v, number_popularity(v)), v))
                    )
            else:
                out.append(rng.randint(0, hi))
        return out

    modes = [
        ("每位热号", "hot"),
        ("每位冷号", "cold"),
        ("冷热均衡", "balanced"),
        ("随机基准", "random"),
        ("冷门避撞", "avoid"),
    ]
    picks = []
    for name, mode in modes[: max(1, groups)]:
        digits = build(mode)
        picks.append(
            {
                "name": name,
                "main": [str(v) for v in digits],
                "aux": [],
                "score": None,
                "collision": _collision(kind, digits, [], pop),
            }
        )
    return {
        "kind": kind,
        "family": "digit",
        "picks": picks,
        "analysis": {},
        "basis": "实测（直选/一等奖注数回归，控销量）" if isinstance(pop, list) else "结构先验（数字偏好）",
        "disclaimer": DISCLAIMER_RECOMMEND,
    }


POOL_STRATEGIES = ["稳健·热号", "进取·遗漏", "冷热均衡", "区间覆盖", "冷热加权", "随机基准", "冷门避撞"]
DIGIT_STRATEGIES = ["每位热号", "每位冷号", "冷热均衡", "随机基准", "冷门避撞"]


def _expected_hits(kind: str) -> float:
    """均匀模型下一注的期望命中数（主区/按位），作为诚实基线。"""
    spec = PICK.get(kind, {})
    if "digit" in spec:
        pos = int(spec["digit"])
        last_hi = int(spec.get("last_hi", 9))
        if kind == "qxc":
            return (pos - 1) / 10 + 1 / (last_hi + 1)
        return pos / 10
    if kind in POOL_SPEC:
        from typing import cast

        from .domain import RULES, Lottery

        _lo, hi, pick = POOL_SPEC[kind]
        # 期望命中 = 票面 k × 开奖球数 D / 池 N（k=D 时退化为 k²/N）
        return pick * RULES[cast("Lottery", kind)].main_count / hi
    return 0.0


def backtest_strategies(kind: str, draws: list[dict[str, Any]], window: int = 200) -> dict[str, Any]:
    """滚动回测各推荐策略：对最近 window 期，每期只用其之前的历史生成各策略注，
    与实际开奖比对命中数。诚实呈现——所有策略都应贴着均匀期望，没有策略能跑赢随机。"""
    spec = PICK.get(kind)
    if not spec:
        raise ValueError(f"未知彩种 {kind}")
    is_digit = "digit" in spec
    names = DIGIT_STRATEGIES if is_digit else POOL_STRATEGIES
    n = len(draws)
    start = max(60, n - window)
    if n - start < 20:
        raise ValueError("可用回测期数不足（需至少 60 期训练 + 20 期测试）")
    dist: dict[str, dict[int, int]] = {name: {} for name in names}
    total = {name: 0 for name in names}
    tested = 0
    for t in range(start, n):
        train = draws[:t]
        actual = draws[t]
        by_name = {p["name"]: p for p in recommend_multi(kind, train, seed=t, groups=len(names))["picks"]}
        actual_main = _main_of(kind, actual)
        for name in names:
            pick = by_name.get(name)
            if not pick:
                continue
            chosen = [int(x) for x in pick["main"]]
            if is_digit:
                hits = sum(
                    1 for i in range(len(actual_main)) if i < len(chosen) and chosen[i] == actual_main[i]
                )
            else:
                hits = len(set(chosen) & set(actual_main))
            dist[name][hits] = dist[name].get(hits, 0) + 1
            total[name] += hits
        tested += 1
    strategies = [
        {
            "name": name,
            "mean_hits": round(total[name] / tested, 3) if tested else 0.0,
            "hit_distribution": {str(k): v for k, v in sorted(dist[name].items())},
        }
        for name in names
    ]
    return {
        "kind": kind,
        "family": "digit" if is_digit else "pool",
        "tested": tested,
        "expected_mean_hits": round(_expected_hits(kind), 3),
        "strategies": strategies,
        "disclaimer": "回测显示各策略平均命中都贴近均匀期望：这是随机开奖的必然结果，"
        "没有策略能提高中奖概率；结构分/避撞只影响号码形态与分摊风险，不改变期望命中。",
    }
