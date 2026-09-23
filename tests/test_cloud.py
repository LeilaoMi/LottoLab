import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from lottolab import worker
from lottolab.app import create_app
from lottolab.cloud import postgres_url, vercel_settings
from lottolab.config import Settings
from lottolab.db import Job, RawSnapshot, make_engine, make_session_factory, now
from lottolab.snapshots import snapshot_bytes
from sqlalchemy import func, select, update

TOKEN = "isolated-cloud-test-token-32-characters"


def cloud_env():
    return {
        "LOTTOLAB_DATABASE_URL": "postgresql://tester:fixture-password@db.example/lottolab",
        "LOTTOLAB_ADMIN_TOKEN": TOKEN,
        "VERCEL_URL": "preview.example",
        "VERCEL_PROJECT_PRODUCTION_URL": "lab.example",
    }


def cloud_client(factory, tmp_path, **overrides):
    settings = Settings(
        _env_file=None,
        **{
            "database_url": factory.kw["bind"].url.render_as_string(hide_password=False),
            "data_dir": tmp_path,
            "admin_token": TOKEN,
            "allowed_hosts": "lab.example",
            "allowed_origins": "https://lab.example",
            "execution_mode": "request",
            "snapshot_storage": "database",
            "allow_local_writes": False,
            "require_read_auth": True,
            "job_timeout_seconds": 30,
            "max_active_jobs": 1,
            **overrides,
        },
    )
    return TestClient(create_app(settings, factory), base_url="https://lab.example"), settings


def queued_job(factory, **overrides):
    with factory() as db:
        job = Job(
            **{
                "kind": "simulation",
                "lottery": "ssq",
                "dataset_kind": "real",
                "params": {"lottery": "ssq", "iterations": 1000},
                **overrides,
            }
        )
        db.add(job)
        db.commit()
        return job.id


def test_cloud_config_defaults_to_public_when_admin_token_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("LOTTOLAB_ALLOW_LOCAL_WRITES=true\n", encoding="utf-8")
    env = {**cloud_env(), "LOTTOLAB_ALLOW_LOCAL_WRITES": "true"}
    env.pop("LOTTOLAB_ADMIN_TOKEN", None)
    settings = vercel_settings(env)
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in settings.database_url
    assert not settings.allow_local_writes
    assert not settings.require_read_auth
    assert settings.public_mode
    assert settings.admin_token == ""
    assert settings.execution_mode == "request"
    assert settings.snapshot_storage == "database"
    assert settings.max_active_jobs == 1
    assert settings.job_timeout_seconds == 240
    assert set(settings.origins) == {"https://lab.example", "https://preview.example"}
    assert settings.max_csv_bytes == 4 * 1024 * 1024


def test_cloud_config_switches_to_private_write_with_admin_token(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("LOTTOLAB_ALLOW_LOCAL_WRITES=true\n", encoding="utf-8")
    settings = vercel_settings({**cloud_env(), "LOTTOLAB_ALLOW_LOCAL_WRITES": "true"})
    assert not settings.allow_local_writes
    assert not settings.require_read_auth
    assert not settings.public_mode
    assert settings.admin_token == TOKEN
    assert settings.execution_mode == "request"
    assert settings.max_active_jobs == 1


def test_cloud_config_rejects_short_admin_token():
    with pytest.raises(ValueError, match="不足 32"):
        vercel_settings({**cloud_env(), "LOTTOLAB_ADMIN_TOKEN": "too-short"})


@pytest.mark.parametrize(
    "key,value",
    [
        ("LOTTOLAB_DATABASE_URL", ""),
        ("LOTTOLAB_DATABASE_URL", "sqlite:///.local/cloud.db"),
        ("LOTTOLAB_DATABASE_URL", "postgresql://user:fixture-secret@localhost/cloud"),
        ("LOTTOLAB_DATABASE_URL", "postgresql://user:fixture-secret@db.example/cloud?sslmode=disable"),
        ("LOTTOLAB_ALLOWED_HOSTS", "*"),
        ("LOTTOLAB_ALLOWED_ORIGINS", "http://insecure.example"),
        ("LOTTOLAB_JOB_TIMEOUT_SECONDS", "300"),
    ],
)
def test_cloud_config_rejects_unsafe_values_without_echoing_credentials(key, value):
    with pytest.raises(ValueError) as error:
        vercel_settings({**cloud_env(), key: value})
    assert "fixture-secret" not in str(error.value)


def test_neon_url_normalization_preserves_escaped_password():
    from sqlalchemy.engine import make_url

    url = make_url(postgres_url("postgres://user:abc%40def%25@db.example/lab?sslmode=require"))
    assert url.password == "abc@def%"
    assert url.drivername == "postgresql+psycopg"


def test_private_api_protects_reads_exports_and_compute(session_factory, tmp_path):
    client, _ = cloud_client(session_factory, tmp_path)
    health = client.get("/api/v1/health").json()
    assert health["worker_ready"] and health["execution_mode"] == "request"
    assert not health["can_read"] and not health["can_write"]
    for path in ("/overview", "/draws", "/draws/export", "/jobs", "/ingestions", "/quality"):
        response = client.get("/api/v1" + path)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
    assert client.post("/api/v1/simulations", json={"iterations": 1000}).status_code == 403
    assert client.get("/api/v1/models").status_code == 200
    headers = {"X-Admin-Token": TOKEN}
    assert client.get("/api/v1/overview", headers=headers).status_code == 200
    assert client.get("/api/v1/health", headers=headers).json()["can_read"]
    assert (
        client.get("/api/v1/draws", headers={**headers, "Origin": "https://untrusted.example"}).status_code
        == 403
    )


def test_request_jobs_and_raw_data_survive_new_app_without_worker_or_raw_files(session_factory, tmp_path):
    client, settings = cloud_client(session_factory, tmp_path)
    headers = {"X-Admin-Token": TOKEN}
    result = client.post("/api/v1/simulations", json={"iterations": 1000}, headers=headers)
    assert result.status_code == 202, result.text
    job = result.json()
    assert job["status"] == "completed" and job["result"]["iterations"] == 1000
    imported = client.post("/api/v1/datasets/demo", json={"count": 100}, headers=headers).json()
    assert imported["status"] == "completed", imported
    assert imported["result"]["accepted"] == 100
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "worker.heartbeat").exists()
    engine = make_engine(settings.database_url, pooled=False)
    try:
        other = make_session_factory(engine)
        restarted, _ = cloud_client(other, tmp_path / "different-machine")
        saved = restarted.get(f"/api/v1/jobs/{job['id']}", headers=headers).json()
        assert saved["result"] == job["result"]
        assert restarted.get("/api/v1/draws?dataset_kind=synthetic", headers=headers).json()["total"] == 100
        with other() as db:
            snapshot = db.scalar(select(RawSnapshot))
            assert b"SIM-" in snapshot_bytes(snapshot)
    finally:
        engine.dispose()


