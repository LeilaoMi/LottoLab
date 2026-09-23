"""盲区回归：QLC 计分一致性、DIGIT simulate、数据源路由、seed 策略敏感性、kl8 票合法性、体积限制。"""

import random
from datetime import date
from math import isclose

import pytest
from lottolab.analysis import simulate
from lottolab.config import Settings
from lottolab.db import Draw, PredictionLog
from lottolab.domain import RULES, qlc_prize_tier
from lottolab.predict import _rank_pick, _zone_cover, backtest_strategies, recommend_multi
from lottolab.review import _score, review_summary
from lottolab.sources import source_route
from lottolab.verify import parse_ticket, score_ticket

# ---------- A3: 七乐彩计分 verify / review 一致 ----------


def test_qlc_verify_six_plus_special_is_tier2():
    # 官方：6 基本 + 特别号命中 → 二等；特别号是第 8 摇出号，票面只有 7 个基本号
    draw = {"main": [1, 2, 3, 4, 5, 6, 7], "special": 8}
    t = parse_ticket("qlc", "01 02 03 04 05 06 + 08")  # 票面含特别号写法兼容
    # 若 SPEC 要求 aux，则用带 + 的；若不要求，纯 7 号也应可解析
    if "error" in t:
        t = parse_ticket("qlc", "01 02 03 04 05 06 09")
        assert "error" not in t
        # 票面 6 个基本命中 + 第 7 个号恰为特别号
        t2 = parse_ticket("qlc", "01 02 03 04 05 06 08")
        r = score_ticket("qlc", t2, draw)
    else:
        r = score_ticket("qlc", t, draw)
    assert r["tier"] == "2" and r["grade"] == "二等奖"


def test_qlc_review_matches_verify_semantics():
    # review 对 QLC：特别号命中 = 开奖特别号 ∈ 预测主区（推荐 aux 为空）
    pred = PredictionLog(kind="qlc", main_numbers=[1, 2, 3, 4, 5, 6, 8], special_numbers=[])
    draw = Draw(
        lottery="qlc",
        issue="x",
        draw_date=date(2026, 1, 1),
        main_numbers=[1, 2, 3, 4, 5, 6, 7],
        special_numbers=[8],
    )
    hit_main, hit_special, prize = _score("qlc", pred, draw)
    assert hit_main == 6
    assert hit_special == 1  # 特别号 8 在预测主区中
    assert prize == "2"  # 6+特别 → 二等，而非三等


def test_qlc_prize_tier_golden_alignment():
    assert qlc_prize_tier(6, 1) == "2"
    assert qlc_prize_tier(6, 0) == "3"
    assert qlc_prize_tier(7, 0) == "1"


# ---------- A2: DIGIT simulate ----------


def test_simulate_digit_expected_and_jackpot_consistent():
    rule = RULES["fc3d"]
    result = simulate(rule, 100000, 7)
    # 按位均匀：期望命中 = 位数/10 = 0.3（不是 main_count²/main_max = 1）
    assert isclose(result["expected_hits"], 0.3, rel_tol=0.05)
    assert isclose(result["mean_hits"], 0.3, abs_tol=0.02)
    # 头奖观测频率应与 jackpot_probability 同量级（1/1000），容许统计波动
    observed = result["jackpots"] / result["iterations"]
    assert observed == pytest.approx(result["jackpot_probability"], rel=0.5)
    assert result["jackpot_probability"] == pytest.approx(1 / 1000)


def test_simulate_digit_distribution_sums_to_iterations():
    result = simulate(RULES["pl3"], 10000, 3)
    assert sum(row["count"] for row in result["distribution"]) == 10000
    # 数字型分布 hits ∈ 0..位数
    assert all(0 <= row["hits"] <= 3 for row in result["distribution"])


# ---------- A6: 数据源路由 ----------


def test_source_route_covers_all_eight():
    expected = {
        "ssq": ("cwl", "ssq"),
        "qlc": ("cwl", "qlc"),
        "kl8": ("cwl", "kl8"),
        "fc3d": ("cwl", "3d"),
        "dlt": ("sporttery", "85"),
        "pl3": ("sporttery", "35"),
        "pl5": ("sporttery", "350133"),
        "qxc": ("sporttery", "04"),
    }
    for kind, (provider, ident) in expected.items():
        route = source_route(kind)
        assert route["provider"] == provider, kind
        assert route["ident"] == ident, kind


