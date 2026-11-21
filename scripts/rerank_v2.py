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
from shops import BUYER_CITY, DIRECT_SHOPS, PLAN_A_SHOP_IDS  # noqa: E402


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_evaluation(item: dict, result: dict) -> str:
    if result.get("recommendation_gate") == "VETO":
        reasons = result.get("veto_reasons") or ["不符合节假日低频用车四大铁律"]
        return "一票否决：" + "；".join(reasons) + "。"
    profile = result.get("v3_profile") or {}
    if profile.get("recommend_reason"):
        text = str(profile["recommend_reason"])
        if item.get("needs_cash_quote"):
            text += " 分期价需询现金价。"
        return text
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


def score_one(item: dict, reviews_by_series: dict | None = None) -> dict:
    """Score one listing in place. Eligible rows keep a V3 total; others stay unscored."""
    brand, manu, inferred = map_manufacturer(item["title"])
    item["brand"] = brand
    item["manufacturer"] = manu
    item["manufacturer_inferred"] = inferred
    item["series"] = series_key(item["title"])
    if reviews_by_series and item["series"] in reviews_by_series:
        item["owner_reviews"] = reviews_by_series[item["series"]]
    else:
        item.setdefault("owner_reviews", {"summary": "", "sources": [], "found": False})
    item.setdefault("sale_status", "on_sale")

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
        item["recommendation_gate"] = "DATA_ISSUE"
        item["veto_reasons"] = []
        item["v3_profile"] = None
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
    if result["condition_gate"] == "REJECT" or result["recommendation_gate"] == "VETO":
        result["total_score"] = -1.0

    item["score_version"] = SCORE_VERSION
    item["score_v1"] = old_total
    item["total_score"] = result["total_score"]
    item["condition_gate"] = result["condition_gate"]
    item["recommendation_gate"] = result["recommendation_gate"]
    item["veto_reasons"] = result["veto_reasons"]
    item["v3_profile"] = result["v3_profile"]
    item["evaluation"] = build_evaluation(item, result)
    item["score_reasons"] = result["reasons"]
    item["score_warnings"] = result["warnings"]
    item["confidence"] = result["confidence"]
    profile = result["v3_profile"] or {}
    item["sort_scores"] = {
        **old_ss,
        "score_version": SCORE_VERSION,
        "total_score": result["total_score"],
        "powertrain_score": result["scores"]["powertrain"],
        "config_score": result["scores"]["config"],
        "value_price_score": result["scores"]["value_price"],
        "condition_score": result["scores"]["condition"],
        "space_score": result["scores"]["space"],
        "price_score": result["scores"]["value_price"],
        "operating_cost_score": result["scores"]["operating_cost"],
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
        "msrp_wan": profile.get("msrp_wan"),
        "discount_fold": profile.get("discount_fold"),
        "weights": dict(WEIGHTS),
        "energy": result["energy"],
        "confidence": result["confidence"],
        "reasons": result["reasons"],
        "warnings": result["warnings"],
        "condition_gate": result["condition_gate"],
        "recommendation_gate": result["recommendation_gate"],
        "note": (
            f"V3.2 SUV-first modern cabin buyer score_version={SCORE_VERSION}; "
            f"weights={WEIGHTS}; tiered_dmi_admission"
        ),
    }
    return item


def _veto_breakdown(items: list[dict]) -> dict[str, int]:
    counts = {"ev_phev": 0, "bev": 0, "risky_phev": 0, "three_cyl": 0, "dry_dct": 0}
    for x in items:
        if x.get("recommendation_gate") != "VETO":
            continue
        blob = " ".join(x.get("veto_reasons") or [])
        if "纯电" in blob:
            counts["bev"] += 1
            counts["ev_phev"] += 1
        elif "插混" in blob:
            counts["risky_phev"] += 1
            counts["ev_phev"] += 1
        if "三缸" in blob:
            counts["three_cyl"] += 1
        if "干式双离合" in blob:
            counts["dry_dct"] += 1
    return counts