def test_request_claim_is_specific_and_does_not_repeat_completed_job(session_factory, tmp_path):
    _, settings = cloud_client(session_factory, tmp_path)
    first, second = queued_job(session_factory), queued_job(session_factory)
    worker.run_request_job(session_factory, second, settings)
    assert worker.claim_job(session_factory, requested_id=second) is None
    with session_factory() as db:
        assert db.get(Job, first).status == "queued"
        assert db.get(Job, second).status == "completed"


@pytest.mark.parametrize("cancel", [False, True])
def test_request_execution_stops_child_on_timeout_or_cancellation(
    session_factory, tmp_path, monkeypatch, cancel
):
    _, settings = cloud_client(session_factory, tmp_path, job_timeout_seconds=10 if cancel else 1)
    children = []

    def slow_child(_job_id, _settings_data):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(20)"],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        children.append(child)
        return child

    monkeypatch.setattr(worker, "start_job_process", slow_child)
    job_id = queued_job(session_factory)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(worker.run_request_job, session_factory, job_id, settings)
        if cancel:
            for _ in range(100):
                with session_factory() as db:
                    if db.get(Job, job_id).status == "running":
                        db.execute(
                            update(Job).where(Job.id == job_id).values(status="cancelled", finished_at=now())
                        )
                        db.commit()
                        break
                time.sleep(0.02)
            else:
                pytest.fail("Job was not claimed")
        future.result(timeout=12)
    assert time.monotonic() - started < 12
    assert len(children) == 1 and children[0].poll() is not None
    with session_factory() as db:
        job = db.get(Job, job_id)
        assert job.status == ("cancelled" if cancel else "failed")
        assert job.finished_at is not None and job.result is None
        if not cancel:
            assert "1 秒运行上限" in job.error


def test_stale_invocations_recover_and_admission_limit_remains_effective(session_factory, tmp_path):
    client, _ = cloud_client(session_factory, tmp_path)
    headers = {"X-Admin-Token": TOKEN}
    old = now() - timedelta(minutes=10)
    queued = queued_job(session_factory, created_at=old)
    running = queued_job(session_factory, status="running", started_at=old)
    active = queued_job(session_factory, status="running", started_at=now())
    response = client.post("/api/v1/simulations", json={"iterations": 1000}, headers=headers)
    assert response.status_code == 429
    items = client.get("/api/v1/jobs", headers=headers).json()["items"]
    states = {job["id"]: job["status"] for job in items}
    assert states == {queued: "failed", running: "failed", active: "running"}
    assert client.post(f"/api/v1/jobs/{active}/cancel", headers=headers).status_code == 200
    assert (
        client.post("/api/v1/simulations", json={"iterations": 1000}, headers=headers).json()["status"]
        == "completed"
    )


def test_cloud_csv_limit_is_enforced_before_import(session_factory, tmp_path):
    client, _ = cloud_client(session_factory, tmp_path, max_csv_bytes=1024)
    response = client.post(
        "/api/v1/imports/csv",
        headers={"X-Admin-Token": TOKEN},
        files={"file": ("too-large.csv", b"x" * 1025, "text/csv")},
    )
    assert response.status_code == 413
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(RawSnapshot)) == 0
