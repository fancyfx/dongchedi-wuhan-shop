#!/usr/bin/env python3
"""Ranking regression tests independent of legacy generated configuration data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ranking_v2.apply_verified import apply_verified_to_listings, effective_price_fields  # noqa: E402
from ranking_v2.data_quality import assess_score_eligibility  # noqa: E402
from ranking_v2.energy import energy_cost_yuan_100km, resolve_ranking_energy  # noqa: E402
from ranking_v2.mileage_score import mileage_score  # noqa: E402
from ranking_v2.score import score_listing  # noqa: E402


def _fixture_trim() -> dict:
    return {
        "trim_id": "trim_ah_fixture",
        "canonical_title": "测试SUV 2022款 1.5T 自动尊贵版",
        "core_specs": {
            "powertrain": "ice",
            "body_type": "紧凑型SUV",
            "seats": 5,
            "engine": "1.5T",
            "transmission": "7挡双离合",
            "length_mm": 4600,
            "width_mm": 1860,
            "height_mm": 1700,
            "wheelbase_mm": 2720,
            "fuel_grade": "92",
            "ranking_energy": {"type": "real_world_fuel", "value": 7.2, "unit": "L/100km"},
            "real_world_fuel_l_100km": 7.2,
            "real_world_sample_n": 50,
        },
        "features": {
            "passive_safety": {
                "front_airbags": True,
                "front_side_airbags": True,
                "curtain_airbags": True,
                "tpms_display": True,
            },
            "active_safety": {
                "aeb": True,
                "fcw": True,
                "ldw": True,
                "lka": True,
                "lane_centering": False,
                "bsd": False,
                "dow": False,
            },
            "parking_adas": {
                "front_parking_radar": True,
                "rear_parking_radar": True,
                "surround_360": True,
                "transparent_chassis_540": False,
                "cruise": "adaptive",
                "auto_park": False,
                "remote_park": False,
            },
            "comfort": {
                "sunroof": "全景天窗",
                "power_tailgate": True,
                "keyless_entry": True,
                "remote_start": False,
                "hud": False,
                "wireless_phone_charging": False,
                "driver_power_seat": True,
                "passenger_power_seat": True,
                "front_seat_heating": True,
                "front_seat_ventilation": False,
                "rear_air_vents": True,
                "climate_control": "automatic_dual_zone",
                "leather_seats": False,
            },
            "infotainment": {
                "center_screen_inches": 12.3,
                "carplay": True,
                "carlife": False,
                "phone_link": True,
                "ota": True,
                "full_lcd_cluster": True,
                "chip_8155": False,
            },
        },
        "data_quality": {
            "core_confidence": 0.99,
            "feature_confidence": "high",
            "known_issues": [],
        },
        "sources": [{"source_type": "autohome_exact_trim"}],
    }


def test_new_configuration_store_has_no_legacy_shards():
    index = json.loads((ROOT / "data" / "vehicle-specs-verified.json").read_text(encoding="utf-8"))
    assert index.get("trim_files") == ["specs/exact-trims-auto.json"]
    assert all(str(v).startswith("trim_ah_") for v in (index.get("sku_to_trim") or {}).values())
    for i in range(1, 5):
        assert not (ROOT / "data" / "specs" / f"exact-trims-{i}.json").exists()


def test_exact_trim_replaces_legacy_claims_and_unknown_is_erased():
    verified = {"fixture": {"trim": _fixture_trim()}}
    poisoned = {
        "sku": "fixture",
        "price": 5.0,
        "price_type": "标价",
        "mileage_wan": 3.0,
        "plate_year": 2022,
        "specs": {
            "match_level": "series_year_tier",
            "features": {"aeb": False, "camera_360": False, "seat_ventilation": True},
        },
    }
    patched = apply_verified_to_listings([poisoned], verified)[0]
    specs = patched["specs"]
    feats = specs["features"]
    assert specs["match_level"] == "exact_trim"
    assert specs["configuration_source"] == "exact_trim_v3"
    assert feats["aeb"] is True
    assert feats["camera_360"] is True
    assert feats["seat_ventilation"] is False

    unknown = {
        "sku": "not-verified",
        "price": 4.0,
        "price_type": "标价",
        "mileage_wan": 3.0,
        "plate_year": 2022,
        "specs": {
            "match_level": "series_year_tier",
            "wheelbase_mm": 2700,
            "features": {"aeb": True, "seat_ventilation": True},
            "aeb": True,
        },
    }
    cleaned = apply_verified_to_listings([unknown], verified)[0]
    assert cleaned["specs"]["features"] == {}
    assert "aeb" not in cleaned["specs"]
    assert cleaned["specs"]["match_level"] == "unverified_config"
    gate = assess_score_eligibility(cleaned)
    assert gate["eligible"] is False
    assert any(x["code"] == "detailed_config_insufficient" for x in gate["issues"])


def test_same_trim_cheaper_lower_mileage_wins():
    verified = {"a": {"trim": _fixture_trim()}, "b": {"trim": _fixture_trim()}}
    base = {
        "price_type": "标价",
        "plate_year": 2022,
        "specs": {},
    }
    a = {**base, "sku": "a", "price": 4.8, "mileage_wan": 2.0}
    b = {**base, "sku": "b", "price": 5.4, "mileage_wan": 6.0}
    a2, b2 = apply_verified_to_listings([a, b], verified)
    assert score_listing(a2)["total_score"] > score_listing(b2)["total_score"]


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
        test_new_configuration_store_has_no_legacy_shards,
        test_exact_trim_replaces_legacy_claims_and_unknown_is_erased,
        test_same_trim_cheaper_lower_mileage_wins,
        test_mileage_score_low_beats_high,
        test_phev_does_not_use_combined_for_cross_powertrain,
        test_95_costs_more_than_92,
        test_finance_reserve,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} tests failed")
    print(f"ALL {len(tests)} PASSED")


if __name__ == "__main__":
    main()