def test_source_route_not_all_game85():
    """来源路由必须按彩种分流——修复前 8 彩种全部 gameNo=85（实为大乐透）。"""
    assert source_route("qlc")["ident"] != "85"
    assert source_route("fc3d")["provider"] == "cwl"
    assert source_route("kl8")["ident"] == "kl8"
    assert source_route("pl3")["ident"] == "35"
    assert source_route("pl5")["ident"] == "350133"
    assert source_route("qxc")["ident"] == "04"


def test_collector_cwl_kl8_and_fc3d_parsers():
    from collector.parsers import parse_cwl

    kl8 = parse_cwl(
        '{"state":0,"result":[{"code":"2026100","date":"2026-09-20","red":"01,02,03,04,05,06,07,08,09,10,11,12,13,14,15,16,17,18,19,20","blue":""}]}',
        "kl8",
    )[0]
    assert len(kl8["main"]) == 20 and kl8["special"] == []
    fc3d = parse_cwl(
        '{"state":0,"result":[{"code":"2026100","date":"2026-09-20","red":"0,5,1","blue":""}]}',
        "fc3d",
    )[0]
    assert fc3d["main"] == [0, 5, 1]


def test_collector_sporttery_digit_families():
    from collector.parsers import parse_sporttery

    payload = (
        '{"success":true,"value":{"list":[{"lotteryDrawNum":"26100",'
        '"lotteryDrawTime":"2026-09-20 21:00:00","lotteryDrawResult":"1 2 3"}]}}'
    )
    assert parse_sporttery(payload, "pl3")[0]["main"] == [1, 2, 3]
    payload5 = (
        '{"success":true,"value":{"list":[{"lotteryDrawNum":"26100",'
        '"lotteryDrawTime":"2026-09-20 21:00:00","lotteryDrawResult":"1 2 3 4 5"}]}}'
    )
    assert parse_sporttery(payload5, "pl5")[0]["main"] == [1, 2, 3, 4, 5]
    payload_qxc = (
        '{"success":true,"value":{"list":[{"lotteryDrawNum":"26100",'
        '"lotteryDrawTime":"2026-09-20 21:00:00","lotteryDrawResult":"1 2 3 4 5 6 7"}]}}'
    )
    assert parse_sporttery(payload_qxc, "qxc")[0]["main"] == [1, 2, 3, 4, 5, 6, 7]


# ---------- A7: 策略 seed 敏感性（按策略而非整体） ----------


def test_rank_pick_respects_seed_on_ties():
    """_rank_pick 对并列候选应消费 rng 破平局；当前实现 (i, rng.random()) 中 i 唯一 → rng 死码。"""
    import inspect

    from lottolab import predict as predict_module

    body = inspect.getsource(predict_module._rank_pick)
    # 回归锚：修复前 keyed=(i, rng.random(), v) 按 (i, rng) 排序，i 唯一 → rng 永不生效
    assert "rng" in body
    # 行为：全同优先级输入下，不同 seed 应可选不同子集
    # 用“无序候选全并列”模拟：ordered 打乱后按位置取，seed 破平局
    tied = list(range(1, 34))
    picks = {tuple(_rank_pick(random.Random(s), tied, 6)) for s in range(10)}
    # 位置优先级固定时结果可相同；关键是 rng 被调用——用 mock 计数
    from unittest.mock import patch

    calls = []
    rng = random.Random(0)
    orig = rng.random

    def counting():
        calls.append(1)
        return orig()

    with patch.object(rng, "random", counting):
        _rank_pick(rng, tied, 6)
    assert calls, "_rank_pick 未调用 rng.random（seeded 破平局承诺落空）"
    assert picks  # 冒烟


def test_zone_cover_consumes_rng():
    """_zone_cover 必须消费 rng：并列频率下不同 seed 应可产生不同票。"""
    import inspect

    from lottolab import predict as predict_module

    body = inspect.getsource(predict_module._zone_cover)
    assert "rng." in body, "_zone_cover 未使用 rng 参数（死随机数回归）"
    freq = {v: 1 for v in range(1, 34)}  # 全并列 → 完全依赖 rng 破平局
    results = {tuple(_zone_cover(random.Random(s), "ssq", freq)) for s in range(5)}
    assert len(results) > 1, "全并列频率下换 seed 结果应变化"