def main() -> None:
    verified_path = ROOT / "data" / "vehicle-specs-verified.json"
    reviews_path = ROOT / "data" / "owner-reviews-by-series.json"
    reviews_by_series = json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path.exists() else {}
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

    eligible_active: list[dict] = []
    below_extra: list[dict] = []
    data_issues: list[dict] = []

    for item in listings:
        score_one(item, reviews_by_series=reviews_by_series)
        if not item.get("score_eligible"):
            data_issues.append(item)
        elif item.get("sale_status") in {"sold", "reserved"} or item.get("recommendation_gate") == "VETO":
            item["display"] = False
            item["rank"] = None
            below_extra.append(item)
        else:
            eligible_active.append(item)

    eligible_active.sort(key=display_sort_key)
    display, scored_below = apply_display_flags(eligible_active, DISPLAY_LIMIT)
    below = scored_below + below_extra
    ranked = eligible_active + below_extra

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

    reserved_count = sum(1 for x in listings if x.get("sale_status") == "reserved")
    vetoed_count = sum(1 for x in listings if x.get("recommendation_gate") == "VETO")
    on_sale_count = sum(1 for x in listings if x.get("sale_status") != "reserved")
    veto_bd = _veto_breakdown(listings)

    meta_path = ROOT / "data" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    filters = dict(meta.get("filters") or {})
    filters.update({"price": "<=6万", "mileage": "<=10万公里", "vehicle_age": "<=10年", **FILTER_META})
    meta["filters"] = filters
    meta["score_version"] = SCORE_VERSION
    meta["sort_preference"] = "v3_2_suv_first_modern_cabin_with_dmi_top30"
    meta["sort_method"] = "ranking_v3_2_suv_cabin_and_tiered_hybrid"
    meta["sort_weights"] = WEIGHTS
    meta["sort_formula"] = (
        "铁律否决（纯电BEV、老架构/高龄高里程/疑似营运插混、三缸机、干式双离合）+ 准新E-CVT电混放行 + 锁单隐藏；"
        "total = 0.28*现代座舱配置 + 0.20*SUV立体空间(轿车降权备选) + 0.20*三大件可靠性 + 0.18*里程车龄 + 0.14*到汉价格值"
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
    meta["library_scored_count"] = len(eligible_active)
    meta["below_display_count"] = len(below)
    meta["display_limit"] = DISPLAY_LIMIT
    meta["display_score_floor"] = display[-1]["total_score"] if display else None
    meta["data_issue_count"] = len(data_issues)
    meta["filtered_count"] = len(listings)
    meta["on_sale_count"] = on_sale_count
    meta["reserved_count"] = reserved_count
    meta["vetoed_count"] = vetoed_count
    meta["veto_breakdown"] = veto_bd
    meta["excluded_short_range_bev_count"] = len(excluded)
    meta["excluded_short_range_bev"] = excluded
    meta["bev_filter"] = FILTER_META.get("exclude_short_range_bev_desc")
    meta["data_quality_policy"] = {
        "exact_trim_only": True,
        "min_config_coverage": 0.60,
        "unscored_message": "详细配置数据不足",
        "issues_file": "data/data-issues.json",
    }

    top_counts: dict[str, int] = {}
    for x in display:
        sid = str(x.get("shop_id") or "")
        top_counts[sid] = top_counts.get(sid, 0) + 1
    inv_counts: dict[str, int] = {}
    fee_samples: dict[str, int] = {}
    for x in listings:
        sid = str(x.get("shop_id") or "")
        inv_counts[sid] = inv_counts.get(sid, 0) + 1
        if sid not in fee_samples and x.get("logistics_fee_yuan") is not None:
            fee_samples[sid] = int(x["logistics_fee_yuan"])
    shops_summary = []
    for sid in PLAN_A_SHOP_IDS:
        reg = DIRECT_SHOPS.get(sid) or {}
        shops_summary.append({
            "shop_id": sid,
            "name": reg.get("name") or sid,
            "short_name": reg.get("short_name") or sid,
            "city": reg.get("city") or "",
            "kind": reg.get("kind") or "直营",
            "is_local": bool(reg.get("is_local")),
            "logistics_fee_yuan": fee_samples.get(sid, reg.get("fallback_logistics_yuan", 1000)),
            "inventory_count": inv_counts.get(sid, 0),
            "top_count": top_counts.get(sid, 0),
        })
    meta["buyer_city"] = BUYER_CITY
    meta["shop_scope"] = "plan_a_7_direct_shops"
    meta["shops"] = shops_summary
    meta["pricing_policy"] = (
        "到汉可比价 = 全款现金价 + 到汉官方物流费（card/detail实时获取，兜底+1000元）+ 异地上牌服务费差额（500元）"
    )
    meta["notes"] = (
        f"算法版本 {SCORE_VERSION}（华中7城直营 · 节假日低频用车买手严选）。"
        f"7城直营在库 {len(listings)} 台（在售 {on_sale_count} / 锁单隐藏 {reserved_count}），"
        f"四大铁律否决 {vetoed_count} 台（新能源{veto_bd['ev_phev']}/三缸{veto_bd['three_cyl']}/干式双离合{veto_bd['dry_dct']}），"
        f"合格参评 {len(eligible_active)} 台，严选展示 Top {len(display)} 台。"
    )
    meta["filter_pipeline"] = (
        f"华中7城官方直营 → 到汉可比总价≤6.0万 → 实时售出清理 & 锁单隐藏({reserved_count}) → "
        f"四大铁律否决({vetoed_count}) → V3综合评分({len(eligible_active)}) → 严选 Top {len(display)}；"
        f"source={n_before} filtered={len(listings)} data_issues={len(data_issues)}"
    )

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
    print(
        f"SCORE_VERSION {SCORE_VERSION} FILTERED {len(listings)} ON_SALE {on_sale_count} "
        f"RESERVED {reserved_count} VETOED {vetoed_count} ELIGIBLE {len(eligible_active)} "
        f"DISPLAY {len(display)} BELOW {len(below)} DATA_ISSUES {len(data_issues)}"
    )
    print("TOP15")
    for x in display[:15]:
        prof = x.get("v3_profile") or {}
        shop_lbl = x.get("shop_short_name") or x.get("city") or "武汉"
        print(
            f"{x['rank']:2} | {x['total_score']:5.1f} | {shop_lbl:<5} | 到汉{x.get('effective_price_wan')}w(裸{x.get('price')}w) "
            f"({prof.get('discount_fold') or '-'}折) | km={x.get('mileage_wan')} | "
            f"{prof.get('gearbox_label') or ''} | {x['title'][:30]} | sku={x['sku']}"
        )
    if data_issues:
        print("DATA_ISSUES_SAMPLE")
        for x in data_issues[:10]:
            codes = ",".join(i.get("code", "") for i in x.get("data_issues") or [])
            print(f" - {x.get('sku')} | {codes} | {x.get('title')}")


if __name__ == "__main__":
    main()
