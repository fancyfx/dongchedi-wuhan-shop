#!/usr/bin/env python3
"""Local-only strict exact-trim configuration refresh.

Configuration policy:
- rebuild the configuration index from scratch on every run;
- only the new AutoHome exact-trim/full-parameter output may be indexed;
- legacy hand-maintained shards and approximate configuration are never reused;
- unmatched listings remain unverified instead of inheriting another trim.

This module is intentionally a local entrypoint. GitHub Actions must not run
vehicle configuration acquisition or ranking calculation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import autohome_exact_rules as rules
import sync_exact_trim_specs_autohome as impl

ROOT = Path(__file__).resolve().parents[1]
AUTO_SHARD_REL = "specs/exact-trims-auto.json"
CONFIG_POLICY = (
    "new-full-config-only; AutoHome exact-trim parameters only; "
    "legacy shards/approximate config forbidden"
)


# AutoHome CSVs use several historical naming schemes. Normalize the exact
# matched column before the shared builder sees it. This is field-name
# compatibility only; it never borrows values from another trim.
_original_parse = impl.parse_matrix_csv


def parse_matrix_csv_strict(blob: bytes, source_path: str, snapshot: str, series_id: int | None = None):
    return [rules.canonicalize_candidate(c) for c in _original_parse(blob, source_path, snapshot, series_id)]


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


# Add exact fields not represented by the shared legacy parser primitives.
_original_build = impl.build_autohome_trim


def build_autohome_trim_strict(candidate, score: float):
    trim_id, trim = _original_build(candidate, score)
    return trim_id, rules.enrich_trim(trim, candidate.rows)


impl.build_autohome_trim = build_autohome_trim_strict


# Vault formats changed over time. One unreadable monthly archive must not
# abort a listing; the source selector can try the next nearby snapshot while
# still requiring an exact trim identity.
_original_vault_files = impl.AutoHomeSource._vault_files


def safe_vault_files(self, month: str):
    try:
        return _original_vault_files(self, month)
    except Exception as exc:
        print(f"AutoHome vault {month} skipped: {type(exc).__name__}: {exc}")
        return {}


impl.AutoHomeSource._vault_files = safe_vault_files


def reset_configuration_store() -> None:
    """Delete all previously indexed configuration before a new local sync."""
    index = {
        "schema_version": "3.0-exact-trim",
        "generated_at": time.strftime("%Y-%m-%d"),
        "configuration_policy": CONFIG_POLICY,
        "trim_files": [AUTO_SHARD_REL],
        "sku_to_trim": {},
    }
    auto = {
        "schema_version": "3.0-exact-trim",
        "configuration_policy": CONFIG_POLICY,
        "trims": {},
    }
    impl.base.dump(impl.base.INDEX, index)
    impl.base.dump(impl.base.AUTO_SHARD, auto)


def enforce_new_only_store() -> None:
    """Fail closed if the synchronizer ever tries to reintroduce old shards."""
    index = json.loads(impl.base.INDEX.read_text(encoding="utf-8"))
    mapping = {str(k): str(v) for k, v in (index.get("sku_to_trim") or {}).items()}
    invalid = {sku: trim_id for sku, trim_id in mapping.items() if not trim_id.startswith("trim_ah_")}
    if invalid:
        sample = list(invalid.items())[:5]
        raise RuntimeError(f"legacy/non-AutoHome trim ids reintroduced: {sample}")

    index["trim_files"] = [AUTO_SHARD_REL]
    index["configuration_policy"] = CONFIG_POLICY
    index["generated_at"] = time.strftime("%Y-%m-%d")
    impl.base.dump(impl.base.INDEX, index)

    auto = json.loads(impl.base.AUTO_SHARD.read_text(encoding="utf-8"))
    auto["schema_version"] = "3.0-exact-trim"
    auto["configuration_policy"] = CONFIG_POLICY
    impl.base.dump(impl.base.AUTO_SHARD, auto)


if __name__ == "__main__":
    reset_configuration_store()
    impl.main()
    enforce_new_only_store()
