#!/usr/bin/env python3
"""CI entrypoint for strict AutoHome exact-trim synchronization.

The production path deliberately revalidates every previously auto-generated
AutoHome mapping on each run. Hand-verified V3 mappings are preserved.
"""
from __future__ import annotations

import json
from pathlib import Path

import autohome_exact_rules as rules
import sync_exact_trim_specs_autohome as impl

ROOT = Path(__file__).resolve().parents[1]


# AutoHome CSVs use several historical naming schemes. Normalize the exact
# matched column before the shared V3 builder sees it.
_original_parse = impl.parse_matrix_csv


def parse_matrix_csv_strict(blob: bytes, source_path: str, snapshot: str, series_id: int | None = None):
    return [
        rules.canonicalize_candidate(c)
        for c in _original_parse(blob, source_path, snapshot, series_id)
    ]


impl.parse_matrix_csv = parse_matrix_csv_strict


# Text similarity alone is not enough: e.g. 18T automatic must never match
# 15T manual. Apply mechanical/range/body identity checks first.
_original_choose = impl.choose_exact


def choose_exact_strict(title: str, series: str, candidates):
    same_identity = [c for c in candidates if rules.critical_identity_compatible(title, c.title)]
    if not same_identity:
        return None, 0.0, "critical_identity_mismatch"
    return _original_choose(title, series, same_identity)


impl.choose_exact = choose_exact_strict


# Add exact fields not represented by the shared Dongchedi-oriented builder.
_original_build = impl.build_autohome_trim


def build_autohome_trim_strict(candidate, score: float):
    trim_id, trim = _original_build(candidate, score)
    return trim_id, rules.enrich_trim(trim, candidate.rows)


impl.build_autohome_trim = build_autohome_trim_strict


# Vault formats have changed over the years. One unreadable monthly archive
# must not abort a listing; the source selector can safely try the next nearby
# snapshot and still require an exact match.
_original_vault_files = impl.AutoHomeSource._vault_files


def safe_vault_files(self, month: str):
    try:
        return _original_vault_files(self, month)
    except Exception as exc:
        print(f"AutoHome vault {month} skipped: {type(exc).__name__}: {exc}")
        return {}


impl.AutoHomeSource._vault_files = safe_vault_files


def reset_auto_generated_mappings() -> None:
    """Remove only machine-generated AutoHome mappings before revalidation."""
    if not impl.base.INDEX.exists():
        return
    index = json.loads(impl.base.INDEX.read_text(encoding="utf-8"))
    mapping = index.get("sku_to_trim") or {}
    index["sku_to_trim"] = {
        str(sku): str(trim_id)
        for sku, trim_id in mapping.items()
        if not str(trim_id).startswith("trim_ah_")
    }
    impl.base.dump(impl.base.INDEX, index)
    impl.base.dump(impl.base.AUTO_SHARD, {"schema_version": "3.0-exact-trim", "trims": {}})


if __name__ == "__main__":
    reset_auto_generated_mappings()
    impl.main()
