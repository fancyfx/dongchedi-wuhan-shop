#!/usr/bin/env python3
"""Daily Wuhan-shop ingest.

Fetch the shop list (search_id paging), read detail cash prices, apply hard
filters, diff the catalog, score with the existing V2 engine, and keep the
board to the top 100. Dry-run writes snapshots and a changelog without
replacing listing files.

Examples:

  python3 scripts/daily_ingest.py --help
  python3 scripts/daily_ingest.py --fixtures .tmp/ingest-probe --limit 3 --dry-run --skip-live-fetch
  python3 scripts/daily_ingest.py

看板「今日更新」读 dashboard/public/data/today-updates.json。快照写进
data/snapshots/YYYYMMDD/ 时会自动导出；其它目录需要再跑：

  python3 scripts/export_today_updates.py
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dcd_fetch import (  # noqa: E402
    FixtureClient,
    HttpClient,
    fetch_shop_batch,
    load_fixture_dir,
    normalize_card,
)
from display_gate import (  # noqa: E402
    DISPLAY_LIMIT,
    apply_display_flags,
    display_sort_key,
    numeric_score,
    ranked_threshold,
)
from filters import admission_reason  # noqa: E402

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
    "series",
    "brand",
    "first_registration_time",
    "detail_shop_id",
)
SCORE_KEYS = (
    "total_score",
    "score_eligible",
    "score_version",
    "score_v1",
    "sort_scores",
    "condition_gate",
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
    changes = []
    if price_of(old) != price_of(new):
        changes.append("price")
    if mile_of(old) != mile_of(new):
        changes.append("mileage")
    if str(old.get("title") or "") != str(new.get("title") or ""):
        changes.append("title")
    if not changes:
        return "unchanged"
    if "price" in changes:
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
    display_limit: int = DISPLAY_LIMIT,
    now: str,
) -> dict[str, Any]:
    """Diff, top-100 admission, and display split. Does not touch disk."""
    by_sku: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in inventory:
        sku = str(item.get("sku") or "")
        if not sku or sku in by_sku:
            continue
        by_sku[sku] = dict(item)
        order.append(sku)
    previous_by_sku = {str(item.get("sku")): item for item in previous_ranked if item.get("sku")}
    previous_display = [
        sku for sku, item in previous_by_sku.items() if item.get("display") is not False
    ]
    threshold = ranked_threshold(list(previous_by_sku.values()), display_limit)
    changelog: list[dict[str, Any]] = []

    def add(change_type: str, item: dict[str, Any] | None, old: dict[str, Any] | None, reason: str | None) -> None:
        changelog.append(_change(change_type, item, old, now=now, reason=reason, threshold=threshold))

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
        old = by_sku.get(sku)
        kind = classify_change(old, item)
        if old is None:
            score = numeric_score(item)
            below = threshold is not None and (score is None or score < threshold - 1e-9)
            if below:
                reason = "no_score" if score is None else "score_below_threshold"
                add("rejected_below_top100", item, None, reason)
                continue
            merged = merge_record(None, item)
            merged["ingest_status"] = "added"
            by_sku[sku] = merged
            order.append(sku)
            admitted_new.append(sku)
            add("added", merged, None, None)
            continue
        if kind == "unchanged":
            continue
        merged = merge_record(old, item)
        merged["ingest_status"] = kind
        by_sku[sku] = merged
        add(kind, merged, old, None)

    def resplit() -> tuple[list[dict[str, Any]], set[str]]:
        scored = [
            by_sku[sku]
            for sku in order
            if sku in by_sku and numeric_score(by_sku[sku]) is not None
        ]
        scored.sort(key=display_sort_key)
        display, _below = apply_display_flags(scored, display_limit)
        return display, {str(item["sku"]) for item in display}

    display, display_ids = resplit()
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
        display, display_ids = resplit()

    for sku, item in by_sku.items():
        if sku not in display_ids:
            item["display"] = False
            item["rank"] = None

    for sku in previous_display:
        if sku in display_ids or sku not in by_sku:
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


def write_catalog(catalog: Path, result: dict[str, Any], *, now: str, threshold: float | None) -> None:
    dump_json(catalog / "listings-filtered.json", result["inventory"])
    dump_json(catalog / "listings-ranked.json", result["ranked"])
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
    meta["ranked_at"] = now
    meta["ranked_count"] = len(display)
    meta["library_scored_count"] = len(display) + len(result["below"])
    meta["below_display_count"] = len(result["below"])
    meta["data_issue_count"] = len(result["issues"])
    meta["filtered_count"] = len(result["inventory"])
    meta["display_limit"] = DISPLAY_LIMIT
    meta["display_score_floor"] = display[-1].get("total_score") if display else None
    meta["ingest_score_threshold"] = threshold
    meta["ingest_at"] = now
    dump_json(meta_path, meta)
    if catalog.resolve() == (ROOT / "data").resolve():
        for name in (
            "listings-ranked.json",
            "listings-filtered.json",
            "shortlist-ranked.json",
            "shortlist-cheapest.json",
        ):
            source = catalog / name
            if source.exists():
                (ROOT / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _score_incoming(
    kept: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    *,
    skip_live_fetch: bool,
    dry_run: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_sku = {str(item.get("sku")): item for item in inventory}
    to_score = [
        item for item in kept
        if classify_change(by_sku.get(str(item.get("sku"))), item) != "unchanged"
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
            matched = match_with_autohome(unknown, live=True, persist=False)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="懂车帝武汉店每日入库（列表、现金价、硬筛、打分、Top100）",
        epilog="快照落在 data/snapshots/YYYYMMDD/ 时会导出看板 today-updates.json；否则再跑 python3 scripts/export_today_updates.py",
    )
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 条本店车辆，0 表示不限制")
    parser.add_argument("--dry-run", action="store_true", help="不改 listings 与 specs 索引；仍写快照和 changelog")
    parser.add_argument(
        "--skip-live-fetch",
        action="store_true",
        help="不跑汽车之家 live 参配，只用已有 specs 缓存打分",
    )
    parser.add_argument("--fixtures", type=Path, default=None, help="从目录读取 list-pageN.json 与 detail-<sku>.json")
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--catalog-dir", type=Path, default=None, help="默认 data/。测试可指向临时目录")
    parser.add_argument("--date", default=None, help="快照目录名 YYYYMMDD，默认上海时区今天")
    parser.add_argument("--display-limit", type=int, default=DISPLAY_LIMIT, help="看板展示条数，默认 100")
    parser.add_argument("--delay", type=float, default=None, help="详情请求间隔秒数。HTTP 默认 0.15，fixtures 默认 0")
    parser.add_argument("--no-snapshots", action="store_true")
    return parser


def run(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    stamp = args.date or today_stamp()
    catalog = (args.catalog_dir or (ROOT / "data")).resolve()
    snapshot_dir = (args.snapshot_dir or (catalog / "snapshots" / stamp)).resolve()
    started = now_iso()
    if args.fixtures:
        client: Any = load_fixture_dir(args.fixtures)
        delay = 0.0 if args.delay is None else args.delay
    else:
        client = HttpClient()
        delay = 0.15 if args.delay is None else args.delay
    if delay:
        original_detail = client.fetch_detail

        def fetch_detail(sku: str):
            payload = original_detail(sku)
            time.sleep(delay)
            return payload

        client.fetch_detail = fetch_detail  # type: ignore[method-assign]

    batch = fetch_shop_batch(client, page_size=args.page_size, limit=max(0, args.limit))
    inventory, previous_ranked = load_state(catalog)
    known = {str(item.get("sku")) for item in inventory}
    kept: list[dict[str, Any]] = []
    rejected_hard: list[dict[str, Any]] = []
    detail_failed: list[dict[str, Any]] = []
    for card in batch.cards:
        sku = str(((card.get("product") or {}).get("event_info") or {}).get("sku_id") or "")
        detail = batch.details.get(sku)
        item = normalize_card(card, detail)
        if sku in batch.detail_errors or item.get("cash_price_wan") in (None, ""):
            reason = "missing_cash_price"
            if sku in batch.detail_errors:
                reason = "missing_cash_price:" + str(batch.detail_errors[sku].get("error") or "")
            item["_reject_reason"] = reason
            # A failed detail read must not delete a car already in the library.
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

    if not args.dry_run:
        write_catalog(catalog, result, now=started, threshold=result["threshold"])

    snapshot_files: list[str] = []
    if not args.no_snapshots:
        for index, page in enumerate(batch.pages):
            snapshot_files.append(write_payload(snapshot_dir, f"list-page-{index:02d}", page))
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
        "below_display_count": len(result["below"]),
        "issue_count": len(result["issues"]),
        "inventory_count": len(result["inventory"]),
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
