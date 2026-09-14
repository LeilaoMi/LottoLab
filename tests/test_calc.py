"""注数/金额计算迁入 trunk 的对等测试（对齐 worker/src/calc.js 语义）。"""

from lottolab.calc import calc_bet, comb, digit3_prize, kl8_prize


def test_comb():
    assert comb(33, 6) == 1107568
    assert comb(6, 6) == 1 and comb(5, 6) == 0


def test_ssq_duplex_and_dantuo():
    r = calc_bet("ssq", {"red": 7, "blue": 1})
    assert r["mode"] == "duplex" and r["bets"] == comb(7, 6) * 1 == 7 and r["amount"] == 14
    d = calc_bet("ssq", {"dan": 2, "tuo": 8, "blue": 1})
    assert d["mode"] == "dantuo" and d["bets"] == comb(8, 4) * 1 == 70


def test_dlt_duplex():
    r = calc_bet("dlt", {"front": 6, "back": 3})
    assert r["bets"] == comb(6, 5) * comb(3, 2) == 18 and r["amount"] == 36


def test_chase_mults():
    r = calc_bet("ssq", {"red": 6, "blue": 1, "chase": 3, "mults": "1,2,4"})
    assert r["chase"]["totalBets"] == 1 + 2 + 4 == 7 and r["chase"]["totalAmount"] == 14


def test_kl8_prize():
    assert kl8_prize(10, 10)["amount"] == 5000000 and kl8_prize(10, 10)["prize"] == "高等奖"
    assert kl8_prize(10, 7)["prize"] == "固定奖" and kl8_prize(10, 7)["amount"] == 80
    assert kl8_prize(10, 4)["amount"] == 0 and kl8_prize(10, 4)["prize"] == "未中"
    assert kl8_prize(10, 0)["amount"] == 2


def test_digit3_prize():
    assert digit3_prize(["1", "2", "3"], ["1", "2", "3"])["prize"] == "直选"
    assert digit3_prize(["1", "2", "3"], ["3", "2", "1"])["prize"] == "组六"
    assert digit3_prize(["1", "1", "2"], ["1", "2", "1"])["prize"] == "组三"
    assert digit3_prize(["1", "2", "3"], ["9", "9", "9"])["prize"] == "未中"
