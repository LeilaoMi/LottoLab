"""数据契约（collector/contract.py）的离线测试。

为什么这组测试重要
2026-09-30 实测覆盖率：backend 85%，collector 9%。contract.py 是 0%。
而 contract.py 是 8 个彩种号池规则的**唯一事实源** —— 采集器与影子作业都 import 它，
落库前的每一次「这注号码合不合规」都走它。一处写错（例如把 qxc 末位号池写成 0..9）
会让整个采集链静默接受或拒绝错误数据，而 201 项测试全绿。

所以这里覆盖每一条会「静默改数据」或「静默放行」的分支。纯标准库、离线、不碰网络与数据库。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))

from contract import (  # noqa: E402
    RULES,
    ContractError,
    canonicalize,
    key,
    normalize_issue,
)

ALL_KINDS = sorted(RULES)


# ---------------------------------------------------------------- 期号归一


def test_normalize_issue_pads_five_digit_to_seven() -> None:
    # 5 位 YYNNN 补 "20"
    assert normalize_issue("ssq", "26103") == "2026103"
    assert normalize_issue("dlt", "26111") == "2026111"


def test_normalize_issue_keeps_seven_digit_as_is() -> None:
    assert normalize_issue("ssq", "2026103") == "2026103"


def test_qxc_keeps_five_digits_and_rejects_seven() -> None:
    """七星彩是契约里唯一的 5 位期号彩种 —— 补 "20" 会把它变成错的期号。"""
    assert normalize_issue("qxc", "26113") == "26113"
    with pytest.raises(ContractError, match="qxc 期号应为5位"):
        normalize_issue("qxc", "2026113")


@pytest.mark.parametrize("kind", [k for k in ALL_KINDS if k != "qxc"])
def test_non_qxc_rejects_wrong_length(kind: str) -> None:
    # 5 位会被补成 7 位（"20261" -> "2020201"，恰好 7 位所以合法），
    # 所以要挑真正无法归一到 7 位的输入：4 位会补成 6 位、8 位原样保留
    for bad in ("2026", "20261001"):
        with pytest.raises(ContractError, match="7 位"):
            normalize_issue(kind, bad)


@pytest.mark.parametrize("bad", ["20x103", "", "  ", "abc"])
def test_normalize_issue_rejects_non_digits(bad: str) -> None:
    with pytest.raises(ContractError):
        normalize_issue("ssq", bad)


def test_normalize_issue_accepts_int() -> None:
    assert normalize_issue("ssq", 2026103) == "2026103"


# ---------------------------------------------------------------- 号码池型


@pytest.mark.parametrize(
    ("kind", "main", "special"),
    [
        ("ssq", [1, 2, 3, 4, 5, 6], [7]),
        ("dlt", [1, 2, 3, 4, 5], [6, 7]),
        ("qlc", [1, 2, 3, 4, 5, 6, 7], [8]),
        ("kl8", list(range(1, 21)), []),
    ],
)
def test_pool_family_accepts_valid(kind: str, main: list[int], special: list[int]) -> None:
    rec = canonicalize(kind, "2026100", main, special, "2026-10-01")
    assert rec["main"] == sorted(main), "池型必须排序"
    assert rec["special"] == sorted(special)


def test_pool_sorts_main() -> None:
    """上游给的顺序不保证升序，契约负责归一 —— 否则跨源指纹会把同一注号码判成两个值。"""
    assert canonicalize("ssq", "2026100", [6, 1, 5, 2, 4, 3], [7], "2026-10-01")["main"] == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize("dup", [[1, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 5]])
def test_pool_rejects_duplicate_main(dup: list[int]) -> None:
    with pytest.raises(ContractError, match="不可重复"):
        canonicalize("ssq", "2026100", dup, [7], "2026-10-01")


@pytest.mark.parametrize(
    ("kind", "bad_main"),
    [
        ("ssq", [0, 1, 2, 3, 4, 5]),  # 下界越界
        ("ssq", [1, 2, 3, 4, 5, 34]),  # 上界越界（ssq 主区最大 33）
        ("dlt", [1, 2, 3, 4, 36]),
        ("qlc", [1, 2, 3, 4, 5, 6, 31]),
        ("kl8", list(range(1, 20)) + [81]),
    ],
)
def test_pool_rejects_out_of_range(kind: str, bad_main: list[int]) -> None:
    special = [] if RULES[kind]["special"][0] == 0 else [1]
    with pytest.raises(ContractError, match=r"主区号须∈"):
        canonicalize(kind, "2026100", bad_main, special, "2026-10-01")


def test_pool_rejects_wrong_count() -> None:
    with pytest.raises(ContractError, match="主区须 6 个"):
        canonicalize("ssq", "2026100", [1, 2, 3, 4, 5], [7], "2026-10-01")


def test_qlc_special_must_not_overlap_main() -> None:
    """七乐彩特别号与基本号同池（都是 1..30），必须显式禁止重复。"""
    with pytest.raises(ContractError, match="特别号不得与基本号重复"):
        canonicalize("qlc", "2026100", [1, 2, 3, 4, 5, 6, 7], [3], "2026-10-01")
    # 不重复时通过
    assert canonicalize("qlc", "2026100", [1, 2, 3, 4, 5, 6, 7], [8], "2026-10-01")


def test_qlc_special_pool_is_30_not_16() -> None:
    """七乐彩特别号是 1..30（不是 1..16）—— 写错会把 17..30 全判成越界。"""
    assert canonicalize("qlc", "2026100", [1, 2, 3, 4, 5, 6, 7], [30], "2026-10-01")


def test_kl8_has_no_special_numbers() -> None:
    with pytest.raises(ContractError, match="辅区须 0 个"):
        canonicalize("kl8", "2026100", list(range(1, 21)), [1], "2026-10-01")


# ---------------------------------------------------------------- 数字型


@pytest.mark.parametrize(
    ("kind", "digits"),
    [("fc3d", [1, 2, 3]), ("pl3", [0, 9, 5]), ("pl5", [1, 2, 3, 4, 5])],
)
def test_digit_family_keeps_order_and_allows_repeat(kind: str, digits: list[int]) -> None:
    """数字型有序、允许重号 —— 排序或去重会把「组三/豹子」这类形态判错。"""
    rec = canonicalize(kind, "2026100", digits, [], "2026-10-01")
    assert rec["main"] == digits, "数字型必须保持原顺序"


def test_digit_allows_repeated_numbers() -> None:
    assert canonicalize("fc3d", "2026100", [7, 7, 7], [], "2026-10-01")["main"] == [7, 7, 7]
    assert canonicalize("pl5", "2026100", [1, 1, 1, 1, 1], [], "2026-10-01")["main"] == [1, 1, 1, 1, 1]


def test_digit_rejects_out_of_range() -> None:
    with pytest.raises(ContractError, match=r"第\d+位须∈\[0,9\]"):
        canonicalize("fc3d", "2026100", [1, 2, 10], [], "2026-10-01")
    with pytest.raises(ContractError, match=r"第\d+位须∈\[0,9\]"):
        canonicalize("pl5", "2026100", [1, 2, 3, 4, 12], [], "2026-10-01")


def test_qxc_last_position_pool_is_0_to_14() -> None:
    """七星彩第 7 位是 0..14（15 格），不是 0..9。

    这是契约里唯一的「某一位号池不等于其它位」的情形。写成 0..9 会把 10..14
    的真实开奖数据全部判成越界丢弃 —— 且丢弃是静默的（计入 rejected）。
    """
    assert canonicalize("qxc", "26113", [1, 2, 3, 4, 5, 6, 14], [], "2026-10-01")["main"][-1] == 14
    assert canonicalize("qxc", "26113", [1, 2, 3, 4, 5, 6, 0], [], "2026-10-01")["main"][-1] == 0
    with pytest.raises(ContractError, match="第7位须∈\\[0,14\\]"):
        canonicalize("qxc", "26113", [1, 2, 3, 4, 5, 6, 15], [], "2026-10-01")


def test_qxc_other_positions_stay_0_to_9() -> None:
    """只有末位放宽到 14，前 6 位仍应是 0..9。"""
    with pytest.raises(ContractError, match="第6位须∈\\[0,9\\]"):
        canonicalize("qxc", "26113", [1, 2, 3, 4, 5, 11, 12], [], "2026-10-01")


def test_qxc_requires_five_digit_issue() -> None:
    with pytest.raises(ContractError, match="qxc 期号应为5位"):
        canonicalize("qxc", "2026113", [1, 2, 3, 4, 5, 6, 7], [], "2026-10-01")


# ---------------------------------------------------------------- 期号与日期一致性


def test_year_mismatch_is_rejected_for_ssq_and_dlt() -> None:
    with pytest.raises(ContractError, match="期号年份与开奖日期不一致"):
        canonicalize("ssq", "2025100", [1, 2, 3, 4, 5, 6], [7], "2026-10-01")


@pytest.mark.parametrize("seq", [0, 367, 999])
def test_out_of_range_year_sequence_is_rejected(seq: int) -> None:
    with pytest.raises(ContractError, match="年内期次越界"):
        canonicalize("ssq", f"2026{seq:03d}", [1, 2, 3, 4, 5, 6], [7], "2026-10-01")


@pytest.mark.parametrize("seq", [1, 100, 366])
def test_in_range_year_sequence_is_accepted(seq: int) -> None:
    assert canonicalize("ssq", f"2026{seq:03d}", [1, 2, 3, 4, 5, 6], [7], "2026-10-01")


# ---------------------------------------------------------------- 指纹与未知彩种


def test_key_is_order_insensitive_for_pool() -> None:
    """池型指纹必须与输入顺序无关 —— 否则同一注号码换个顺序会被判成「多源不一致」。"""
    a = canonicalize("ssq", "2026100", [1, 2, 3, 4, 5, 6], [7], "2026-10-01")
    b = canonicalize("ssq", "2026100", [6, 5, 4, 3, 2, 1], [7], "2026-10-01")
    assert key(a) == key(b)


def test_key_is_order_sensitive_for_digit() -> None:
    """数字型指纹必须区分顺序 —— 123 与 321 是不同的开奖号。"""
    a = canonicalize("fc3d", "2026100", [1, 2, 3], [], "2026-10-01")
    b = canonicalize("fc3d", "2026100", [3, 2, 1], [], "2026-10-01")
    assert key(a) != key(b)


def test_key_differs_on_date() -> None:
    a = canonicalize("ssq", "2026100", [1, 2, 3, 4, 5, 6], [7], "2026-10-01")
    b = canonicalize("ssq", "2026100", [1, 2, 3, 4, 5, 6], [7], "2026-10-08")
    assert key(a) != key(b), "同号码不同开奖日期是数据矛盾，指纹必须能区分"


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ContractError, match="未知彩种"):
        canonicalize("nope", "2026100", [1], [], "2026-10-01")


def test_all_kinds_have_consistent_rule_shape() -> None:
    """规则表本身的形状一致性 —— 少一个键会让 canonicalize 在某个彩种上 KeyError。"""
    for kind, rule in RULES.items():
        assert rule["family"] in {"POOL", "DIGIT"}, kind
        assert len(rule["main"]) == 3, f"{kind} main 应为 (count, lo, hi)"
        assert len(rule["special"]) == 3, f"{kind} special 应为 (count, lo, hi)"
        assert rule["issue"] == (5 if kind == "qxc" else 7), f"{kind} 期号位数"
        if rule["family"] == "DIGIT":
            assert rule["special"][0] == 0, f"{kind} 数字型不应有辅区"
        if rule.get("last_hi") is not None:
            assert kind == "qxc", "last_hi 只应用于七星彩末位"


def test_rules_main_and_backend_domain_agree() -> None:
    """采集层契约与后端领域模型必须对同一批彩种给出一致的号池。

    两处各自定义 8 个彩种的规则 —— 如果某次只改了一边（比如后端把 qxc 末位
    改成 0..9 而采集层还是 0..14），数据会在落库前被一边的规则悄悄拒掉，
    而两边各自的单测都还是绿的。这条测试就是防这个。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from lottolab.domain import RULES as DOMAIN  # noqa: PLC0415

    assert sorted(RULES) == sorted(DOMAIN), "采集层与后端的彩种集合不一致"
    for kind in RULES:
        c_main = RULES[kind]["main"]
        d = DOMAIN[kind]
        # domain.Rule 是扁平字段（main_count / main_max / special_count / special_max / last_max），
        # 不是 tuple，所以别拿 d.main 去比 —— Rule 没有那个属性。
        assert RULES[kind]["family"] == d.family, f"{kind} family 不一致"
        assert c_main[0] == d.main_count, f"{kind} 选号个数：contract={c_main[0]} domain={d.main_count}"
        assert c_main[2] == d.main_max, f"{kind} 号池上界：contract={c_main[2]} domain={d.main_max}"
        c_spec = RULES[kind]["special"]
        assert c_spec[0] == d.special_count, f"{kind} 副区个数：contract={c_spec[0]} domain={d.special_count}"
        if c_spec[0]:
            assert c_spec[2] == d.special_max, f"{kind} 副区上界：contract={c_spec[2]} domain={d.special_max}"
        # 数字型号的「末位放宽号池」两处必须同步：写错一处，真实开奖号会被
        # 静默计入 rejected（丢弃不会有任何报错）
        c_last = RULES[kind].get("last_max") or RULES[kind].get("last_hi")
        assert c_last == d.last_max, f"{kind} 末位号池：contract={c_last} domain={d.last_max}"
