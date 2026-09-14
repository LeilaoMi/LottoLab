"""Lottery rules and strict, transport-independent draw validation."""

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from math import comb
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

Lottery = Literal["ssq", "dlt"]
DatasetKind = Literal["real", "synthetic"]
Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2, allow_inf_nan=False)]
DISCLAIMER = "用于历史数据分析、统计实验与概率教育，不提供中奖保证，也不构成购彩建议。"


@dataclass(frozen=True)
class Rule:
    code: Lottery
    name: str
    main_max: int
    main_count: int
    special_max: int
    special_count: int
    weekdays: tuple[int, ...]
    version: str
    ticket_price: str = "2.00"

    @property
    def combinations(self) -> int:
        return comb(self.main_max, self.main_count) * comb(self.special_max, self.special_count)

    def public(self) -> dict:
        return {
            **asdict(self),
            "combinations": self.combinations,
            "main_probability": self.main_count / self.main_max,
            "special_probability": self.special_count / self.special_max,
        }


RULES: dict[Lottery, Rule] = {
    "ssq": Rule("ssq", "双色球", 33, 6, 16, 1, (1, 3, 6), "ssq-number-space-v1"),
    "dlt": Rule("dlt", "大乐透", 35, 5, 12, 2, (0, 2, 5), "dlt-number-space-v1"),
}


class DrawInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    lottery: Lottery
    issue: str = Field(min_length=5, max_length=32)
    draw_date: date
    main_numbers: list[StrictInt]
    special_numbers: list[StrictInt]
    dataset_kind: DatasetKind = "real"
    sales: Money | None = None
    pool_amount: Money | None = None
    prizes: dict[str, Money] = Field(default_factory=dict)

    @field_validator("draw_date")
    @classmethod
    def no_future_draws(cls, value: date) -> date:
        if value > datetime.now(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("开奖日期不能在未来")
        return value

    @model_validator(mode="after")
    def validate_rule(self):
        rule = RULES[self.lottery]
        if self.dataset_kind == "real":
            if not self.issue.isascii() or not self.issue.isdigit() or len(self.issue) != 7:
                raise ValueError("真实期号使用四位年份加三位序号，例如 2026105")
            if int(self.issue[:4]) != self.draw_date.year or not 1 <= int(self.issue[4:]) <= 366:
                raise ValueError("期号年份或期次与开奖日期不一致")
        elif not self.issue.startswith("SIM-"):
            raise ValueError("演示期号必须以 SIM- 开头，避免与真实期次混淆")
        for name, values, count, maximum in (
            ("主区", self.main_numbers, rule.main_count, rule.main_max),
            ("附加区", self.special_numbers, rule.special_count, rule.special_max),
        ):
            if len(values) != count:
                raise ValueError(f"{name}必须恰好有 {count} 个号码")
            if len(set(values)) != count:
                raise ValueError(f"{name}号码不能重复")
            if any(value < 1 or value > maximum for value in values):
                raise ValueError(f"{name}号码范围为 1–{maximum}")
        self.main_numbers.sort()
        self.special_numbers.sort()
        return self

    def identity_payload(self) -> dict:
        return {
            "lottery": self.lottery,
            "issue": self.issue,
            "draw_date": self.draw_date.isoformat(),
            "main_numbers": self.main_numbers,
            "special_numbers": self.special_numbers,
            "dataset_kind": self.dataset_kind,
        }


def ssq_prize_tier(main_hits: int, special_hits: int) -> str | None:
    if main_hits == 6:
        return "1" if special_hits else "2"
    if main_hits == 5:
        return "3" if special_hits else "4"
    if main_hits == 4:
        return "4" if special_hits else "5"
    if main_hits == 3 and special_hits:
        return "5"
    return "6" if special_hits else None


def dlt_prize_tier(main_hits: int, special_hits: int) -> str | None:
    return {
        (5, 2): "1",
        (5, 1): "2",
        (5, 0): "3",
        (4, 2): "4",
        (4, 1): "5",
        (3, 2): "6",
        (4, 0): "7",
        (3, 1): "8",
        (2, 2): "8",
        (3, 0): "9",
        (2, 1): "9",
        (1, 2): "9",
        (0, 2): "9",
    }.get((main_hits, special_hits))


def qlc_prize_tier(main_hits: int, special_hits: int) -> str | None:
    """七乐彩官方七档：special_hits 传 0/1（是否命中特别号）。对齐 lottery-web prizeQLC。"""
    return {
        (7, 1): "1",
        (7, 0): "1",
        (6, 1): "2",
        (6, 0): "3",
        (5, 1): "4",
        (5, 0): "5",
        (4, 1): "6",
        (4, 0): "7",
    }.get((main_hits, special_hits))
