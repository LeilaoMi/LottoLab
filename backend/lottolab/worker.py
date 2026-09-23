"""Single-job child processes keep CPU work outside the HTTP server."""

import json
import logging
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import DatasetVersion, Job, make_engine, make_session_factory, now
from .domain import RULES
from .provenance import execution_metadata
from .schemas import (
    BacktestRequest,
    CoverRequest,
    DemoRequest,
    RandomnessRequest,
    SimulationRequest,
    SyncRequest,
)

logger = logging.getLogger("lottolab.worker")


def perform_job(job_id: str, settings_data: dict):
    settings = Settings.model_validate(settings_data)
    engine = make_engine(settings.database_url, pooled=settings.execution_mode == "worker")
    factory = make_session_factory(engine)

    def progress(value):
        with factory() as db:
            db.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(progress=value))
            db.commit()

    try:
        with factory() as db:
            job = db.get(Job, job_id)
            if not job or job.status != "running":
                return
            kind, payload = job.kind, job.params
            dataset = db.get(DatasetVersion, job.dataset_id) if job.dataset_id else None
            draws = dataset.draws if dataset else []
        rule = RULES[payload["lottery"]]
        execution = execution_metadata(rule.version)
        config: (
            SyncRequest | DemoRequest | RandomnessRequest | BacktestRequest | SimulationRequest | CoverRequest
        )
        if kind == "sync":
            from .ingestion import ingest_records
            from .sources import fetch_source

            config = SyncRequest.model_validate(payload)
            batches, warnings = fetch_source(config.lottery, config.count, settings.source_timeout_seconds)
            runs = []
            for index, batch in enumerate(batches):
                with factory() as db:
                    runs.append(
                        ingest_records(
                            db,
                            batch.records,
                            lottery=config.lottery,
                            dataset_kind="real",
                            source=batch.source,
                            source_url=batch.url,
                            raw=batch.raw,
                            data_dir=settings.data_dir,
                            store_in_database=settings.snapshot_storage == "database",
                        )
                    )
                progress(int(95 * (index + 1) / len(batches)))
            result = {
                "runs": runs,
                "warnings": warnings,
                "source_reported_total": batches[0].reported_total,
                **{
                    key: sum(run[key] for run in runs)
                    for key in ("received", "accepted", "duplicates", "rejected", "conflicts")
                },
            }
        elif kind == "demo":
            from .ingestion import canonical, ingest_records, synthetic_records

            config = DemoRequest.model_validate(payload)
            records = synthetic_records(config.lottery, config.count, config.seed)
            with factory() as db:
                result = ingest_records(
                    db,
                    records,
                    lottery=config.lottery,
                    dataset_kind="synthetic",
                    source="均匀随机演示数据",
                    source_url=f"synthetic://seed/{config.seed}",
                    raw=canonical(records),
                    data_dir=settings.data_dir,
                    store_in_database=settings.snapshot_storage == "database",
                )
        elif kind == "randomness":
            from .analysis import randomness

            config = RandomnessRequest.model_validate(payload)
            result = randomness(draws[-config.window :], rule, trials=config.trials, seed=config.seed)
        elif kind == "backtest":
            from .backtest import run_backtest

            config = BacktestRequest.model_validate(payload)
            result = run_backtest(draws, rule, config, progress)
        elif kind == "simulation":
            from .analysis import simulate

            config = SimulationRequest.model_validate(payload)
            result = simulate(rule, config.iterations, config.seed)
        elif kind == "covering":
            from .optimization import optimize_cover

            config = CoverRequest.model_validate(payload)
            result = optimize_cover(
                rule,
                config.candidate_numbers,
                config.ticket_count,
                config.target_hits,
                config.seed,
                config.samples,
                progress,
            )
        else:
            raise ValueError("未知任务类型")
        result["execution"] = execution
        with factory() as db:
            db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(status="completed", result=result, progress=100, finished_at=now())
            )
            db.commit()
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        # 对外只暴露可安全展示的信息；完整堆栈仅进服务端日志
        if isinstance(exc, ValueError):
            public_error = str(exc)[:400]
        else:
            public_error = f"任务执行失败（{type(exc).__name__}），详情见服务端日志"
        with factory() as db:
            db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(status="failed", error=public_error, finished_at=now())
            )
            db.commit()
    finally:
        engine.dispose()


