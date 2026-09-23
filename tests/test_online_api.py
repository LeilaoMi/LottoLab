"""B1 统一后端在线端点测试：bet / verify / recommend（复用 trunk calc/verify/predict）。"""

from fastapi.testclient import TestClient
from lottolab.app import create_app
from lottolab.config import Settings

CSV = "issue,draw_date,main_numbers,special_numbers\n2026105,2026-09-10,02 04 13 14 15 30,08\n"


def client_for(factory, tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        allow_local_writes=True,
        allowed_hosts="127.0.0.1,testserver",
        admin_token="test-only-token-32-characters-ok",
    )
    return TestClient(
        create_app(settings, factory), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 55000)
    )


def test_online_endpoints(session_factory, tmp_path):
    client = client_for(session_factory, tmp_path)
    # bet 纯计算（不需数据）
    assert client.get('/api/v1/bet?kind=ssq&p={"red":7,"blue":1}').json()["bets"] == 7
    assert client.get('/api/v1/bet?kind=dlt&p={"front":6,"back":3}').json()["amount"] == 36
    assert client.get("/api/v1/bet?kind=nope").status_code == 400
    assert client.get("/api/v1/bet?kind=ssq&p=notjson").status_code == 422
    # 无数据 → recommend 404（B3 前小彩种无 trunk 数据）
    assert client.get("/api/v1/recommend?kind=fc3d").status_code == 404
    seed = client.post(
        "/api/v1/imports/csv",
        files={"file": ("d.csv", CSV, "text/csv")},
        data={"lottery": "ssq", "dataset_kind": "real"},
    )
    assert seed.status_code == 200, seed.text
    rec = client.get("/api/v1/recommend?kind=ssq&seed=5")
    assert rec.status_code == 200, rec.text
    body = rec.json()
    assert len(body["main"]) == 6 and len(set(body["main"])) == 6 and len(body["aux"]) == 1
    assert client.get("/api/v1/recommend?kind=ssq&seed=5").json() == body  # 同 seed 确定
    ver = client.post(
        "/api/v1/verify", json={"kind": "ssq", "lines": ["02 04 13 14 15 30 + 08"], "codes": ["2026105"]}
    )
    assert ver.status_code == 200, ver.text
    assert ver.json()["total"]["won"] == 1
    assert client.post("/api/v1/verify", json={"kind": "ssq", "lines": [], "codes": []}).status_code == 422
    get_ver = client.get(
        "/api/v1/verify",
        params={"kind": "ssq", "lines": "02 04 13 14 15 30 + 08", "codes": "2026105"},
    )
    assert get_ver.status_code == 200, get_ver.text
    assert get_ver.json() == ver.json()
    assert client.get("/api/v1/verify", params={"kind": "nope"}).status_code == 400
    assert client.get("/api/v1/verify", params={"kind": "ssq"}).status_code == 422
