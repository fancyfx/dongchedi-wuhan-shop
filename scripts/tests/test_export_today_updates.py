#!/usr/bin/env python3
"""Highlight rule for the dashboard today-updates export."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from export_today_updates import (  # noqa: E402
    board_ranks,
    build_payload,
    enrich_change,
    is_highlight,
    self_check,
)


def test_only_added_inside_top10_is_highlight() -> None:
    assert is_highlight("added", 1)
    assert is_highlight("added", 10)
    assert not is_highlight("added", 11)
    assert not is_highlight("updated", 1)
    assert not is_highlight("updated_price", 2)
    assert not is_highlight("added", None)


def test_payload_splits_highlights_from_other_new_cars() -> None:
    ranked = [
        {"sku": "a", "rank": 1, "total_score": 60},
        {"sku": "b", "rank": 10, "total_score": 50},
        {"sku": "c", "rank": 11, "total_score": 49},
        {"sku": "d", "rank": 2, "total_score": 59},
    ]
    payload = build_payload(
        date="20261103",
        generated_at="2026-11-03T12:00:00+08:00",
        source="snapshot",
        has_snapshot=True,
        snapshot_dir="data/snapshots/20261103",
        note=None,
        summary={"dry_run": True},
        changelog=[
            {"sku": "a", "title": "A", "change_type": "added"},
            {"sku": "b", "title": "B", "change_type": "added"},
            {"sku": "c", "title": "C", "change_type": "added"},
            {"sku": "d", "title": "D", "change_type": "updated_price", "old_price": 6, "new_price": 5},
            {"sku": "e", "title": "E", "change_type": "updated"},
        ],
        ranks=board_ranks(ranked),
    )
    assert [item["sku"] for item in payload["highlights"]] == ["a", "b"]
    assert payload["counts"]["added"] == 3
    assert payload["counts"]["info_updated"] == 2
    assert payload["counts"]["highlights"] == 2
    assert all(item["change_type"] == "added" and item["rank"] <= 10 for item in payload["highlights"])


def test_board_rank_beats_a_stale_changelog_rank() -> None:
    item = enrich_change({"sku": "c", "title": "C", "change_type": "added", "rank": 1}, {"c": 11})
    assert item is not None
    assert item["rank"] == 11
    assert item["highlight"] is False


def main() -> None:
    test_only_added_inside_top10_is_highlight()
    test_payload_splits_highlights_from_other_new_cars()
    test_board_rank_beats_a_stale_changelog_rank()
    self_check()
    print("test_export_today_updates ok")


if __name__ == "__main__":
    main()
