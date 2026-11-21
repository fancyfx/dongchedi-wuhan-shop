#!/usr/bin/env python3
"""Direct-operated Dongchedi shops registry (Plan A: Central China + low-freight) & landed cost helpers."""
from __future__ import annotations

from typing import Any

BUYER_CITY = "武汉"
BUYER_CITY_CODE = 420100
WUHAN_SHOP_ID = "118608"

LOCAL_PLATE_FEE_YUAN = 500
REMOTE_PLATE_FEE_DEFAULT_YUAN = 1000
DEFAULT_REMOTE_LOGISTICS_YUAN = 1000

DIRECT_SHOPS: dict[str, dict[str, Any]] = {
    "118608": {
        "shop_id": "118608",
        "name": "懂车帝汽车商城•武汉店",
        "short_name": "武汉店",
        "city": "武汉",
        "kind": "直营大店",
        "is_local": True,
        "fallback_logistics_yuan": 0,
    },
    "196923": {
        "shop_id": "196923",
        "name": "懂车帝汽车商城•长沙仓",
        "short_name": "长沙仓",
        "city": "长沙",
        "kind": "直营仓",
        "is_local": False,
        "fallback_logistics_yuan": 750,
    },
    "64909": {
        "shop_id": "64909",
        "name": "懂车帝汽车商城•合肥店",
        "short_name": "合肥店",
        "city": "合肥",
        "kind": "直营大店",
        "is_local": False,
        "fallback_logistics_yuan": 840,
    },
    "179450": {
        "shop_id": "179450",
        "name": "懂车帝汽车商城•南京仓",
        "short_name": "南京仓",
        "city": "南京",
        "kind": "直营仓",
        "is_local": False,
        "fallback_logistics_yuan": 1180,
    },
    "175870": {
        "shop_id": "175870",
        "name": "懂车帝汽车商城•郑州仓",
        "short_name": "郑州仓",
        "city": "郑州",
        "kind": "直营仓",
        "is_local": False,
        "fallback_logistics_yuan": 1200,
    },
    "225430": {
        "shop_id": "225430",
        "name": "懂车帝汽车商城•重庆旗舰店",
        "short_name": "重庆旗舰店",
        "city": "重庆",
        "kind": "直营大店",
        "is_local": False,
        "fallback_logistics_yuan": 1300,
    },
    "183004": {
        "shop_id": "183004",
        "name": "懂车帝汽车商城•成都仓",
        "short_name": "成都仓",
        "city": "成都",
        "kind": "直营仓",
        "is_local": False,
        "fallback_logistics_yuan": 1300,
    },
}

PLAN_A_SHOP_IDS: tuple[str, ...] = tuple(DIRECT_SHOPS.keys())
ALLOWED_SHOP_IDS: frozenset[str] = frozenset(PLAN_A_SHOP_IDS)


def shop_meta(shop_id: str | None) -> dict[str, Any] | None:
    if not shop_id:
        return None
    return DIRECT_SHOPS.get(str(shop_id).strip())


def parse_shop_list_arg(raw: str | None) -> list[str]:
    """Parse --shops CLI argument ('plan_a' or comma-separated shop IDs)."""
    text = str(raw or "").strip()
    if not text or text.lower() in {"plan_a", "all"}:
        return list(PLAN_A_SHOP_IDS)
    out: list[str] = []
    for part in text.split(","):
        sid = part.strip()
        if sid and sid not in out:
            out.append(sid)
    return out or list(PLAN_A_SHOP_IDS)


def _to_int_yuan(val: Any) -> int | None:
    if val is None or isinstance(val, bool) or val == "":
        return None
    try:
        num = float(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return int(round(num))


def compute_landed_costs(
    shop_id: str | None,
    *,
    city: str | None = None,
    api_logistics_yuan: int | float | None = None,
    api_plate_fee_yuan: int | float | None = None,
) -> dict[str, Any]:
    """Compute landed logistics + plate fee diff to Wuhan for one listing."""
    sid = str(shop_id or "").strip()
    meta = shop_meta(sid)
    shop_city = str((meta or {}).get("city") or city or "").strip() or BUYER_CITY
    shop_short_name = str((meta or {}).get("short_name") or (f"{shop_city}直营" if shop_city else "直营店"))
    is_local = (sid == WUHAN_SHOP_ID) or (not sid and shop_city == BUYER_CITY)

    api_logi = _to_int_yuan(api_logistics_yuan)
    api_plate = _to_int_yuan(api_plate_fee_yuan)

    if is_local:
        logistics_fee_yuan = 0
        logistics_fee_source = "local_wuhan"
        plate_service_fee_yuan = api_plate if (api_plate is not None and api_plate >= 0) else LOCAL_PLATE_FEE_YUAN
        plate_fee_diff_yuan = 0
    else:
        if api_logi is not None and api_logi > 0:
            logistics_fee_yuan = api_logi
            logistics_fee_source = "api"
        elif meta and meta.get("fallback_logistics_yuan") not in (None, 0):
            logistics_fee_yuan = int(meta["fallback_logistics_yuan"])
            logistics_fee_source = "city_cache"
        else:
            logistics_fee_yuan = DEFAULT_REMOTE_LOGISTICS_YUAN
            logistics_fee_source = "default_1000"

        plate_service_fee_yuan = (
            api_plate if (api_plate is not None and api_plate > 0) else REMOTE_PLATE_FEE_DEFAULT_YUAN
        )
        plate_fee_diff_yuan = max(0, plate_service_fee_yuan - LOCAL_PLATE_FEE_YUAN)

    landed_extra_yuan = logistics_fee_yuan + plate_fee_diff_yuan
    return {
        "is_local_wuhan": is_local,
        "shop_short_name": shop_short_name,
        "shop_city": shop_city,
        "logistics_fee_yuan": logistics_fee_yuan,
        "logistics_fee_source": logistics_fee_source,
        "plate_service_fee_yuan": plate_service_fee_yuan,
        "plate_fee_diff_yuan": plate_fee_diff_yuan,
        "landed_extra_yuan": landed_extra_yuan,
        "landed_extra_wan": round(landed_extra_yuan / 10000.0, 4),
    }


def compute_landed_price_wan(base_price_wan: float, landed_extra_yuan: int | float) -> float:
    return round(float(base_price_wan) + float(landed_extra_yuan or 0) / 10000.0, 2)
