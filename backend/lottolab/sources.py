"""Fixed public-source adapters. No arbitrary URL fetching."""

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

import httpx
from bs4 import BeautifulSoup

from .domain import RULES, Lottery

CWL_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
TC_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"

CWL_NAMES: dict[Lottery, str] = {"ssq": "ssq", "qlc": "qlc", "kl8": "kl8", "fc3d": "3d"}
SPORTTERY_GAMES: dict[Lottery, str] = {"dlt": "85", "pl3": "35", "pl5": "350133", "qxc": "04"}


class SourceRoute(TypedDict):
    provider: Literal["cwl", "sporttery"]
    ident: str
    url: str
    source_label: str


def source_route(lottery: Lottery) -> SourceRoute:
    """Official history endpoint for each lottery (no more gameNo=85 for everything)."""
    if lottery in CWL_NAMES:
        return {
            "provider": "cwl",
            "ident": CWL_NAMES[lottery],
            "url": CWL_URL,
            "source_label": "中国福彩",
        }
    return {
        "provider": "sporttery",
        "ident": SPORTTERY_GAMES[lottery],
        "url": TC_URL,
        "source_label": "中国体彩",
    }


@dataclass
class SourceBatch:
    source: str
    url: str
    raw: bytes
    records: list[dict]
    reported_total: int | None = None


def money(value) -> str | None:
    text = str(value if value is not None else "").strip().replace(",", "")
    return text if re.fullmatch(r"\d+(\.\d{1,2})?", text) else None


def _split_numbers(text: str) -> list[int]:
    parts = re.split(r"[,\s]+", (text or "").strip())
    out: list[int] = []
    for part in parts:
        if not part:
            continue
        out.append(int(part))
    return out


def parse_cwl(payload: dict, lottery: Lottery = "ssq") -> list[dict]:
    if payload.get("state") != 0 and payload.get("state") is not None:
        raise ValueError("中国福彩返回了无法识别的数据结构")
    if not isinstance(payload.get("result"), list):
        raise ValueError("中国福彩返回了无法识别的数据结构")
    rule = RULES[lottery]
    rows: list[dict] = []
    for item in payload["result"]:
        try:
            main = _split_numbers(str(item.get("red", "")))
            special: list[int] = []
            if rule.family == "POOL" and rule.special_count:
                blue = str(item.get("blue") or "").strip()
                special = [int(blue)] if blue else []
            rows.append(
                {
                    "issue": str(item["code"]),
                    "draw_date": str(item["date"])[:10],
                    "main_numbers": main,
                    "special_numbers": special,
                    "sales": money(item.get("sales")),
                    "pool_amount": money(item.get("poolmoney")),
                    "prizes": {
                        str(p["type"]): money(p["typemoney"])
                        for p in item.get("prizegrades", [])
                        if money(p.get("typemoney")) is not None and int(p["type"]) <= 6
                    },
                }
            )
        except (KeyError, ValueError, TypeError) as exc:
            rows.append(
                {"issue": str(item.get("code", "")), "_parse_error": f"源字段不完整：{exc}", "raw": item}
            )
    return rows


def parse_500(html: str, lottery: Lottery) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    main_count, special_count = (6, 1) if lottery == "ssq" else (5, 2)
    for tr in soup.select("#tdata tr"):
        cells = [td.get_text(" ", strip=True).replace("\xa0", " ").strip() for td in tr.select("td")]
        if not cells or not re.fullmatch(r"\d{5,7}", cells[0]):
            continue
        try:
            date_cell = next(v for v in reversed(cells) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v))
            issue = "20" + cells[0] if len(cells[0]) == 5 else cells[0]
            rows.append(
                {
                    "issue": issue,
                    "draw_date": date_cell,
                    "main_numbers": [int(v) for v in cells[1 : 1 + main_count]],
                    "special_numbers": [
                        int(v) for v in cells[1 + main_count : 1 + main_count + special_count]
                    ],
                }
            )
        except (ValueError, StopIteration) as exc:
            rows.append(
                {"issue": cells[0], "_parse_error": f"备用源行解析失败：{exc}", "raw": {"cells": cells}}
            )
    if not rows:
        raise ValueError("备用数据页没有可识别的开奖记录")
    return rows


