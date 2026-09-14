"""HTTP boundary: validated inputs, explicit scope, bounded jobs and safe local use."""

import csv
import hmac
import io
import ipaddress
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import date
from threading import Lock
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .analysis import summarize
from .calc import calc_bet
from .config import Settings, get_settings
from .db import Draw, IngestionRun, Job, QualityIssue, make_engine, make_session_factory, now
from .domain import DISCLAIMER, RULES, DatasetKind, DrawInput, Lottery
from .ingestion import digest, freeze_dataset, ingest_records, load_draws, parse_csv
from .predict import recommend
from .schemas import (
    BacktestRequest,
    CoverRequest,
    DemoRequest,
    RandomnessRequest,
    ResolutionRequest,
    SimulationRequest,
    SyncRequest,
    TicketRequest,
)
from .verify import verify_batch
from .worker import expire_interrupted_jobs, run_request_job

logger = logging.getLogger("lottolab")


def can_write(request: Request, settings: Settings) -> bool:
    origin = request.headers.get("origin")
    if origin and origin not in settings.origins:
        return False
    token = request.headers.get("x-admin-token", "")
    if (
        settings.admin_token
        and token
        and hmac.compare_digest(token.encode("utf-8"), settings.admin_token.encode("utf-8"))
    ):
        return True
    if settings.allow_local_writes and request.client:
        try:
            return ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            return False
    return False


