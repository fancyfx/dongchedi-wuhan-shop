"""Compose V2 total score for one listing."""
from __future__ import annotations

from typing import Any

from .age_score import age_score, age_years_from_plate
from .body_score import body_preference_score
from .condition_gate import condition_gate
from .config import SCORE_VERSION, WEIGHTS
from .config_score import config_score
from .data_quality import data_quality_score
from .mileage_score import mileage_score
from .operating_cost import operating_cost_score
from .price_score import price_score
from .space_score import space_score

SCORE_VERSION = SCORE_VERSION  # re-export


def _is_suv(item: dict, specs: dict) -> bool:
    bt = str(specs.get("body_type") or "")
    if "SUV" in bt.upper() or "跨界" in bt:
        return True
    if "轿" in bt:
        return False
    ss = item.get("sort_scores") or {}
    return bool(ss.get("is_suv"))


def score_listing(item: dict[str, Any], today=None) -> dict[str, Any]:
    specs = item.get("specs") or {}
    eff = float(item.get("effective_price_wan") or item.get("price") or 0)
    price_s = price_score(eff)
    cfg = config_score(specs)
    op = operating_cost_score(specs)
    sp = space_score(specs)
    age_y, age_conf = age_years_from_plate(
        item.get("plate_year") or item.get("model_year"),
        item.get("plate_date"),
        today=today,
    )
    item["_age_years"] = age_y
    age_s = age_score(age_y)
    mile_s = mileage_score(item.get("mileage_wan"))
    is_suv = _is_suv(item, specs)
    body_s = body_preference_score(specs, is_suv_fallback=is_suv)
    dq = data_quality_score(specs, energy_conf=float(op.get("confidence") or 0))

    scores = {
        "price": price_s,
        "config": cfg["config_score"],
        "operating_cost": op["operating_cost_score"],
        "space": sp["space_score"],
        "age": age_s,
        "mileage": mile_s,
        "body_preference": body_s,
        "data_quality": dq["data_quality"],
    }
    total = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)
    total = round(total, 1)

    gate = condition_gate(item)

    reasons = []
    warnings = list(gate.get("warnings") or [])
    if item.get("needs_cash_quote"):
        reasons.append(
            f"分期展示价 {item.get('display_price_wan', item.get('price'))} 万，"
            f"排序用估算价 {eff} 万（+{item.get('finance_reserve_wan', 0.5)}）"
        )
        warnings.append("needs_cash_quote")
    else:
        reasons.append(f"可比价格 {eff} 万")

    if mile_s >= 90:
        reasons.append(f"里程 {item.get('mileage_wan')} 万公里，里程优势明显")
    elif mile_s <= 42:
        reasons.append(f"里程 {item.get('mileage_wan')} 万公里偏高")

    if body_s >= 85:
        reasons.append(f"车身 {specs.get('body_type') or 'SUV'} 符合偏好")
    elif body_s <= 40:
        reasons.append(f"轿车/两厢，车身偏好分较低")

    cost = op.get("energy_cost_yuan_100km")
    if cost is not None:
        reasons.append(
            f"能源成本约 {cost} 元/100km（{op.get('type')}: {op.get('value')}{op.get('unit')}）"
        )
    elif op.get("note"):
        warnings.append(op["note"])

    match_level = (specs.get("match_level") or "").lower()
    if match_level == "unverified_config":
        warnings.append("该车型尚未进入 V3 精确配置库，配置字段按未知处理")
    elif cfg["coverage"] < 0.4:
        warnings.append("精确车型配置核验覆盖率较低，配置分已向中性收缩")

    for issue in (specs.get("verification_issues") or [])[:2]:
        warnings.append(str(issue))

    confidence = {
        "price": item.get("price_confidence", 0.9),
        "config": round(cfg["coverage"], 3),
        "energy": op.get("confidence", 0),
        "core_specs": specs.get("core_confidence") or (0.9 if specs.get("specs_found") else 0.3),
        "age": age_conf,
        "space": sp.get("confidence"),
    }

    return {
        "score_version": SCORE_VERSION,
        "total_score": total,
        "scores": scores,
        "weights": dict(WEIGHTS),
        "confidence": confidence,
        "reasons": reasons[:6],
        "warnings": warnings,
        "condition_gate": gate["condition_gate"],
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
            "raw": cfg["config_raw"],
            "coverage": cfg["coverage"],
            "earned_points": cfg["earned_points"],
        },
        "space_meta": sp,
        "is_suv": is_suv,
        "age_years": age_y,
    }
