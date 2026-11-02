#!/usr/bin/env python3
"""Regression tests for ranking engine V2 (§18 of design doc)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ranking_v2.apply_verified import (  # noqa: E402
    apply_verified_to_listings,
    effective_price_fields,
    load_verified_by_sku,
    null_advanced_features,
)
from ranking_v2.energy import energy_cost_yuan_100km, resolve_ranking_energy  # noqa: E402
from ranking_v2.mileage_score import mileage_score  # noqa: E402
from ranking_v2.score import score_listing  # noqa: E402


def _load_ranked():
    return json.loads((ROOT / "data" / "listings-ranked.json").read_text(encoding="utf-8"))


def _by_sku(listings, sku):
    for x in listings:
        if str(x.get("sku")) == str(sku):
            return x
    raise KeyError(sku)


def test_tang_dm_energy_not_combined():
    verified = load_verified_by_sku(ROOT / "data" / "vehicle-specs-verified.json")
    raw = _load_ranked()
    # start from a minimal tang-like item if already reranked
    item = None
    for x in raw:
        if x["sku"] == "357215359":
            item = x
            break
    assert item is not None
    # re-apply verified on a copy with poisoned combined fuel
    poisoned = json.loads(json.dumps(item))
    poisoned.setdefault("specs", {})["fuel_l_100km"] = 1.8
    poisoned["specs"]["powertrain_type"] = "phev"
    patched = apply_verified_to_listings([poisoned], verified)[0]
    resolved = resolve_ranking_energy(patched["specs"])
    assert resolved["value"] != 1.8
    assert resolved["value"] != 2.0
    assert abs(float(resolved["value"]) - 9.02) < 0.01
    cost = energy_cost_yuan_100km(patched["specs"])
    assert cost["energy_cost_yuan_100km"] is not None
    assert cost["energy_cost_yuan_100km"] > 50  # 9.02*8 ≈ 72


def test_xingrui_cheaper_lower_mileage_wins():
    """Doc §18 case2: same trim, A cheaper + lower mileage must beat B.

    Live listings may differ on price_type (分期 vs 标价); the regression
    equalizes price_type so only price/mileage individual differences remain,
    matching "其他车型参数完全相同".
    """
    verified = load_verified_by_sku(ROOT / "data" / "vehicle-specs-verified.json")
    raw = _load_ranked()
    a = _by_sku(raw, "356994816")  # 5.39 / 7.43
    b = _by_sku(raw, "357156086")  # 5.49 / 9.25
    a = json.loads(json.dumps(a))
    b = json.loads(json.dumps(b))
    a["price"] = 5.39
    a["mileage_wan"] = 7.43
    a["price_type"] = "标价"
    b["price"] = 5.49
    b["mileage_wan"] = 9.25
    b["price_type"] = "标价"
    a2 = apply_verified_to_listings([a], verified)[0]
    b2 = apply_verified_to_listings([b], verified)[0]
    # verified JSON may reassert original price_type; force equal cash-list basis
    for it, price in ((a2, 5.39), (b2, 5.49)):
        it["price"] = price
        it["price_type"] = "标价"
        it.update(effective_price_fields(price, "标价"))
    sa = score_listing(a2)
    sb = score_listing(b2)
    assert sa["total_score"] > sb["total_score"], (
        sa["total_score"], sb["total_score"], sa["scores"], sb["scores"]
    )


def test_mileage_score_low_beats_high():
    assert mileage_score(2.49) > mileage_score(7.0)


def test_series_year_tier_advanced_features_null():
    specs = {
        "match_level": "series_year_tier",
        "specs_found": True,
        "features": {
            "seat_ventilation": True,
            "aeb": True,
            "camera_360": True,
            "l2": True,
            "power_tailgate": True,
        },
    }
    out = null_advanced_features(specs)
    assert out["features"]["seat_ventilation"] is None
    assert out["features"]["aeb"] is None
    assert out["features"]["camera_360"] is None

    verified = load_verified_by_sku(ROOT / "data" / "vehicle-specs-verified.json")
    raw = _load_ranked()
    # 博瑞 series_year_tier
    item = _by_sku(raw, "357172812")
    patched = apply_verified_to_listings([json.loads(json.dumps(item))], verified)[0]
    feats = patched["specs"].get("features") or {}
    # if match was series_year_tier, advanced must be null
    if (item.get("specs") or {}).get("match_level") == "series_year_tier":
        assert feats.get("seat_ventilation") is None
        assert feats.get("aeb") is None
        assert feats.get("camera_360") is None


def test_phev_does_not_use_combined_for_cross_powertrain():
    specs = {
        "powertrain": "phev",
        "powertrain_type": "phev",
        "fuel_l_100km": 1.8,
        "official_fuel_l_100km": 1.8,
        "official_standard": "WLTC综合（不可用于跨动力排名）",
        "fuel_grade": "92",
    }
    resolved = resolve_ranking_energy(specs)
    assert resolved["value"] is None
    assert "unknown" in resolved["type"] or resolved["confidence"] == 0.0

    specs2 = {
        "powertrain": "phev",
        "low_soc_fuel_l_100km": 5.3,
        "fuel_l_100km": 2.87,
        "fuel_grade": "92",
    }
    r2 = resolve_ranking_energy(specs2)
    assert abs(r2["value"] - 5.3) < 0.01


def test_95_costs_more_than_92():
    specs92 = {
        "powertrain": "ice",
        "ranking_energy": {"type": "real_world_fuel", "value": 8.3, "unit": "L/100km"},
        "fuel_grade": "92",
        "real_world_sample_n": 50,
    }
    specs95 = {
        "powertrain": "ice",
        "ranking_energy": {"type": "real_world_fuel", "value": 8.3, "unit": "L/100km", "fuel_grade": "95"},
        "fuel_grade": "95",
        "real_world_sample_n": 50,
    }
    c92 = energy_cost_yuan_100km(specs92)["energy_cost_yuan_100km"]
    c95 = energy_cost_yuan_100km(specs95)["energy_cost_yuan_100km"]
    assert c95 > c92


def test_binyue_2024_low_mileage_direction():
    verified = load_verified_by_sku(ROOT / "data" / "vehicle-specs-verified.json")
    raw = _load_ranked()
    older = _by_sku(raw, "357100389")  # 2023 4.98万km
    newer = _by_sku(raw, "357298372")  # 2024 1.22万km
    a = apply_verified_to_listings([json.loads(json.dumps(older))], verified)[0]
    b = apply_verified_to_listings([json.loads(json.dumps(newer))], verified)[0]
    sa = score_listing(a)
    sb = score_listing(b)
    # mileage+age should favor 2024 low-mileage; allow price difference
    assert sb["scores"]["mileage"] > sa["scores"]["mileage"]
    assert sb["scores"]["age"] >= sa["scores"]["age"]
    # total may or may not win solely on that, but direction of those dims is required
    assert sb["scores"]["mileage"] - sa["scores"]["mileage"] > 10


def test_finance_reserve():
    ep = effective_price_fields(4.99, "分期")
    assert ep["needs_cash_quote"] is True
    assert abs(ep["effective_price_wan"] - 5.49) < 0.01
    assert ep["price_confidence"] == 0.5
    ep2 = effective_price_fields(5.99, "标价")
    assert ep2["effective_price_wan"] == 5.99
    assert ep2["needs_cash_quote"] is False


def main():
    tests = [
        test_tang_dm_energy_not_combined,
        test_xingrui_cheaper_lower_mileage_wins,
        test_mileage_score_low_beats_high,
        test_series_year_tier_advanced_features_null,
        test_phev_does_not_use_combined_for_cross_powertrain,
        test_95_costs_more_than_92,
        test_binyue_2024_low_mileage_direction,
        test_finance_reserve,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    if failed:
        raise SystemExit(f"{failed} tests failed")
    print(f"ALL {len(tests)} PASSED")


if __name__ == "__main__":
    main()
