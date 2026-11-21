"""Compose V3 total score for holiday low-frequency used-car selection."""
from __future__ import annotations

from typing import Any

from .age_score import age_years_from_plate
from .anchors import interpolate
from .condition_gate import condition_gate
from .config import (
    SCORE_VERSION,
    V3_AGE_POINTS_YEARS,
    V3_CONFIG_CURVE_POINTS,
    V3_MILEAGE_POINTS,
    V3_WHEELBASE_POINTS,
    VALUE_DISCOUNT_POINTS,
    VALUE_PRICE_POINTS,
    WEIGHTS,
)
from .config_score import config_score
from .live_specs import extract_live_profile, resolve_spec_id
from .operating_cost import operating_cost_score
from .powertrain_score import (
    build_v3_profile,
    evaluate_veto,
    score_powertrain_reliability,
)
from .space_score import space_score

SCORE_VERSION = SCORE_VERSION  # re-export


def _is_suv(item: dict, specs: dict) -> bool:
    bt = str(specs.get("body_type") or "")
    if "SUV" in bt.upper() or "跨界" in bt:
        return True
    if "轿" in bt or "型车" in bt:
        return False
    ss = item.get("sort_scores") or {}
    return bool(ss.get("is_suv"))


def _v3_config_score(specs: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    live = live or {}
    base = config_score(specs)
    feats = specs.get("features") or {}
    if not feats:
        return {
            "config_score": 15.0,
            "raw_points": 0.0,
            "coverage": base.get("coverage", 0.0),
            "sub_buckets": {"safety": 0.0, "adas": 0.0, "comfort": 0.0},
        }

    ab = feats.get("airbags") or 0
    knee = bool(live.get("knee_airbag"))
    has_l2 = bool(feats.get("acc")) and bool(feats.get("aeb")) and (
        bool(feats.get("lka")) or bool(feats.get("lane_centering"))
    )

    s_safe = 0.0
    if ab >= 6:
        s_safe += 13.0
    elif ab >= 4:
        s_safe += 7.0
    if knee:
        s_safe += 5.0
    if feats.get("esp"):
        s_safe += 3.0
    if feats.get("aeb"):
        s_safe += 9.0
    if feats.get("bsd") or feats.get("dow"):
        s_safe += 4.0
    s_safe = min(34.0, s_safe)

    s_adas = 0.0
    if feats.get("acc"):
        s_adas += 9.0
    elif live.get("has_fixed_cruise") or "定速" in str(feats.get("cruise") or ""):
        s_adas += 3.0
    if feats.get("lka") or feats.get("lane_centering"):
        s_adas += 6.0
    if has_l2:
        s_adas += 4.0
    if feats.get("camera_360"):
        s_adas += 7.0
    elif live.get("has_reverse_camera"):
        s_adas += 3.0
    if feats.get("front_radar") and feats.get("rear_radar"):
        s_adas += 4.0
    elif feats.get("rear_radar"):
        s_adas += 2.0
    if feats.get("auto_park") or feats.get("transparent_chassis"):
        s_adas += 2.0
    s_adas = min(32.0, s_adas)

    s_comf = 0.0
    if feats.get("seat_heating"):
        s_comf += 7.0
    if feats.get("seat_ventilation"):
        s_comf += 4.0
    if feats.get("power_driver_seat"):
        s_comf += 4.0
    if feats.get("power_passenger_seat"):
        s_comf += 3.0
    if feats.get("carplay") or feats.get("phone_link"):
        s_comf += 4.0
    if feats.get("power_tailgate"):
        s_comf += 4.0
    if feats.get("panoramic_sunroof"):
        s_comf += 3.0
    if feats.get("dual_zone_climate"):
        s_comf += 2.5
    if feats.get("keyless_entry"):
        s_comf += 2.0
    if feats.get("rear_ac_vents"):
        s_comf += 1.5
    if feats.get("hud"):
        s_comf += 2.0
    if feats.get("wireless_charge") or feats.get("full_lcd_cluster"):
        s_comf += 1.5
    s_comf = min(34.0, s_comf)

    raw_pts = s_safe + s_adas + s_comf
    curved = interpolate(raw_pts, V3_CONFIG_CURVE_POINTS)
    return {
        "config_score": round(curved, 2),
        "raw_points": round(raw_pts, 2),
        "coverage": base.get("coverage", 0.0),
        "sub_buckets": {
            "safety": round(s_safe, 1),
            "adas": round(s_adas, 1),
            "comfort": round(s_comf, 1),
        },
    }


def _v3_value_price_score(eff_price: float, msrp_wan: float | None) -> dict[str, Any]:
    abs_s = interpolate(eff_price, VALUE_PRICE_POINTS)
    if msrp_wan and msrp_wan > 0:
        ratio = eff_price / msrp_wan
        disc_s = interpolate(ratio, VALUE_DISCOUNT_POINTS)
        val_s = 0.55 * disc_s + 0.45 * abs_s
    else:
        ratio = None
        disc_s = None
        val_s = abs_s
    return {
        "value_price_score": round(val_s, 2),
        "abs_price_score": round(abs_s, 2),
        "discount_score": round(disc_s, 2) if disc_s is not None else None,
        "discount_ratio": round(ratio, 4) if ratio is not None else None,
    }


def _v3_condition_score(mileage_wan: Any, age_years: float | None) -> dict[str, Any]:
    mile = float(mileage_wan) if mileage_wan is not None else 6.0
    mile_s = interpolate(mile, V3_MILEAGE_POINTS)
    age_s = interpolate(float(age_years), V3_AGE_POINTS_YEARS) if age_years is not None else 50.0
    cond_s = (13.0 / 18.0) * mile_s + (5.0 / 18.0) * age_s
    return {
        "condition_score": round(cond_s, 2),
        "mileage_score": round(mile_s, 2),
        "age_score": round(age_s, 2),
    }


def _v3_space_score(specs: dict[str, Any], sp_fallback: dict[str, Any]) -> float:
    wb = specs.get("wheelbase_mm")
    if wb is not None:
        return round(interpolate(float(wb), V3_WHEELBASE_POINTS), 2)
    return float(sp_fallback.get("space_score") or 50.0)


def score_listing(item: dict[str, Any], today=None) -> dict[str, Any]:
    specs = item.get("specs") or {}
    spec_id = specs.get("live_spec_id") or resolve_spec_id(
        item, allow_title_match=specs.get("configuration_unverified") is not True
    )
    live = extract_live_profile(str(spec_id)) if spec_id else None

    eff = float(item.get("effective_price_wan") or item.get("price") or 0)
    msrp_wan = (live or {}).get("msrp_wan") or specs.get("msrp_wan")
    age_y, age_conf = age_years_from_plate(
        item.get("plate_year") or item.get("model_year"),
        item.get("plate_date"),
        today=today,
    )
    item["_age_years"] = age_y

    veto = evaluate_veto(item, specs, live)
    pt_info = score_powertrain_reliability(item, specs, live)
    cfg = _v3_config_score(specs, live)
    val = _v3_value_price_score(eff, msrp_wan)
    cond = _v3_condition_score(item.get("mileage_wan"), age_y)
    sp_meta = space_score(specs)
    sp_s = _v3_space_score(specs, sp_meta)
    op = operating_cost_score(specs)

    scores = {
        "powertrain": pt_info["powertrain_score"],
        "config": cfg["config_score"],
        "value_price": val["value_price_score"],
        "condition": cond["condition_score"],
        "space": sp_s,
    }
    total = round(sum(scores[k] * WEIGHTS[k] for k in WEIGHTS), 1)
    if veto["vetoed"]:
        total = -1.0

    gate = condition_gate(item)
    is_suv = _is_suv(item, specs)
    v3_profile = build_v3_profile(item, specs, live, pt_info, scores)

    reasons: list[str] = []
    warnings = list(gate.get("warnings") or [])
    if veto["vetoed"]:
        reasons.extend(veto["reasons"])
        warnings.extend(veto["reasons"])
    else:
        extra_yuan = int(item.get("landed_extra_yuan") or 0)
        cash_wan = float(item.get("cash_price_wan") or item.get("price") or eff)
        logi_yuan = int(item.get("logistics_fee_yuan") or 0)
        pdiff_yuan = int(item.get("plate_fee_diff_yuan") or 0)
        if extra_yuan > 0:
            fee_desc = f"裸车 {cash_wan:.2f} 万 + 物流{logi_yuan}元"
            if pdiff_yuan > 0:
                fee_desc += f"/上牌差{pdiff_yuan}元"
            if v3_profile.get("discount_fold") is not None:
                reasons.append(
                    f"到汉可比价 {eff:.2f} 万（{fee_desc}，指导价 {msrp_wan:.2f} 万，{v3_profile['discount_fold']} 折）"
                )
            else:
                reasons.append(f"到汉可比价 {eff:.2f} 万（{fee_desc}）")
        elif v3_profile.get("discount_fold") is not None:
            reasons.append(
                f"现金价 {eff:.2f} 万（指导价 {msrp_wan:.2f} 万，{v3_profile['discount_fold']} 折）"
            )
        else:
            reasons.append(f"可比价格 {eff:.2f} 万")
        reasons.append(f"三大件：{v3_profile['powertrain_summary']}")
        if v3_profile["feature_highlights"]:
            reasons.append("核心配置：" + " / ".join(v3_profile["feature_highlights"][:5]))
        mile = item.get("mileage_wan")
        if mile is not None and float(mile) <= 3.5:
            reasons.append(f"实表里程 {float(mile):.2f} 万公里，车况占优")
        for note in pt_info["notes"][:2]:
            if any(w in note for w in ("偏高", "差", "暗电流", "隐藏式", "日产", "95")):
                warnings.append(note)

    if item.get("needs_cash_quote"):
        warnings.append("needs_cash_quote")
    for issue in (specs.get("verification_issues") or [])[:2]:
        warnings.append(str(issue))

    confidence = {
        "price": item.get("price_confidence", 0.9),
        "config": round(cfg["coverage"], 3),
        "energy": op.get("confidence", 0),
        "core_specs": specs.get("core_confidence") or (0.9 if specs.get("specs_found") else 0.3),
        "age": age_conf,
        "space": sp_meta.get("confidence"),
    }

    return {
        "score_version": SCORE_VERSION,
        "total_score": total,
        "scores": {
            **scores,
            "price": val["abs_price_score"],
            "age": cond["age_score"],
            "mileage": cond["mileage_score"],
            "operating_cost": op["operating_cost_score"],
            "body_preference": 100.0 if is_suv else 50.0,
            "data_quality": 95.0 if specs.get("verified") else 50.0,
        },
        "weights": dict(WEIGHTS),
        "confidence": confidence,
        "reasons": reasons[:6],
        "warnings": list(dict.fromkeys(warnings)),
        "condition_gate": gate["condition_gate"],
        "recommendation_gate": "VETO" if veto["vetoed"] else "PASS",
        "veto_reasons": veto["reasons"],
        "v3_profile": v3_profile,
        "gate_flags": gate.get("flags") or [],
        "effective_price_wan": eff,
        "energy": {
            "cost_yuan_100km": op.get("energy_cost_yuan_100km"),
            "type": op.get("type"),
            "value": op.get("value"),
            "unit": op.get("unit"),
            "fuel_grade": op.get("fuel_grade"),
            "scenario": op.get("scenario"),
        },
        "config_meta": {
            "raw": cfg["raw_points"],
            "coverage": cfg["coverage"],
            "sub_buckets": cfg["sub_buckets"],
        },
        "space_meta": sp_meta,
        "is_suv": is_suv,
        "age_years": age_y,
    }
