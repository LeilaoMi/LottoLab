"""B3-3 生产入库：拉 17500 小彩种 → 复用 LottoLab 正规 ingest_records 写入 draws（溯源天然一致）。

用法：
    LOTTOLAB_DATABASE_URL=<neon url> python collector/ingest_neon.py            # 全部 6 小彩种
    LOTTOLAB_DATABASE_URL=... python collector/ingest_neon.py --kinds fc3d,kl8   # 指定
    python collector/ingest_neon.py --dry                                        # 只预览不写
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import parsers as P  # noqa: E402
from lottolab.db import make_engine, make_session_factory  # noqa: E402
from lottolab.ingestion import ingest_records  # noqa: E402

SRC = {
    "fc3d": ("3d_asc.txt", 3, 0),
    "pl3": ("pl3_asc.txt", 3, 0),
    "pl5": ("pl5_asc.txt", 5, 0),
    "qlc": ("7lc_asc.txt", 7, 1),
    "qxc": ("7xc_asc.txt", 7, 0),
    "kl8": ("kl8_asc.txt", 20, 0),
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


def fetch(url: str) -> str:
    # 不关闭 TLS 校验（去掉 -k）；data.17500.cn 若仅 HTTP 可达则按原样请求
    r = subprocess.run(
        ["curl", "--ssl-no-revoke", "--max-time", "60", "-A", UA, "-s", url],
        capture_output=True,
        text=True,
        timeout=75,
    )
    return r.stdout


def build(kind: str):
    fn, mc, sc = SRC[kind]
    url = f"https://data.17500.cn/{fn}"
    txt = fetch(url)
    if not txt.strip():
        url = f"http://data.17500.cn/{fn}"
        txt = fetch(url)
    recs = P.parse_17500(txt, kind, mc, sc)
    out = [
        {
            "issue": r["issue"],
            "draw_date": r["draw_date"],
            "main_numbers": r["main"],
            "special_numbers": r["special"],
        }
        for r in recs
    ]
    return out, url, txt.encode("utf-8", "ignore")


def main() -> None:
    dry = "--dry" in sys.argv
    kinds = list(SRC)
    for a in sys.argv:
        if a.startswith("--kinds="):
            kinds = a.split("=", 1)[1].split(",")
    url = os.environ.get("LOTTOLAB_DATABASE_URL")
    factory = None
    if url and not dry:
        factory = make_session_factory(make_engine(url, pooled=False))
    for kind in kinds:
        recs, src_url, raw = build(kind)
        if not recs:
            print(f"[{kind}] 无数据/源不可达")
            continue
        if dry:
            print(f"[dry] {kind}: 可入库 {len(recs)} 期，最新 {recs[0]['issue']}")
            continue
        with factory() as s:
            r = ingest_records(
                s,
                recs,
                lottery=kind,
                dataset_kind="real",
                source="17500",
                source_url=src_url,
                raw=raw,
                data_dir=Path(".local"),
                store_in_database=True,
            )
            s.commit()
            print(f"[{kind}] 新增 {r['accepted']} · 重复 {r['duplicates']} · 拒绝 {r['rejected']}")


if __name__ == "__main__":
    main()
