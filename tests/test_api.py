from fastapi.testclient import TestClient
from lottolab import __version__
from lottolab.app import create_app
from lottolab.config import Settings
from lottolab.db import Job
from lottolab.ingestion import canonical, ingest_records, synthetic_records
from lottolab.worker import claim_job, perform_job
from sqlalchemy import select


def client_for(factory, tmp_path, *, local=True, host="127.0.0.1"):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        allow_local_writes=local,
        allowed_hosts="127.0.0.1,testserver",
        admin_token="test-only-token-32-characters-ok",
    )
    app = create_app(settings, factory)
    return TestClient(app, base_url="http://127.0.0.1:8000", client=(host, 55000)), settings


def test_authentication_origin_and_forwarded_ip(session_factory, tmp_path):
    client, _ = client_for(session_factory, tmp_path, host="203.0.113.2")
    body = {"lottery": "ssq", "iterations": 1000}
    assert client.post("/api/v1/simulations", json=body).status_code == 403
    assert (
        client.post("/api/v1/simulations", json=body, headers={"X-Forwarded-For": "127.0.0.1"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/simulations",
            json=body,
            headers={"X-Admin-Token": "test-only-token-32-characters-ok"},
        ).status_code
        == 202
    )
    local, _ = client_for(session_factory, tmp_path)
    assert (
        local.post(
            "/api/v1/simulations", json=body, headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )


def test_csv_api_pagination_and_errors(session_factory, tmp_path):
    client, _ = client_for(session_factory, tmp_path)
    content = "issue,draw_date,main_numbers,special_numbers\n2026105,2026-09-10,02 04 13 14 15 30,08\n"
    response = client.post(
        "/api/v1/imports/csv",
        files={"file": ("draws.csv", content, "text/csv")},
        data={"lottery": "ssq", "dataset_kind": "real"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 1
    assert client.get("/api/v1/draws?search=2026105&limit=1").json()["total"] == 1
    assert client.get("/api/v1/draws?lottery=dlt").json()["total"] == 0
    assert client.get("/api/v1/draws?limit=50000").status_code == 422
    assert client.get("/api/v1/draws?start_date=2026-09-10&end_date=2026-09-01").status_code == 422
    assert client.get("/api/v1/draws/2099001").status_code == 404
    assert "2026105" in client.get("/api/v1/draws/export").text


def test_job_queue_claim_cancellation_and_real_worker(session_factory, tmp_path):
    client, settings = client_for(session_factory, tmp_path)
    result = client.post("/api/v1/simulations", json={"iterations": 1000}).json()
    job_id = result["id"]
    assert claim_job(session_factory) == job_id
    assert claim_job(session_factory) is None
    settings.database_url = str(session_factory.kw["bind"].url)
    perform_job(job_id, settings.model_dump(mode="json"))
    done = client.get(f"/api/v1/jobs/{job_id}").json()
    assert done["status"] == "completed"
    assert done["result"]["iterations"] == 1000
    assert len(done["result"]["execution"]["code_fingerprint"]) == 64
    assert done["result"]["execution"]["rule_version"] == "ssq-number-space-v1"
    assert done["result"]["execution"]["packages"]["lottolab"] == __version__
    second = client.post("/api/v1/simulations", json={"iterations": 1000}).json()
    assert client.post(f"/api/v1/jobs/{second['id']}/cancel").status_code == 200
    assert claim_job(session_factory) is None
    assert client.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 409


def test_backtest_freezes_dataset_and_requires_history(session_factory, tmp_path):
    client, _ = client_for(session_factory, tmp_path)
    assert client.post("/api/v1/backtests", json={"test_draws": 20}).status_code == 422
    records = synthetic_records("ssq", 120, 8)
    with session_factory() as db:
        ingest_records(
            db,
            records,
            lottery="ssq",
            dataset_kind="synthetic",
            source="fixture",
            source_url="synthetic://8",
            raw=canonical(records),
            data_dir=tmp_path,
        )
    response = client.post(
        "/api/v1/backtests", json={"dataset_kind": "synthetic", "test_draws": 20, "models": ["uniform"]}
    )
    assert response.status_code == 202
    with session_factory() as db:
        job = db.scalar(select(Job).where(Job.id == response.json()["id"]))
        assert len(job.dataset_id) == 64
