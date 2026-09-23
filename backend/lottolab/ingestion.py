"""Immutable source snapshots and idempotent, audited imports."""

import csv
import hashlib
import io
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import DatasetVersion, Draw, IngestionRun, QualityIssue
from .domain import RULES, DatasetKind, DrawInput, Lottery
from .snapshots import save_snapshot


def canonical(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    ).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def parse_csv(raw: bytes) -> list[dict]:
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("CSV 文件不能超过 8 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gb18030")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    needed = {"issue", "draw_date", "main_numbers", "special_numbers"}
    if not reader.fieldnames or not needed.issubset(reader.fieldnames):
        raise ValueError("CSV 需要 issue、draw_date、main_numbers、special_numbers 四列")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("CSV 不能包含重名列")
    rows = []
    for index, row in enumerate(reader, 1):
        if index > 10000:
            raise ValueError("单次最多导入 10000 条记录")
        try:
            if None in row:
                raise ValueError("列数多于表头；号码列表含逗号时请用双引号包围")
            parsed = {
                "issue": row["issue"],
                "draw_date": row["draw_date"],
                "main_numbers": [
                    int(v) for v in re.split(r"[,;\s]+", row["main_numbers"].strip()) if v.strip()
                ],
                "special_numbers": [
                    int(v) for v in re.split(r"[,;\s]+", row["special_numbers"].strip()) if v.strip()
                ],
            }
            for key in ("lottery", "dataset_kind", "sales", "pool_amount"):
                if row.get(key):
                    parsed[key] = row[key]
            if row.get("prizes"):
                parsed["prizes"] = json.loads(row["prizes"])
            rows.append(parsed)
        except (ValueError, TypeError, AttributeError) as exc:
            rows.append({"issue": row.get("issue"), "_parse_error": str(exc), "raw": row})
    if not rows:
        raise ValueError("CSV 没有数据行")
    return rows


