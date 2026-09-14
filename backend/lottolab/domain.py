"""Lottery rules and strict, transport-independent draw validation."""

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from math import comb
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

Lottery = Literal["ssq", "dlt", "qlc", "kl8", "fc3d", "pl3", "pl5", "qxc"]
DatasetKind = Literal["real", "synthetic"]
Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2, allow_inf_nan=False)]
DISCLAIMER = "用于历史数据分析、统计实验与概率教育，不提供中奖保证，也不构成购彩建议。"


@dataclass(frozen=True)
class Rule:
    code: Lottery
    name: str
    family: str  # POOL（选k、升序、去重） | DIGIT（逐位、有序、可重）
    main_max: int
    main_count: int
    special_max: int
    special_count: int
    weekdays: tuple[int, ...]
    version: str
    last_max: int | None = None  # DIGIT 末位上限（七星彩 0–14）
    ticket_price: str = "2.00"

    @property
    def combinations(self) -> int:
        if self.family == "DIGIT":
            base = self.main_max + 1
            if self.last_max is not None:
                return base ** (self.main_count - 1) * (self.last_max + 1)
            return base**self.main_count
        special = comb(self.special_max, self.special_count) if self.special_count else 1
        return comb(self.main_max, self.main_count) * special

    def public(self) -> dict:
        return {
            **asdict(self),
            "combinations": self.combinations,
            "main_probability": (self.main_count / self.main_max) if self.main_max else 0.0,
            "special_probability": (self.special_count / self.special_max) if self.special_max else 0.0,
        }


RULES: dict[Lottery, Rule] = {
    "ssq": Rule("ssq", "双色球", "POOL", 33, 6, 16, 1, (1, 3, 6), "ssq-number-space-v1"),
    "dlt": Rule("dlt", "大乐透", "POOL", 35, 5, 12, 2, (0, 2, 5), "dlt-number-space-v1"),
    "qlc": Rule("qlc", "七乐彩", "POOL", 30, 7, 30, 1, (1, 3, 5), "qlc-number-space-v1"),
    "kl8": Rule("kl8", "快乐8", "POOL", 80, 20, 0, 0, (0, 1, 2, 3, 4, 5, 6), "kl8-number-space-v1"),
    "fc3d": Rule("fc3d", "福彩3D", "DIGIT", 9, 3, 0, 0, (0, 1, 2, 3, 4, 5, 6), "fc3d-number-space-v1"),
    "pl3": Rule("pl3", "排列3", "DIGIT", 9, 3, 0, 0, (0, 1, 2, 3, 4, 5, 6), "pl3-number-space-v1"),
    "pl5": Rule("pl5", "排列5", "DIGIT", 9, 5, 0, 0, (0, 1, 2, 3, 4, 5, 6), "pl5-number-space-v1"),
    "qxc": Rule("qxc", "七星彩", "DIGIT", 9, 7, 0, 0, (2, 5), "qxc-number-space-v1", last_max=14),
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
            width = 5 if self.lottery == "qxc" else 7
            if not self.issue.isascii() or not self.issue.isdigit() or len(self.issue) != width:
                raise ValueError(f"真实期号须 {width} 位数字")
            year = int(self.issue[:4]) if width == 7 else 2000 + int(self.issue[:2])
            seq = int(self.issue[4:]) if width == 7 else int(self.issue[2:])
            if year != self.draw_date.year or not 1 <= seq <= 366:
                raise ValueError("期号年份或期次与开奖日期不一致")
        elif not self.issue.startswith("SIM-"):
            raise ValueError("演示期号必须以 SIM- 开头，避免与真实期次混淆")
        if rule.family == "POOL":
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
        else:  # DIGIT：逐位、有序、可重号、含 0，不排序
            if self.special_numbers:
                raise ValueError("数字型彩种无附加区")
            n = rule.main_count
            if len(self.main_numbers) != n:
                raise ValueError(f"须 {n} 位数字")
            for i, v in enumerate(self.main_numbers):
                cap = rule.last_max if (rule.last_max is not None and i == n - 1) else rule.main_max
                if v < 0 or v > cap:
                    raise ValueError(f"第 {i + 1} 位须在 0–{cap}")
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