def test_recommend_multi_strategy_seed_sensitivity():
    draws = [
        {"red": [6, 11, 13, 14, 22, 30], "blue": 14},
        {"red": [2, 4, 13, 14, 15, 30], "blue": 8},
        {"red": [11, 12, 13, 19, 20, 31], "blue": 3},
    ] * 10
    a = recommend_multi("ssq", draws, seed=1, groups=7)
    b = recommend_multi("ssq", draws, seed=2, groups=7)
    # 「冷热加权」「随机基准」必须随 seed 变；「区间覆盖」修复后也应变
    by_name_a = {p["name"]: p for p in a["picks"]}
    by_name_b = {p["name"]: p for p in b["picks"]}
    assert by_name_a["随机基准"]["main"] != by_name_b["随机基准"]["main"]
    assert by_name_a["冷热加权"]["main"] != by_name_b["冷热加权"]["main"]
    # 区间覆盖在频率有并列时应可能变化（死 rng 回归）
    # 不强制必须不同（取决于并列结构），但 _zone_cover 不得忽略 rng 参数


# ---------- A4/A5: kl8 回测票与复盘基线 ----------


def test_kl8_backtest_tickets_parseable():
    import random as _r

    r = _r.Random(1)
    rows = []
    for i in range(150):
        rows.append({"code": f"2025{i:03d}", "nums": sorted(r.sample(range(1, 81), 20))})
    backtest_strategies("kl8", rows, window=50)
    # 回测产出的票面应能被验奖引擎接受（1..10 个号）
    # 注：回测记录在 strategies 命中分布中体现；此处验证推荐路径票面
    multi = recommend_multi("kl8", rows, seed=1, groups=7)
    for p in multi["picks"]:
        line = " ".join(p["main"])
        parsed = parse_ticket("kl8", line)
        assert "error" not in parsed, f"{p['name']}: {parsed}"
        assert 1 <= len(parsed["main"]) <= 10


def test_review_summary_uses_recommend_pick_count(session_factory):
    from lottolab.review import log_predictions

    picks = [
        {"strategy": "稳健·热号", "main": list(range(1, 11)), "aux": []},
        {"strategy": "随机基准", "main": list(range(11, 21)), "aux": []},
    ]
    with session_factory() as s:
        log_predictions(s, "kl8", "2099001", picks)
        summary = review_summary(s, "kl8")
    # 10 号票 vs 开奖 20/80：期望 = 10×20/80 = 2.5
    assert summary["expected_hit"] == pytest.approx(2.5)


# ---------- C3: chunked 请求体绕过 ----------


def test_chunked_body_without_content_length_rejected(session_factory, tmp_path):
    from tests.test_api import client_for

    client, _ = client_for(session_factory, tmp_path)
    # httpx 支持按生成器发 chunked 请求
    big = b"x" * 70000
    response = client.post(
        "/api/v1/simulations",
        content=iter([big]),
        headers={"Content-Encoding": "identity"},
    )
    assert response.status_code == 413


# ---------- A9: 数字型 χ² 小样本期望频数守卫 ----------


def test_digit_randomness_small_sample_flags_low_expectation():
    from lottolab.analysis import randomness

    # 30 期七星彩：末位 k=15 → 期望频数 = 30/15 = 2 < 5
    data = [
        {
            "issue": f"261{i:02d}",
            "draw_date": "2026-01-01",
            "main_numbers": [0, 1, 2, 3, 4, 5, 14],
            "special_numbers": [],
        }
        for i in range(30)
    ]
    # 修正日期多样性
    from datetime import timedelta

    base = date(2026, 1, 1)
    for i, d in enumerate(data):
        d["draw_date"] = (base + timedelta(days=i)).isoformat()
    result = randomness(data, RULES["qxc"], trials=999, seed=1)
    low = [t for t in result["tests"] if t.get("low_expected")]
    # 至少末位（期望 2）应被标记 low_expected，或整体 limitations 提示
    assert low or any("期望" in m for m in result.get("limitations", [])) or result.get("low_power_warning")


# ---------- A10: GET review 不应隐式写库（行为约束） ----------


