"""验奖引擎迁入 trunk 的单测（对等 worker/src/verify-batch.js）。"""

from lottolab.verify import parse_ticket, score_ticket


def test_parse_ssq_ok_and_errors():
    ok = parse_ticket("ssq", "01 05 13 14 22 30 + 04")
    assert ok == {"main": ["01", "05", "13", "14", "22", "30"], "aux": ["04"]}
    assert "error" in parse_ticket("ssq", "01 05 13 14 22 + 04")  # 主区少一个
    assert "error" in parse_ticket("ssq", "01 01 13 14 22 30 + 04")  # 重复号
    assert "error" in parse_ticket("ssq", "01 05 13 14 22 99 + 04")  # 越界


def test_parse_digit_allows_repeat_and_pad():
    assert parse_ticket("fc3d", "922") == {"main": ["9", "2", "2"], "aux": []}  # 连写
    assert parse_ticket("pl3", "1 1 7") == {"main": ["1", "1", "7"], "aux": []}  # 可重号、不补零


def test_score_ssq_tiers_and_amount_honesty():
    draw = {"red": [6, 11, 13, 14, 22, 30], "blue": 14}
    t1 = parse_ticket("ssq", "06 11 13 14 22 30 + 14")
    r1 = score_ticket("ssq", t1, draw)
    assert r1["tier"] == "1" and r1["grade"] == "一等奖" and r1["amount"] is None  # 浮动奖不给金额
    t3 = parse_ticket("ssq", "06 11 13 14 22 07 + 14")
    r3 = score_ticket("ssq", t3, draw)
    assert r3["tier"] == "3" and r3["amount"] == 3000
    t6 = parse_ticket("ssq", "01 02 03 04 05 06 + 14")
    assert score_ticket("ssq", t6, draw)["tier"] == "6" and score_ticket("ssq", t6, draw)["amount"] == 5


def test_score_dlt_amount_none():
    draw = {"front": [1, 6, 14, 15, 26], "back": [8, 9]}
    t = parse_ticket("dlt", "01 06 14 15 26 + 08 09")
    r = score_ticket("dlt", t, draw)
    assert r["tier"] == "1" and r["grade"] == "一等奖" and r["amount"] is None


def test_score_kl8():
    draw = {"nums": list(range(1, 21))}
    t = parse_ticket("kl8", "03 08 10 16 18 20 23 29 31 35")
    r = score_ticket("kl8", t, draw)
    assert r["pick"] == 10 and r["hit"] == 6 and r["amount"] == 5


def test_score_digit3():
    t = parse_ticket("fc3d", "922")
    assert score_ticket("fc3d", t, {"digits": [9, 2, 2]})["grade"] == "直选"


def test_score_pl5_positional():
    t = parse_ticket("pl5", "1 2 3 4 5")
    r = score_ticket("pl5", t, {"digits": [1, 2, 3, 4, 5]})
    assert r["grade"] == "全中" and r["amount"] is None
