#!/usr/bin/env python3
"""Headless Dongchedi Wuhan-shop list + cash-price client.

List pagination must carry the previous page's data.event_info.search_id.
Changing only offset repeats page 1. Cards whose shop_id is not 118608 are
padding and are dropped. Cash price is data.product.sku_list[0].sku_price
(fen / price_str). The sku_id+shop_id detail URL returns 502 and is not used.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

from filters import WUHAN_SHOP_ID

LIST_URL = "https://m.dcdapp.com/motor/ecom/sophon/guide/card/query/"
DETAIL_URL = "https://m.dcdapp.com/motor/ecom/sophon/guide/card/detail"
MID_LIST = "200100034"
MID_DETAIL = "400000003"
SHOP_ID = WUHAN_SHOP_ID
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.50(0x18003237) NetType/WIFI Language/zh_CN"
)
SHANGHAI = timezone(timedelta(hours=8))

LIST_FILTERS = [
    {"key": "shop_id", "val": [SHOP_ID]},
    {"key": "price", "val": ["0,6"]},
    {"key": "car_mileage", "val": ["0,10"]},
    {"key": "car_age", "val": ["0,10"]},
]


class FetchError(RuntimeError):
    def __init__(self, url: str, status: int, body: bytes):
        super().__init__(f"HTTP {status} for {url[:180]}")
        self.url = url
        self.status = status
        self.body = body


def build_list_url(offset: int, count: int, search_id: str) -> str:
    params = {
        "mid": MID_LIST,
        "count": str(count),
        "offset": str(offset),
        "city_name": "武汉",
        "sh_city_name": "武汉",
        "filter_list_json": json.dumps(LIST_FILTERS, ensure_ascii=False, separators=(",", ":")),
        "sort_list_json": '[{"key":"sort=0"}]',
        "search_params_json": json.dumps({"search_id": search_id}, ensure_ascii=False),
    }
    return LIST_URL + "?" + urllib.parse.urlencode(params)


def build_detail_url(sku: str) -> str:
    params = {
        "product_id": str(sku),
        "biz_type": "2",
        "card_type_source": "1",
        "mid": MID_DETAIL,
    }
    return DETAIL_URL + "?" + urllib.parse.urlencode(params)


def _search_id(page: dict[str, Any]) -> str:
    return str(((page.get("data") or {}).get("event_info") or {}).get("search_id") or "")


def _cards(page: dict[str, Any]) -> list[dict[str, Any]]:
    return list((page.get("data") or {}).get("card_list") or [])


def card_shop_id(card: dict[str, Any]) -> str:
    event = ((card.get("product") or {}).get("event_info") or {})
    return str(event.get("shop_id") or "")


def card_sku(card: dict[str, Any]) -> str:
    event = ((card.get("product") or {}).get("event_info") or {})
    return str(event.get("sku_id") or "")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def parse_cash_price(detail: dict[str, Any]) -> dict[str, Any]:
    """sku_price.price is fen. 5990000 fen = 5.99 万."""
    product = (detail.get("data") or {}).get("product") or {}
    sku0 = (product.get("sku_list") or [{}])[0]
    sku_price = sku0.get("sku_price") or {}
    fen = sku_price.get("price")
    price_str = str(sku_price.get("price_str") or "").strip()
    wan = None
    if isinstance(fen, (int, float)) and not isinstance(fen, bool) and fen > 0:
        wan = round(float(fen) / 1_000_000, 2)
    elif price_str:
        try:
            wan = round(float(price_str), 2)
        except ValueError:
            wan = None
    shop = (product.get("product_shop") or {}).get("shop_id")
    return {
        "sku_id": sku0.get("sku_id"),
        "cash_price_fen": fen,
        "cash_price_str": price_str or None,
        "cash_price_unit": sku_price.get("price_unit") or None,
        "cash_price_wan": wan,
        "shop_id": None if shop in (None, "") else str(shop),
        "api_status": detail.get("status"),
    }


def normalize_card(card: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    product = card.get("product") or {}
    event = product.get("event_info") or {}
    desc = product.get("product_desc") or {}
    list_price = product.get("product_price") or {}
    image = ((product.get("product_image") or {}).get("main_image") or {}).get("url") or ""
    tags = []
    for tag in product.get("product_tag_list") or []:
        text = str(tag.get("text") or "").strip()
        if text:
            tags.append(text)
    sku = str(event.get("sku_id") or "")
    shop_id = str(event.get("shop_id") or "")
    self_trade = _truthy(event.get("is_self_trade_car"))
    source_name = str(event.get("source_type_name") or "")
    badges: list[str] = []
    if self_trade or source_name.startswith("自营"):
        badges.append("直营")
    try:
        mileage = float(event.get("mileage"))
    except (TypeError, ValueError):
        mileage = None
    try:
        model_year = int(str(event.get("year") or "")[:4])
    except ValueError:
        model_year = None
    plate_year = model_year
    reg = event.get("first_registration_time")
    if reg not in (None, ""):
        try:
            plate_year = datetime.fromtimestamp(int(reg), SHANGHAI).year
        except (TypeError, ValueError, OverflowError, OSError):
            plate_year = model_year
    try:
        list_wan = float(list_price.get("text"))
    except (TypeError, ValueError):
        list_wan = None
    item: dict[str, Any] = {
        "sku": sku,
        "title": desc.get("title") or event.get("full_name") or "",
        "shop_id": shop_id,
        "shop_name": event.get("shop_name") or "",
        "series": event.get("series_name") or event.get("car_series_name") or "",
        "brand": event.get("brand_name") or "",
        "mileage_wan": mileage,
        "model_year": model_year,
        "plate_year": plate_year,
        "year": desc.get("sub_title") or "",
        "city": event.get("shop_city_name") or event.get("car_source_city_name") or "武汉",
        "tags": tags,
        "badges": badges,
        "is_self_trade_car": self_trade,
        "source_type": event.get("source_type"),
        "source_type_name": source_name,
        "fuel_form": event.get("fuel_form"),
        "cover": image,
        "detail_url": (
            "https://m.dcdapp.com/motor/feoffline/usedcar_detail/detail.html"
            f"?sku_id={sku}&shop_id={shop_id or SHOP_ID}"
        ),
        "list_price_wan": list_wan,
        "first_registration_time": reg,
        "price_type": "现金价",
        "prefix": "现金价",
    }
    if detail:
        cash = parse_cash_price(detail)
        item["cash_price_fen"] = cash["cash_price_fen"]
        item["cash_price_str"] = cash["cash_price_str"]
        item["cash_price_wan"] = cash["cash_price_wan"]
        if cash["cash_price_wan"] is not None:
            item["price"] = cash["cash_price_wan"]
        if cash.get("shop_id"):
            item["shop_id"] = str(cash["shop_id"])
            item["detail_shop_id"] = str(cash["shop_id"])
    return item


@dataclass
class FetchBatch:
    cards: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, dict[str, Any]] = field(default_factory=dict)
    detail_errors: dict[str, dict[str, Any]] = field(default_factory=dict)


class HttpClient:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def get_json(self, url: str) -> tuple[int, dict[str, Any]]:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": (
                    "https://m.dcdapp.com/motor/feoffline/usedcar_shop_page/home.html"
                    f"?shop_id={SHOP_ID}"
                ),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status = exc.code
        if status != 200:
            raise FetchError(url, status, body)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise FetchError(url, status, body) from exc
        return status, payload

    def fetch_list(self, offset: int, count: int, search_id: str) -> tuple[int, dict[str, Any]]:
        return self.get_json(build_list_url(offset, count, search_id))

    def fetch_detail(self, sku: str) -> tuple[int, dict[str, Any]]:
        return self.get_json(build_detail_url(sku))


class FixtureClient:
    """Replay saved list pages. A later page requested without search_id repeats page 1."""

    def __init__(self, pages: list[dict[str, Any]], details: dict[str, dict[str, Any]]):
        self.pages = pages
        self.details = details
        self.list_calls: list[tuple[int, int, str]] = []

    def fetch_list(self, offset: int, count: int, search_id: str) -> tuple[int, dict[str, Any]]:
        self.list_calls.append((offset, count, search_id))
        index = len(self.list_calls) - 1
        if index >= len(self.pages):
            return 200, {
                "status": 0,
                "data": {"card_list": [], "page": {"has_more": False}, "event_info": {}},
            }
        if index > 0 and not search_id:
            return 200, self.pages[0]
        return 200, self.pages[index]

    def fetch_detail(self, sku: str) -> tuple[int, dict[str, Any]]:
        if sku not in self.details:
            raise FetchError(build_detail_url(sku), 404, b"missing fixture")
        return 200, self.details[sku]


def load_fixture_dir(directory: Path) -> FixtureClient:
    pages = []
    for path in sorted(directory.glob("list-page*.json")):
        if not re.fullmatch(r"list-page\d+", path.stem):
            continue
        pages.append(json.loads(path.read_text(encoding="utf-8")))
    details: dict[str, dict[str, Any]] = {}
    for path in directory.glob("detail-*.json"):
        if not re.fullmatch(r"detail-\d+", path.stem):
            continue
        sku = path.stem.split("-", 1)[1]
        details[sku] = json.loads(path.read_text(encoding="utf-8"))
    if not pages:
        raise FileNotFoundError(f"no list-pageN.json under {directory}")
    return FixtureClient(pages, details)


def fetch_shop_batch(
    client: Any,
    *,
    page_size: int = 20,
    limit: int = 0,
    max_pages: int = 40,
    on_detail_error: Callable[[str, Exception], None] | None = None,
) -> FetchBatch:
    """Walk search_id pages and attach a detail payload for each kept card."""
    batch = FetchBatch()
    search_id = ""
    offset = 0
    seen: set[str] = set()
    for _ in range(max_pages):
        _status, page = client.fetch_list(offset, page_size, search_id)
        batch.pages.append(page)
        search_id = _search_id(page) or search_id
        cards = _cards(page)
        if not cards:
            break
        fresh: list[dict[str, Any]] = []
        in_shop = 0
        for card in cards:
            if card_shop_id(card) != SHOP_ID:
                continue
            in_shop += 1
            sku = card_sku(card)
            if not sku or sku in seen:
                continue
            seen.add(sku)
            fresh.append(card)
        if in_shop == 0 or not fresh:
            # Other-shop padding, or a repeated page because search_id was dropped.
            break
        for card in fresh:
            batch.cards.append(card)
            sku = card_sku(card)
            try:
                _detail_status, detail = client.fetch_detail(sku)
                batch.details[sku] = detail
            except Exception as exc:
                batch.detail_errors[sku] = {
                    "sku": sku,
                    "error": f"{type(exc).__name__}: {exc}",
                    "status": getattr(exc, "status", None),
                }
                if on_detail_error:
                    on_detail_error(sku, exc)
            if limit and len(batch.cards) >= limit:
                return batch
        page_info = (page.get("data") or {}).get("page") or {}
        if not page_info.get("has_more"):
            break
        if not search_id:
            break
        offset = int(page_info.get("offset") or (offset + page_size))
    return batch
