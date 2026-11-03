"""Top-100 display gate shared by daily ingest and rerank_v2.

The score cutoff is the current library's Nth total_score. It is never a
hard-coded constant. N defaults to 100.
"""
from __future__ import annotations

from typing import Any

DISPLAY_LIMIT = 100


def numeric_score(item: dict[str, Any] | None) -> float | None:
    if not item:
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
        0 if item.get("condition_gate") != "REJECT" else 1,
        -(numeric_score(item) if numeric_score(item) is not None else float(item.get("total_score") or 0)),
        -float((item.get("sort_scores") or {}).get("price_score") or 0),
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
