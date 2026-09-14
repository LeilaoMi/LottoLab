"""B3 域模型：POOL/DIGIT 两类记录的校验与组合数（新增，向后兼容 ssq/dlt）。"""

from datetime import date

import pytest
from lottolab.domain import RULES, DrawInput
from pydantic import ValidationError

D = date(2026, 9, 13)


def _di(**kw):
    base = dict(dataset_kind="real", draw_date=D, sales=None, pool_amount=None, prizes={})
    base.update(kw)
    return DrawInput(**base)


def test_digit_preserves_order_and_allows_repeat():
    di = _di(lottery="fc3d", issue="2026246", main_numbers=[9, 8, 2], special_numbers=[])
    assert di.main_numbers == [9, 8, 2]  # 不排序、可重号语义


def test_digit_rejects_special_and_out_of_range():
    with pytest.raises(ValidationError):
        _di(lottery="pl3", issue="2026246", main_numbers=[1, 2, 3], special_numbers=[5])
    with pytest.raises(ValidationError):
        _di(lottery="fc3d", issue="2026246", main_numbers=[9, 8, 12], special_numbers=[])


def test_qxc_five_digit_issue_and_last_max_14():
    di = _di(lottery="qxc", issue="26106", main_numbers=[5, 1, 9, 5, 8, 5, 11], special_numbers=[])
    assert di.issue == "26106"
    with pytest.raises(ValidationError):
        _di(lottery="qxc", issue="26106", main_numbers=[5, 1, 9, 5, 8, 5, 15], special_numbers=[])


def test_pool_still_sorts_and_dedups():
    di = _di(lottery="ssq", issue="2026106", main_numbers=[30, 6, 11, 13, 14, 22], special_numbers=[14])
    assert di.main_numbers == [6, 11, 13, 14, 22, 30]  # POOL 仍升序


def test_combinations_and_public_no_crash():
    assert RULES["fc3d"].combinations == 1000
    assert RULES["qxc"].combinations == 10**6 * 15
    assert RULES["kl8"].public()["special_probability"] == 0.0  # 无辅区不除零
    assert RULES["ssq"].combinations == 17721088  # 旧值不变
