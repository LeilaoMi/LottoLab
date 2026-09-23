"""应用层 POST 限流：按 IP 滑动窗口，超限 429。"""

from fastapi.testclient import TestClient
from lottolab.app import create_app
from lottolab.config import Settings
from lottolab.ratelimit import PostRateLimiter


def client_for(factory, tmp_path, per_minute):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        allow_local_writes=True,
        allowed_hosts="127.0.0.1,testserver",
        admin_token="test-only-token-32-characters-ok",
        rate_limit_posts_per_minute=per_minute,
    )
    return TestClient(
        create_app(settings, factory), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 55000)
    )


def test_post_rate_limit_blocks_after_budget(session_factory, tmp_path):
    client = client_for(session_factory, tmp_path, 2)
    assert client.post("/api/v1/no-such-route").status_code == 404
    assert client.post("/api/v1/no-such-route").status_code == 404
    limited = client.post("/api/v1/no-such-route")
    assert limited.status_code == 429
    assert "频繁" in limited.json()["detail"]


def test_post_rate_limit_keys_by_forwarded_ip(session_factory, tmp_path):
    client = client_for(session_factory, tmp_path, 1)
    headers = {"X-Forwarded-For": "203.0.113.7"}
    assert client.post("/api/v1/no-such-route", headers=headers).status_code == 404
    assert client.post("/api/v1/no-such-route", headers=headers).status_code == 429
    other = {"X-Forwarded-For": "203.0.113.8"}
    assert client.post("/api/v1/no-such-route", headers=other).status_code == 404


def test_post_rate_limit_disabled_at_zero(session_factory, tmp_path):
    client = client_for(session_factory, tmp_path, 0)
    for _ in range(5):
        assert client.post("/api/v1/no-such-route").status_code == 404


def test_post_rate_limit_does_not_touch_get(session_factory, tmp_path):
    client = client_for(session_factory, tmp_path, 1)
    assert client.get("/api/v1/no-such-route").status_code == 404
    assert client.get("/api/v1/no-such-route").status_code == 404


def test_post_rate_limit_keys_by_client_ip_not_forwarded_leftmost_spoof(session_factory, tmp_path):
    """非受信直连忽略伪造 XFF：预算按对端 IP；失败鉴权也计次。"""
    client = TestClient(
        _settings_app(session_factory, tmp_path, 1),
        base_url="http://127.0.0.1:8000",
        client=("203.0.113.50", 55000),
    )
    spoof = {"X-Forwarded-For": "1.2.3.4"}
    # 非回环 → 无本地写权限，先计限流再 403
    assert client.post("/api/v1/no-such-route", headers=spoof).status_code == 403
    assert client.post("/api/v1/no-such-route", headers=spoof).status_code == 429


def _settings_app(factory, tmp_path, per_minute, **extra):
    from lottolab.app import create_app

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        allow_local_writes=True,
        allowed_hosts="127.0.0.1,testserver",
        admin_token="test-only-token-32-characters-ok",
        rate_limit_posts_per_minute=per_minute,
        **extra,
    )
    return create_app(settings, factory)


def test_limiter_unit_slides_window():
    limiter = PostRateLimiter(2)
    assert limiter.allowed("k", now=0.0)
    assert limiter.allowed("k", now=1.0)
    assert not limiter.allowed("k", now=2.0)
    assert limiter.allowed("k", now=61.0)
    disabled = PostRateLimiter(0)
    assert disabled.allowed("k") and disabled.allowed("k")
