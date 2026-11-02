"""V2 config score: point table + coverage shrink to 50. No powertrain_value."""
from __future__ import annotations

from typing import Any

from .config import CONFIG_POINTS, CONFIG_POINTS_MAX


def _feat(specs: dict, *keys: str) -> bool | None:
    """True/False if known, None if unknown."""
    feats = specs.get("features") or {}
    for k in keys:
        if k in feats:
            v = feats[k]
        elif k in specs:
            v = specs[k]
        else:
            continue
        if v is None:
            return None
        if v is True:
            return True
        if v is False:
            return False
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return True if v > 0 else False
        if isinstance(v, str):
            s = v.strip()
            if not s or s in ("-", "无", "否"):
                return False
            return True
    return None


def _cruise_is_acc(specs: dict) -> bool | None:
    feats = specs.get("features") or {}
    cruise = feats.get("cruise", specs.get("cruise"))
    if cruise is None:
        # explicit acc flag
        return _feat(specs, "acc")
    if cruise is False:
        return False
    cs = str(cruise).lower()
    if any(t in cs for t in ("acc", "自适应", "iacc", "全速", "智驾")):
        return True
    if "定速" in cs:
        return False
    return None


def _verified_points(specs: dict) -> tuple[float, float, dict]:
    """Return (earned_points, verified_weight, detail). null keys don't count as verified."""
    earned = 0.0
    verified_w = 0.0
    detail = {}

    def add(name: str, present: bool | None):
        nonlocal earned, verified_w
        w = float(CONFIG_POINTS[name])
        if present is None:
            detail[name] = "unknown"
            return
        verified_w += w
        if present:
            earned += w
            detail[name] = "yes"
        else:
            detail[name] = "no"

    airbags = specs.get("airbags")
    if airbags is None:
        airbags = (specs.get("features") or {}).get("airbags")
    if airbags is None:
        detail["airbags_6plus"] = "unknown"
    else:
        try:
            add("airbags_6plus", int(airbags) >= 6)
        except (TypeError, ValueError):
            detail["airbags_6plus"] = "unknown"

    add("esp", _feat(specs, "esp"))
    add("aeb", _feat(specs, "aeb"))
    add("fcw", _feat(specs, "fcw"))
    add("lka", _feat(specs, "lka"))
    add("lane_centering", _feat(specs, "lane_centering"))
    add("bsd", _feat(specs, "bsd"))
    add("dow", _feat(specs, "dow"))
    add("acc", _cruise_is_acc(specs))
    add("camera_360", _feat(specs, "camera_360"))

    fr = _feat(specs, "front_radar")
    rr = _feat(specs, "rear_radar")
    if fr is None and rr is None:
        detail["radar_front_rear"] = "unknown"
    else:
        # if either known false and other unknown -> treat carefully
        if fr is True and rr is True:
            add("radar_front_rear", True)
        elif fr is False and rr is False:
            add("radar_front_rear", False)
        elif fr is True or rr is True:
            # partial — count as verified present with half? Doc says 前+后雷达
            # require both; if only one known true and other unknown -> unknown
            if fr is not None and rr is not None:
                add("radar_front_rear", bool(fr and rr))
            else:
                detail["radar_front_rear"] = "unknown"
                # don't add to verified
        else:
            detail["radar_front_rear"] = "unknown"

    add("auto_park", _feat(specs, "auto_park"))
    add("power_driver_seat", _feat(specs, "power_driver_seat"))
    add("power_passenger_seat", _feat(specs, "power_passenger_seat"))
    add("seat_heating", _feat(specs, "seat_heating"))
    add("seat_ventilation", _feat(specs, "seat_ventilation"))
    add("panoramic_sunroof", _feat(specs, "panoramic_sunroof"))
    add("power_tailgate", _feat(specs, "power_tailgate"))
    add("keyless_entry", _feat(specs, "keyless_entry"))
    add("remote_start", _feat(specs, "remote_start"))
    add("rear_ac_vents", _feat(specs, "rear_ac_vents"))
    add("dual_zone_climate", _feat(specs, "dual_zone_climate"))
    add("leather_seats", _feat(specs, "leather_seats"))
    add("full_lcd_cluster", _feat(specs, "full_lcd_cluster"))

    screen = specs.get("screen_inch")
    if screen is None:
        screen = (specs.get("features") or {}).get("screen_inch")
    if screen is None:
        detail["screen_12plus"] = "unknown"
    else:
        try:
            add("screen_12plus", float(screen) >= 12)
        except (TypeError, ValueError):
            detail["screen_12plus"] = "unknown"

    phone = _feat(specs, "carplay", "hicar", "phone_link", "android_auto")
    add("phone_link", phone)
    add("wireless_charge", _feat(specs, "wireless_charge"))
    add("voice_control", _feat(specs, "voice_control"))
    add("ota", _feat(specs, "ota"))
    add("hud", _feat(specs, "hud"))
    add("chip_8155", _feat(specs, "chip_8155"))

    return earned, verified_w, detail


def config_score(specs: dict[str, Any] | None) -> dict[str, Any]:
    specs = specs or {}
    match_level = (specs.get("match_level") or "").lower()

    # series_only / unknown: no config evidence
    if match_level in ("series_only", "unknown", "") and not specs.get("specs_found"):
        return {
            "config_score": 50.0,
            "config_raw": 50.0,
            "coverage": 0.0,
            "earned_points": 0.0,
            "verified_weight": 0.0,
            "detail": {},
            "note": "无可靠配置来源，收缩到中性50",
        }

    # For series_year_tier, advanced features should already be null'd;
    # coverage will be low → shrink to 50.
    earned, verified_w, detail = _verified_points(specs)
    total_w = float(CONFIG_POINTS_MAX)
    coverage = verified_w / total_w if total_w else 0.0
    raw = (earned / total_w * 100.0) if total_w else 50.0
    # shrink unknown toward 50
    score = 50.0 + coverage * (raw - 50.0)
    return {
        "config_score": round(score, 2),
        "config_raw": round(raw, 2),
        "coverage": round(coverage, 4),
        "earned_points": round(earned, 2),
        "verified_weight": round(verified_w, 2),
        "detail": detail,
    }
