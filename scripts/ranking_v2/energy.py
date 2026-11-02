"""Unify powertrains to energy_cost_yuan_100km."""
from __future__ import annotations

from typing import Any

from .config import ENERGY


def gas_price(fuel_grade: str | None, cfg: dict | None = None) -> float:
    cfg = cfg or ENERGY
    g = str(fuel_grade or "92")
    if "95" in g:
        return float(cfg["gas_95_yuan_l"])
    return float(cfg["gas_92_yuan_l"])


def _apply_official_multiplier(value: float, ranking_energy: dict, cfg: dict) -> float:
    t = str(ranking_energy.get("type") or "")
    mult = ranking_energy.get("fallback_multiplier_recommended")
    if mult is not None:
        return float(value) * float(mult)
    if "wltc" in t.lower():
        return float(value) * float(cfg["wltc_fallback_multiplier"])
    if "nedc" in t.lower():
        return float(value) * float(cfg["nedc_fallback_multiplier"])
    return float(value)


def resolve_ranking_energy(specs: dict[str, Any], cfg: dict | None = None) -> dict[str, Any]:
    """Return {value, unit, type, confidence, l100_or_kwh, forbids_combined_phev}."""
    cfg = cfg or ENERGY
    specs = specs or {}
    pt = (specs.get("powertrain") or specs.get("powertrain_type") or "ice").lower()
    if pt in ("纯电", "pure_ev"):
        pt = "bev"
    if pt in ("插混", "dm", "dm-i", "dmi"):
        pt = "phev"
    if pt in ("混动", "油电混动"):
        pt = "hev"

    re = specs.get("ranking_energy")
    if isinstance(re, dict) and re.get("value") is not None:
        unit = re.get("unit") or "L/100km"
        val = float(re["value"])
        typ = str(re.get("type") or "")
        if unit == "L/100km" and (
            "official_wltc" in typ or "official_nedc" in typ or "with_uncertainty" in typ
        ):
            val = _apply_official_multiplier(val, re, cfg)
            conf = 0.65 if "wltc" in typ.lower() else 0.55
        elif typ in ("real_world_fuel", "owner_fuel", "measured_fuel"):
            conf = 1.0 if (specs.get("real_world_sample_n") or 0) >= cfg["real_world_min_n"] else 0.85
        elif typ == "low_soc_fuel":
            conf = 0.9
        elif unit == "kWh/100km":
            conf = 0.85
        else:
            conf = 0.7
        return {
            "powertrain": pt,
            "value": val,
            "unit": unit,
            "type": typ,
            "confidence": conf,
            "raw_ranking_energy": re,
            "fuel_grade": re.get("fuel_grade") or specs.get("fuel_grade") or "92",
        }

    # Infer without verified ranking_energy
    if pt == "bev":
        kwh = specs.get("electric_kwh_100km")
        if kwh is None:
            return {"powertrain": pt, "value": None, "unit": "kWh/100km", "type": "unknown", "confidence": 0.0}
        return {
            "powertrain": pt,
            "value": float(kwh),
            "unit": "kWh/100km",
            "type": "electricity",
            "confidence": 0.7,
            "fuel_grade": None,
        }

    if pt == "phev":
        # FORBID combined / official综合
        low = specs.get("low_soc_fuel_l_100km")
        if low is not None:
            return {
                "powertrain": pt,
                "value": float(low),
                "unit": "L/100km",
                "type": "low_soc_fuel",
                "confidence": 0.9,
                "fuel_grade": specs.get("fuel_grade") or "92",
            }
        rw = specs.get("real_world_fuel_l_100km")
        n = specs.get("real_world_sample_n") or 0
        if rw is not None and n >= cfg["real_world_min_n"]:
            return {
                "powertrain": pt,
                "value": float(rw),
                "unit": "L/100km",
                "type": "real_world_fuel",
                "confidence": 0.85,
                "fuel_grade": specs.get("fuel_grade") or "92",
            }
        # Do NOT fall back to fuel_l_100km (often combined 1.x)
        return {
            "powertrain": pt,
            "value": None,
            "unit": "L/100km",
            "type": "unknown_phev_no_low_soc",
            "confidence": 0.0,
            "fuel_grade": specs.get("fuel_grade") or "92",
            "warning": "PHEV缺少低SOC/实耗，禁用综合油耗",
        }

    # ICE / HEV
    rw = specs.get("real_world_fuel_l_100km")
    n = specs.get("real_world_sample_n") or 0
    if rw is not None and n >= cfg["real_world_min_n"]:
        return {
            "powertrain": pt,
            "value": float(rw),
            "unit": "L/100km",
            "type": "real_world_fuel",
            "confidence": 1.0,
            "fuel_grade": specs.get("fuel_grade") or "92",
        }
    if rw is not None:
        return {
            "powertrain": pt,
            "value": float(rw),
            "unit": "L/100km",
            "type": "real_world_fuel_low_n",
            "confidence": 0.8,
            "fuel_grade": specs.get("fuel_grade") or "92",
        }

    official = specs.get("official_fuel_l_100km")
    std = str(specs.get("official_standard") or "")
    fuel = specs.get("fuel_l_100km")
    if official is not None:
        if "WLTC" in std.upper() or std.upper() == "WLTC":
            return {
                "powertrain": pt,
                "value": float(official) * float(cfg["wltc_fallback_multiplier"]),
                "unit": "L/100km",
                "type": "official_wltc_x1.15",
                "confidence": 0.65,
                "fuel_grade": specs.get("fuel_grade") or "92",
            }
        if "NEDC" in std.upper():
            return {
                "powertrain": pt,
                "value": float(official) * float(cfg["nedc_fallback_multiplier"]),
                "unit": "L/100km",
                "type": "official_nedc_x1.20",
                "confidence": 0.55,
                "fuel_grade": specs.get("fuel_grade") or "92",
            }
        # unknown standard — treat cautiously as WLTC-like
        return {
            "powertrain": pt,
            "value": float(official) * float(cfg["wltc_fallback_multiplier"]),
            "unit": "L/100km",
            "type": "official_unknown_x1.15",
            "confidence": 0.5,
            "fuel_grade": specs.get("fuel_grade") or "92",
        }

    if fuel is not None and pt not in ("phev",):
        # Legacy field; assume may be official-ish
        return {
            "powertrain": pt,
            "value": float(fuel) * float(cfg["wltc_fallback_multiplier"]),
            "unit": "L/100km",
            "type": "legacy_fuel_l_100km_x1.15",
            "confidence": 0.45,
            "fuel_grade": specs.get("fuel_grade") or "92",
        }

    return {
        "powertrain": pt,
        "value": None,
        "unit": "L/100km",
        "type": "unknown",
        "confidence": 0.0,
        "fuel_grade": specs.get("fuel_grade") or "92",
    }


def energy_cost_yuan_100km(
    specs: dict[str, Any],
    cfg: dict | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    cfg = cfg or ENERGY
    scenario = scenario or cfg["default_scenario"]
    resolved = resolve_ranking_energy(specs, cfg)
    pt = resolved["powertrain"]
    val = resolved.get("value")
    unit = resolved.get("unit")
    if val is None:
        return {
            **resolved,
            "energy_cost_yuan_100km": None,
            "scenario": scenario,
        }

    if unit == "kWh/100km" or pt == "bev":
        price = float(cfg["home_electricity_yuan_kwh"])
        cost = float(val) * price
        return {
            **resolved,
            "energy_cost_yuan_100km": round(cost, 2),
            "scenario": scenario,
            "unit_price": price,
        }

    # liquid fuel
    gprice = gas_price(resolved.get("fuel_grade"), cfg)
    cost = float(val) * gprice
    return {
        **resolved,
        "energy_cost_yuan_100km": round(cost, 2),
        "scenario": scenario,
        "unit_price": gprice,
    }
