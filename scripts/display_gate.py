"""Top-30 display gate shared by daily ingest and rerank_v2.

The score cutoff is the current library's Nth total_score. It is never a
hard-coded constant. N defaults to 30.
"""
from __future__ import annotations

from typing import Any

DISPLAY_LIMIT = 30
WUHAN_SHOP_ID = "118608"
WUHAN_CITY = "武汉"


def is_local_wuhan(item: dict[str, Any] | None) -> bool:
    if not item:
        return False
    flag = item.get("is_local_wuhan")
    if isinstance(flag, bool):
        return flag
    sid = str(item.get("shop_id") or "").strip()
    if sid:
        return sid == WUHAN_SHOP_ID
    return str(item.get("city") or "").strip() == WUHAN_CITY


def numeric_score(item: dict[str, Any] | None) -> float | None:
    if not item:
        return None
    if item.get("sale_status") in {"sold", "reserved"}:
        return None
    if item.get("recommendation_gate") == "VETO":
        return None
    if item.get("score_eligible") is False:
        return None
    if item.get("condition_gate") in {"REJECT", "DATA_ISSUE"}:
        return None
    score = item.get("total_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if score < 0:
        return None
    return float(score)


def display_sort_key(item: dict[str, Any]) -> tuple:
    """Best-first key. Matches rerank_v2, with sku as a stable tie-break."""
    return (
        0 if item.get("condition_gate") != "REJECT" and item.get("recommendation_gate") != "VETO" else 1,
        -(numeric_score(item) if numeric_score(item) is not None else float(item.get("total_score") or 0)),
        -float((item.get("sort_scores") or {}).get("powertrain_score") or (item.get("sort_scores") or {}).get("price_score") or 0),
        float(item.get("effective_price_wan") or item.get("price") or 99),
        float(item.get("mileage_wan") or 99),
        str(item.get("sku") or ""),
    )


def ranked_threshold(items: list[dict[str, Any]], limit: int = DISPLAY_LIMIT) -> float | None:
    """Score of the current Nth displayed/scored car. None when the library is shorter than N."""
    scored = [item for item in items if numeric_score(item) is not None]
    scored.sort(key=display_sort_key)
    if limit <= 0 or len(scored) < limit:
        return None
    return float(scored[limit - 1]["total_score"])


def apply_display_flags(
    scored_sorted: list[dict[str, Any]],
    limit: int = DISPLAY_LIMIT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Mark an already best-first scored list. Returns (display, below)."""
    for index, item in enumerate(scored_sorted, 1):
        shown = index <= limit and numeric_score(item) is not None
        item["library_rank"] = index
        item["display"] = shown
        item["rank"] = index if shown else None
    display = [item for item in scored_sorted if item.get("display")]
    below = [item for item in scored_sorted if not item.get("display")]
    return display, below


def build_wuhan_board(
    scored_sorted: list[dict[str, Any]],
    limit: int = DISPLAY_LIMIT,
) -> list[dict[str, Any]]:
    """Build independent Wuhan local top-N board from an already best-first scored list.

    Marks `wuhan_library_rank`, `wuhan_display`, and `wuhan_rank` on every item in place
    without mutating the national board's `rank` / `display`, and returns shallow-copied
    rows whose `rank` is the Wuhan board rank (1..limit) and `national_rank` preserves
    the overall board rank.
    """
    wuhan_board: list[dict[str, Any]] = []
    wuhan_index = 0
    for item in scored_sorted:
        if not is_local_wuhan(item):
            item["wuhan_library_rank"] = None
            item["wuhan_display"] = False
            item["wuhan_rank"] = None
            continue
        wuhan_index += 1
        shown = wuhan_index <= limit and numeric_score(item) is not None
        item["wuhan_library_rank"] = wuhan_index
        item["wuhan_display"] = shown
        item["wuhan_rank"] = wuhan_index if shown else None
        if shown:
            row = dict(item)
            row["national_rank"] = item.get("rank")
            row["rank"] = wuhan_index
            row["display"] = True
            row["board_scope"] = "wuhan"
            wuhan_board.append(row)
    return wuhan_board
