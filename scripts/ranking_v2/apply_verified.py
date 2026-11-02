"""Apply V3 exact-trim vehicle data to listings.

Configuration policy:
- Exact-trim data in data/vehicle-specs-verified.json is the only source used
  for configuration scoring.
- Legacy/approximate configuration fields on listings are never used as a
  fallback.
- Unknown values remain None and therefore do not earn configuration points.
"""
from __future__ import annotations

import copy
from typing import Any

from .config import FINANCE


def effective_price_fields(
    display_price: float,
    price_type: str | None,
    cash_price: float | None = None,
    finance_all_in: float | None = None,
    reserve: float | None = None,
) -> dict[str, Any]:
    reserve = FINANCE["unknown_all_in_reserve_wan"] if reserve is None else reserve
    pt = (price_type or "标价").strip()
    if cash_price is not None:
        return {
            "display_price_wan": display_price,
            "effective_price_wan": float(cash_price),
            "price_confidence": 0.95,
            "needs_cash_quote": False,
            "price_basis": "cash",
        }
    if finance_all_in is not None:
        return {
            "display_price_wan": display_price,
            "effective_price_wan": float(finance_all_in),
            "price_confidence": 0.85,
            "needs_cash_quote": False,
            "price_basis": "finance_all_in",
        }
    if pt == "分期":
        return {
            "display_price_wan": display_price,
            "effective_price_wan": round(float(display_price) + reserve, 2),
            "price_confidence": 0.5,
            "needs_cash_quote": True,
            "price_basis": "finance_display_plus_reserve",
            "finance_reserve_wan": reserve,
        }
    conf = 0.85 if pt == "券后" else 0.9
    return {
        "display_price_wan": display_price,
        "effective_price_wan": float(display_price),
        "price_confidence": conf,
        "needs_cash_quote": False,
        "price_basis": "display",
    }


def _tri_or(values: list[Any]) -> bool | None:
    known = [v for v in values if v is not None]
    if not known:
        return None
    if any(v is True for v in known):
        return True
    if all(v is False for v in known):
        return False
    return None


def _airbag_count(passive: dict[str, Any]) -> int | None:
    keys = ("front_airbags", "front_side_airbags", "curtain_airbags")
    vals = [passive.get(k) for k in keys]
    if any(v is None for v in vals):
        return None
    return sum(2 for v in vals if v is True)


def _is_panorama(sunroof: Any) -> bool | None:
    if sunroof is None:
        return None
    if sunroof is False:
        return False
    s = str(sunroof).strip().lower()
    if not s:
        return None
    if "panoramic" in s or "全景" in s:
        return True
    if s in ("none", "无", "false"):
        return False
    return False


def _is_dual_zone(climate: Any) -> bool | None:
    if climate is None:
        return None
    s = str(climate).strip().lower()
    if not s:
        return None
    if any(x in s for x in ("dual", "multi_zone", "multi-zone", "双区", "多区")):
        return True
    if any(x in s for x in ("manual", "single", "手动", "单区")):
        return False
    return None


def _cruise_value(cruise: Any) -> str | None:
    if cruise is None:
        return None
    s = str(cruise).strip().lower()
    if not s or s in ("none", "无", "false"):
        return None
    if "full_speed_adaptive" in s or "全速" in s:
        return "全速自适应巡航"
    if "adaptive" in s or s == "acc" or "自适应" in s:
        return "ACC自适应巡航"
    if "fixed" in s or "定速" in s:
        return "定速巡航"
    return str(cruise)


def _normalize_features(trim_features: dict[str, Any]) -> dict[str, Any]:
    passive = trim_features.get("passive_safety") or {}
    active = trim_features.get("active_safety") or {}
    park = trim_features.get("parking_adas") or {}
    comfort = trim_features.get("comfort") or {}
    info = trim_features.get("infotainment") or {}

    carplay = info.get("carplay")
    carlife = info.get("carlife")
    phone_link = _tri_or([carplay, carlife])

    return {
        "airbags": _airbag_count(passive),
        "esp": None,
        "aeb": active.get("aeb"),
        "fcw": active.get("fcw"),
        "ldw": active.get("ldw"),
        "lka": active.get("lka"),
        "lane_centering": active.get("lane_centering"),
        "bsd": active.get("bsd"),
        "dow": active.get("dow"),
        "acc": True if (park.get("cruise") in ("adaptive", "full_speed_adaptive", "acc")) else (
            False if park.get("cruise") in ("fixed", "none", False) else None
        ),
        "cruise": _cruise_value(park.get("cruise")),
        "camera_360": park.get("surround_360"),
        "transparent_chassis": park.get("transparent_chassis_540"),
        "front_radar": park.get("front_parking_radar"),
        "rear_radar": park.get("rear_parking_radar"),
        "auto_park": park.get("auto_park"),
        "remote_park": park.get("remote_park"),
        "power_driver_seat": comfort.get("driver_power_seat"),
        "power_passenger_seat": comfort.get("passenger_power_seat"),
        "seat_heating": comfort.get("front_seat_heating"),
        "seat_ventilation": comfort.get("front_seat_ventilation"),
        "panoramic_sunroof": _is_panorama(comfort.get("sunroof")),
        "power_tailgate": comfort.get("power_tailgate"),
        "keyless_entry": comfort.get("keyless_entry"),
        "remote_start": comfort.get("remote_start"),
        "rear_ac_vents": comfort.get("rear_air_vents"),
        "dual_zone_climate": _is_dual_zone(comfort.get("climate_control")),
        "leather_seats": None,
        "full_lcd_cluster": None,
        "screen_inch": info.get("center_screen_inches"),
        "carplay": carplay,
        "carlife": carlife,
        "phone_link": phone_link,
        "wireless_charge": comfort.get("wireless_phone_charging"),
        "voice_control": None,
        "ota": info.get("ota"),
        "hud": comfort.get("hud"),
        "chip_8155": None,
    }


