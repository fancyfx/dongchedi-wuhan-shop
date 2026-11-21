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
from shops import compute_landed_costs, compute_landed_price_wan


def ensure_landed_cost_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Ensure direct-shop landed cost fields exist without overwriting verified API fees."""
    shop_id = str(item.get("shop_id") or "").strip()
    costs = compute_landed_costs(
        shop_id,
        city=item.get("city"),
        api_logistics_yuan=item.get("logistics_fee_yuan"),
        api_plate_fee_yuan=item.get("plate_service_fee_yuan"),
    )
    if item.get("is_local_wuhan") is None:
        item["is_local_wuhan"] = costs["is_local_wuhan"]
    if not item.get("shop_short_name"):
        item["shop_short_name"] = costs["shop_short_name"]
    if not item.get("city"):
        item["city"] = costs["shop_city"]
    if item.get("logistics_fee_yuan") is None or (not costs["is_local_wuhan"] and int(item.get("logistics_fee_yuan") or 0) <= 0):
        item["logistics_fee_yuan"] = costs["logistics_fee_yuan"]
        item["logistics_fee_source"] = costs["logistics_fee_source"]
    elif not item.get("logistics_fee_source"):
        item["logistics_fee_source"] = costs["logistics_fee_source"]
    if item.get("plate_service_fee_yuan") is None:
        item["plate_service_fee_yuan"] = costs["plate_service_fee_yuan"]
    if item.get("plate_fee_diff_yuan") is None:
        item["plate_fee_diff_yuan"] = costs["plate_fee_diff_yuan"]
    if item.get("landed_extra_yuan") is None or (not costs["is_local_wuhan"] and int(item.get("landed_extra_yuan") or 0) <= 0):
        item["landed_extra_yuan"] = costs["landed_extra_yuan"]
        item["landed_extra_wan"] = costs["landed_extra_wan"]
    elif item.get("landed_extra_wan") is None:
        item["landed_extra_wan"] = round(float(item["landed_extra_yuan"]) / 10000.0, 4)
    base_wan = item.get("cash_price_wan") if item.get("cash_price_wan") not in (None, "") else item.get("price")
    if base_wan not in (None, ""):
        item["landed_price_wan"] = compute_landed_price_wan(float(base_wan), item["landed_extra_yuan"])
    return item


def effective_price_fields(
    display_price: float,
    price_type: str | None,
    cash_price: float | None = None,
    finance_all_in: float | None = None,
    reserve: float | None = None,
    landed_extra_yuan: int | float = 0,
) -> dict[str, Any]:
    reserve = FINANCE["unknown_all_in_reserve_wan"] if reserve is None else reserve
    extra_yuan = max(0, int(round(float(landed_extra_yuan or 0))))
    pt = (price_type or "标价").strip()
    if cash_price is not None:
        eff = compute_landed_price_wan(float(cash_price), extra_yuan)
        return {
            "display_price_wan": display_price,
            "cash_price_wan": float(cash_price),
            "landed_extra_yuan": extra_yuan,
            "landed_price_wan": eff,
            "effective_price_wan": eff,
            "price_confidence": 0.95,
            "needs_cash_quote": False,
            "price_basis": "cash_plus_landed" if extra_yuan > 0 else "cash",
        }
    if finance_all_in is not None:
        eff = compute_landed_price_wan(float(finance_all_in), extra_yuan)
        return {
            "display_price_wan": display_price,
            "landed_extra_yuan": extra_yuan,
            "landed_price_wan": eff,
            "effective_price_wan": eff,
            "price_confidence": 0.85,
            "needs_cash_quote": False,
            "price_basis": "finance_all_in",
        }
    if pt == "分期":
        eff = compute_landed_price_wan(float(display_price) + reserve, extra_yuan)
        return {
            "display_price_wan": display_price,
            "landed_extra_yuan": extra_yuan,
            "landed_price_wan": eff,
            "effective_price_wan": eff,
            "price_confidence": 0.5,
            "needs_cash_quote": True,
            "price_basis": "finance_display_plus_reserve",
            "finance_reserve_wan": reserve,
        }
    conf = 0.85 if pt == "券后" else 0.9
    eff = compute_landed_price_wan(float(display_price), extra_yuan)
    return {
        "display_price_wan": display_price,
        "landed_extra_yuan": extra_yuan,
        "landed_price_wan": eff,
        "effective_price_wan": eff,
        "price_confidence": conf,
        "needs_cash_quote": False,
        "price_basis": "display_plus_landed" if extra_yuan > 0 else "display",
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
    phone_link = info.get("phone_link")
    if phone_link is None:
        phone_link = _tri_or([carplay, carlife])

    return {
        "airbags": _airbag_count(passive),
        "esp": active.get("esp"),
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
        "leather_seats": comfort.get("leather_seats"),
        "full_lcd_cluster": info.get("full_lcd_cluster"),
        "screen_inch": info.get("center_screen_inches"),
        "carplay": carplay,
        "carlife": carlife,
        "phone_link": phone_link,
        "wireless_charge": comfort.get("wireless_phone_charging"),
        "voice_control": info.get("voice_control"),
        "ota": info.get("ota"),
        "hud": comfort.get("hud"),
        "chip_8155": info.get("chip_8155"),
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
            "msrp_wan": trim.get("msrp_wan"),
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


def enrich_specs_with_live_tree(item: dict[str, Any], *, allow_title_match: bool = True) -> dict[str, Any]:
    """Attach live-config mechanical metadata, or recover exact specs for unindexed trims."""
    from .live_specs import build_specs_from_live_profile, extract_live_profile, resolve_spec_id

    specs = dict(item.get("specs") or {})
    exact = (
        specs.get("match_level") == "exact_trim"
        and specs.get("verified") is True
        and specs.get("specs_found") is True
        and specs.get("configuration_source") == "exact_trim_v3"
    )
    for src in specs.get("verification_sources") or []:
        if isinstance(src, dict) and src.get("spec_id"):
            break
    spec_id = resolve_spec_id(item, allow_title_match=allow_title_match and not exact)
    profile = extract_live_profile(str(spec_id)) if spec_id else None
    if not profile:
        return item

    item = copy.deepcopy(item)
    if not exact:
        built = build_specs_from_live_profile(profile)
        item["specs"] = built
        item["detailed_config"] = built
        specs = built
    else:
        if specs.get("msrp_wan") is None and profile.get("msrp_wan") is not None:
            specs["msrp_wan"] = profile["msrp_wan"]
        if str(specs.get("engine") or "").strip() in ("", "●") and profile.get("engine_text"):
            specs["engine"] = profile["engine_text"]
        if not specs.get("body_type") and profile.get("body_type"):
            specs["body_type"] = profile["body_type"]
        if specs.get("wheelbase_mm") is None and profile.get("wheelbase_mm") is not None:
            specs["wheelbase_mm"] = profile["wheelbase_mm"]
        if specs.get("length_mm") is None and profile.get("length_mm") is not None:
            specs["length_mm"] = profile["length_mm"]
        if specs.get("width_mm") is None and profile.get("width_mm") is not None:
            specs["width_mm"] = profile["width_mm"]
        if specs.get("height_mm") is None and profile.get("height_mm") is not None:
            specs["height_mm"] = profile["height_mm"]
        if specs.get("seats") is None and profile.get("seats") is not None:
            specs["seats"] = profile["seats"]
        if specs.get("low_soc_fuel_l_100km") is None and profile.get("low_soc_fuel_l_100km") is not None:
            specs["low_soc_fuel_l_100km"] = profile["low_soc_fuel_l_100km"]
            if specs.get("powertrain") == "phev" and not specs.get("ranking_energy"):
                specs["ranking_energy"] = {
                    "type": "low_soc_fuel",
                    "value": profile["low_soc_fuel_l_100km"],
                    "unit": "L/100km",
                }

    for k in (
        "engine_model",
        "cylinders",
        "intake",
        "fuel_injection",
        "horsepower_ps",
        "torque_nm",
        "transmission_type",
        "transmission_short",
        "rear_suspension",
        "drive_type",
        "energy_type",
        "battery_type",
        "knee_airbag",
        "has_reverse_camera",
        "has_fixed_cruise",
    ):
        val = profile.get(k)
        if val not in (None, ""):
            specs[k] = val
    specs["live_spec_id"] = profile["spec_id"]
    item["specs"] = specs
    item["detailed_config"] = specs
    return item


def apply_verified_record(item: dict[str, Any], verified: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(item)
    trim = verified.get("trim") or verified
    item["specs"] = _verified_specs_from_trim(trim)
    item["detailed_config"] = item["specs"]
    return enrich_specs_with_live_tree(item, allow_title_match=False)


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
            if item.get("title"):
                item = enrich_specs_with_live_tree(item, allow_title_match=True)
            if not (
                (item.get("specs") or {}).get("match_level") == "exact_trim"
                and (item.get("specs") or {}).get("verified") is True
            ):
                item = sanitize_unverified_listing(item)

        item = ensure_landed_cost_fields(item)
        ep = effective_price_fields(
            float(item.get("price") or 0),
            item.get("price_type"),
            cash_price=item.get("cash_price_wan"),
            finance_all_in=item.get("finance_all_in_price_wan"),
            landed_extra_yuan=item.get("landed_extra_yuan") or 0,
        )
        item.update(ep)
        out.append(item)
    return out