def test_review_endpoint_get_defaults_readonly():
    """GET /predictions/review 默认不写库；显式 reconcile=true 才对账。"""
    import inspect

    from lottolab import app as app_module

    src = inspect.getsource(app_module.create_app)
    assert "reconcile: bool = Query(False)" in src
    assert "reconcile_sessions" in src
    # 对账调用必须包在显式开关内
    body = src.split("def review_predictions_ep", 1)[1].split("def ", 1)[0]
    assert "if reconcile:" in body
    assert "can_write(request, settings)" in body
    assert "reconcile_sessions(db, kind)" in body


# ---------- C5/B 残余：限流先于鉴权、reconcile 写权限、短 token、CSV 空附加区 ----------


def test_settings_reject_short_admin_token_without_local_writes():
    with pytest.raises(ValueError, match="不足 32"):
        Settings(_env_file=None, admin_token="too-short", allow_local_writes=False)
    assert (
        Settings(_env_file=None, admin_token="too-short", allow_local_writes=True).admin_token == "too-short"
    )


def test_rate_limit_consumes_budget_before_failed_auth(session_factory, tmp_path):
    """失败鉴权的 POST 也要耗限流预算（中间件限流先于 can_write）。"""
    from fastapi.testclient import TestClient
    from lottolab.app import create_app

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        allow_local_writes=False,
        allowed_hosts="127.0.0.1,testserver",
        admin_token="test-only-token-32-characters-ok",
        rate_limit_posts_per_minute=1,
    )
    client = TestClient(
        create_app(settings, session_factory), base_url="http://127.0.0.1:8000", client=("203.0.113.9", 55000)
    )
    body = {"lottery": "ssq", "iterations": 1000}
    assert client.post("/api/v1/simulations", json=body).status_code == 403
    limited = client.post("/api/v1/simulations", json=body)
    assert limited.status_code == 429
    assert "频繁" in limited.json()["detail"]


def test_heavy_get_rate_limit(session_factory, tmp_path):
    from fastapi.testclient import TestClient
    from lottolab.app import create_app

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        allow_local_writes=True,
        allowed_hosts="127.0.0.1,testserver",
        admin_token="test-only-token-32-characters-ok",
        rate_limit_heavy_gets_per_minute=1,
    )
    client = TestClient(
        create_app(settings, session_factory), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 55000)
    )
    assert client.get("/api/v1/recommend?kind=fc3d").status_code == 404
    limited = client.get("/api/v1/recommend?kind=fc3d")
    assert limited.status_code == 429
    # 普通 GET 不计入 heavy 预算
    assert client.get("/api/v1/health").status_code == 200


def test_reconcile_requires_write_permission(session_factory, tmp_path):
    from fastapi.testclient import TestClient
    from lottolab.app import create_app

    token = "test-only-token-32-characters-ok"
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        allow_local_writes=False,
        allowed_hosts="lab.example,testserver",
        allowed_origins="https://lab.example",
        admin_token=token,
        require_read_auth=False,
    )
    client = TestClient(create_app(settings, session_factory), base_url="https://lab.example")
    assert client.get("/api/v1/predictions/review?kind=ssq").status_code == 200
    assert client.get("/api/v1/predictions/review?kind=ssq&reconcile=true").status_code == 403
    with_token = client.get(
        "/api/v1/predictions/review?kind=ssq&reconcile=true", headers={"X-Admin-Token": token}
    )
    assert with_token.status_code == 200


def test_client_ip_takes_last_trusted_xff():
    from lottolab.ratelimit import client_ip
    from starlette.requests import Request

    # 受信代理 peer → 取 XFF 最右非代理跳（真实客户端）
    trusted_scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"host", b"lab.example"), (b"x-forwarded-for", b"10.0.0.1, 93.184.216.34")],
        "client": ("10.0.0.1", 1),
        "server": ("lab.example", 443),
        "scheme": "https",
        "query_string": b"",
        "root_path": "",
    }
    assert client_ip(Request(trusted_scope), trusted_proxies=["10.0.0.1"]) == "93.184.216.34"
    # 非受信直连 → 忽略伪造 XFF，按对端 IP
    direct_scope = dict(trusted_scope, client=("8.8.8.8", 1))
    assert client_ip(Request(direct_scope), trusted_proxies=[]) == "8.8.8.8"
