from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool

from .domain import RULES


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


def number_constraint() -> str:
    clauses = []
    for rule in RULES.values():
        terms = [f"lottery = '{rule.code}'"]
        if rule.family == "POOL":
            for field, count, maximum in (
                ("main_numbers", rule.main_count, rule.main_max),
                ("special_numbers", rule.special_count, rule.special_max),
            ):
                terms.append(f"coalesce(json_array_length({field}), -1) = {count}")
                for i in range(count):
                    terms.append(f"CAST({field} ->> {i} AS INTEGER) BETWEEN 1 AND {maximum}")
                    if i:
                        terms.append(
                            f"CAST({field} ->> {i - 1} AS INTEGER) < CAST({field} ->> {i} AS INTEGER)"
                        )
        else:  # DIGIT：逐位、有序、可重、含 0；无附加区
            n = rule.main_count
            terms.append("coalesce(json_array_length(special_numbers), -1) = 0")
            terms.append(f"coalesce(json_array_length(main_numbers), -1) = {n}")
            for i in range(n):
                cap = rule.last_max if (rule.last_max is not None and i == n - 1) else rule.main_max
                terms.append(f"CAST(main_numbers ->> {i} AS INTEGER) BETWEEN 0 AND {cap}")
        clauses.append("(" + " AND ".join(terms) + ")")
    return " OR ".join(clauses)


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    raw_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    lottery: Mapped[str] = mapped_column(String(8))
    dataset_kind: Mapped[str] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str] = mapped_column(Text, default="")
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    snapshot_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    received: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    conflicts: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)

    def public(self) -> dict:
        return {
            "id": self.id,
            "lottery": self.lottery,
            "dataset_kind": self.dataset_kind,
            "source": self.source,
            "source_url": self.source_url,
            "snapshot_hash": self.snapshot_hash,
            "created_at": self.created_at.isoformat(),
            "received": self.received,
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "rejected": self.rejected,
            "conflicts": self.conflicts,
            "warnings": self.warnings,
        }


class Draw(Base):
    __tablename__ = "draws"
    __table_args__ = (
        UniqueConstraint("lottery", "issue", name="uq_draw_lottery_issue"),
        CheckConstraint("dataset_kind IN ('real', 'synthetic')", name="ck_draw_kind"),
        CheckConstraint("sales IS NULL OR sales >= 0", name="ck_draw_sales"),
        CheckConstraint("pool_amount IS NULL OR pool_amount >= 0", name="ck_draw_pool"),
        CheckConstraint(number_constraint(), name="ck_draw_numbers"),
        Index("ix_draw_scope_date", "lottery", "dataset_kind", "draw_date", "issue"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    lottery: Mapped[str] = mapped_column(String(8))
    issue: Mapped[str] = mapped_column(String(32))
    draw_date: Mapped[date] = mapped_column(Date)
    dataset_kind: Mapped[str] = mapped_column(String(12), default="real")
    main_numbers: Mapped[list[int]] = mapped_column(JSON)
    special_numbers: Mapped[list[int]] = mapped_column(JSON)
    sales: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    pool_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    prizes: Mapped[dict] = mapped_column(JSON, default=dict)
    identity_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(80))
    ingestion_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"))
    rule_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    def public(self) -> dict:
        return {
            "id": self.id,
            "lottery": self.lottery,
            "issue": self.issue,
            "draw_date": self.draw_date.isoformat(),
            "dataset_kind": self.dataset_kind,
            "main_numbers": self.main_numbers,
            "special_numbers": self.special_numbers,
            "sales": str(self.sales) if self.sales is not None else None,
            "pool_amount": str(self.pool_amount) if self.pool_amount is not None else None,
            "prizes": self.prizes,
            "source": self.source,
            "ingestion_id": self.ingestion_id,
            "rule_version": self.rule_version,
        }


class QualityIssue(Base):
    __tablename__ = "quality_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ingestion_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    lottery: Mapped[str] = mapped_column(String(8))
    row_number: Mapped[int] = mapped_column(Integer)
    issue: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    raw_record: Mapped[dict] = mapped_column(JSON)
    resolution_state: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    resolution: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lottery: Mapped[str] = mapped_column(String(8))
    dataset_kind: Mapped[str] = mapped_column(String(12))
    draw_count: Mapped[int] = mapped_column(Integer)
    draws: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')", name="ck_job_status"
        ),
        Index("ix_job_claim", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(32))
    lottery: Mapped[str] = mapped_column(String(8))
    dataset_kind: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    params: Mapped[dict] = mapped_column(JSON)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_versions.id"))
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def public(self, detail: bool = True) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind,
            "lottery": self.lottery,
            "dataset_kind": self.dataset_kind,
            "status": self.status,
            "params": self.params,
            "dataset_id": self.dataset_id,
            "error": self.error,
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
        if detail:
            data["result"] = self.result
        return data


def make_engine(url: str, *, pooled: bool = True):
    if url.startswith("sqlite") and ":memory:" not in url:
        Path(url.split("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {} if pooled else {"poolclass": NullPool}
    connect_args: dict[str, Any] = (
        {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}
    )
    if not pooled and url.startswith("postgresql+psycopg"):
        # Transaction poolers may route subsequent requests to different servers.
        connect_args = {"connect_timeout": 10, "prepare_threshold": None}
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args=connect_args,
        **options,
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
