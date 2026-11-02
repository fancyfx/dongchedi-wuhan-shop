"""Patch listings with verified JSON; null advanced features for non-exact match."""
from __future__ import annotations

import copy
from typing import Any

from .config import ADVANCED_FEATURE_KEYS, FINANCE


def _is_exact(match_level: str | None) -> bool:
    if not match_level:
        return False
    ml = match_level.lower()
    return ml in ("exact", "exact_trim")


def null_advanced_features(specs: dict[str, Any]) -> dict[str, Any]:
    """For non-exact match: advanced feature fields -> null (not false, not true)."""
    specs = copy.deepcopy(specs) if specs else {}
    feats = dict(specs.get("features") or {})
    for k in ADVANCED_FEATURE_KEYS:
        feats[k] = None
        if k in specs:
            specs[k] = None
    # ACC often lives in cruise string — clear adaptive cruise claims
    cruise = feats.get("cruise") or specs.get("cruise")
    if cruise:
        cs = str(cruise)
        if any(t in cs for t in ("ACC", "自适应", "iACC", "IACC", "全速", "智驾巡航")):
            feats["cruise"] = None
            specs["cruise"] = None
    if "adas_level" in specs:
        specs["adas_level"] = None
    if "adas_level" in feats:
        feats["adas_level"] = None
    specs["features"] = feats
    specs["advanced_features_nulled"] = True
    return specs


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
    # 标价 / 券后 / other
    conf = 0.85 if pt == "券后" else 0.9
    return {
        "display_price_wan": display_price,
        "effective_price_wan": float(display_price),
        "price_confidence": conf,
        "needs_cash_quote": False,
        "price_basis": "display",
    }


def apply_verified_record(item: dict[str, Any], verified: dict[str, Any]) -> dict[str, Any]:
    """Overlay verified_core onto listing specs; keep listing price/mileage from item."""
    item = copy.deepcopy(item)
    vc = verified.get("verified_core") or {}
    listing_v = verified.get("listing") or {}
    specs = dict(item.get("specs") or {})
    match_level = specs.get("match_level")

    # Core dimensions / powertrain from verification
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
    ):
        if vc.get(k) is not None:
            specs[k] = vc[k]

    if vc.get("powertrain"):
        specs["powertrain_type"] = vc["powertrain"]
        specs["powertrain"] = vc["powertrain"]

    if vc.get("ranking_energy"):
        specs["ranking_energy"] = vc["ranking_energy"]

    specs["core_confidence"] = vc.get("core_confidence")
    specs["feature_confidence"] = vc.get("feature_confidence")
    specs["verification_issues"] = vc.get("issues") or []
    specs["verification_sources"] = vc.get("sources") or []
    specs["verified"] = True
    specs["specs_found"] = True

    # Prefer verified listing price_type if present
    if listing_v.get("price_type"):
        item["price_type"] = listing_v["price_type"]

    # Non-exact: null advanced features (even if previously filled by series_year_tier)
    if not _is_exact(match_level):
        specs = null_advanced_features(specs)
        specs["specs_approx"] = True
    else:
        # exact: keep existing features but do not invent; mark verified
        specs["specs_approx"] = False
        # Still: if feature_matrix says partial, we don't invent — leave as-is from prior fetch
        # but strip only if features were from approx (shouldn't be for exact)

    item["specs"] = specs
    item["detailed_config"] = specs
    return item


def sanitize_non_exact_listing(item: dict[str, Any]) -> dict[str, Any]:
    """Null advanced features when match is not exact (for cars without verified overlay)."""
    item = copy.deepcopy(item)
    specs = item.get("specs") or {}
    if not specs:
        return item
    if _is_exact(specs.get("match_level")):
        return item
    item["specs"] = null_advanced_features(specs)
    item["detailed_config"] = item["specs"]
    return item


def load_verified_by_sku(path) -> dict[str, dict]:
    import json
    from pathlib import Path

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for v in data.get("vehicles") or []:
        sku = str((v.get("listing") or {}).get("sku") or "")
        if sku:
            out[sku] = v
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
            item = sanitize_non_exact_listing(item)
        # Always attach effective price
        ep = effective_price_fields(
            float(item.get("price") or 0),
            item.get("price_type"),
            cash_price=item.get("cash_price_wan"),
            finance_all_in=item.get("finance_all_in_price_wan"),
        )
        item.update(ep)
        out.append(item)
    return out