def parse_sporttery(payload: dict, lottery: Lottery = "dlt") -> list[dict]:
    value = payload.get("value", {})
    items = value.get("list")
    if not isinstance(items, list):
        raise ValueError("中国体彩返回了无法识别的数据结构")
    rule = RULES[lottery]
    rows: list[dict] = []
    for item in items:
        try:
            numbers = _split_numbers(str(item.get("lotteryDrawResult", "")))
            issue = str(item["lotteryDrawNum"])
            issue = "20" + issue if len(issue) == 5 else issue
            main_count = rule.main_count
            if rule.family == "DIGIT":
                main, special = numbers[:main_count], []
            else:
                main = numbers[:main_count]
                special = numbers[main_count : main_count + rule.special_count]
            rows.append(
                {
                    "issue": issue,
                    "draw_date": item["lotteryDrawTime"][:10],
                    "main_numbers": main,
                    "special_numbers": special,
                    "sales": money(item.get("totalSaleAmount")),
                    "pool_amount": money(item.get("poolBalanceAfterdraw")),
                }
            )
        except (KeyError, ValueError, TypeError) as exc:
            rows.append({"issue": str(item.get("lotteryDrawNum", "")), "_parse_error": str(exc), "raw": item})
    return rows


def request(client: httpx.Client, url: str, params: dict) -> httpx.Response:
    last_error = None
    for attempt in range(3):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            if len(response.content) > 12 * 1024 * 1024:
                raise ValueError("数据源响应超过大小限制")
            return response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            last_error = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403, 404):
                break
            if attempt < 2:
                time.sleep(0.5 * 2**attempt)
    raise RuntimeError("公开数据源请求失败，请稍后重试或导入 CSV") from last_error


def fetch_source(lottery: Lottery, count: int, timeout: float = 20) -> tuple[list[SourceBatch], list[str]]:
    errors: list[str] = []
    route = source_route(lottery)
    headers = {
        "User-Agent": "LottoLab/0.1 (public historical data research)",
        "Referer": (
            "https://static.sporttery.cn/"
            if route["provider"] == "sporttery"
            else "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/"
        ),
    }
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
    ) as client:
        batches = []
        try:
            remaining = count
            page = 1
            while remaining > 0:
                size = min(1000, count) if route["provider"] == "cwl" else min(100, count)
                if route["provider"] == "cwl":
                    params: dict[str, Any] = {
                        "name": route["ident"],
                        "pageNo": page,
                        "pageSize": size,
                        "systemType": "PC",
                    }
                else:
                    params = {
                        "gameNo": route["ident"],
                        "provinceId": "0",
                        "pageSize": size,
                        "pageNo": page,
                        "isVerify": "1",
                    }
                response = request(client, route["url"], params)
                payload = response.json()
                records = (
                    parse_cwl(payload, lottery)
                    if route["provider"] == "cwl"
                    else parse_sporttery(payload, lottery)
                )
                if not records:
                    break
                batches.append(
                    SourceBatch(
                        route["source_label"],
                        str(response.url),
                        response.content,
                        records[:remaining],
                        payload.get("total"),
                    )
                )
                remaining -= len(records)
                if len(records) < size:
                    break
                page += 1
                if remaining > 0:
                    time.sleep(0.8)
            if batches:
                return batches, errors
            raise ValueError("官方源返回空数据")
        except (RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            errors.append("官方数据源暂不可用；可通过导入报告查看实际来源或改用 CSV 导入。")
        if lottery not in ("ssq", "dlt"):
            raise RuntimeError("该彩种官方源暂不可用，且无备用 HTML 源；请稍后重试或导入 CSV") from None
        url = f"https://datachart.500.com/{lottery}/history/newinc/history.php"
        response = request(client, url, {"limit": count})
        html = response.content.decode("utf-8", errors="replace")
        records = parse_500(html, lottery)[:count]
        return [SourceBatch("500 公开数据（备用）", str(response.url), response.content, records)], errors
