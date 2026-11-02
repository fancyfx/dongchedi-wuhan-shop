#!/usr/bin/env python3
"""Score listings from real trim-level specs (not title tier-word heuristics).

Config proxy weights (documented in meta):
  safety 25% | adas 25% | comfort 20% | cabin_tech 15% | powertrain_value 15%
Each sub-score is 0–100 from boolean/enum features in `specs`.
Space/fuel proxies prefer measured dimensions / official fuel figures when present.
"""
from __future__ import annotations

from typing import Any


CONFIG_WEIGHTS = {
    "safety": 0.25,
    "adas": 0.25,
    "comfort": 0.20,
    "cabin_tech": 0.15,
    "powertrain_value": 0.15,
}

TOTAL_WEIGHTS = {
    "config": 0.40,
    "space": 0.25,
    "fuel": 0.15,
    "price": 0.15,
    "suv": 0.05,
}


def _b(specs: dict, *keys: str) -> bool:
    feats = specs.get("features") or {}
    for k in keys:
        v = feats.get(k, specs.get(k))
        if v is True:
            return True
        if isinstance(v, (int, float)) and v > 0:
            return True
        if isinstance(v, str) and v.strip() and v not in ("-", "无", "否"):
            return True
    return False


def _n(specs: dict, key: str, default: float | None = None) -> float | None:
    v = specs.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def safety_score(specs: dict) -> float:
    airbags = int(_n(specs, "airbags", 2) or 2)
    pts = 0.0
    pts += min(40.0, airbags / 6.0 * 40.0)
    for k, w in (
        ("esp", 12),
        ("tpms", 8),
        ("isofix", 6),
        ("aeb", 16),
        ("fcw", 8),
        ("ldw", 6),
        ("fatigue_monitor", 4),
    ):
        if _b(specs, k):
            pts += w
    return max(0.0, min(100.0, pts))


def adas_score(specs: dict) -> float:
    pts = 0.0
    cruise = (specs.get("features") or {}).get("cruise") or specs.get("cruise") or ""
    cruise_s = str(cruise).lower()
    if "iacc" in cruise_s or "集成" in cruise_s or "智驾" in cruise_s:
        pts += 35
    elif "acc" in cruise_s or "自适应" in cruise_s:
        pts += 28
    elif "定速" in cruise_s or cruise:
        pts += 10
    for k, w in (
        ("lka", 12),
        ("lane_centering", 10),
        ("bsd", 10),
        ("dow", 6),
        ("auto_park", 8),
        ("remote_park", 5),
        ("highway_assist", 8),
        ("l2", 6),
    ):
        if _b(specs, k):
            pts += w
    level = specs.get("adas_level") or (specs.get("features") or {}).get("adas_level")
    if level in ("L2+", "L2.5", "L2++"):
        pts += 8
    elif level == "L2":
        pts += 4
    return max(0.0, min(100.0, pts))


def comfort_score(specs: dict) -> float:
    pts = 0.0
    for k, w in (
        ("leather_seats", 12),
        ("power_driver_seat", 10),
        ("power_passenger_seat", 6),
        ("seat_heating", 10),
        ("seat_ventilation", 8),
        ("dual_zone_climate", 10),
        ("rear_ac_vents", 6),
        ("panoramic_sunroof", 12),
        ("sunroof", 6),
        ("power_tailgate", 8),
        ("keyless_entry", 6),
        ("remote_start", 6),
    ):
        if _b(specs, k):
            pts += w
    # avoid double-counting sunroof + panoramic
    if _b(specs, "panoramic_sunroof") and _b(specs, "sunroof"):
        pts -= 6
    return max(0.0, min(100.0, pts))


def cabin_tech_score(specs: dict) -> float:
    pts = 0.0
    screen = _n(specs, "screen_inch", 0) or _n(specs.get("features") or {}, "screen_inch", 0) or 0
    if screen >= 15:
        pts += 22
    elif screen >= 12:
        pts += 18
    elif screen >= 10:
        pts += 12
    elif screen >= 8:
        pts += 7
    cluster = _n(specs, "cluster_inch", 0) or 0
    if cluster >= 10 or _b(specs, "full_lcd_cluster"):
        pts += 12
    elif cluster >= 7:
        pts += 7
    for k, w in (
        ("voice_control", 10),
        ("ota", 10),
        ("connected_car", 8),
        ("camera_360", 12),
        ("camera_reverse", 5),
        ("wireless_charge", 6),
        ("hud", 5),
        ("chip_8155", 10),
    ):
        if _b(specs, k):
            pts += w
    return max(0.0, min(100.0, pts))


