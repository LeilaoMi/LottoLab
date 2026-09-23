"""每日开奖同步：从 17500 拉 8 彩种最新若干期 → 归一期号 → 正规校验 → 幂等追加到生产 draws。

与 shadow_parallel 互补：影子并跑只写影子表做比对、不改生产；本作业把当日真实开奖正式落库。
安全边界：只做 INSERT ... ON CONFLICT DO NOTHING，绝不 UPDATE/DELETE 既有行；
每彩种保留一条 IngestionRun 溯源；期号经 normalize_issue 归一（dlt 5 位→7 位，qxc 保持 5 位）。
号码范围/升序/可重等由数据库 family-aware CHECK 兜底，不合规记录计入 rejected 而非崩溃。

用法：
    DATABASE_URL=<neon-url> python collector/daily_sync.py            # 默认每彩种最新 40 期
    DATABASE_URL=... python collector/daily_sync.py --recent=200
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingest_neon as IN  # noqa: E402
from contract import normalize_issue  # noqa: E402
from lottolab.db import Draw, IngestionRun, make_engine, make_session_factory  # noqa: E402
from lottolab.domain import RULES, DrawInput  # noqa: E402
from lottolab.ingestion import digest  # noqa: E402
from lottolab.snapshots import save_snapshot  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

# ingest_neon.SRC 只映射 6 小彩种；17500 同样有 ssq/dlt 全量文件，补进来即可同步全部 8 彩种。
IN.SRC.setdefault("ssq", ("ssq_asc.txt", 6, 1))
IN.SRC.setdefault("dlt", ("dlt_asc.txt", 5, 2))
KINDS = ["ssq", "dlt", "fc3d", "pl3", "pl5", "qlc", "qxc", "kl8"]
CHUNK = 1000  # 每批 ≤1000 行，远离 PG 65535 绑定参数上限


def _recent() -> int:
    for i, arg in enumerate(sys.argv):
        if arg.startswith("--recent"):
            value = arg.split("=", 1)[1] if "=" in arg else sys.argv[i + 1]
            return max(1, min(int(value), 10000))
    return int(os.environ.get("RECENT", "40"))


def sync_kind(factory, kind: str, n: int) -> int:
    recs, src_url, raw = IN.build(kind)
    recs = recs[:n]
    if not recs:
        raise RuntimeError(f"[{kind}] 源返回空数据，每日同步中止（避免静默零更新）")
    with factory() as session:
        snapshot_hash = save_snapshot(session, raw, None)
        run = IngestionRun(
            lottery=kind,
            dataset_kind="real",
            source="17500",
            source_url=src_url,
            snapshot_hash=snapshot_hash,
            snapshot_path=f"{snapshot_hash}.snapshot",
            received=len(recs),
        )
        session.add(run)
        session.flush()
        rows: list[dict] = []
        rejected = 0
        for record in recs:
            try:
                record = {**record, "issue": normalize_issue(kind, record["issue"])}
                draw = DrawInput.model_validate({**record, "lottery": kind, "dataset_kind": "real"})
            except (ValidationError, ValueError, TypeError):
                rejected += 1
                continue
            payload = draw.model_dump(mode="json")
            payload["draw_date"] = draw.draw_date
            rows.append(
                {
                    **payload,
                    "identity_hash": digest(draw.identity_payload()),
                    "source": "17500",
                    "ingestion_id": run.id,
                    "rule_version": RULES[kind].version,
                }
            )
        accepted = 0
        for i in range(0, len(rows), CHUNK):
            part = rows[i : i + CHUNK]
            stmt = (
                pg_insert(Draw)
                .values(part)
                .on_conflict_do_nothing(index_elements=["lottery", "issue"])
                .returning(Draw.id)
            )
            accepted += len(session.execute(stmt).fetchall())
        run.accepted = accepted
        run.rejected = rejected
        run.duplicates = len(rows) - accepted
        session.commit()
        print(f"[{kind}] 拉{len(recs)} 新增{accepted} 重复{run.duplicates} 拒绝{rejected}", flush=True)
        return accepted


def main() -> None:
    raw_url = os.environ.get("DATABASE_URL") or os.environ.get("LOTTOLAB_DATABASE_URL")
    if not raw_url:
        raise SystemExit("需要 DATABASE_URL（Neon 连接串）")
    url = raw_url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    factory = make_session_factory(make_engine(url, pooled=False))
    n = _recent()
    total = 0
    failures: list[str] = []
    for kind in KINDS:
        try:
            total += sync_kind(factory, kind, n)
        except Exception as exc:  # noqa: BLE001 — 单彩种失败需汇总后非零退出
            failures.append(str(exc))
            print(f"[{kind}] 失败：{exc}", flush=True)
    if failures:
        raise SystemExit(f"每日同步失败 {len(failures)} 个彩种：" + "; ".join(failures))
    print(f"每日同步完成：本次新增 {total} 期", flush=True)


if __name__ == "__main__":
    main()
