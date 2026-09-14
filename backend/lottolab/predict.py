"""预测引擎 · 确定性核心（自 lottery-web worker/src/predict.js 迁入 trunk 的第一片）。

只含无随机、可精确断言的部分：分区、AC 值、二项显著性、结构分（和值/奇偶/大小/跨度/区分布/AC）。
带随机的 pickN/kill/dan/recommend 留待后续片（会引入可注入的 seed 以便复现测试）。
"""

from __future__ import annotations

import math
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