def create_app(settings: Settings | None = None, session_factory=None) -> FastAPI:
    settings = settings or get_settings()
    engine = (
        None
        if session_factory
        else make_engine(settings.database_url, pooled=settings.execution_mode == "worker")
    )
    factory = session_factory or make_session_factory(engine)
    resolution_lock = Lock()
    enqueue_lock = Lock()

    @asynccontextmanager
    async def lifespan(_app):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        yield
        if engine:
            engine.dispose()

    app = FastAPI(title="LottoLab", version=__version__, description=DISCLAIMER, lifespan=lifespan)
    app.state.session_factory = factory
    app.state.settings = settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )

    def session():
        with factory() as value:
            yield value

    DB = Annotated[Session, Depends(session)]

    def authorize(request: Request):
        if not can_write(request, settings):
            raise HTTPException(
                403, "需要管理员权限；本地开发须绑定回环地址并开启本地写入，部署模式使用管理员令牌"
            )

    @app.exception_handler(ValueError)
    async def invalid_value(_request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_request, _exc):
        logger.exception("Database operation failed")
        return JSONResponse(
            status_code=503, content={"detail": "数据库暂时不可用，请检查连接和迁移状态后重试"}
        )

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        public_api = {"/api/v1/health", "/api/v1/rules", "/api/v1/models"}
        if (
            settings.require_read_auth
            and request.url.path.startswith("/api/")
            and request.url.path not in public_api
            and request.method != "OPTIONS"
            and not can_write(request, settings)
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "请先验证管理员令牌以访问私人工作台"},
                headers={"Cache-Control": "no-store"},
            )
        if request.method == "POST" and request.url.path.startswith("/api/"):
            if not can_write(request, settings):
                return JSONResponse(
                    status_code=403, content={"detail": "需要管理员权限或明确启用的本地访问权限"}
                )
            limit = settings.max_csv_bytes + 65536 if request.url.path == "/api/v1/imports/csv" else 65536
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > limit):
                return JSONResponse(status_code=413, content={"detail": "请求内容超过大小限制"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/health")
    def health(request: Request, db: DB):
        db.execute(text("SELECT 1"))
        heartbeat = settings.data_dir / "worker.heartbeat"
        worker_ready = settings.execution_mode == "request" or (
            heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < 15
        )
        return {
            "status": "ok",
            "version": __version__,
            "database": db.get_bind().dialect.name,
            "worker_ready": worker_ready,
            "can_write": can_write(request, settings),
            "can_read": not settings.require_read_auth or can_write(request, settings),
            "execution_mode": settings.execution_mode,
            "job_timeout_seconds": settings.job_timeout_seconds,
            "max_csv_bytes": settings.max_csv_bytes,
            "disclaimer": DISCLAIMER,
        }

    @app.get("/api/v1/rules")
    def rules():
        return {"items": [rule.public() for rule in RULES.values()], "disclaimer": DISCLAIMER}

    @app.get("/api/v1/draws/latest")
    def latest(db: DB, lottery: Lottery = "ssq", dataset_kind: DatasetKind = "real"):
        draw = db.scalar(
            select(Draw)
            .where(Draw.lottery == lottery, Draw.dataset_kind == dataset_kind)
            .order_by(Draw.draw_date.desc(), Draw.issue.desc())
            .limit(1)
        )
        return {"draw": draw.public() if draw else None}

    @app.get("/api/v1/draws")
    def draws(
        db: DB,
        lottery: Lottery = "ssq",
        dataset_kind: DatasetKind = "real",
        offset: int = Query(0, ge=0),
        limit: int = Query(30, ge=1, le=200),
        search: str = Query("", max_length=32),
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        if start_date and end_date and start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        filters = [Draw.lottery == lottery, Draw.dataset_kind == dataset_kind]
        if search:
            filters.append(Draw.issue.contains(search, autoescape=True))
        if start_date:
            filters.append(Draw.draw_date >= start_date)
        if end_date:
            filters.append(Draw.draw_date <= end_date)
        total = db.scalar(select(func.count()).select_from(Draw).where(*filters))
        items = db.scalars(
            select(Draw)
            .where(*filters)
            .order_by(Draw.draw_date.desc(), Draw.issue.desc())
            .offset(offset)
            .limit(limit)
        )
        return {"items": [draw.public() for draw in items], "total": total, "offset": offset, "limit": limit}

    @app.get("/api/v1/draws/export")
    def export(db: DB, lottery: Lottery = "ssq", dataset_kind: DatasetKind = "real"):
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "lottery",
                "dataset_kind",
                "issue",
                "draw_date",
                "main_numbers",
                "special_numbers",
                "sales",
                "pool_amount",
                "prizes",
            ]
        )
        for draw in load_draws(db, lottery, dataset_kind):
            writer.writerow(
                [
                    lottery,
                    dataset_kind,
                    draw["issue"],
                    draw["draw_date"],
                    " ".join(f"{n:02d}" for n in draw["main_numbers"]),
                    " ".join(f"{n:02d}" for n in draw["special_numbers"]),
                    draw["sales"],
                    draw["pool_amount"],
                    json.dumps(draw["prizes"]),
                ]
            )
        return Response(
            content="\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="lottolab-{lottery}-{dataset_kind}.csv"'},
        )

    @app.get("/api/v1/draws/{issue}")
    def draw_by_issue(issue: str, db: DB, lottery: Lottery = "ssq", dataset_kind: DatasetKind = "real"):
        draw = db.scalar(
            select(Draw).where(
                Draw.lottery == lottery, Draw.issue == issue, Draw.dataset_kind == dataset_kind
            )
        )
        if not draw:
            raise HTTPException(404, "没有找到该期开奖")
        return draw.public()

    @app.get("/api/v1/overview")
    def overview(db: DB, lottery: Lottery = "ssq", dataset_kind: DatasetKind = "real"):
        rows = load_draws(db, lottery, dataset_kind)
        jobs_count = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.lottery == lottery, Job.dataset_kind == dataset_kind, Job.status == "completed")
        )
        quality_count = db.scalar(
            select(func.count())
            .select_from(QualityIssue)
            .join(IngestionRun)
            .where(
                QualityIssue.lottery == lottery,
                IngestionRun.dataset_kind == dataset_kind,
                QualityIssue.resolution_state == "open",
            )
        )
        return {
            "lottery": lottery,
            "dataset_kind": dataset_kind,
            "total": len(rows),
            "first_date": rows[0]["draw_date"] if rows else None,
            "last_date": rows[-1]["draw_date"] if rows else None,
            "latest": rows[-1] if rows else None,
            "sources": sorted({row["source"] for row in rows}),
            "quality_issues": quality_count,
            "experiments": jobs_count,
            "rule": RULES[lottery].public(),
            "statistics": summarize(rows[-100:], RULES[lottery]),
            "disclaimer": DISCLAIMER,
            "coverage_note": "覆盖范围为本库实际收录时间，不代表全部历史均已收录。",
        }

    @app.get("/api/v1/statistics/frequency")
    @app.get("/api/v1/statistics/omission")
    def statistics(
        db: DB,
        lottery: Lottery = "ssq",
        dataset_kind: DatasetKind = "real",
        window: int = Query(300, ge=10, le=3000),
    ):
        rows = load_draws(db, lottery, dataset_kind)
        return summarize(rows[-window:], RULES[lottery])

    ONLINE_KINDS = {"ssq", "dlt", "qlc", "kl8", "fc3d", "pl3", "pl5", "qxc"}

    def _rows(db: Session, kind: str) -> list[dict]:
        return [
            d.public()
            for d in db.scalars(
                select(Draw)
                .where(Draw.lottery == kind, Draw.dataset_kind == "real")
                .order_by(Draw.draw_date, Draw.issue)
            )
        ]

    def _as_online(kind: str, rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            main = r["main_numbers"]
            spc = r["special_numbers"] or []
            base: dict = {"code": r["issue"], "date": str(r["draw_date"])}
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
            out.append(base)
        return out

    @app.get("/api/v1/bet")
    def bet(kind: str, p: str = "{}"):
        if kind not in ONLINE_KINDS:
            raise HTTPException(400, "未知彩种")
        try:
            params = json.loads(p or "{}")
        except json.JSONDecodeError:
            raise HTTPException(422, "参数 p 须为 JSON") from None
        return calc_bet(kind, params)

    @app.post("/api/v1/verify")
    def verify(db: DB, payload: dict):
        kind = str(payload.get("kind", ""))
        if kind not in ONLINE_KINDS:
            raise HTTPException(400, "未知彩种")
        lines = [str(x) for x in (payload.get("lines") or [])]
        codes = [str(c) for c in (payload.get("codes") or [])]
        if not lines or not codes:
            raise HTTPException(422, "需要 lines 与 codes")
        return verify_batch(kind, _as_online(kind, _rows(db, kind)), lines, codes)

    @app.get("/api/v1/recommend")
    def recommend_ep(db: DB, kind: str = "ssq", seed: int = 1):
        if kind not in ONLINE_KINDS:
            raise HTTPException(400, "未知彩种")
        rows = _as_online(kind, _rows(db, kind))
        if not rows:
            raise HTTPException(404, f"{kind} 暂无可用开奖数据（trunk 尚未收录该彩种，见 B3）")
        return recommend(kind, rows, seed)

    @app.get("/api/v1/ingestions")
    def ingestions(db: DB, lottery: Lottery = "ssq", dataset_kind: DatasetKind = "real"):
        runs = db.scalars(
            select(IngestionRun)
            .where(IngestionRun.lottery == lottery, IngestionRun.dataset_kind == dataset_kind)
            .order_by(IngestionRun.created_at.desc())
            .limit(50)
        )
        return {"items": [run.public() for run in runs]}

    @app.get("/api/v1/quality")
    def quality(db: DB, lottery: Lottery = "ssq", dataset_kind: DatasetKind = "real"):
        issues = db.scalars(
            select(QualityIssue)
            .join(IngestionRun)
            .where(QualityIssue.lottery == lottery, IngestionRun.dataset_kind == dataset_kind)
            .order_by(QualityIssue.created_at.desc())
            .limit(100)
        )
        items = []
        for item in issues:
            existing = db.scalar(select(Draw).where(Draw.lottery == lottery, Draw.issue == item.issue))
            incoming = None
            if item.severity == "conflict":
                try:
                    incoming = DrawInput.model_validate(
                        {**item.raw_record, "lottery": lottery, "dataset_kind": dataset_kind}
                    ).model_dump(mode="json")
                except ValueError:
                    pass
            items.append(
                {
                    "id": item.id,
                    "issue": item.issue,
                    "row": item.row_number,
                    "severity": item.severity,
                    "reason": item.reason,
                    "resolution_state": item.resolution_state,
                    "created_at": item.created_at.isoformat(),
                    "incoming": incoming,
                    "existing": existing.public() if existing else None,
                    "existing_identity_hash": existing.identity_hash if existing else None,
                    "existing_record_hash": digest(existing.public()) if existing else None,
                }
            )
        return {"items": items}

    @app.post("/api/v1/quality/{issue_id}/resolve", dependencies=[Depends(authorize)])
    def resolve_quality(issue_id: str, payload: ResolutionRequest, db: DB):
        with resolution_lock:
            return apply_resolution(issue_id, payload, db)

    def apply_resolution(issue_id: str, payload: ResolutionRequest, db: Session):
        issue = db.get(QualityIssue, issue_id)
        if not issue or issue.resolution_state != "open":
            raise HTTPException(409, "该记录不存在或已经处理，请刷新")
        run = db.get(IngestionRun, issue.ingestion_id)
        existing = db.scalar(
            select(Draw).where(Draw.lottery == issue.lottery, Draw.issue == issue.issue).with_for_update()
        )
        audit = {
            "action": payload.action,
            "resolved_at": now().isoformat(),
            "old": existing.public() if existing else None,
        }
        if payload.action == "accept_incoming":
            if issue.severity != "conflict" or not existing or not run:
                raise ValueError("只有通过校验的冲突记录可以采用；非法行请修正 CSV 后重导入")
            if (
                payload.expected_identity_hash != existing.identity_hash
                or payload.expected_record_hash != digest(existing.public())
            ):
                raise HTTPException(409, "已有记录发生变化，请重新比较后操作")
            draw = DrawInput.model_validate(
                {**issue.raw_record, "lottery": issue.lottery, "dataset_kind": run.dataset_kind}
            )
            values = draw.model_dump(mode="json")
            values["draw_date"] = draw.draw_date
            for field in ("sales", "pool_amount"):
                if values[field] is None:
                    values[field] = getattr(existing, field)
            values["prizes"] = {**existing.prizes, **values["prizes"]}
            values.update(
                identity_hash=digest(draw.identity_payload()), source=run.source, ingestion_id=run.id
            )
            changed = db.execute(
                update(Draw)
                .where(Draw.id == existing.id, Draw.identity_hash == payload.expected_identity_hash)
                .values(**values)
                .returning(Draw.id)
            ).scalar_one_or_none()
            if changed is None:
                db.rollback()
                raise HTTPException(409, "记录被并发修改，请刷新")
            # Record the persisted revision, including financial fields retained
            # from the previous source when the incoming record omits them.
            db.refresh(existing)
            audit["new"] = existing.public()
        changed = db.execute(
            update(QualityIssue)
            .where(QualityIssue.id == issue_id, QualityIssue.resolution_state == "open")
            .values(resolution_state="resolved", resolution=audit)
            .returning(QualityIssue.id)
        ).scalar_one_or_none()
        if changed is None:
            db.rollback()
            raise HTTPException(409, "该问题已被其他请求处理")
        db.commit()
        return {"status": "resolved", "action": payload.action}

    @app.post("/api/v1/imports/csv", dependencies=[Depends(authorize)])
    def import_csv(
        db: DB,
        file: Annotated[UploadFile, File()],
        lottery: Annotated[Lottery, Form()] = "ssq",
        dataset_kind: Annotated[DatasetKind, Form()] = "real",
    ):
        raw = file.file.read(settings.max_csv_bytes + 1)
        if len(raw) > settings.max_csv_bytes:
            raise HTTPException(413, f"CSV 文件不能超过 {settings.max_csv_bytes // (1024 * 1024)} MB")
        records = parse_csv(raw)
        return ingest_records(
            db,
            records,
            lottery=lottery,
            dataset_kind=dataset_kind,
            source="CSV 导入",
            source_url="",
            raw=raw,
            data_dir=settings.data_dir,
            store_in_database=settings.snapshot_storage == "database",
        )

    def enqueue(kind: str, params, db: Session, with_dataset: bool = False):
        with enqueue_lock:
            if db.get_bind().dialect.name == "postgresql":
                # Serialize admission across independent function instances.
                db.execute(text("SELECT pg_advisory_xact_lock(736823615)"))
            if settings.execution_mode == "request":
                expire_interrupted_jobs(db, settings)
            job = create_job(kind, params, db, with_dataset)
        if settings.execution_mode == "request":
            run_request_job(factory, job.id, settings)
            db.refresh(job)
        return job.public()

    def create_job(kind: str, params, db: Session, with_dataset: bool):
        active = db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(["queued", "running"])))
        if (active or 0) >= settings.max_active_jobs:
            raise HTTPException(429, "已有较多任务排队，请等待当前任务完成")
        if with_dataset:
            conflicts = db.scalar(
                select(func.count())
                .select_from(QualityIssue)
                .join(IngestionRun)
                .where(
                    QualityIssue.lottery == params.lottery,
                    IngestionRun.dataset_kind == params.dataset_kind,
                    QualityIssue.severity == "conflict",
                    QualityIssue.resolution_state == "open",
                )
            )
            if conflicts:
                raise ValueError("该数据区存在未复核冲突，请先在质量报告中处理后再运行实验")
        dataset = freeze_dataset(db, params.lottery, params.dataset_kind) if with_dataset else None
        if dataset and kind == "backtest" and dataset.draw_count < 80 + params.test_draws:
            raise ValueError(f"至少需要 {80 + params.test_draws} 期数据，其中 80 期用于初始训练")
        if dataset and kind == "randomness" and dataset.draw_count < 30:
            raise ValueError("随机性检验至少需要 30 期数据")
        job = Job(
            kind=kind,
            lottery=params.lottery,
            dataset_kind=params.dataset_kind,
            params=params.model_dump(mode="json"),
            dataset_id=dataset.id if dataset else None,
        )
        db.add(job)
        db.commit()
        return job

    @app.post("/api/v1/sources/sync", status_code=202, dependencies=[Depends(authorize)])
    def sync(payload: SyncRequest, db: DB):
        return enqueue("sync", payload, db)

    @app.post("/api/v1/datasets/demo", status_code=202, dependencies=[Depends(authorize)])
    def demo(payload: DemoRequest, db: DB):
        return enqueue("demo", payload, db)

    @app.post("/api/v1/statistics/randomness", status_code=202, dependencies=[Depends(authorize)])
    def run_randomness(payload: RandomnessRequest, db: DB):
        return enqueue("randomness", payload, db, True)

    @app.post("/api/v1/backtests", status_code=202, dependencies=[Depends(authorize)])
    def run_backtest(payload: BacktestRequest, db: DB):
        return enqueue("backtest", payload, db, True)

    @app.post("/api/v1/simulations", status_code=202, dependencies=[Depends(authorize)])
    def run_simulation(payload: SimulationRequest, db: DB):
        return enqueue("simulation", payload, db)

    @app.post("/api/v1/optimizations/covering", status_code=202, dependencies=[Depends(authorize)])
    def run_cover(payload: CoverRequest, db: DB):
        return enqueue("covering", payload, db)

    @app.get("/api/v1/jobs")
    def list_jobs(
        db: DB,
        lottery: Lottery = "ssq",
        dataset_kind: DatasetKind = "real",
        kind: str | None = Query(None, max_length=32),
    ):
        if settings.execution_mode == "request":
            expire_interrupted_jobs(db, settings)
            db.commit()
        query = select(Job).where(Job.lottery == lottery, Job.dataset_kind == dataset_kind)
        if kind:
            query = query.where(Job.kind == kind)
        jobs = db.scalars(query.order_by(Job.created_at.desc()).limit(40))
        return {"items": [job.public(False) for job in jobs]}

    @app.get("/api/v1/jobs/{job_id}")
    @app.get("/api/v1/backtests/{job_id}")
    def get_job(job_id: str, db: DB):
        if settings.execution_mode == "request":
            expire_interrupted_jobs(db, settings)
            db.commit()
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(404, "没有找到该任务")
        return job.public()

    @app.post("/api/v1/jobs/{job_id}/cancel", dependencies=[Depends(authorize)])
    def cancel(job_id: str, db: DB):
        result = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(["queued", "running"]))
            .values(status="cancelled", finished_at=now())
            .returning(Job.id)
        ).scalar_one_or_none()
        db.commit()
        if result is None:
            raise HTTPException(409, "任务不存在或已结束")
        return {"status": "cancelled"}

    @app.get("/api/v1/models")
    def model_list():
        from .backtest import MODEL_CATALOG

        return {"items": MODEL_CATALOG, "disclaimer": DISCLAIMER}

    @app.post("/api/v1/strategies/generate", dependencies=[Depends(authorize)])
    def generate(payload: TicketRequest, db: DB):
        from .optimization import generate_tickets

        return generate_tickets(
            RULES[payload.lottery],
            payload.count,
            payload.seed,
            payload.strategy,
            load_draws(db, payload.lottery, payload.dataset_kind),
        )

    if settings.frontend_dir.is_dir():
        assets = settings.frontend_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        def home():
            return FileResponse(settings.frontend_dir / "index.html")

    return app