def _verified_specs_from_trim(trim: dict[str, Any]) -> dict[str, Any]:
    core = trim.get("core_specs") or {}
    dq = trim.get("data_quality") or {}
    specs: dict[str, Any] = {}

    for k in (
        "length_mm",
        "width_mm",
        "height_mm",
        "wheelbase_mm",
        "seats",
        "body_type",
        "engine",
        "transmission",
        "fuel_grade",
        "official_fuel_l_100km",
        "official_standard",
        "low_soc_fuel_l_100km",
        "real_world_fuel_l_100km",
        "real_world_sample_n",
        "electric_kwh_100km",
        "ev_range_km",
        "ev_range_standard",
        "ranking_energy",
    ):
        if k in core:
            specs[k] = core.get(k)

    powertrain = core.get("powertrain")
    if powertrain:
        specs["powertrain"] = powertrain
        specs["powertrain_type"] = powertrain

    normalized = _normalize_features(trim.get("features") or {})
    specs["features"] = normalized
    for k in ("airbags", "screen_inch"):
        specs[k] = normalized.get(k)

    specs.update(
        {
            "match_level": "exact_trim",
            "trim_id": trim.get("trim_id"),
            "canonical_title": trim.get("canonical_title"),
            "specs_found": True,
            "specs_approx": False,
            "verified": True,
            "verification_schema": "3.0-exact-trim-detailed",
            "configuration_source": "exact_trim_v3",
            "core_confidence": dq.get("core_confidence"),
            "feature_confidence": 0.95 if dq.get("feature_confidence") == "high" else 0.75,
            "verification_issues": dq.get("known_issues") or [],
            "verification_sources": trim.get("sources") or [],
        }
    )
    return specs


def apply_verified_record(item: dict[str, Any], verified: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(item)
    trim = verified.get("trim") or verified
    item["specs"] = _verified_specs_from_trim(trim)
    item["detailed_config"] = item["specs"]
    return item


def sanitize_unverified_listing(item: dict[str, Any]) -> dict[str, Any]:
    """Keep listing/core metadata but remove every legacy config claim."""
    item = copy.deepcopy(item)
    specs = copy.deepcopy(item.get("specs") or {})
    specs["features"] = {}
    for k in (
        "airbags", "esp", "aeb", "fcw", "ldw", "lka", "lane_centering",
        "bsd", "dow", "acc", "cruise", "camera_360", "front_radar",
        "rear_radar", "auto_park", "power_driver_seat", "power_passenger_seat",
        "seat_heating", "seat_ventilation", "panoramic_sunroof", "power_tailgate",
        "keyless_entry", "remote_start", "rear_ac_vents", "dual_zone_climate",
        "leather_seats", "full_lcd_cluster", "screen_inch", "carplay", "hicar",
        "phone_link", "android_auto", "wireless_charge", "voice_control", "ota",
        "hud", "chip_8155",
    ):
        specs.pop(k, None)
    specs["specs_found"] = False
    specs["specs_approx"] = False
    specs["verified"] = False
    specs["configuration_source"] = "unverified_v3"
    specs["configuration_unverified"] = True
    specs["feature_confidence"] = 0.0
    specs["match_level"] = "unverified_config"
    specs["verification_issues"] = ["详细配置数据不足"]
    item["specs"] = specs
    item["detailed_config"] = specs
    return item


def load_verified_by_sku(path) -> dict[str, dict]:
    import json
    from pathlib import Path

    index_path = Path(path)
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "3.0-exact-trim":
        raise ValueError(f"unsupported verified spec schema: {data.get('schema_version')}")

    trims: dict[str, dict] = {}
    for rel in data.get("trim_files") or []:
        shard_path = index_path.parent / str(rel)
        shard = json.loads(shard_path.read_text(encoding="utf-8"))
        for trim_id, trim in (shard.get("trims") or {}).items():
            trim = dict(trim)
            trim["trim_id"] = trim_id
            dq = trim.setdefault("data_quality", {})
            dq.setdefault("core_confidence", 0.95)
            dq.setdefault("feature_confidence", "high")
            trims[str(trim_id)] = trim

    out: dict[str, dict] = {}
    for sku, trim_id in (data.get("sku_to_trim") or {}).items():
        trim = trims.get(str(trim_id))
        if trim:
            out[str(sku)] = {"listing": {"sku": str(sku), "trim_id": str(trim_id)}, "trim": trim}
    return out


def apply_verified_to_listings(
    listings: list[dict[str, Any]],
    verified_by_sku: dict[str, dict],
) -> list[dict[str, Any]]:
    out = []
    for item in listings:
        sku = str(item.get("sku") or "")
        if sku in verified_by_sku:
            item = apply_verified_record(item, verified_by_sku[sku])
        else:
            item = sanitize_unverified_listing(item)

        ep = effective_price_fields(
            float(item.get("price") or 0),
            item.get("price_type"),
            cash_price=item.get("cash_price_wan"),
            finance_all_in=item.get("finance_all_in_price_wan"),
        )
        item.update(ep)
        out.append(item)
    return out
