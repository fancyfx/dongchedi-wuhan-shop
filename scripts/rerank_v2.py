#!/usr/bin/env python3
"""V2 re-rank: apply verified specs, fixed-anchor scores, write artifacts."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from filters import FILTER_META, MAX_BEV_RANGE_KM, filter_listings  # noqa: E402
from ranking_v2.apply_verified import apply_verified_to_listings, load_verified_by_sku  # noqa: E402
from ranking_v2.config import ENERGY, FINANCE, SCORE_VERSION, WEIGHTS  # noqa: E402
from ranking_v2.score import score_listing  # noqa: E402

# reuse manufacturer mapping from V1 rerank
from rerank_composite import map_manufacturer, series_key  # noqa: E402


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_evaluation(item: dict, result: dict) -> str:
    bits = list(result.get("reasons") or [])[:3]
    warns = result.get("warnings") or []
    if result.get("condition_gate") == "MANUAL_REVIEW":
        bits.append("⚠️ 待人工确认")
    if item.get("needs_cash_quote"):
        bits.append("分期价需询现金价")
    text = "；".join(bits)
    if warns:
        text += "。提示：" + "；".join(str(w) for w in warns[:2])
    return text + ("。" if text and not text.endswith("。") else "")


def main() -> None:
    verified_path = ROOT / "data" / "vehicle-specs-verified.json"
    src = None
    for candidate in (
        ROOT / "data" / "listings-ranked.json",
        ROOT / "listings-ranked.json",
        ROOT / "data" / "listings-filtered.json",
    ):
        if candidate.exists():
            src = candidate
            break
    if not src:
        raise SystemExit("no listings source")

    raw = json.loads(src.read_text(encoding="utf-8"))
    listings, excluded = filter_listings(raw)
    n_before = len(raw)

    verified = load_verified_by_sku(verified_path) if verified_path.exists() else {}
    listings = apply_verified_to_listings(listings, verified)

    for item in listings:
        brand, manu, inferred = map_manufacturer(item["title"])
        item["brand"] = brand
        item["manufacturer"] = manu
        item["manufacturer_inferred"] = inferred
        item["series"] = series_key(item["title"])
        item.setdefault("owner_reviews", {"summary": "", "sources": [], "found": False})

        # preserve V1 score if present
        old_total = item.get("total_score")
        old_ss = dict(item.get("sort_scores") or {})

        result = score_listing(item)
        if result["condition_gate"] == "REJECT":
            result["total_score"] = -1.0

        item["score_version"] = SCORE_VERSION
        item["score_v1"] = old_total
        item["total_score"] = result["total_score"]
        item["condition_gate"] = result["condition_gate"]
        item["evaluation"] = build_evaluation(item, result)
        item["score_reasons"] = result["reasons"]
        item["score_warnings"] = result["warnings"]
        item["confidence"] = result["confidence"]

        ss = {
            **old_ss,
            "score_version": SCORE_VERSION,
            "total_score": result["total_score"],
            "price_score": result["scores"]["price"],
            "config_score": result["scores"]["config"],
            "operating_cost_score": result["scores"]["operating_cost"],
            "space_score": result["scores"]["space"],
            "age_score": result["scores"]["age"],
            "mileage_score": result["scores"]["mileage"],
            "body_preference_score": result["scores"]["body_preference"],
            "data_quality_score": result["scores"]["data_quality"],
            # keep legacy aliases for dashboard compatibility
            "config_norm": result["scores"]["config"],
            "space_norm": result["scores"]["space"],
            "fuel_norm": result["scores"]["operating_cost"],
            "suv_score": result["scores"]["body_preference"],
            "config_proxy": result["scores"]["config"],
            "space_proxy": result["scores"]["space"],
            "fuel_proxy": result["scores"]["operating_cost"],
            "is_suv": result["is_suv"],
            "price": item.get("price"),
            "effective_price_wan": result["effective_price_wan"],
            "weights": dict(WEIGHTS),
            "energy": result["energy"],
            "confidence": result["confidence"],
            "reasons": result["reasons"],
            "warnings": result["warnings"],
            "condition_gate": result["condition_gate"],
            "note": (
                f"V2固定锚点 score_version={SCORE_VERSION}; "
                f"weights={WEIGHTS}; scenario={ENERGY['default_scenario']}; "
                f"no cohort min-max"
            ),
        }
        item["sort_scores"] = ss

    # rank: REJECT last
    listings.sort(
        key=lambda x: (
            0 if x.get("condition_gate") != "REJECT" else 1,
            -float(x.get("total_score") or 0),
            -float((x.get("sort_scores") or {}).get("price_score") or 0),
            float(x.get("effective_price_wan") or x.get("price") or 99),
            float(x.get("mileage_wan") or 99),
        )
    )
    for i, item in enumerate(listings, 1):
        item["rank"] = i

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat(timespec="seconds")
    shortlist = listings[:30]
    cheapest = sorted(
        listings,
        key=lambda x: (
            float(x.get("effective_price_wan") or x["price"]),
            -float(x.get("total_score") or 0),
        ),
    )[:30]

    meta_path = ROOT / "data" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    filters = dict(meta.get("filters") or {})
    filters.update({"price": "<=6万", "mileage": "<=10万公里", "vehicle_age": "<=10年", **FILTER_META})
    meta["filters"] = filters
    meta["score_version"] = SCORE_VERSION
    meta["sort_preference"] = "v2_fixed_anchor_total_score"
    meta["sort_method"] = "ranking_v2_fixed_anchors"
    meta["sort_weights"] = WEIGHTS
    meta["sort_formula"] = (
        "total = 0.15*price + 0.30*config + 0.15*operating_cost + 0.20*space "
        "+ 0.05*age + 0.05*mileage + 0.05*body_preference + 0.05*data_quality; "
        "fixed anchors (no cohort min-max); "
        "operating_cost from energy_cost_yuan_100km; "
        "finance display +0.5万 reserve when price_type=分期"
    )
    meta["energy_prices"] = {
        "gas_92_yuan_l": ENERGY["gas_92_yuan_l"],
        "gas_95_yuan_l": ENERGY["gas_95_yuan_l"],
        "home_electricity_yuan_kwh": ENERGY["home_electricity_yuan_kwh"],
        "public_electricity_yuan_kwh": ENERGY["public_electricity_yuan_kwh"],
        "wltc_fallback_multiplier": ENERGY["wltc_fallback_multiplier"],
        "nedc_fallback_multiplier": ENERGY["nedc_fallback_multiplier"],
    }
    meta["energy_scenario"] = ENERGY["default_scenario"]
    meta["finance_reserve_wan"] = FINANCE["unknown_all_in_reserve_wan"]
    meta["verified_specs_file"] = "data/vehicle-specs-verified.json"
    meta["verified_sku_count"] = len(verified)
    meta["ranked_at"] = now
    meta["ranked_count"] = len(listings)
    meta["filtered_count"] = len(listings)
    meta["excluded_short_range_bev_count"] = len(excluded)
    meta["excluded_short_range_bev"] = excluded
    meta["bev_filter"] = FILTER_META.get("exclude_short_range_bev_desc")
    meta["notes"] = (
        f"算法版本 {SCORE_VERSION}。固定锚点评分；能源场景 {ENERGY['default_scenario']}；"
        f"油价92={ENERGY['gas_92_yuan_l']}/95={ENERGY['gas_95_yuan_l']}，家用电={ENERGY['home_electricity_yuan_kwh']}；"
        f"分期价+{FINANCE['unknown_all_in_reserve_wan']}万不确定性；"
        f"前{len(verified)}条核验参数已覆盖；series_year_tier高级配置置null；"
        f"短名单为过滤后按V2总分排序前30。"
    )
    meta["filter_pipeline"] = (
        f"shop_id=118608 → price≤6 → mileage≤10万km → age≤10年 → "
        f"exclude_short_range_bev; before={n_before} after={len(listings)}"
    )

    for p in (ROOT / "listings-ranked.json", ROOT / "data" / "listings-ranked.json"):
        dump_json(p, listings)
    for p in (ROOT / "listings-filtered.json", ROOT / "data" / "listings-filtered.json"):
        dump_json(p, listings)
    for p in (ROOT / "shortlist-ranked.json", ROOT / "data" / "shortlist-ranked.json"):
        dump_json(p, shortlist)
    for p in (ROOT / "shortlist-cheapest.json", ROOT / "data" / "shortlist-cheapest.json"):
        dump_json(p, cheapest)
    dump_json(ROOT / "data" / "excluded-short-range-bev.json", excluded)
    dump_json(meta_path, meta)

    # sync dashboard public data
    dash = ROOT / "dashboard" / "public" / "data"
    if dash.exists():
        for name in (
            "listings-ranked.json",
            "listings-filtered.json",
            "shortlist-ranked.json",
            "shortlist-cheapest.json",
            "meta.json",
            "vehicle-specs-verified.json",
        ):
            srcp = ROOT / "data" / name
            if srcp.exists():
                dump_json(dash / name, json.loads(srcp.read_text(encoding="utf-8")))

    print(f"SRC {src}")
    print(f"SCORE_VERSION {SCORE_VERSION} AFTER {len(listings)} VERIFIED {len(verified)}")
    print("TOP15")
    for x in listings[:15]:
        en = (x.get("sort_scores") or {}).get("energy") or {}
        print(
            f"{x['rank']:2} | {x['total_score']:5.1f} | eff={x.get('effective_price_wan')} | "
            f"km={x.get('mileage_wan')} | gate={x.get('condition_gate')} | "
            f"cost={en.get('cost_yuan_100km')} | {x['title'][:40]} | sku={x['sku']}"
        )


if __name__ == "__main__":
    main()
