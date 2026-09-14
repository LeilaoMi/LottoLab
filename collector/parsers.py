"""
parsers.py —— 方案B 采集器的各源解析（纯函数，输入原始文本、输出 canonical 前记录）。
只负责“把一个源的响应变成结构化记录”，交叉校验/落库交给 collect_core。无网络依赖，可离线测。
"""

from __future__ import annotations

import json
import re


def _digits(cell):
    m = re.fullmatch(r"\d+", cell.strip())
    return int(cell) if m else None


# ---------- 福彩官方 cwl.gov.cn（JSON）：ssq / qlc / fc3d / kl8 ----------
def parse_cwl(text: str, kind: str):
    data = json.loads(text)
    if data.get("state") != 0 or not isinstance(data.get("result"), list):
        raise ValueError("cwl 返回非成功结构")
    out = []
    for it in data["result"]:
        issue = str(it["code"])
        date = str(it.get("date", ""))[:10]
        if kind == "ssq":
            main = [int(x) for x in it["red"].split(",")]
            special = [int(it["blue"])] if str(it.get("blue", "")).isdigit() else []
        elif kind == "qlc":
            main = [int(x) for x in it["red"].split(",")]
            special = [int(it["blue"])] if str(it.get("blue", "")).isdigit() else []
        else:
            raise ValueError(f"parse_cwl 不支持 {kind}")
        sales = it.get("sales") or None
        pool = it.get("poolmoney") or None
        prizes = {str(p["type"]): (p.get("typemoney") or None) for p in it.get("prizegrades", [])}
        out.append(
            {
                "issue": issue,
                "main": main,
                "special": special,
                "draw_date": date,
                "sales": sales,
                "pool": pool,
                "prizes": prizes,
            }
        )
    return out


# ---------- 500.com history.php（HTML 表）：ssq / dlt ----------
_ROW = re.compile(r'<tr class="t_tr1">(.*?)</tr>', re.S)
_MAIN = re.compile(r'<td class="[^"]*cfont2"[^>]*>\s*(\d+)\s*</td>')
_AUX = re.compile(r'<td class="[^"]*cfont4"[^>]*>\s*(\d+)\s*</td>')
_DATE = re.compile(r"<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>")
_ISSUE = re.compile(r"<td[^>]*>\s*(\d{5,7})\s*</td>")


def parse_500(text: str, kind: str):
    out = []
    for row in _ROW.findall(text):
        main = [int(x) for x in _MAIN.findall(row)]
        aux = [int(x) for x in _AUX.findall(row)]
        dm = _DATE.search(row)
        im = _ISSUE.search(row)
        if not (dm and im):
            continue
        out.append({"issue": im.group(1), "main": main, "special": aux, "draw_date": dm.group(1)})
    return out


# ---------- 17500 txt（空格分列）：kl8 / fc3d / pl3 / pl5 / qxc / qlc ----------
# 形态：issue date  <若干号码>  其余奖金/销量列（截断到号码个数即可）
def parse_17500(text: str, kind: str, main_count: int, special_count: int = 0, last_hi: int | None = None):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out = []
    for ln in lines:
        p = ln.split()
        if len(p) < 2 + main_count:
            continue
        issue, date = p[0], (p[1] or "")[:10]
        if not re.fullmatch(r"\d{5,7}", issue):
            continue
        nums = [int(x) for x in p[2 : 2 + main_count]]
        special = (
            [int(x) for x in p[2 + main_count : 2 + main_count + special_count]] if special_count else []
        )
        out.append({"issue": issue, "main": nums, "special": special, "draw_date": date})
    out.reverse()  # 文件升序 → 输出按 issue 降序（最新在前）
    return out


# ---------- 体彩官方 webapi.sporttery.cn（getHistoryPageListV1，需 Referer 头）：dlt ----------
def parse_sporttery(text: str, kind: str) -> list[dict]:
    data = json.loads(text)
    if not data.get("success") or not isinstance(data.get("value"), dict):
        raise ValueError("sporttery 返回非成功结构")
    picks = {"dlt": (5, 2)}.get(kind)
    if not picks:
        raise ValueError(f"parse_sporttery 不支持 {kind}")
    mc, sc = picks
    out = []
    for it in data["value"].get("list", []):
        toks = str(it.get("lotteryDrawResult", "")).split()
        if len(toks) < mc + sc:
            continue
        out.append(
            {
                "issue": str(it.get("lotteryDrawNum", "")),
                "main": [int(x) for x in toks[:mc]],
                "special": [int(x) for x in toks[mc : mc + sc]],
                "draw_date": str(it.get("lotteryDrawTime", ""))[:10],
            }
        )
    return out
