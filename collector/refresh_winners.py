"""刷新各彩种真实一等奖注数 + 销量 → draws（prizes['winner_count_1'] + sales）。

主源 17500（data.17500.cn，GitHub runner 可达、可每日刷新）：
  ssq/dlt/qlc 的 txt 直接带一等奖注数(n1) 与销量；kl8/fc3d/pl3/pl5/qxc 只带销量。
备源（补 17500 缺的注数，境内源、境外 runner 可能不可达→优雅跳过）：
  cwl(ssq/qlc/kl8/3d) 与 sporttery(dlt/pl3/pl5/qxc)。
冷门度只对浮动奖(ssq/dlt/qlc/qxc一等)有期望回报意义；固定奖(kl8/3d/排3/排5)注数仅作描述。
用法：DATABASE_URL=<neon> python collector/refresh_winners.py [ssq dlt ...]
"""

import json
import os
import subprocess
import sys
from decimal import Decimal
from typing import Any

from contract import normalize_issue
from lottolab.db import Draw, make_engine, make_session_factory
from sqlalchemy import select

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
TXT = {
    "ssq": "ssq_asc.txt",
    "dlt": "dlt_asc.txt",
    "qlc": "7lc_asc.txt",
    "kl8": "kl8_asc.txt",
    "fc3d": "3d_asc.txt",
    "pl3": "pl3_asc.txt",
    "pl5": "pl5_asc.txt",
    "qxc": "7xc_asc.txt",
}
# 17500 txt 列偏移：(销量列, 一等奖注数列或 None)
IDX = {
    "ssq": (15, 17),
    "dlt": (16, 18),
    "qlc": (10, 12),
    "kl8": (22, None),
    "fc3d": (10, None),
    "pl3": (5, None),
    "pl5": (7, None),
    "qxc": (9, None),
}
# 备源：cwl name / sporttery gameNo（补 17500 缺的注数）
BACKUP = {
    "ssq": ("cwl", "ssq"),
    "qlc": ("cwl", "qlc"),
    "kl8": ("cwl", "kl8"),
    "fc3d": ("cwl", "3d"),
    "dlt": ("sporttery", "85"),
    "pl3": ("sporttery", "35"),
    "pl5": ("sporttery", "350133"),
    "qxc": ("sporttery", "04"),
}
KINDS = ["ssq", "dlt", "qlc", "kl8", "fc3d", "pl3", "pl5", "qxc"]


def _curl(url: str, referer: str) -> str:
    r = subprocess.run(  # noqa: S603
        [
            "curl",
            "--ssl-no-revoke",
            "--max-time",
            "60",
            "-A",
            UA,
            "-H",
            f"Referer: {referer}",
            "-s",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=75,
    )
    return r.stdout


def _num(x: str) -> int:
    x = (x or "").replace(",", "").strip()
    return int(x) if x.isdigit() else 0


def from_17500(kind: str) -> dict[str, tuple[int, int | None]]:
    """返回 issue → (sales, n1或None)。"""
    sales_i, n1_i = IDX[kind]
    txt = _curl(f"https://data.17500.cn/{TXT[kind]}", "http://www.17500.cn/")
    if not any(ln.split() for ln in txt.splitlines()):
        txt = _curl(f"http://data.17500.cn/{TXT[kind]}", "http://www.17500.cn/")
    out: dict[str, tuple[int, int | None]] = {}
    for ln in txt.splitlines():
        t = ln.split()
        if len(t) <= sales_i or not t[0].isdigit():
            continue
        issue = normalize_issue(kind, t[0])
        n1 = _num(t[n1_i]) if (n1_i is not None and len(t) > n1_i) else None
        out[issue] = (_num(t[sales_i]), n1)
    return out


def from_backup(kind: str) -> dict[str, int]:
    src, ident = BACKUP[kind]
    try:
        if src == "cwl":
            url = f"https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name={ident}&issueCount=3000"
            key = "x10z10" if ident == "kl8" else 1
            data = json.loads(_curl(url, "https://www.cwl.gov.cn/"))
            out: dict[str, int] = {}
            for it in data.get("result", []):
                wn = next((p.get("typenum") for p in it.get("prizegrades", []) if p.get("type") == key), None)
                if wn not in (None, ""):
                    out[normalize_issue(kind, str(it["code"]))] = int(str(wn).replace(",", ""))
            return out
        url = (
            "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
            f"?gameNo={ident}&provinceId=0&pageSize=100&isVerify=1&pageNo=1"
        )
        data = json.loads(_curl(url, "https://static.sporttery.cn/"))
        out = {}
        for it in (data.get("value") or {}).get("list") or []:
            tiers = it.get("prizeLevelList") or []
            cnt = tiers[0].get("stakeCount") if tiers else None
            if cnt not in (None, ""):
                out[normalize_issue(kind, str(it["lotteryDrawNum"]))] = int(str(cnt).replace(",", ""))
        return out
    except Exception as exc:  # noqa: BLE001 备源不可达→仅用 17500 已有的注数
        print(f"[{kind}] 备源不可达（{type(exc).__name__}），仅用 17500", flush=True)
        return {}


def refresh(factory, kind: str) -> dict[str, Any]:
    data17 = from_17500(kind)
    backup = from_backup(kind) if any(n1 is None for _, n1 in data17.values()) else {}
    sales_u = n1_u = 0
    with factory() as s:
        for d in s.scalars(select(Draw).where(Draw.lottery == kind, Draw.dataset_kind == "real")).all():
            sales, n1 = data17.get(d.issue, (None, None))
            if n1 is None:
                n1 = backup.get(d.issue)
            if sales and (d.sales is None or Decimal(sales) != d.sales):
                d.sales = Decimal(sales)
                sales_u += 1
            if n1 is not None:
                prizes = dict(d.prizes or {})
                if prizes.get("winner_count_1") != str(n1):
                    prizes["winner_count_1"] = str(n1)
                    d.prizes = prizes
                    n1_u += 1
        s.commit()
    return {"源": len(data17), "销量更新": sales_u, "注数更新": n1_u}


def main() -> None:
    raw = os.environ.get("DATABASE_URL") or os.environ.get("LOTTOLAB_DATABASE_URL")
    if not raw:
        raise SystemExit("需要 DATABASE_URL")
    url = raw.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    factory = make_session_factory(make_engine(url, pooled=False))
    kinds = sys.argv[1:] or KINDS
    totals: dict[str, Any] = {}
    for kind in kinds:
        totals[kind] = refresh(factory, kind)
        print(f"[{kind}] {totals[kind]}", flush=True)
    print("完成：", totals, flush=True)


if __name__ == "__main__":
    main()
