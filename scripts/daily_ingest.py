#!/usr/bin/env python3
"""Daily multi-shop direct-operated ingest (Plan A: 7 Central China shops).

Fetch shop lists (search_id paging), read detail cash prices & Wuhan logistics/plate
fees, apply landed-budget hard filters (<=6.0w landed in Wuhan), diff the catalog,
sync missing AutoHome specs via param API, score with V3 engine, download covers,
and keep the display board to the top 30.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dcd_fetch import (  # noqa: E402
    FetchError,
    FixtureClient,
    HttpClient,
    fetch_multi_shop_batch,
    fetch_shop_batch,
    load_fixture_dir,
    normalize_card,
    parse_cash_price,
    parse_fulfillment_fees,
    parse_sale_status,
)
from display_gate import (  # noqa: E402
    DISPLAY_LIMIT,
    apply_display_flags,
    build_wuhan_board,
    display_sort_key,
    is_local_wuhan,
    numeric_score,
    ranked_threshold,
)
from filters import admission_reason  # noqa: E402
from shops import (  # noqa: E402
    BUYER_CITY,
    DIRECT_SHOPS,
    PLAN_A_SHOP_IDS,
    compute_landed_costs,
    compute_landed_price_wan,
    parse_shop_list_arg,
)

SHANGHAI = timezone(timedelta(hours=8))
MARKET_KEYS = (
    "title",
    "price",
    "price_type",
    "prefix",
    "cash_price_wan",
    "cash_price_fen",
    "cash_price_str",
    "list_price_wan",
    "mileage_wan",
    "model_year",
    "plate_year",
    "year",
    "city",
    "tags",
    "is_self_trade_car",
    "source_type",
    "source_type_name",
    "fuel_form",
    "cover",
    "detail_url",
    "shop_id",
    "shop_name",
    "shop_short_name",
    "is_local_wuhan",
    "logistics_fee_yuan",
    "logistics_fee_source",
    "plate_service_fee_yuan",
    "plate_fee_diff_yuan",
    "landed_extra_yuan",
    "landed_extra_wan",
    "landed_price_wan",
    "delivery_eta",
    "series",
    "brand",
    "first_registration_time",
    "detail_shop_id",
    "sale_status",
    "product_status",
    "status_modify_time",
)
SCORE_KEYS = (
    "total_score",
    "score_eligible",
    "score_version",
    "score_v1",
    "sort_scores",
    "condition_gate",
    "recommendation_gate",
    "veto_reasons",
    "v3_profile",
    "evaluation",
    "score_reasons",
    "score_warnings",
    "confidence",
    "config_coverage",
    "energy_confidence",
    "data_issues",
    "effective_price_wan",
    "display_price_wan",
    "needs_cash_quote",
    "price_basis",
    "price_confidence",
    "specs",
    "detailed_config",
    "brand",
    "manufacturer",
    "manufacturer_inferred",
    "series",
)


def now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def today_stamp() -> str:
    return datetime.now(SHANGHAI).strftime("%Y%m%d")


def dump_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def price_of(item: dict[str, Any] | None) -> float | None:
    if not item:
        return None
    raw = item.get("cash_price_wan")
    if raw in (None, ""):
        raw = item.get("price")
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


def mile_of(item: dict[str, Any] | None) -> float | None:
    if not item:
        return None
    try:
        return round(float(item.get("mileage_wan")), 2)
    except (TypeError, ValueError):
        return None


def classify_change(old: dict[str, Any] | None, new: dict[str, Any]) -> str:
    if old is None:
        return "added"
    if old.get("sale_status") == "reserved" and new.get("sale_status", "on_sale") == "on_sale":
        return "restored_on_sale"
    changes = []
    if price_of(old) != price_of(new):
        changes.append("price")
    old_extra = old.get("landed_extra_yuan")
    new_extra = new.get("landed_extra_yuan")
    if old_extra is not None and new_extra is not None and int(old_extra) != int(new_extra):
        changes.append("landed_cost")
    elif old_extra is None and new_extra is not None and int(new_extra) > 0:
        changes.append("landed_cost")
    if old.get("shop_id") and new.get("shop_id") and str(old.get("shop_id")) != str(new.get("shop_id")):
        changes.append("landed_cost")
    if mile_of(old) != mile_of(new):
        changes.append("mileage")
    if str(old.get("title") or "") != str(new.get("title") or ""):
        changes.append("title")
    if not changes:
        return "unchanged"
    if "price" in changes or "landed_cost" in changes:
        return "updated_price"
    return "updated"


def merge_record(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    if old is None:
        return dict(new)
    merged = dict(old)
    for key in MARKET_KEYS:
        value = new.get(key)
        if value in (None, "", []):
            continue
        merged[key] = value
    badges = [str(badge) for badge in (old.get("badges") or [])]
    for badge in new.get("badges") or []:
        text = str(badge)
        if text and text not in badges:
            badges.append(text)
    if badges:
        merged["badges"] = badges
    if "score_eligible" in new:
        for key in SCORE_KEYS:
            if key in new:
                merged[key] = new[key]
    return merged


def _change(
    change_type: str,
    item: dict[str, Any] | None,
    old: dict[str, Any] | None,
    *,
    now: str,
    reason: str | None,
    threshold: float | None,
) -> dict[str, Any]:
    source = item or old or {}
    return {
        "sku": str(source.get("sku") or ""),
        "title": source.get("title"),
        "change_type": change_type,
        "old_price": price_of(old),
        "new_price": price_of(item),
        "old_score": numeric_score(old),
        "new_score": numeric_score(item) if item else None,
        "reason": reason,
        "threshold": threshold,
        "at": now,
    }


def apply_catalog_update(
    inventory: list[dict[str, Any]],
    previous_ranked: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    rejected_hard: list[dict[str, Any]],
    *,
    reconciled_missing: dict[str, dict[str, Any]] | None = None,
    admit_below_threshold: bool = True,
    display_limit: int = DISPLAY_LIMIT,
    now: str,
) -> dict[str, Any]:
    """Diff, sold/reserved reconciliation, top-N admission, and display split."""
    by_sku: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in inventory:
        sku = str(item.get("sku") or "")
        if not sku or sku in by_sku:
            continue
        row = dict(item)
        row.setdefault("sale_status", "on_sale")
        by_sku[sku] = row
        order.append(sku)
    previous_by_sku = {str(item.get("sku")): item for item in previous_ranked if item.get("sku")}
    previous_display = [
        sku for sku, item in previous_by_sku.items() if item.get("display") is not False
    ]
    threshold = ranked_threshold(list(previous_by_sku.values()), display_limit)
    changelog: list[dict[str, Any]] = []

    def add(change_type: str, item: dict[str, Any] | None, old: dict[str, Any] | None, reason: str | None) -> None:
        changelog.append(_change(change_type, item, old, now=now, reason=reason, threshold=threshold))

    # Reconcile SKUs already in inventory that did not appear in today's list.
    for sku, info in (reconciled_missing or {}).items():
        sku = str(sku)
        old = by_sku.get(sku)
        if old is None:
            continue
        status = str(info.get("status") or "")
        if status == "sold":
            by_sku.pop(sku, None)
            order = [existing for existing in order if existing != sku]
            add("removed_sold", info.get("item"), old, info.get("reason") or "product_status_0_sold")
        elif status == "reserved":
            was_reserved = old.get("sale_status") == "reserved"
            was_displayed = sku in previous_by_sku
            old["sale_status"] = "reserved"
            old["product_status"] = info.get("product_status", 5)
            if info.get("status_modify_time"):
                old["status_modify_time"] = info["status_modify_time"]
            old["display"] = False
            old["rank"] = None
            old["ingest_status"] = "reserved"
            if not was_reserved or was_displayed:
                add("reserved_hidden", old, old, info.get("reason") or "product_status_5_reserved")
        elif status == "hard_rejected":
            by_sku.pop(sku, None)
            order = [existing for existing in order if existing != sku]
            add("removed_hard_filter", info.get("item"), old, info.get("reason"))
        elif status == "on_sale":
            updated_item = info.get("item")
            was_reserved = old.get("sale_status") == "reserved"
            if updated_item:
                merged = merge_record(old, updated_item)
                merged["sale_status"] = "on_sale"
                merged["product_status"] = info.get("product_status", 1)
                if was_reserved:
                    merged["ingest_status"] = "restored_on_sale"
                    by_sku[sku] = merged
                    add("restored_on_sale", merged, old, "returned_to_on_sale")
                elif price_of(old) != price_of(updated_item):
                    merged["ingest_status"] = "updated_price"
                    by_sku[sku] = merged
                    add("updated_price", merged, old, None)
                else:
                    by_sku[sku] = merged
            elif was_reserved:
                old["sale_status"] = "on_sale"
                old["product_status"] = info.get("product_status", 1)
                old["ingest_status"] = "restored_on_sale"
                add("restored_on_sale", old, old, "returned_to_on_sale")
        elif status == "detail_failed":
            add("detail_failed", info.get("item"), old, info.get("reason"))

    rejected_skus: set[str] = set()
    for item in rejected_hard:
        sku = str(item.get("sku") or "")
        old = by_sku.get(sku)
        if old is not None:
            by_sku.pop(sku, None)
            order = [existing for existing in order if existing != sku]
            add("removed_hard_filter", item, old, item.get("_reject_reason"))
        else:
            add("rejected_hard_filter", item, None, item.get("_reject_reason"))
        if sku:
            rejected_skus.add(sku)

    admitted_new: list[str] = []
    for item in incoming:
        sku = str(item.get("sku") or "")
        if not sku or sku in rejected_skus:
            continue
        item_sale = item.get("sale_status") or "on_sale"
        old = by_sku.get(sku)
        if item_sale == "sold":
            if old is not None:
                by_sku.pop(sku, None)
                order = [existing for existing in order if existing != sku]
                add("removed_sold", item, old, "product_status_0_sold")
            continue
        if item_sale == "reserved":
            if old is not None:
                was_reserved = old.get("sale_status") == "reserved"
                merged = merge_record(old, item)
                merged["sale_status"] = "reserved"
                merged["display"] = False
                merged["rank"] = None
                merged["ingest_status"] = "reserved"
                by_sku[sku] = merged
                if not was_reserved:
                    add("reserved_hidden", merged, old, "product_status_5_reserved")
            continue

        if old is None:
            if not admit_below_threshold:
                score = numeric_score(item)
                below = threshold is not None and (score is None or score < threshold - 1e-9)
                if below:
                    reason = "no_score" if score is None else "score_below_threshold"
                    add("rejected_below_top100", item, None, reason)
                    continue
            merged = merge_record(None, item)
            merged["sale_status"] = "on_sale"
            merged["ingest_status"] = "added"
            by_sku[sku] = merged
            order.append(sku)
            admitted_new.append(sku)
            add("added", merged, None, None)
            continue

        kind = classify_change(old, item)
        if kind == "unchanged":
            # Ensure stale reserved state or refreshed metadata stays clean
            if old.get("sale_status") != "on_sale":
                old["sale_status"] = "on_sale"
            if "score_eligible" in item:
                for key in SCORE_KEYS:
                    if key in item:
                        old[key] = item[key]
            continue
        merged = merge_record(old, item)
        merged["sale_status"] = "on_sale"
        merged["ingest_status"] = kind
        by_sku[sku] = merged
        add(kind, merged, old, None)

    def resplit() -> tuple[list[dict[str, Any]], set[str], list[dict[str, Any]]]:
        scored = [
            by_sku[sku]
            for sku in order
            if sku in by_sku and numeric_score(by_sku[sku]) is not None
        ]
        scored.sort(key=display_sort_key)
        display, _below = apply_display_flags(scored, display_limit)
        wuhan_display = build_wuhan_board(scored, display_limit)
        return display, {str(item["sku"]) for item in display}, wuhan_display

    display, display_ids, wuhan_display = resplit()
    if not admit_below_threshold:
        rolled = [sku for sku in admitted_new if sku not in display_ids]
        if rolled:
            changelog = [
                row for row in changelog
                if not (row["change_type"] == "added" and row["sku"] in set(rolled))
            ]
            for sku in rolled:
                item = by_sku.pop(sku)
                order = [existing for existing in order if existing != sku]
                add("rejected_below_top100", item, None, "not_in_display_top100")
            display, display_ids, wuhan_display = resplit()

    wuhan_display_ids = {str(item["sku"]) for item in wuhan_display}
    for sku, item in by_sku.items():
        if sku not in display_ids:
            item["display"] = False
            item["rank"] = None
        if sku not in wuhan_display_ids:
            item["wuhan_display"] = False
            item["wuhan_rank"] = None

    for sku in previous_display:
        if sku in display_ids or sku not in by_sku:
            continue
        if any(row["sku"] == sku and row["change_type"] in {"reserved_hidden", "removed_sold"} for row in changelog):
            continue
        add("display_dropped", by_sku.get(sku), previous_by_sku.get(sku), "outside_top100_display")

    inventory_out = [by_sku[sku] for sku in order if sku in by_sku]
    issue_ids = {str(item["sku"]) for item in inventory_out if item.get("score_eligible") is False}
    issues = [item for item in inventory_out if str(item["sku"]) in issue_ids]
    below = [
        item
        for item in inventory_out
        if str(item["sku"]) not in display_ids and str(item["sku"]) not in issue_ids
    ]
    return {
        "inventory": inventory_out,
        "ranked": display,
        "ranked_wuhan": wuhan_display,
        "below": below,
        "issues": issues,
        "changelog": changelog,
        "threshold": threshold,
    }


def load_state(catalog: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = load_json(catalog / "listings-ranked.json", [])
    issues = load_json(catalog / "data-issues.json", [])
    inventory = load_json(catalog / "listings-filtered.json", None)
    if inventory is None:
        seen = {str(item.get("sku")) for item in ranked}
        inventory = list(ranked) + [item for item in issues if str(item.get("sku")) not in seen]
    return inventory, ranked


def write_payload(directory: Path, stem: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    if len(raw) >= 100_000:
        name = f"{stem}.json.gz"
        with gzip.open(directory / name, "wb") as handle:
            handle.write(raw)
        return name
    name = f"{stem}.json"
    (directory / name).write_bytes(raw)
    return name


def write_catalog(
    catalog: Path,
    result: dict[str, Any],
    *,
    now: str,
    threshold: float | None,
    shop_ids: list[str] | None = None,
) -> None:
    dump_json(catalog / "listings-filtered.json", result["inventory"])
    dump_json(catalog / "listings-ranked.json", result["ranked"])
    wuhan_display = result.get("ranked_wuhan") or []
    dump_json(catalog / "listings-ranked-wuhan.json", wuhan_display)
    dump_json(catalog / "listings-below-display.json", result["below"])
    dump_json(catalog / "data-issues.json", result["issues"])
    display = result["ranked"]
    shortlist = display[:30]
    cheapest = sorted(
        display,
        key=lambda item: (
            float(item.get("effective_price_wan") or item.get("price") or 99),
            -(numeric_score(item) or 0),
        ),
    )[:30]
    dump_json(catalog / "shortlist-ranked.json", shortlist)
    dump_json(catalog / "shortlist-cheapest.json", cheapest)
    meta_path = catalog / "meta.json"
    meta = load_json(meta_path, {})
    inv = result["inventory"]
    top_counts: dict[str, int] = {}
    for row in display:
        sid = str(row.get("shop_id") or "")
        top_counts[sid] = top_counts.get(sid, 0) + 1
    inv_counts: dict[str, int] = {}
    shop_fee_samples: dict[str, int] = {}
    for row in inv:
        sid = str(row.get("shop_id") or "")
        inv_counts[sid] = inv_counts.get(sid, 0) + 1
        if sid not in shop_fee_samples and row.get("logistics_fee_yuan") is not None:
            shop_fee_samples[sid] = int(row["logistics_fee_yuan"])

    scope_ids = list(shop_ids or PLAN_A_SHOP_IDS)
    shops_summary = []
    for sid in scope_ids:
        reg = DIRECT_SHOPS.get(sid) or {}
        shops_summary.append({
            "shop_id": sid,
            "name": reg.get("name") or sid,
            "short_name": reg.get("short_name") or sid,
            "city": reg.get("city") or "",
            "kind": reg.get("kind") or "直营",
            "is_local": bool(reg.get("is_local")),
            "logistics_fee_yuan": shop_fee_samples.get(sid, reg.get("fallback_logistics_yuan", 1000)),
            "inventory_count": inv_counts.get(sid, 0),
            "top_count": top_counts.get(sid, 0),
        })

    on_sale_count = sum(1 for x in inv if x.get("sale_status") != "reserved")
    reserved_count = sum(1 for x in inv if x.get("sale_status") == "reserved")
    vetoed_count = sum(1 for x in inv if x.get("recommendation_gate") == "VETO")
    eligible_count = sum(1 for x in inv if numeric_score(x) is not None)
    wuhan_inv = [x for x in inv if is_local_wuhan(x)]
    wuhan_on_sale = sum(1 for x in wuhan_inv if x.get("sale_status") != "reserved")
    wuhan_reserved = sum(1 for x in wuhan_inv if x.get("sale_status") == "reserved")
    wuhan_vetoed = sum(1 for x in wuhan_inv if x.get("recommendation_gate") == "VETO")
    wuhan_eligible = sum(1 for x in wuhan_inv if numeric_score(x) is not None)

    meta["buyer_city"] = BUYER_CITY
    meta["shop_scope"] = "plan_a_7_direct_shops"
    meta["shops"] = shops_summary
    meta["boards"] = {
        "wuhan": {
            "key": "wuhan",
            "label": "武汉榜",
            "subtitle": "武汉本地直营 · 免物流直提",
            "data_file": "listings-ranked-wuhan.json",
            "inventory_count": len(wuhan_inv),
            "on_sale_count": wuhan_on_sale,
            "reserved_count": wuhan_reserved,
            "vetoed_count": wuhan_vetoed,
            "eligible_count": wuhan_eligible,
            "ranked_count": len(wuhan_display),
            "display_limit": DISPLAY_LIMIT,
            "display_score_floor": wuhan_display[-1].get("total_score") if wuhan_display else None,
        },
        "national": {
            "key": "national",
            "label": "全国榜",
            "subtitle": "全国官方直营 · 到汉统一比价",
            "data_file": "listings-ranked.json",
            "inventory_count": len(inv),
            "on_sale_count": on_sale_count,
            "reserved_count": reserved_count,
            "vetoed_count": vetoed_count,
            "eligible_count": eligible_count,
            "ranked_count": len(display),
            "display_limit": DISPLAY_LIMIT,
            "display_score_floor": display[-1].get("total_score") if display else None,
        },
    }
    meta["wuhan_ranked_count"] = len(wuhan_display)
    meta["wuhan_eligible_count"] = wuhan_eligible
    meta["wuhan_display_score_floor"] = wuhan_display[-1].get("total_score") if wuhan_display else None
    meta["on_sale_count"] = on_sale_count
    meta["reserved_count"] = reserved_count
    meta["vetoed_count"] = vetoed_count
    meta["ranked_at"] = now
    meta["ranked_count"] = len(display)
    meta["library_scored_count"] = eligible_count
    meta["below_display_count"] = len(result["below"])
    meta["data_issue_count"] = len(result["issues"])
    meta["filtered_count"] = len(inv)
    meta["display_limit"] = DISPLAY_LIMIT
    meta["display_score_floor"] = display[-1].get("total_score") if display else None
    meta["ingest_score_threshold"] = threshold
    meta["ingest_at"] = now
    dump_json(meta_path, meta)
    if catalog.resolve() == (ROOT / "data").resolve():
        for name in (
            "listings-ranked.json",
            "listings-ranked-wuhan.json",
            "listings-filtered.json",
            "shortlist-ranked.json",
            "shortlist-cheapest.json",
        ):
            source = catalog / name
            if source.exists():
                (ROOT / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        dash = ROOT / "dashboard" / "public" / "data"
        if dash.exists():
            for name in (
                "listings-ranked.json",
                "listings-ranked-wuhan.json",
                "listings-filtered.json",
                "shortlist-ranked.json",
                "shortlist-cheapest.json",
                "data-issues.json",
                "meta.json",
            ):
                source = catalog / name
                if source.exists():
                    (dash / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _score_incoming(
    kept: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    *,
    skip_live_fetch: bool,
    dry_run: bool,
    force_rescore_all: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_sku = {str(item.get("sku")): item for item in inventory}
    to_score = [
        item for item in kept
        if force_rescore_all or classify_change(by_sku.get(str(item.get("sku"))), item) != "unchanged"
    ]
    notes: dict[str, Any] = {
        "scored": 0,
        "live_match_attempted": 0,
        "live_matched": 0,
        "specs_error": None,
        "pending_verified": {},
    }
    if not to_score:
        return kept, notes
    from ingest_score import load_verified, match_with_autohome, prepare_and_score

    verified = load_verified(ROOT)
    unknown = []
    for item in to_score:
        sku = str(item.get("sku") or "")
        old = by_sku.get(sku) or {}
        old_specs = old.get("specs") or {}
        cached = sku in verified or (
            old_specs.get("match_level") == "exact_trim" and old_specs.get("verified") is True
        )
        if not cached:
            unknown.append(item)
    if unknown and not skip_live_fetch:
        notes["live_match_attempted"] = len(unknown)
        try:
            matched = match_with_autohome(unknown, live=True, persist=False, write_trees=not dry_run)
            verified.update(matched)
            notes["pending_verified"] = matched
            notes["live_matched"] = len(matched)
        except Exception as exc:
            notes["specs_error"] = f"{type(exc).__name__}: {exc}"
    scored: dict[str, dict[str, Any]] = {}
    for item in to_score:
        sku = str(item.get("sku") or "")
        old = by_sku.get(sku)
        if old and str(sku) not in verified:
            # Keep an already exact spec blob when the index has no row for this sku.
            specs = old.get("specs") or {}
            if specs.get("match_level") == "exact_trim" and specs.get("verified") is True:
                item = dict(item)
                item["specs"] = specs
                item["detailed_config"] = old.get("detailed_config") or specs
        scored[sku] = prepare_and_score(item, verified)
    notes["scored"] = len(scored)
    merged_incoming = [scored.get(str(item.get("sku")), item) for item in kept]
    notes["dry_run"] = dry_run
    return merged_incoming, notes


def sync_missing_covers(items: list[dict[str, Any]], *, max_workers: int = 6) -> int:
    """Download missing SKU cover JPEGs into images/ and dashboard/public/images/."""
    img_dir = ROOT / "images"
    dash_img_dir = ROOT / "dashboard" / "public" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    dash_img_dir.mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        sku = str(item.get("sku") or "").strip()
        url = str(item.get("cover") or "").strip()
        if not sku or not url or sku in seen:
            continue
        seen.add(sku)
        p1 = img_dir / f"{sku}.jpg"
        p2 = dash_img_dir / f"{sku}.jpg"
        if p1.exists() and p1.stat().st_size > 1000:
            if not p2.exists() or p2.stat().st_size != p1.stat().st_size:
                p2.write_bytes(p1.read_bytes())
            continue
        jobs.append((sku, url))
    if not jobs:
        return 0

    def _download(job: tuple[str, str]) -> bool:
        sku, url = job
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            if len(data) < 1000:
                return False
            (img_dir / f"{sku}.jpg").write_bytes(data)
            (dash_img_dir / f"{sku}.jpg").write_bytes(data)
            return True
        except Exception:
            return False

    downloaded = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for ok in ex.map(_download, jobs):
            if ok:
                downloaded += 1
    return downloaded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="懂车帝直营多店每日入库（华中7城列表、现金价+到汉物流费、硬筛、V3打分、Top30）",
        epilog="快照落在 data/snapshots/YYYYMMDD/ 时会导出看板 today-updates.json；否则再跑 python3 scripts/export_today_updates.py",
    )
    parser.add_argument("--shops", default="plan_a", help="门店范围：plan_a（默认7城直营）或逗号分隔 shop_id")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 条直营车辆，0 表示不限制")
    parser.add_argument("--dry-run", action="store_true", help="不改 listings 与 specs 索引；仍写快照和 changelog")
    parser.add_argument(
        "--skip-live-fetch",
        action="store_true",
        help="不跑汽车之家 live 参配，只用已有 specs 缓存打分",
    )
    parser.add_argument("--fixtures", type=Path, default=None, help="从目录读取 list-pageN.json 与 detail-<sku>.json")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--workers", type=int, default=8, help="详情并发请求线程数，默认 8")
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--catalog-dir", type=Path, default=None, help="默认 data/。测试可指向临时目录")
    parser.add_argument("--date", default=None, help="快照目录名 YYYYMMDD，默认上海时区今天")
    parser.add_argument("--display-limit", type=int, default=DISPLAY_LIMIT, help="看板展示条数，默认 30")
    parser.add_argument("--delay", type=float, default=None, help="详情请求间隔秒数。HTTP 默认 0.05，fixtures 默认 0")
    parser.add_argument("--no-snapshots", action="store_true")
    parser.add_argument("--no-reconcile", action="store_true", help="跳过对不在列表中的旧库车源做详情对账")
    parser.add_argument("--no-covers", action="store_true", help="跳过自动补齐封面图")
    return parser


def _reconcile_missing_inventory(
    client: Any,
    inventory: list[dict[str, Any]],
    seen_skus: set[str],
    batch: Any,
    *,
    fetched_shop_ids: set[str],
    skip_live_fetch: bool,
    dry_run: bool,
) -> dict[str, dict[str, Any]]:
    """Fetch detail for known inventory SKUs from fetched shops absent from today's list."""
    missing_rows = [
        row for row in inventory
        if str(row.get("sku") or "")
        and str(row.get("sku") or "") not in seen_skus
        and (not fetched_shop_ids or str(row.get("shop_id") or "") in fetched_shop_ids)
    ]
    out: dict[str, dict[str, Any]] = {}
    if not missing_rows:
        return out
    from ingest_score import load_verified, prepare_and_score

    verified = load_verified(ROOT)
    for row in missing_rows:
        sku = str(row["sku"])
        cached_detail = batch.details.get(sku)
        if cached_detail is not None:
            detail = cached_detail
        else:
            try:
                _st, detail = client.fetch_detail(sku)
                batch.details[sku] = detail
            except Exception as exc:
                status_code = getattr(exc, "status", None)
                if isinstance(exc, FetchError) and status_code in (404, 410):
                    out[sku] = {"status": "sold", "reason": f"http_{status_code}_gone"}
                else:
                    batch.detail_errors[sku] = {
                        "sku": sku,
                        "error": f"{type(exc).__name__}: {exc}",
                        "status": status_code,
                    }
                    out[sku] = {"status": "detail_failed", "reason": f"reconcile_detail_error:{type(exc).__name__}"}
                continue

        sale = parse_sale_status(detail)
        cash = parse_cash_price(detail)
        if sale["sale_status"] == "sold":
            out[sku] = {
                "status": "sold",
                "product_status": sale["product_status"],
                "reason": "product_status_0_sold",
            }
            continue
        if sale["sale_status"] == "reserved":
            out[sku] = {
                "status": "reserved",
                "product_status": sale["product_status"],
                "status_modify_time": sale["status_modify_time"],
                "reason": "product_status_5_reserved",
            }
            continue

        candidate = dict(row)
        if cash["cash_price_wan"] is not None:
            candidate["cash_price_wan"] = cash["cash_price_wan"]
            candidate["cash_price_fen"] = cash["cash_price_fen"]
            candidate["cash_price_str"] = cash["cash_price_str"]
            candidate["price"] = cash["cash_price_wan"]
        if cash.get("shop_id"):
            candidate["shop_id"] = str(cash["shop_id"])
            candidate["detail_shop_id"] = str(cash["shop_id"])
        ful = parse_fulfillment_fees(detail, expected_city=BUYER_CITY)
        costs = compute_landed_costs(
            candidate.get("shop_id"),
            city=candidate.get("city"),
            api_logistics_yuan=ful["api_logistics_yuan"],
            api_plate_fee_yuan=ful["api_plate_fee_yuan"],
        )
        candidate["is_local_wuhan"] = costs["is_local_wuhan"]
        candidate["shop_short_name"] = costs["shop_short_name"]
        candidate["city"] = costs["shop_city"]
        candidate["logistics_fee_yuan"] = costs["logistics_fee_yuan"]
        candidate["logistics_fee_source"] = costs["logistics_fee_source"]
        candidate["plate_service_fee_yuan"] = costs["plate_service_fee_yuan"]
        candidate["plate_fee_diff_yuan"] = costs["plate_fee_diff_yuan"]
        candidate["landed_extra_yuan"] = costs["landed_extra_yuan"]
        candidate["landed_extra_wan"] = costs["landed_extra_wan"]
        if ful["delivery_eta"]:
            candidate["delivery_eta"] = ful["delivery_eta"]
        base_wan = candidate.get("cash_price_wan") or candidate.get("price")
        if base_wan not in (None, ""):
            candidate["landed_price_wan"] = compute_landed_price_wan(float(base_wan), costs["landed_extra_yuan"])

        candidate["sale_status"] = "on_sale"
        candidate["product_status"] = sale["product_status"]
        if sale["status_modify_time"]:
            candidate["status_modify_time"] = sale["status_modify_time"]

        hard_reason = admission_reason(candidate)
        if hard_reason:
            candidate["_reject_reason"] = hard_reason
            out[sku] = {"status": "hard_rejected", "item": candidate, "reason": hard_reason}
            continue

        if (
            price_of(row) != price_of(candidate)
            or row.get("landed_extra_yuan") != candidate.get("landed_extra_yuan")
            or row.get("sale_status") == "reserved"
        ):
            candidate = prepare_and_score(candidate, verified)
        out[sku] = {
            "status": "on_sale",
            "product_status": sale["product_status"],
            "item": candidate,
        }
    return out