def ingest_records(
    session: Session,
    records: list[dict],
    *,
    lottery: Lottery,
    dataset_kind: DatasetKind,
    source: str,
    source_url: str,
    raw: bytes,
    data_dir: Path,
    store_in_database: bool = False,
) -> dict:
    if not records or len(records) > 10000:
        raise ValueError("导入记录数必须在 1–10000 之间")
    snapshot_hash = save_snapshot(session, raw, None if store_in_database else data_dir / "raw")
    run = IngestionRun(
        lottery=lottery,
        dataset_kind=dataset_kind,
        source=source,
        source_url=source_url,
        snapshot_hash=snapshot_hash,
        snapshot_path=f"{snapshot_hash}.snapshot",
        received=len(records),
        accepted=0,
        duplicates=0,
        rejected=0,
        conflicts=0,
        warnings=0,
    )
    session.add(run)
    session.flush()
    examples: list[dict] = []

    def report(index: int, record: dict, severity: str, reason: str):
        issue = str(record.get("issue", ""))[:64] or None
        session.add(
            QualityIssue(
                ingestion_id=run.id,
                lottery=lottery,
                row_number=index,
                issue=issue,
                severity=severity,
                reason=reason,
                raw_record=record,
            )
        )
        if len(examples) < 30:
            examples.append({"row": index, "issue": issue, "severity": severity, "reason": reason})

    for index, record in enumerate(records, 1):
        try:
            if record.get("_parse_error"):
                raise ValueError(record["_parse_error"])
            if (
                record.get("lottery", lottery) != lottery
                or record.get("dataset_kind", dataset_kind) != dataset_kind
            ):
                raise ValueError("记录的彩种或数据类型与本次导入范围不一致")
            draw = DrawInput.model_validate({**record, "lottery": lottery, "dataset_kind": dataset_kind})
        except (ValidationError, ValueError, TypeError) as exc:
            run.rejected += 1
            reason = (
                "; ".join(e["msg"] for e in exc.errors(include_url=False))
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            report(index, record, "invalid", reason[:1800])
            continue
        identity_hash = digest(draw.identity_payload())
        existing = session.scalar(select(Draw).where(Draw.lottery == lottery, Draw.issue == draw.issue))
        if existing:
            metadata_changed = any(
                value is not None and value != getattr(existing, field)
                for field, value in (("sales", draw.sales), ("pool_amount", draw.pool_amount))
            )
            metadata_changed |= any(
                key not in existing.prizes or Decimal(str(existing.prizes[key])) != value
                for key, value in draw.prizes.items()
            )
            if existing.identity_hash == identity_hash and not metadata_changed:
                run.duplicates += 1
            else:
                run.conflicts += 1
                report(
                    index,
                    record,
                    "conflict",
                    "同一期次已有不同开奖结果或财务字段，已隔离，请比较后选择保留或修订",
                )
            continue
        payload = draw.model_dump(mode="json")
        payload["draw_date"] = draw.draw_date
        try:
            with session.begin_nested():
                session.add(
                    Draw(
                        **payload,
                        identity_hash=identity_hash,
                        source=source,
                        ingestion_id=run.id,
                        rule_version=RULES[lottery].version,
                    )
                )
                session.flush()
            run.accepted += 1
        except IntegrityError:
            concurrent = session.scalar(select(Draw).where(Draw.lottery == lottery, Draw.issue == draw.issue))
            if concurrent and concurrent.identity_hash == identity_hash:
                run.duplicates += 1
            else:
                run.conflicts += 1
                report(index, record, "conflict", "并发导入或数据库约束冲突，记录未写入")
            continue
        if draw.draw_date.weekday() not in RULES[lottery].weekdays:
            run.warnings += 1
            report(index, record, "warning", "开奖日期不在通常开奖星期内；已保留，请核对特殊日历")
    session.commit()
    return {**run.public(), "issues": examples}


def load_draws(session: Session, lottery: Lottery, dataset_kind: DatasetKind) -> list[dict]:
    return [
        draw.public()
        for draw in session.scalars(
            select(Draw)
            .where(Draw.lottery == lottery, Draw.dataset_kind == dataset_kind)
            .order_by(Draw.draw_date, Draw.issue)
        )
    ]


def freeze_dataset(session: Session, lottery: Lottery, dataset_kind: DatasetKind) -> DatasetVersion:
    rows = [
        {key: value for key, value in row.items() if key != "id"}
        for row in load_draws(session, lottery, dataset_kind)
    ]
    version_id = digest({"lottery": lottery, "dataset_kind": dataset_kind, "draws": rows})
    version = session.get(DatasetVersion, version_id)
    if not version:
        version = DatasetVersion(
            id=version_id, lottery=lottery, dataset_kind=dataset_kind, draw_count=len(rows), draws=rows
        )
        try:
            with session.begin_nested():
                session.add(version)
                session.flush()
        except IntegrityError:
            version = session.get(DatasetVersion, version_id)
    if version is None:
        raise RuntimeError("无法取得冻结的数据版本")
    return version


def synthetic_records(lottery: Lottery, count: int, seed: int = 2026) -> list[dict]:
    rule = RULES[lottery]
    rng = np.random.default_rng(seed)
    # A fixed endpoint keeps a seed's demonstration dataset stable across days.
    day = date(2025, 12, 31)
    dates: list[date] = []
    while len(dates) < count:
        if day.weekday() in rule.weekdays:
            dates.append(day)
        day -= timedelta(days=1)
    return [
        {
            "lottery": lottery,
            "issue": f"SIM-{seed:08x}-{index:05d}",
            "draw_date": day.isoformat(),
            "main_numbers": sorted(
                int(v) for v in rng.choice(np.arange(1, rule.main_max + 1), rule.main_count, replace=False)
            ),
            "special_numbers": sorted(
                int(v)
                for v in rng.choice(np.arange(1, rule.special_max + 1), rule.special_count, replace=False)
            ),
            "dataset_kind": "synthetic",
        }
        for index, day in enumerate(reversed(dates), 1)
    ]