def claim_job(factory, requested_id: str | None = None) -> str | None:
    with factory() as db:
        job_id = requested_id or db.scalar(
            select(Job.id).where(Job.status == "queued").order_by(Job.created_at).limit(1)
        )
        if not job_id:
            return None
        claimed = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", started_at=now(), progress=1)
            .returning(Job.id)
        ).scalar_one_or_none()
        db.commit()
        return claimed


def expire_interrupted_jobs(db: Session, settings: Settings) -> None:
    """Recover abandoned invocations on the next authorized request or worker tick."""
    cutoff = now() - timedelta(seconds=settings.job_timeout_seconds + 30)
    stale = and_(Job.status == "running", Job.started_at < cutoff)
    if settings.execution_mode == "request":
        stale = or_(stale, and_(Job.status == "queued", Job.created_at < cutoff))
    db.execute(
        update(Job)
        .where(stale)
        .values(status="failed", error="任务超时或执行进程中断，请重新提交", finished_at=now())
    )


def start_job_process(job_id: str, settings_data: dict) -> subprocess.Popen:
    """Start only the calculator, without re-importing a hosting runtime's __main__."""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("job_process.py"))],
        stdin=subprocess.PIPE,
        creationflags=creationflags,
    )
    try:
        assert child.stdin is not None
        # Credentials travel over a private pipe, never in process arguments. Vercel
        # installs some dependencies at runtime; preserve their resolved import paths.
        child.stdin.write(
            json.dumps({"job_id": job_id, "settings": settings_data, "python_path": sys.path}).encode("utf-8")
        )
        child.stdin.close()
    except Exception:
        child.kill()
        child.wait(timeout=5)
        raise
    return child


def run_claimed_job(factory, job_id: str, settings: Settings, heartbeat: Path | None = None) -> None:
    """Wait for one bounded child; never leave work running after the request returns."""
    settings_data = settings.model_dump(mode="json")
    settings_data["admin_token"] = ""
    child = None
    failure = "工作进程退出，任务未完成，请重试"
    started = time.monotonic()
    try:
        child = start_job_process(job_id, settings_data)
        next_status_check = started
        while child.poll() is None:
            try:
                child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
            if heartbeat is not None:
                heartbeat.touch()
            current_time = time.monotonic()
            if current_time - started >= settings.job_timeout_seconds:
                failure = f"任务达到 {settings.job_timeout_seconds} 秒运行上限，请减少规模后重试"
                break
            if current_time >= next_status_check:
                with factory() as db:
                    status = db.scalar(select(Job.status).where(Job.id == job_id))
                if status != "running":
                    break
                next_status_check = current_time + 2
    except Exception:
        logger.exception("Unable to supervise job %s", job_id)
        failure = "任务执行进程异常，请重试"
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
        with factory() as db:
            db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(status="failed", error=failure, finished_at=now())
            )
            db.commit()


def run_request_job(factory, job_id: str, settings: Settings) -> None:
    if claim_job(factory, requested_id=job_id):
        run_claimed_job(factory, job_id, settings)


def run_worker(once: bool = False):
    settings = get_settings()
    if settings.execution_mode != "worker":
        raise ValueError("请求执行模式不需要常驻 worker，请通过应用提交任务")
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    try:
        while True:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            heartbeat = settings.data_dir / "worker.heartbeat"
            heartbeat.touch()
            with factory() as db:
                expire_interrupted_jobs(db, settings)
                db.commit()
            job_id = claim_job(factory)
            if not job_id:
                if once:
                    return
                time.sleep(settings.poll_seconds)
                continue
            run_claimed_job(factory, job_id, settings, heartbeat)
            if once:
                return
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