def powertrain_value_score(specs: dict) -> float:
    pt = (specs.get("powertrain_type") or "").lower()
    pts = 40.0  # baseline ICE
    if pt in ("bev", "pure_ev", "纯电"):
        pts = 88
    elif pt in ("phev", "dm", "dm-i", "插混"):
        pts = 92
    elif pt in ("hev", "混动", "油电混动"):
        pts = 78
    elif pt in ("reev", "增程"):
        pts = 85
    if _b(specs, "awd", "4wd"):
        pts += 8
    disp = _n(specs, "displacement_l")
    if disp is not None:
        if disp <= 1.5:
            pts += 4
        elif disp >= 2.0 and pt in ("ice", "gasoline", "燃油", ""):
            pts -= 4
    motor = specs.get("motor") or specs.get("engine") or ""
    if "智驾" in str(specs.get("trim_name") or ""):
        pts += 2
    if "2.0T" in str(motor) and pt in ("phev", "dm", "dm-i", "插混"):
        pts += 4
    return max(0.0, min(100.0, pts))


def config_proxy_from_specs(specs: dict) -> float:
    """Raw config proxy 0–100 from real feature flags."""
    if not specs or not specs.get("specs_found"):
        return 0.0
    parts = {
        "safety": safety_score(specs),
        "adas": adas_score(specs),
        "comfort": comfort_score(specs),
        "cabin_tech": cabin_tech_score(specs),
        "powertrain_value": powertrain_value_score(specs),
    }
    total = sum(parts[k] * CONFIG_WEIGHTS[k] for k in CONFIG_WEIGHTS)
    specs["config_subscores"] = {k: round(v, 2) for k, v in parts.items()}
    return round(total, 2)


def space_proxy_from_specs(specs: dict, is_suv: bool) -> float:
    if not specs or not specs.get("specs_found"):
        return 0.0
    wb = _n(specs, "wheelbase_mm", 2600) or 2600
    length = _n(specs, "length_mm", 4500) or 4500
    seats = int(_n(specs, "seats", 5) or 5)
    # map typical compact sedan ~2650wb to ~40, mid-size SUV 2800 to ~85, 7-seat bonus
    pts = (wb - 2400) / (2950 - 2400) * 70.0
    pts += (length - 4200) / (5000 - 4200) * 15.0
    if seats >= 7:
        pts += 15
    elif seats >= 6:
        pts += 8
    if is_suv or (specs.get("body_type") or "").upper().find("SUV") >= 0:
        pts += 8
    return max(0.0, min(100.0, pts))


def fuel_proxy_from_specs(specs: dict) -> float:
    if not specs or not specs.get("specs_found"):
        return 0.0
    pt = (specs.get("powertrain_type") or "").lower()
    if pt in ("bev", "pure_ev", "纯电"):
        return 95.0
    if pt in ("phev", "dm", "dm-i", "插混"):
        # prefer stated depleting / WLTC hybrid figure if present
        f = _n(specs, "fuel_l_100km")
        if f is not None:
            # 3.8 -> ~95, 7 -> ~70, 10 -> ~45
            return max(40.0, min(98.0, 110 - f * 6))
        return 88.0
    if pt in ("hev", "混动", "油电混动"):
        return 80.0
    if pt in ("reev", "增程"):
        return 86.0
    f = _n(specs, "fuel_l_100km")
    if f is not None:
        return max(5.0, min(90.0, 100 - f * 8))
    disp = _n(specs, "displacement_l")
    if disp is None:
        return 45.0
    if disp <= 1.4:
        return 62.0
    if disp <= 1.6:
        return 55.0
    if disp <= 2.0:
        return 42.0
    return 28.0


def is_suv_from_specs(specs: dict, fallback: bool = False) -> bool:
    bt = (specs.get("body_type") or "").upper()
    if "SUV" in bt or "跨界" in bt:
        return True
    if "轿" in bt or "SEDAN" in bt or "HATCH" in bt:
        return False
    return fallback
