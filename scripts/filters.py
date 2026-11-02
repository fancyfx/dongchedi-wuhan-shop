#!/usr/bin/env python3
"""Hard filters for Wuhan shop listings (shop_id=118608).

叠加规则：价格≤6万、里程≤10万公里、车龄≤10年，以及排除短续航纯电。
晨检/入库脚本应调用 is_short_range_bev / keep_listing，命中则不入库。
"""
from __future__ import annotations

import re
from typing import Any

MAX_BEV_RANGE_KM = 300

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


def is_pure_bev(item: dict[str, Any] | str) -> bool:
    """动力为纯电：含纯电/EV/磷酸铁锂等，且非插混/增程；或属微型纯电车系。"""
    text = _blob(item)
    if is_hybrid_powertrain(text):
        return False
    if is_micro_bev_series(text):
        return True
    if any(m in text for m in PURE_BEV_MARKERS):
        return True
    if EV_TOKEN_RE.search(text):
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
    text = _blob(item)
    if not is_pure_bev(text):
        return None
    rng = parse_bev_range_km(text)
    if rng is not None and rng <= MAX_BEV_RANGE_KM:
        return f"pure_bev_range_{rng}km_le_{MAX_BEV_RANGE_KM}"
    if rng is None and is_micro_bev_series(text):
        return "micro_city_bev_series_no_parsed_range"
    return None


def is_short_range_bev(item: dict[str, Any] | str) -> bool:
    return short_range_bev_reason(item) is not None


def keep_listing(item: dict[str, Any]) -> bool:
    """入库硬筛：短续航纯电不入库（其余价格/里程/车龄由抓取侧保证）。"""
    return not is_short_range_bev(item)


def filter_listings(
    listings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in listings:
        reason = short_range_bev_reason(item)
        if reason:
            excluded.append(
                {
                    "sku": item.get("sku"),
                    "title": item.get("title"),
                    "price": item.get("price"),
                    "series": item.get("series"),
                    "reason": reason,
                    "parsed_range_km": parse_bev_range_km(item),
                }
            )
        else:
            kept.append(item)
    return kept, excluded


FILTER_META = {
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