def run(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    stamp = args.date or today_stamp()
    catalog = (args.catalog_dir or (ROOT / "data")).resolve()
    snapshot_dir = (args.snapshot_dir or (catalog / "snapshots" / stamp)).resolve()
    started = now_iso()
    shop_ids = parse_shop_list_arg(args.shops)
    if args.fixtures:
        client: Any = load_fixture_dir(args.fixtures)
        delay = 0.0 if args.delay is None else args.delay
        page_size = 20 if "--page-size" not in (argv or []) else args.page_size
        batch = fetch_shop_batch(client, page_size=page_size, limit=max(0, args.limit))
        fetched_shop_ids = {"118608"}
    else:
        client = HttpClient()
        delay = 0.05 if args.delay is None else args.delay
        batch = fetch_multi_shop_batch(
            client,
            shop_ids,
            page_size=args.page_size,
            limit=max(0, args.limit),
            detail_workers=max(1, args.workers),
            detail_delay=delay,
        )
        fetched_shop_ids = set(shop_ids)

    inventory, previous_ranked = load_state(catalog)
    known = {str(item.get("sku")) for item in inventory}
    seen_list_skus: set[str] = set()
    kept: list[dict[str, Any]] = []
    rejected_hard: list[dict[str, Any]] = []
    detail_failed: list[dict[str, Any]] = []
    for card in batch.cards:
        sku = str(((card.get("product") or {}).get("event_info") or {}).get("sku_id") or "")
        if sku:
            seen_list_skus.add(sku)
        detail = batch.details.get(sku)
        item = normalize_card(card, detail)
        if sku in batch.detail_errors or item.get("cash_price_wan") in (None, ""):
            reason = "missing_cash_price"
            if sku in batch.detail_errors:
                reason = "missing_cash_price:" + str(batch.detail_errors[sku].get("error") or "")
            item["_reject_reason"] = reason
            if sku in known:
                detail_failed.append(item)
            else:
                rejected_hard.append(item)
            continue
        reason = admission_reason(item)
        if reason:
            item["_reject_reason"] = reason
            rejected_hard.append(item)
            continue
        kept.append(item)
    reconciled_missing: dict[str, dict[str, Any]] = {}
    if args.limit == 0 and not args.no_reconcile:
        reconciled_missing = _reconcile_missing_inventory(
            client,
            inventory,
            seen_list_skus,
            batch,
            fetched_shop_ids=fetched_shop_ids,
            skip_live_fetch=args.skip_live_fetch,
            dry_run=args.dry_run,
        )
    incoming, score_notes = _score_incoming(
        kept,
        inventory,
        skip_live_fetch=args.skip_live_fetch,
        dry_run=args.dry_run,
    )
    result = apply_catalog_update(
        inventory,
        previous_ranked,
        incoming,
        rejected_hard,
        reconciled_missing=reconciled_missing,
        admit_below_threshold=True,
        display_limit=args.display_limit,
        now=started,
    )
    for item in detail_failed:
        result["changelog"].append(
            _change(
                "detail_failed",
                item,
                next((row for row in inventory if str(row.get("sku")) == str(item.get("sku"))), None),
                now=started,
                reason=item.get("_reject_reason"),
                threshold=result["threshold"],
            )
        )
    pending = score_notes.pop("pending_verified", {})
    admitted = {
        row["sku"]
        for row in result["changelog"]
        if row["change_type"] in {"added", "updated", "updated_price"}
    }
    committed_specs = 0
    if pending and admitted and not args.dry_run:
        from ingest_score import commit_verified

        committed_specs = commit_verified({sku: pending[sku] for sku in admitted if sku in pending})

    covers_downloaded = 0
    if not args.dry_run:
        write_catalog(catalog, result, now=started, threshold=result["threshold"], shop_ids=list(fetched_shop_ids) if args.fixtures else shop_ids)
        if not args.fixtures and not args.no_covers and catalog.resolve() == (ROOT / "data").resolve():
            cover_targets = list(result["ranked"]) + [
                x for x in result["inventory"] if x.get("recommendation_gate") != "VETO"
            ]
            covers_downloaded = sync_missing_covers(cover_targets)

    snapshot_files: list[str] = []
    if not args.no_snapshots:
        if args.fixtures:
            for index, page in enumerate(batch.pages):
                snapshot_files.append(write_payload(snapshot_dir, f"list-page-{index:02d}", page))
        else:
            for sid, pidx, page in batch.shop_pages:
                snapshot_files.append(write_payload(snapshot_dir, f"list-{sid}-page-{pidx:02d}", page))
        for sku, detail in batch.details.items():
            snapshot_files.append(write_payload(snapshot_dir, f"detail-{sku}", detail))
        for sku, error in batch.detail_errors.items():
            snapshot_files.append(write_payload(snapshot_dir, f"detail-{sku}-error", error))
        dump_json(snapshot_dir / "changelog.json", result["changelog"])
        snapshot_files.append("changelog.json")

    counts: dict[str, int] = {}
    for row in result["changelog"]:
        counts[row["change_type"]] = counts.get(row["change_type"], 0) + 1
    summary = {
        "started_at": started,
        "dry_run": bool(args.dry_run),
        "skip_live_fetch": bool(args.skip_live_fetch),
        "fixtures": str(args.fixtures) if args.fixtures else None,
        "shops": shop_ids if not args.fixtures else ["118608"],
        "shop_stats": batch.shop_stats,
        "limit": args.limit,
        "display_limit": args.display_limit,
        "catalog_dir": str(catalog),
        "snapshot_dir": None if args.no_snapshots else str(snapshot_dir),
        "pages": len(batch.pages),
        "shop_cards": len(batch.cards),
        "details": len(batch.details),
        "detail_errors": len(batch.detail_errors),
        "hard_kept": len(kept),
        "hard_rejected": len(rejected_hard),
        "threshold": result["threshold"],
        "changelog_counts": counts,
        "display_count": len(result["ranked"]),
        "wuhan_display_count": len(result["ranked_wuhan"]),
        "below_display_count": len(result["below"]),
        "issue_count": len(result["issues"]),
        "inventory_count": len(result["inventory"]),
        "covers_downloaded": covers_downloaded,
        "catalog_written": not args.dry_run,
        "specs_committed": committed_specs,
        "score": {key: value for key, value in score_notes.items() if key != "dry_run"},
        "snapshot_files": snapshot_files,
    }
    if not args.no_snapshots:
        dump_json(snapshot_dir / "summary.json", summary)
        snapshot_files.append("summary.json")
        maybe_export_today(snapshot_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def maybe_export_today(snapshot_dir: Path) -> None:
    """Refresh the dashboard file when this run wrote a repo snapshot."""
    snapshots_root = (ROOT / "data" / "snapshots").resolve()
    try:
        resolved = snapshot_dir.resolve()
    except OSError:
        return
    if resolved.parent != snapshots_root:
        return
    try:
        from export_today_updates import export_snapshot

        export_snapshot(resolved)
    except (Exception, SystemExit) as exc:
        print(f"today-updates export failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def main() -> None:
    run()


if __name__ == "__main__":
    main()
