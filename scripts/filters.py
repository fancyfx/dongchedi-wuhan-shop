#!/usr/bin/env python3
"""Hard filters for Wuhan shop listings (shop_id=118608).

叠加规则：本店、现金价≤6万、里程≤10万公里、车龄≤10年（上牌年≥当年-10）、
直营或自营信号，以及排除短续航纯电。晨检/入库脚本应调用 keep_listing。
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

MAX_BEV_RANGE_KM = 300
WUHAN_SHOP_ID = "118608"
MAX_PRICE_WAN = 6.0
MAX_MILEAGE_WAN = 10.0
MAX_AGE_YEARS = 10
SHANGHAI = timezone(timedelta(hours=8))

# 列表 event_info.fuel_form。阶段 A 样本：1 汽油，4 纯电，6 插混（汉DM）。
BEV_FUEL_FORMS = {"4", "bev", "ev", "纯电", "电动"}
HYBRID_FUEL_FORMS = {"6", "phev", "reev", "hev", "插混", "增程", "混动"}

HYBRID_MARKERS = (
    "DM-i",
    "DM‑i",
    "DM-I",
    "DMi",
    "dmi",
    "插混",
    "混动",
    "增程",
    "PHEV",
    "HEV",
    "iDD",
)

# 微型/城市代步纯电车系（无法解析续航时也排除）
MICRO_BEV_SERIES = (
    "宏光MINIEV",
    "宏光 MINIEV",
    "MINIEV",
    "MINI EV",
    "奔奔E-Star",
    "奔奔E星",
    "奔奔 E-Star",
    "奔奔E",
    "奇瑞eQ",
    "eQ1",
    "长安Lumin",
    "Lumin",
    "熊猫",
    "五菱之光EV",
    "之光EV",
    "Air ev",
    "Air EV",
    "Air ev晴空",
    "KiWi",
    "宝骏E",
    "Baojun E",
    "BaojunE",
)

PURE_BEV_MARKERS = (
    "纯电",
    "磷酸铁锂",
    "磷酸铁锂电池",
)

# 标题里带单位的续航；另抓「续航xxx」
RANGE_PATTERNS = (
    re.compile(r"(\d{2,4})\s*(?:km|KM|Km|公里)", re.I),
    re.compile(r"续航\s*(\d{2,4})", re.I),
)

# 「海豹06DM」「唐DM」「宋Pro DM」等插混记号（避免被 EV/磷酸铁锂误伤）
DM_POWERTRAIN_RE = re.compile(r"(?<![A-Za-z])DM(?![A-Za-z])", re.I)
EV_TOKEN_RE = re.compile(r"(?<![A-Za-z])EV(?![A-Za-z])", re.I)


def _blob(item: dict[str, Any] | str) -> str:
    if isinstance(item, str):
        return item
    parts = [
        str(item.get("title") or ""),
        str(item.get("series") or ""),
        " ".join(str(t) for t in (item.get("tags") or [])),
        str(item.get("year") or ""),
        str(item.get("extra") or ""),
        " ".join(str(t) for t in (item.get("extras") or [])),
        str(item.get("banner") or ""),
    ]
    return " ".join(parts)


def is_hybrid_powertrain(text: str) -> bool:
    if any(m in text for m in HYBRID_MARKERS):
        return True
    # 唐DM / 海豹06DM / 宋Pro DM 等（排除 MINIEV 无 DM）
    if DM_POWERTRAIN_RE.search(text):
        return True
    return False


def is_micro_bev_series(text: str) -> bool:
    return any(k in text for k in MICRO_BEV_SERIES)


def _fuel_form(item: dict[str, Any] | str) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("fuel_form") or "").strip().lower()


def is_pure_bev(item: dict[str, Any] | str) -> bool:
    """动力为纯电：含纯电/EV/磷酸铁锂、fuel_form=4，或标题带「310km」这类续航款，且非插混/增程。"""
    text = _blob(item)
    fuel = _fuel_form(item)
    if fuel in HYBRID_FUEL_FORMS or is_hybrid_powertrain(text):
        return False
    if fuel in BEV_FUEL_FORMS:
        return True
    if is_micro_bev_series(text):
        return True
    if any(m in text for m in PURE_BEV_MARKERS):
        return True
    if EV_TOKEN_RE.search(text):
        return True
    # 懂车帝纯电车款常写成「310km 梦想版」，标题里不一定有「纯电」。插混的 55KM 已在上面排除。
    if re.search(r"(?<![A-Za-z0-9])(\d{2,4})\s*km\b", text, re.I):
        return True
    return False


def parse_bev_range_km(item: dict[str, Any] | str) -> int | None:
    text = _blob(item)
    found: list[int] = []
    for pat in RANGE_PATTERNS:
        for m in pat.finditer(text):
            for g in m.groups():
                if g:
                    found.append(int(g))
    if not found:
        return None
    # 插混纯电续航常见 55/71/80/120，不应当作 BEV 整车续航；
    # 本函数仅在 is_pure_bev 为真时使用，故取标题中出现的续航值（通常唯一）。
    # 若多个，取最大（如同时写 200km/CLTC）。
    return max(found)


def short_range_bev_reason(item: dict[str, Any] | str) -> str | None:
    """若应排除短续航纯电，返回原因；否则 None。"""
    if not is_pure_bev(item):
        return None
    text = _blob(item)
    rng = parse_bev_range_km(item)
    if rng is not None and rng <= MAX_BEV_RANGE_KM:
        return f"pure_bev_range_{rng}km_le_{MAX_BEV_RANGE_KM}"
    if rng is None and is_micro_bev_series(text):
        return "micro_city_bev_series_no_parsed_range"
    return None


def is_short_range_bev(item: dict[str, Any] | str) -> bool:
    return short_range_bev_reason(item) is not None



def badge_blob(item: dict[str, Any] | str) -> str:
    if isinstance(item, str):
        return item
    return " ".join(str(b) for b in (item.get("badges") or []))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _badge_is_zhiying(badge: Any) -> bool:
    text = str(badge or "").strip()
    if not text or "非直营" in text:
        return False
    return "直营" in text


def is_self_trade(item: dict[str, Any] | str) -> bool:
    """列表自营信号。is_self_trade_car 与 source_type_name 二者有一即可，缺字段不误杀。"""
    if not isinstance(item, dict):
        return str(item or "").strip().startswith("自营")
    if _truthy(item.get("is_self_trade_car")):
        return True
    return str(item.get("source_type_name") or "").strip().startswith("自营")


def is_zhiying(item: dict[str, Any] | str) -> bool:
    """直营，或与直营等价的自营信号。

    接受历史角标「直营」、is_self_trade_car 为真、source_type_name 以「自营」开头。
    标题或营销文案里出现「直营」不算，避免详情文案误收。
    """
    if not isinstance(item, dict):
        text = str(item or "").strip()
        return text.startswith("自营") or text == "直营" or (
            text.startswith("直营") and "直营车" not in text
        )
    if any(_badge_is_zhiying(badge) for badge in (item.get("badges") or [])):
        return True
    if item.get("zhiying") is True:
        return True
    return is_self_trade(item)


def non_zhiying_reason(item: dict[str, Any] | str) -> str | None:
    if is_zhiying(item):
        return None
    return "not_zhiying_or_self_trade"



def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def listing_price_wan(item: dict[str, Any]) -> float | None:
    """硬筛价：有详情现金价时只用现金价，避免列表券后价放行。"""
    if item.get("cash_price_wan") not in (None, ""):
        return _as_float(item.get("cash_price_wan"))
    return _as_float(item.get("price"))


def plate_year_of(item: dict[str, Any], today: date | None = None) -> int | None:
    today = today or date.today()
    for key in ("plate_year", "model_year"):
        raw = item.get(key)
        if raw in (None, ""):
            continue
        try:
            year = int(str(raw)[:4])
        except (TypeError, ValueError):
            continue
        if 1980 <= year <= today.year + 1:
            return year
    reg = item.get("first_registration_time") or item.get("plate_date")
    if isinstance(reg, str) and reg.isdigit():
        reg = int(reg)
    if isinstance(reg, (int, float)) and reg > 1_000_000_000:
        try:
            return datetime.fromtimestamp(int(reg), SHANGHAI).year
        except (OverflowError, OSError, ValueError):
            return None
    return None


def shop_reason(item: dict[str, Any]) -> str | None:
    shop = str(item.get("shop_id") or "").strip()
    if not shop:
        return "missing_shop_id"
    if shop != WUHAN_SHOP_ID:
        return f"shop_id_{shop}_not_{WUHAN_SHOP_ID}"
    return None


def price_reason(item: dict[str, Any]) -> str | None:
    price = listing_price_wan(item)
    if price is None or price <= 0:
        return "missing_cash_or_price"
    if price > MAX_PRICE_WAN + 1e-9:
        return f"price_{price:g}_gt_{MAX_PRICE_WAN:g}"
    return None


def mileage_reason(item: dict[str, Any]) -> str | None:
    mile = _as_float(item.get("mileage_wan"))
    if mile is None or mile < 0:
        return "missing_mileage"
    if mile > MAX_MILEAGE_WAN + 1e-9:
        return f"mileage_{mile:g}_gt_{MAX_MILEAGE_WAN:g}"
    return None


def age_reason(item: dict[str, Any], today: date | None = None) -> str | None:
    today = today or date.today()
    year = plate_year_of(item, today)
    if year is None:
        return "missing_plate_year"
    # 上牌年 >= 当年-10。车龄按整年，不精确到日。
    if year < today.year - MAX_AGE_YEARS:
        return f"plate_year_{year}_older_than_{MAX_AGE_YEARS}y"
    return None


def admission_reason(item: dict[str, Any], today: date | None = None) -> str | None:
    """全部硬筛。命中则不入库。"""
    return (
        shop_reason(item)
        or non_zhiying_reason(item)
        or price_reason(item)
        or mileage_reason(item)
        or age_reason(item, today)
        or short_range_bev_reason(item)
    )


def keep_listing(item: dict[str, Any], today: date | None = None) -> bool:
    """入库硬筛：本店、现金价、里程、车龄、直营/自营、短续航纯电。"""
    return admission_reason(item, today=today) is None



def filter_listings(
    listings: list[dict[str, Any]],
    today: date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in listings:
        reason = admission_reason(item, today=today)
        if reason:
            excluded.append(
                {
                    "sku": item.get("sku"),
                    "title": item.get("title"),
                    "price": listing_price_wan(item),
                    "series": item.get("series"),
                    "badges": item.get("badges"),
                    "shop_id": item.get("shop_id"),
                    "reason": reason,
                    "parsed_range_km": parse_bev_range_km(item),
                }
            )
        else:
            kept.append(item)
    return kept, excluded



FILTER_META = {
    "shop_id": WUHAN_SHOP_ID,
    "price_max_wan": MAX_PRICE_WAN,
    "mileage_max_wan": MAX_MILEAGE_WAN,
    "age_max_years": MAX_AGE_YEARS,
    "require_zhiying": True,
    "require_zhiying_desc": (
        "直营角标，或列表 is_self_trade_car / source_type_name 以「自营」开头；"
        "非自营且非直营不入库。标题里的「直营」营销字样不算。"
    ),
    "exclude_short_range_bev": True,
    "max_bev_range_km": MAX_BEV_RANGE_KM,
    "exclude_short_range_bev_desc": (
        f"排除续航≤{MAX_BEV_RANGE_KM}km 的纯电，以及无法解析续航的微型/城市代步纯电"
        "（宏光MINIEV/Lumin/熊猫/之光EV/Air ev 等）；插混/增程与续航>300 纯电保留"
    ),
}



if __name__ == "__main__":
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    path = root / "data" / "listings-ranked.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    kept, excluded = filter_listings(data)
    print(f"in={len(data)} kept={len(kept)} excluded={len(excluded)}")
    for e in excluded:
        print(f" - {e['reason']:40} | {e['price']} | {e['title']}")
