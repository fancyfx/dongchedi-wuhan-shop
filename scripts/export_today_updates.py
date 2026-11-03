#!/usr/bin/env python3
"""Export today's ingest snapshot into the dashboard today-updates JSON.

重点推荐 = change_type 为 added，且全场 total_score 排名（listings-ranked.json 的 rank）在 1 到 10。
信息更新（updated / updated_price）和排名在 10 名之外的新车都不是重点推荐。

用法（仓库根目录）：

    python3 scripts/export_today_updates.py
    python3 scripts/export_today_updates.py --date 20261103
    python3 scripts/export_today_updates.py --write-fixture
    python3 scripts/export_today_updates.py --self-check

默认读取 data/snapshots 下最新的 YYYYMMDD 目录（changelog.json + summary.json），
排名取 dashboard/public/data/listings-ranked.json（没有则用 data/listings-ranked.json），
写出 dashboard/public/data/today-updates.json。

daily_ingest.py 把快照写进 data/snapshots/YYYYMMDD/ 时会调用 export_snapshot。
快照目录不在这个路径下时，需要自己再跑上面的命令。
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "snapshots"
PUBLIC_RANKED = ROOT / "dashboard" / "public" / "data" / "listings-ranked.json"
DATA_RANKED = ROOT / "data" / "listings-ranked.json"
DEFAULT_OUT = ROOT / "dashboard" / "public" / "data" / "today-updates.json"
DEFAULT_FIXTURE = ROOT / "dashboard" / "public" / "data" / "today-updates.fixture.json"
HIGHLIGHT_MAX_RANK = 10
SCHEMA = "today-updates/v1"
CST = timezone(timedelta(hours=8))
SUMMARY_KEYS = (
    "started_at",
    "dry_run",
    "threshold",
    "display_count",
    "below_display_count",
    "issue_count",
    "inventory_count",
    "catalog_written",
    "changelog_counts",
)
RULES = {
    "highlight": "change_type == added AND rank >= 1 AND rank <= 10",
    "rank": "listings-ranked.json rank，全场 total_score 得分排名，1 最好",
    "info_updated": ["updated", "updated_price"],
}


def now_iso() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def num_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if isinstance(value, str) and value.strip():
        try:
            number = float(value)
        except ValueError:
            return None
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    return None


def as_rank(value: Any) -> int | None:
    number = num_or_none(value)
    if number is None:
        return None
    if isinstance(number, float) and not number.is_integer():
        return None
    rank = int(number)
    return rank if rank >= 1 else None


def is_highlight(change_type: str, rank: int | None) -> bool:
    return change_type == "added" and rank is not None and 1 <= rank <= HIGHLIGHT_MAX_RANK


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def board_ranks(listings: list[dict[str, Any]]) -> dict[str, int]:
    """Prefer the explicit rank field. Fill gaps from total_score order."""
    ranks: dict[str, int] = {}
    seen: set[str] = set()
    missing = False
    for item in listings:
        sku = str(item.get("sku") or "")
        if not sku or sku in seen:
            continue
        seen.add(sku)
        rank = as_rank(item.get("rank"))
        if rank is None:
            missing = True
        else:
            ranks[sku] = rank
    if not missing:
        return ranks
    scored: list[tuple[float, int, str]] = []
    for index, item in enumerate(listings):
        sku = str(item.get("sku") or "")
        score = num_or_none(item.get("total_score"))
        if sku and isinstance(score, (int, float)):
            scored.append((float(score), index, sku))
    scored.sort(key=lambda row: (-row[0], row[1]))
    for position, (_score, _index, sku) in enumerate(scored, start=1):
        ranks.setdefault(sku, position)
    return ranks


def resolve_rank(row: dict[str, Any], ranks: dict[str, int]) -> int | None:
    sku = str(row.get("sku") or "")
    if sku in ranks:
        return ranks[sku]
    return as_rank(row.get("rank"))


def enrich_change(row: dict[str, Any], ranks: dict[str, int]) -> dict[str, Any] | None:
    sku = str(row.get("sku") or "").strip()
    if not sku:
        return None
    change_type = str(row.get("change_type") or "").strip() or "updated"
    rank = resolve_rank(row, ranks)
    reason = row.get("reason")
    return {
        "sku": sku,
        "title": row.get("title") or sku,
        "change_type": change_type,
        "old_price": num_or_none(row.get("old_price")),
        "new_price": num_or_none(row.get("new_price")),
        "old_score": num_or_none(row.get("old_score")),
        "new_score": num_or_none(row.get("new_score")),
        "rank": rank,
        "reason": None if reason in (None, "") else reason,
        "at": row.get("at"),
        "highlight": is_highlight(change_type, rank),
    }


def count_items(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "added": 0,
        "updated": 0,
        "updated_price": 0,
        "info_updated": 0,
        "highlights": 0,
        "display_dropped": 0,
        "rejected_hard_filter": 0,
        "rejected_below_top100": 0,
        "removed_hard_filter": 0,
        "detail_failed": 0,
        "not_admitted": 0,
        "other": 0,
        "total": len(items),
    }
    known = {
        "added",
        "updated",
        "updated_price",
        "display_dropped",
        "rejected_hard_filter",
        "rejected_below_top100",
        "removed_hard_filter",
        "detail_failed",
    }
    for item in items:
        kind = item["change_type"]
        if item["highlight"]:
            counts["highlights"] += 1
        if kind in counts and kind in known:
            counts[kind] += 1
        elif kind not in known:
            counts["other"] += 1
    counts["info_updated"] = counts["updated"] + counts["updated_price"]
    counts["not_admitted"] = (
        counts["rejected_hard_filter"]
        + counts["rejected_below_top100"]
        + counts["removed_hard_filter"]
        + counts["detail_failed"]
    )
    return counts


def empty_counts() -> dict[str, int]:
    return count_items([])


def pick_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    picked: dict[str, Any] = {}
    for key in SUMMARY_KEYS:
        if key in summary:
            picked[key] = summary[key]
    return picked


def rel_to_root(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def build_payload(
    *,
    date: str | None,
    generated_at: str,
    source: str,
    has_snapshot: bool,
    snapshot_dir: str | None,
    note: str | None,
    summary: dict[str, Any],
    changelog: list[dict[str, Any]],
    ranks: dict[str, int],
    source_files: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    items = [item for row in changelog if (item := enrich_change(row, ranks)) is not None]
    highlights = sorted(
        [item for item in items if item["highlight"]],
        key=lambda item: (item["rank"] or 9999, item["sku"]),
    )
    if note is None and source == "snapshot" and has_snapshot and items and not any(item["change_type"] == "added" for item in items):
        note = "这份快照没有新入库（added）。重点推荐需要新入库，并且全场排名在前 10。"
    if note is None and source == "snapshot" and has_snapshot and not items:
        note = "今日快照的 changelog 是空的。"
    return {
        "schema": SCHEMA,
        "date": date,
        "generated_at": generated_at,
        "source": source if has_snapshot else "missing",
        "has_snapshot": has_snapshot,
        "changelog_empty": len(items) == 0,
        "snapshot_dir": snapshot_dir,
        "note": note,
        "rules": RULES,
        "summary": summary,
        "counts": count_items(items),
        "source_files": source_files or {},
        "highlights": highlights,
        "items": items,
    }


def missing_payload(note: str, generated_at: str | None = None) -> dict[str, Any]:
    return build_payload(
        date=None,
        generated_at=generated_at or now_iso(),
        source="missing",
        has_snapshot=False,
        snapshot_dir=None,
        note=note,
        summary={},
        changelog=[],
        ranks={},
    )


def find_latest_snapshot(root: Path = ROOT) -> Path | None:
    base = root / "data" / "snapshots"
    if not base.is_dir():
        return None
    dirs = [path for path in base.iterdir() if path.is_dir() and re.fullmatch(r"\d{8}", path.name)]
    if not dirs:
        return None
    return sorted(dirs, key=lambda path: path.name)[-1]


def default_ranked_path() -> Path:
    if PUBLIC_RANKED.exists():
        return PUBLIC_RANKED
    return DATA_RANKED


def export_snapshot(
    snapshot_dir: Path,
    *,
    ranked_path: Path | None = None,
    out_path: Path | None = None,
    generated_at: str | None = None,
) -> Path:
    """Write today-updates.json for one snapshot directory. Returns the output path."""
    snapshot_dir = snapshot_dir.resolve()
    ranked_file = (ranked_path or default_ranked_path()).resolve()
    destination = (out_path or DEFAULT_OUT).resolve()
    stamp = generated_at or now_iso()
    date = snapshot_dir.name if re.fullmatch(r"\d{8}", snapshot_dir.name) else None
    changelog_path = snapshot_dir / "changelog.json"
    summary_path = snapshot_dir / "summary.json"
    if not changelog_path.exists() and not summary_path.exists():
        payload = missing_payload(f"快照目录里没有 changelog.json 或 summary.json：{rel_to_root(snapshot_dir)}", stamp)
    else:
        changelog = load_json(changelog_path, [])
        summary = load_json(summary_path, {})
        if not isinstance(changelog, list):
            raise SystemExit(f"changelog 不是数组：{changelog_path}")
        listings = load_json(ranked_file, [])
        if not isinstance(listings, list):
            raise SystemExit(f"排名文件不是数组：{ranked_file}")
        payload = build_payload(
            date=date,
            generated_at=stamp,
            source="snapshot",
            has_snapshot=True,
            snapshot_dir=rel_to_root(snapshot_dir),
            note=None,
            summary=pick_summary(summary if isinstance(summary, dict) else {}),
            changelog=changelog,
            ranks=board_ranks(listings),
            source_files={
                "changelog": rel_to_root(changelog_path) if changelog_path.exists() else None,
                "summary": rel_to_root(summary_path) if summary_path.exists() else None,
                "ranked": rel_to_root(ranked_file) if ranked_file.exists() else None,
            },
        )
    dump_json(destination, payload)
    counts = payload["counts"]
    print(
        f"today-updates -> {rel_to_root(destination)} "
        f"added={counts['added']} info_updated={counts['info_updated']} "
        f"highlights={counts['highlights']} total={counts['total']}"
    )
    return destination


def _listing_by_rank(listings: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    found: dict[int, dict[str, Any]] = {}
    for item in listings:
        rank = as_rank(item.get("rank"))
        if rank is not None and rank not in found:
            found[rank] = item
    return found


def _fixture_row(item: dict[str, Any], change_type: str, generated_at: str, reason: str | None) -> dict[str, Any]:
    rank = as_rank(item.get("rank"))
    price = num_or_none(item.get("price"))
    score = num_or_none(item.get("total_score"))
    old_price = None if change_type == "added" else price
    if change_type == "updated_price" and isinstance(price, (int, float)):
        old_price = round(float(price) + 0.4, 2)
    return {
        "sku": str(item.get("sku") or ""),
        "title": item.get("title") or item.get("sku"),
        "change_type": change_type,
        "old_price": old_price,
        "new_price": price,
        "old_score": None if change_type == "added" else score,
        "new_score": score,
        "rank": rank,
        "reason": reason,
        "at": generated_at,
    }


def build_fixture(listings: list[dict[str, Any]], generated_at: str | None = None) -> dict[str, Any]:
    stamp = generated_at or now_iso()
    by_rank = _listing_by_rank(listings)
    required = (1, 2, 5, 8, 11)
    missing = [rank for rank in required if rank not in by_rank]
    if missing:
        raise SystemExit(f"排名文件缺少演示需要的名次：{missing}")
    changelog = [
        _fixture_row(by_rank[1], "added", stamp, None),
        _fixture_row(by_rank[8], "added", stamp, None),
        _fixture_row(by_rank[11], "added", stamp, None),
        _fixture_row(by_rank[2], "updated_price", stamp, "fixture_price_change"),
        _fixture_row(by_rank[5], "updated", stamp, "fixture_info_change"),
        {
            "sku": "357097175",
            "title": "荣威i5 2026款 1.5L CVT豪华版",
            "change_type": "display_dropped",
            "old_price": 5.59,
            "new_price": 5.59,
            "old_score": 44.2,
            "new_score": 44.2,
            "rank": None,
            "reason": "outside_top100_display",
            "at": stamp,
        },
        {
            "sku": "357261851",
            "title": "星愿 2026款 310km 梦想版",
            "change_type": "rejected_hard_filter",
            "old_price": None,
            "new_price": None,
            "old_score": None,
            "new_score": None,
            "rank": None,
            "reason": "missing_cash_price",
            "at": stamp,
        },
    ]
    # Fixture ranks are the cars' real board ranks. Pass an empty rank map so the
    # explicit rank on each row is kept, including the off-board rows.
    note = (
        "演示数据，不是今日真实入库。"
        "重点推荐只有新入库且全场排名 ≤ 10：第 1 名和第 8 名。"
        "第 11 名虽然新入库，但不在前 10。"
        "第 2 名只是价格更新，第 5 名只是信息更新，即使排进前 10 也不是重点推荐。"
    )
    return build_payload(
        date="fixture",
        generated_at=stamp,
        source="fixture",
        has_snapshot=True,
        snapshot_dir=None,
        note=note,
        summary={"dry_run": True, "demo": True, "catalog_written": False},
        changelog=changelog,
        ranks={},
        source_files={"ranked": rel_to_root(default_ranked_path())},
    )


def write_fixture(listings: list[dict[str, Any]], out_path: Path | None = None) -> Path:
    destination = (out_path or DEFAULT_FIXTURE).resolve()
    payload = build_fixture(listings)
    dump_json(destination, payload)
    skus = [item["sku"] for item in payload["highlights"]]
    print(f"today-updates fixture -> {rel_to_root(destination)} highlights={skus}")
    return destination


def self_check() -> None:
    assert is_highlight("added", 1)
    assert is_highlight("added", 10)
    assert not is_highlight("added", 11)
    assert not is_highlight("added", 0)
    assert not is_highlight("added", None)
    assert not is_highlight("updated", 1)
    assert not is_highlight("updated_price", 1)
    assert not is_highlight("display_dropped", 1)
    assert not is_highlight("rejected_hard_filter", 1)

    ranked = [
        {"sku": "a", "title": "A", "rank": 1, "price": 5, "total_score": 60},
        {"sku": "b", "title": "B", "rank": 10, "price": 4, "total_score": 50},
        {"sku": "c", "title": "C", "rank": 11, "price": 3, "total_score": 49},
        {"sku": "d", "title": "D", "rank": 2, "price": 5.5, "total_score": 59},
    ]
    ranks = board_ranks(ranked)
    changelog = [
        {"sku": "a", "title": "A", "change_type": "added", "new_price": 5, "new_score": 60},
        {"sku": "b", "title": "B", "change_type": "added", "new_price": 4, "new_score": 50},
        {"sku": "c", "title": "C", "change_type": "added", "new_price": 3, "new_score": 49},
        {"sku": "d", "title": "D", "change_type": "updated_price", "old_price": 6, "new_price": 5.5, "old_score": 59, "new_score": 59},
        {"sku": "e", "title": "E", "change_type": "display_dropped", "rank": 1},
        {"sku": "a", "title": "A", "change_type": "added", "rank": 1},
    ]
    # Last row repeats sku a but is still just another changelog line; highlights are per row.
    payload = build_payload(
        date="20261103",
        generated_at="2026-11-03T12:00:00+08:00",
        source="snapshot",
        has_snapshot=True,
        snapshot_dir="data/snapshots/20261103",
        note=None,
        summary={},
        changelog=changelog[:5],
        ranks=ranks,
    )
    assert {item["sku"] for item in payload["highlights"]} == {"a", "b"}
    assert payload["counts"]["added"] == 3
    assert payload["counts"]["highlights"] == 2
    assert payload["counts"]["info_updated"] == 1
    assert payload["counts"]["updated_price"] == 1
    assert payload["counts"]["display_dropped"] == 1
    stale = enrich_change({"sku": "c", "title": "C", "change_type": "added", "rank": 1}, ranks)
    assert stale is not None and stale["rank"] == 11 and stale["highlight"] is False
    off_board = enrich_change({"sku": "z", "title": "Z", "change_type": "added", "rank": 4}, {})
    assert off_board is not None and off_board["highlight"] is True
    top_update = enrich_change({"sku": "d", "title": "D", "change_type": "updated_price", "rank": 2}, ranks)
    assert top_update is not None and top_update["highlight"] is False
    print("export_today_updates self-check ok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把当日入库快照导出成看板 today-updates.json")
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--date", default=None, help="data/snapshots 下的 YYYYMMDD")
    parser.add_argument("--ranked", type=Path, default=None, help="默认看板 public 里的 listings-ranked.json")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--write-fixture", action="store_true", help="额外写 today-updates.fixture.json")
    parser.add_argument("--fixture-only", action="store_true", help="只写演示文件")
    parser.add_argument("--fixture-out", type=Path, default=None)
    parser.add_argument("--self-check", action="store_true", help="只跑规则自检，不写文件")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    self_check()
    if args.self_check:
        return
    ranked_file = args.ranked or default_ranked_path()
    listings = load_json(ranked_file, [])
    if not isinstance(listings, list):
        raise SystemExit(f"排名文件不是数组：{ranked_file}")
    if not args.fixture_only:
        if args.snapshot_dir is not None:
            snapshot = args.snapshot_dir
        elif args.date:
            snapshot = SNAPSHOTS / args.date
        else:
            snapshot = find_latest_snapshot()
        if snapshot is None or not snapshot.exists():
            payload = missing_payload("没有找到 data/snapshots/YYYYMMDD 今日快照。")
            destination = args.out or DEFAULT_OUT
            dump_json(destination, payload)
            print(f"today-updates -> {rel_to_root(destination)} (no snapshot)")
        else:
            export_snapshot(snapshot, ranked_path=ranked_file, out_path=args.out or DEFAULT_OUT)
    if args.write_fixture or args.fixture_only:
        write_fixture(listings, args.fixture_out or DEFAULT_FIXTURE)


if __name__ == "__main__":
    main()
