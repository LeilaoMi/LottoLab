"""预测引擎 · 确定性核心（自 lottery-web worker/src/predict.js 迁入 trunk 的第一片）。

只含无随机、可精确断言的部分：分区、AC 值、二项显著性、结构分（和值/奇偶/大小/跨度/区分布/AC）。
带随机的 pickN/kill/dan/recommend 留待后续片（会引入可注入的 seed 以便复现测试）。
"""

from __future__ import annotations

import math
import random
from typing import Any

PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79}

# pool 类彩种主区界（与 contract 对齐）：min, max, pick
POOL_SPEC: dict[str, tuple[int, int, int]] = {
    "ssq": (1, 33, 6),
    "dlt": (1, 35, 5),
    "qlc": (1, 30, 7),
    "kl8": (1, 80, 20),
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
