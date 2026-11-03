"""Attach cached exact-trim specs and score listings with the existing V2 engine.

Live AutoHome matching is optional. --skip-live-fetch uses only the on-disk
verified cache. New trims are returned in memory; the caller decides whether
to commit them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _is_exact(specs: dict[str, Any] | None) -> bool:
    specs = specs or {}
    return (
        specs.get("match_level") == "exact_trim"
        and specs.get("verified") is True
        and specs.get("specs_found") is True
        and specs.get("configuration_source") == "exact_trim_v3"
    )


def load_verified(root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = root or ROOT
    path = root / "data" / "vehicle-specs-verified.json"
    if not path.exists():
        return {}
    from ranking_v2.apply_verified import load_verified_by_sku

    return load_verified_by_sku(path)


def prepare_and_score(item: dict[str, Any], verified_by_sku: dict[str, dict[str, Any]]) -> dict[str, Any]:
    from ranking_v2.apply_verified import (
        apply_verified_record,
        effective_price_fields,
        sanitize_unverified_listing,
    )
    from rerank_v2 import score_one

    sku = str(item.get("sku") or "")
    if sku in verified_by_sku:
        item = apply_verified_record(item, verified_by_sku[sku])
    elif not _is_exact(item.get("specs")):
        item = sanitize_unverified_listing(item)
    cash = item.get("cash_price_wan")
    priced = effective_price_fields(
        float(item.get("price") or 0),
        item.get("price_type"),
        cash_price=float(cash) if cash not in (None, "") else None,
    )
    item.update(priced)
    return score_one(item)


def match_with_autohome(
    listings: list[dict[str, Any]],
    *,
    live: bool,
    persist: bool,
) -> dict[str, dict[str, Any]]:
    """Identity-match unknown SKUs. live=True also pulls AutoHome config pages."""
    import sync_exact_trim_specs_strict  # noqa: F401  (applies strict identity patches)
    import sync_exact_trim_specs_autohome as impl

    result = impl.sync_listings(
        listings,
        live=live,
        persist=persist,
        write_report=False,
        source_label="daily_ingest",
    )
    return dict(result.get("verified") or {})


def commit_verified(verified_by_sku: dict[str, dict[str, Any]]) -> int:
    import sync_exact_trim_specs_autohome as impl

    return int(impl.commit_verified(verified_by_sku))
