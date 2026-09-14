"""
contract.py —— 方案B 数据契约的可执行实现（仅标准库，离线可测、无网络）。
严格对齐 P0/contract.md：POOL/DIGIT 两类记录 + 期号归一 + 号码范围校验。
任何不合规记录抛 ContractError（供采集器在落库前拒绝，而非静默改数据）。
"""
from __future__ import annotations
from dataclasses import dataclass

# family, main=(count, lo, hi), special=(count, lo, hi), issue_digits
# qlc 特别号须与基本号不重复，单独在 validate 里处理；kl8 主区固定 20/80。
RULES: dict[str, dict] = {
    "ssq": {"family": "POOL",  "main": (6, 1, 33), "special": (1, 1, 16), "issue": 7},
    "dlt": {"family": "POOL",  "main": (5, 1, 35), "special": (2, 1, 12), "issue": 7},
    "qlc": {"family": "POOL",  "main": (7, 1, 30), "special": (1, 1, 30), "issue": 7, "no_dup_with_main": True},
    "kl8": {"family": "POOL",  "main": (20, 1, 80), "special": (0, 0, 0),  "issue": 7},
    "fc3d": {"family": "DIGIT", "main": (3, 0, 9), "special": (0, 0, 0), "issue": 7},
    "pl3":  {"family": "DIGIT", "main": (3, 0, 9), "special": (0, 0, 0), "issue": 7},
    "pl5":  {"family": "DIGIT", "main": (5, 0, 9), "special": (0, 0, 0), "issue": 7},
    # 七星彩：期号 5 位（契约唯一例外）；7 位数字，末位号池 0..14
    "qxc":  {"family": "DIGIT", "main": (7, 0, 9), "special": (0, 0, 0), "issue": 5, "last_hi": 14},
}

class ContractError(ValueError):
    pass


def normalize_issue(kind: str, issue: str | int) -> str:
    """期号归一：ssq/dlt/... 5位YYNNN→20+（7位）；qxc 保持5位；已是7位则原样。"""
    s = str(issue).strip()
    if not s.isdigit():
        raise ContractError(f"期号必须为数字：{s!r}")
    if kind == "qxc":
        if len(s) == 5:
            return s
        raise ContractError(f"qxc 期号应为5位，实得 {len(s)}：{s}")
    # 其余：允许 5 位补 "20"，否则须 7 位
    if len(s) == 5:
        s = "20" + s
    if len(s) != 7:
        raise ContractError(f"{kind} 期号归一后须 7 位（YYYYNNN），实得 {s!r}")
    return s


def _check_year_seq(issue: str, draw_date: str) -> None:
    if draw_date and int(issue[:4]) != int(draw_date[:4]):
        raise ContractError(f"期号年份与开奖日期不一致：{issue} vs {draw_date}")
    seq = int(issue[4:])
    if not 1 <= seq <= 366:
        raise ContractError(f"年内期次越界(1..366)：{issue}")


def canonicalize(kind: str, issue, main: list, special: list, draw_date: str = "") -> dict:
    """把一注原始记录归一为 canonical 记录；不合规抛 ContractError。"""
    if kind not in RULES:
        raise ContractError(f"未知彩种 {kind}")
    r = RULES[kind]
    mcnt, mlo, mhi = r["main"]
    scnt, slo, shi = r["special"]
    main = [int(x) for x in main]
    special = [int(x) for x in (special or [])]

    if len(main) != mcnt:
        raise ContractError(f"{kind} 主区须 {mcnt} 个，实得 {len(main)}")
    if r["family"] == "POOL":
        if len(set(main)) != mcnt:
            raise ContractError(f"{kind} 主区号码不可重复（池型）：{main}")
        if any(v < mlo or v > mhi for v in main):
            raise ContractError(f"{kind} 主区号须∈[{mlo},{mhi}]：{main}")
        main_out = sorted(main)
    else:  # DIGIT：有序、可重号，不排序不去重
        hi = r.get("last_hi", mhi)
        for i, v in enumerate(main):
            cap = hi if (i == mcnt - 1 and "last_hi" in r) else mhi
            if v < mlo or v > cap:
                raise ContractError(f"{kind} 第{i+1}位须∈[{mlo},{cap}]：{v}")
        main_out = main  # 保持顺序

    if len(special) != scnt:
        raise ContractError(f"{kind} 辅区须 {scnt} 个，实得 {len(special)}")
    if scnt:
        if any(v < slo or v > shi for v in special):
            raise ContractError(f"{kind} 辅区号须∈[{slo},{shi}]：{special}")
        special_out = sorted(set(special))
        if r.get("no_dup_with_main") and set(special_out) & set(main_out):
            raise ContractError(f"{kind} 特别号不得与基本号重复：{special_out}∩{main_out}")
    else:
        special_out = []

    iss = normalize_issue(kind, issue)
    if kind in ("ssq", "dlt") and r["family"] == "POOL":
        _check_year_seq(iss, draw_date)

    return {"kind": kind, "issue": iss, "family": r["family"],
            "main": main_out, "special": special_out, "draw_date": (draw_date or "")[:10]}


def key(rec: dict):
    """多源比对的规范化指纹：与原始字符串无关，只认归一后的语义。"""
    return (rec["kind"], rec["issue"], tuple(rec["main"]), tuple(rec["special"]), rec["draw_date"])
