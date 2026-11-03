#!/usr/bin/env python3
"""V2 re-rank with exact-trim hard data-quality gating."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from display_gate import DISPLAY_LIMIT, apply_display_flags, display_sort_key  # noqa: E402
from filters import FILTER_META, filter_listings  # noqa: E402
from ranking_v2.apply_verified import apply_verified_to_listings, load_verified_by_sku  # noqa: E402
from ranking_v2.config import ENERGY, FINANCE, SCORE_VERSION, WEIGHTS  # noqa: E402
from ranking_v2.data_quality import assess_score_eligibility  # noqa: E402
from ranking_v2.score import score_listing  # noqa: E402
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


def issue_evaluation(issues: list[dict]) -> str:
    messages = [str(x.get("message") or x.get("code")) for x in issues]
    if not messages:
        messages = ["数据不足"]
    return "；".join(messages[:4]) + "，不参与评分。"


def score_one(item: dict) -> dict:
    """Score one listing in place. Eligible rows keep a V2 total; others stay unscored."""
    brand, manu, inferred = map_manufacturer(item["title"])
    item["brand"] = brand
    item["manufacturer"] = manu
    item["manufacturer_inferred"] = inferred
    item["series"] = series_key(item["title"])
    item.setdefault("owner_reviews", {"summary": "", "sources": [], "found": False})

    old_total = item.get("total_score")
    old_ss = dict(item.get("sort_scores") or {})
    quality = assess_score_eligibility(item)
    item["score_eligible"] = bool(quality["eligible"])
    item["data_issues"] = quality["issues"]
    item["config_coverage"] = round(float(quality["config_coverage"]), 4)
    item["energy_confidence"] = round(float(quality["energy_confidence"]), 3)

    if not quality["eligible"]:
        item["score_version"] = SCORE_VERSION
        item["score_v1"] = old_total
        item["total_score"] = None
        item["rank"] = None
        item["condition_gate"] = "DATA_ISSUE"
        item["evaluation"] = issue_evaluation(quality["issues"])
        item["score_reasons"] = []
        item["score_warnings"] = [x["message"] for x in quality["issues"]]
        item["sort_scores"] = {
            "score_version": SCORE_VERSION,
            "total_score": None,
            "config_score": None,
            "config_norm": None,
            "config_proxy": None,
            "is_suv": "suv" in str((item.get("specs") or {}).get("body_type") or "").lower(),
            "price": item.get("price"),
            "effective_price_wan": item.get("effective_price_wan"),
            "condition_gate": "DATA_ISSUE",
            "note": "数据不足，不参与评分",
        }
        return item

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
    item["sort_scores"] = {
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
            f"V2 fixed anchors score_version={SCORE_VERSION}; "
            f"exact-trim gate passed; weights={WEIGHTS}; scenario={ENERGY['default_scenario']}"
        ),
    }
    return item


def main() -> None:
    verified_path = ROOT / "data" / "vehicle-specs-verified.json"
    # listings-filtered retains the complete post-hard-filter inventory, including
    # data-issue rows. Prefer it so an unscored listing is never lost on reruns.
    src = None
    for candidate in (
        ROOT / "data" / "listings-filtered.json",
        ROOT / "listings-filtered.json",
        ROOT / "data" / "listings-ranked.json",
        ROOT / "listings-ranked.json",
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

    ranked: list[dict] = []
    data_issues: list[dict] = []

    for item in listings:
        score_one(item)
        if item.get("score_eligible"):
            ranked.append(item)
        else:
            data_issues.append(item)

    ranked.sort(key=display_sort_key)
    display, below = apply_display_flags(ranked)

    # Stable issue ordering: config gaps first, then price/title for inspection.
    data_issues.sort(
        key=lambda x: (
            0 if any(i.get("code") == "detailed_config_insufficient" for i in x.get("data_issues") or []) else 1,
            float(x.get("price") or 99),
            str(x.get("title") or ""),
        )
    )

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat(timespec="seconds")
    shortlist = display[:30]
    cheapest = sorted(
        display,
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
    meta["sort_preference"] = "v2_fixed_anchor_total_score_exact_trim_only"
    meta["sort_method"] = "ranking_v2_fixed_anchors_with_hard_data_gate"
    meta["sort_weights"] = WEIGHTS
    meta["sort_formula"] = (
        "eligible only: exact-trim config coverage>=60%, valid price/mileage/age/space/energy; "
        "total = 0.15*price + 0.30*config + 0.15*operating_cost + 0.20*space "
        "+ 0.05*age + 0.05*mileage + 0.05*body_preference + 0.05*data_quality; "
        "fixed anchors (no cohort min-max)"
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
    meta["ranked_count"] = len(display)
    meta["library_scored_count"] = len(ranked)
    meta["below_display_count"] = len(below)
    meta["display_limit"] = DISPLAY_LIMIT
    meta["display_score_floor"] = display[-1]["total_score"] if display else None
    meta["data_issue_count"] = len(data_issues)
    meta["filtered_count"] = len(listings)
    meta["excluded_short_range_bev_count"] = len(excluded)
    meta["excluded_short_range_bev"] = excluded
    meta["bev_filter"] = FILTER_META.get("exclude_short_range_bev_desc")
    meta["data_quality_policy"] = {
        "exact_trim_only": True,
        "min_config_coverage": 0.60,
        "unscored_message": "详细配置数据不足",
        "issues_file": "data/data-issues.json",
    }
    meta["notes"] = (
        f"算法版本 {SCORE_VERSION}。仅 exact-trim 且配置覆盖率>=60%的车辆参与评分；"
        f"评分车辆 {len(ranked)}，看板展示前 {len(display)} 名，低于展示线 {len(below)}，"
        f"数据异常/待补全 {len(data_issues)}。"
        "缺详细配置、空间、价格、里程、车龄或能耗任一关键数据时不再给中性分，统一进入数据异常 Tab。"
    )
    meta["filter_pipeline"] = (
        f"shop_id=118608 → hard filters → exact-trim/data-quality gate → top {len(display)} display; "
        f"source={n_before} filtered={len(listings)} scored={len(ranked)} "
        f"display={len(display)} below={len(below)} data_issues={len(data_issues)}"
    )

    # listings-ranked.json is the board display set (top 100). Filtered keeps
    # every admitted car, including scored rows that fell below the display line.
    for item in data_issues:
        item["display"] = False
        item["rank"] = None
    all_filtered = ranked + data_issues
    for p in (ROOT / "listings-ranked.json", ROOT / "data" / "listings-ranked.json"):
        dump_json(p, display)
    dump_json(ROOT / "data" / "listings-below-display.json", below)
    for p in (ROOT / "listings-filtered.json", ROOT / "data" / "listings-filtered.json"):
        dump_json(p, all_filtered)
    for p in (ROOT / "shortlist-ranked.json", ROOT / "data" / "shortlist-ranked.json"):
        dump_json(p, shortlist)
    for p in (ROOT / "shortlist-cheapest.json", ROOT / "data" / "shortlist-cheapest.json"):
        dump_json(p, cheapest)
    dump_json(ROOT / "data" / "data-issues.json", data_issues)
    dump_json(ROOT / "data" / "excluded-short-range-bev.json", excluded)
    dump_json(meta_path, meta)

    dash = ROOT / "dashboard" / "public" / "data"
    if dash.exists():
        for name in (
            "listings-ranked.json",
            "listings-filtered.json",
            "shortlist-ranked.json",
            "shortlist-cheapest.json",
            "data-issues.json",
            "meta.json",
            "vehicle-specs-verified.json",
        ):
            srcp = ROOT / "data" / name
            if srcp.exists():
                dump_json(dash / name, json.loads(srcp.read_text(encoding="utf-8")))

    print(f"SRC {src}")
    print(f"SCORE_VERSION {SCORE_VERSION} FILTERED {len(listings)} SCORED {len(ranked)} DISPLAY {len(display)} BELOW {len(below)} DATA_ISSUES {len(data_issues)} VERIFIED {len(verified)}")
    print("TOP15")
    for x in display[:15]:
        en = (x.get("sort_scores") or {}).get("energy") or {}
        print(
            f"{x['rank']:2} | {x['total_score']:5.1f} | eff={x.get('effective_price_wan')} | "
            f"km={x.get('mileage_wan')} | gate={x.get('condition_gate')} | "
            f"cost={en.get('cost_yuan_100km')} | {x['title'][:40]} | sku={x['sku']}"
        )
    if data_issues:
        print("DATA_ISSUES_SAMPLE")
        for x in data_issues[:10]:
            codes = ",".join(i.get("code", "") for i in x.get("data_issues") or [])
            print(f" - {x.get('sku')} | {codes} | {x.get('title')}")


if __name__ == "__main__":
    main()
