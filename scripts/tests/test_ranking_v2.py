#!/usr/bin/env python3
"""Regression tests for ranking engine V2 with exact-trim V3 config data."""
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
)
from ranking_v2.data_quality import assess_score_eligibility  # noqa: E402
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


def test_v3_exact_trim_mapping_and_no_legacy_config_fallback():
    verified = load_verified_by_sku(ROOT / "data" / "vehicle-specs-verified.json")
    assert len(verified) >= 30

    poisoned = {
        "sku": "357298372",
        "price": 5.39,
        "price_type": "标价",
        "specs": {
            "match_level": "series_year_tier",
            "features": {"aeb": True, "camera_360": True, "seat_ventilation": True, "power_tailgate": True},
        },
    }
    patched = apply_verified_to_listings([poisoned], verified)[0]
    specs = patched["specs"]
    feats = specs["features"]
    assert specs["match_level"] == "exact_trim"
    assert specs["configuration_source"] == "exact_trim_v3"
    assert feats["aeb"] is False
    assert feats["camera_360"] is False
    assert feats["seat_ventilation"] is False
    assert feats["power_tailgate"] is False

    unknown = {
        "sku": "not-in-v3",
        "price": 4.0,
        "price_type": "标价",
        "mileage_wan": 3.0,
        "plate_year": 2022,
        "specs": {
            "match_level": "exact",
            "wheelbase_mm": 2700,
            "features": {"aeb": True, "seat_ventilation": True},
            "aeb": True,
        },
    }
    cleaned = apply_verified_to_listings([unknown], verified)[0]
    assert cleaned["specs"]["features"] == {}
    assert "aeb" not in cleaned["specs"]
    assert cleaned["specs"]["wheelbase_mm"] == 2700
    assert cleaned["specs"]["match_level"] == "unverified_config"
    assert cleaned["specs"]["specs_found"] is False
    gate = assess_score_eligibility(cleaned)
    assert gate["eligible"] is False
    assert any(x["code"] == "detailed_config_insufficient" for x in gate["issues"])


def test_tang_dm_energy_not_combined():
    verified = load_verified_by_sku(ROOT / "data" / "vehicle-specs-verified.json")
    raw = _load_ranked()
    item = _by_sku(raw, "357215359")
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
    assert cost["energy_cost_yuan_100km"] > 50


def test_xingrui_cheaper_lower_mileage_wins():
    verified = load_verified_by_sku(ROOT / "data" / "vehicle-specs-verified.json")
    raw = _load_ranked()
    a = json.loads(json.dumps(_by_sku(raw, "356994816")))
    b = json.loads(json.dumps(_by_sku(raw, "357156086")))
    a["price"], a["mileage_wan"], a["price_type"] = 5.39, 7.43, "标价"
    b["price"], b["mileage_wan"], b["price_type"] = 5.49, 9.25, "标价"
    a2 = apply_verified_to_listings([a], verified)[0]
    b2 = apply_verified_to_listings([b], verified)[0]
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
    older = _by_sku(raw, "357100389")
    newer = _by_sku(raw, "357298372")
    a = apply_verified_to_listings([json.loads(json.dumps(older))], verified)[0]
    b = apply_verified_to_listings([json.loads(json.dumps(newer))], verified)[0]
    sa = score_listing(a)
    sb = score_listing(b)
    assert sb["scores"]["mileage"] > sa["scores"]["mileage"]
    assert sb["scores"]["age"] >= sa["scores"]["age"]
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
        test_v3_exact_trim_mapping_and_no_legacy_config_fallback,
        test_tang_dm_energy_not_combined,
        test_xingrui_cheaper_lower_mileage_wins,
        test_mileage_score_low_beats_high,
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
