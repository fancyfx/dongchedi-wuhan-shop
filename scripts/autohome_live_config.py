"""Fetch complete AutoHome exact-trim parameters from live config pages.

Vault CSV snapshots (swoiow/autohome) are often missing columns for older
months. The live page https://car.autohome.com.cn/config/spec/{spec_id}.html
is the authoritative full parameter table for display and scoring.

This module shells out to scripts/autohome_live_fetch.mjs (Chrome + puppeteer-
core). On fetch failure the caller must keep vault CSV values / nulls.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FETCH_JS = ROOT / "scripts" / "autohome_live_fetch.mjs"
NODE_DIR = ROOT / ".external" / "autohome-live-node"
CACHE_PATH = ROOT / "data" / "specs" / "autohome-live-cache.json"
DEFAULT_CHROME = os.environ.get("CHROME_PATH", "/usr/bin/google-chrome")


def ensure_runtime() -> None:
    if shutil.which("node") is None:
        raise RuntimeError("node is required for AutoHome live config fetch")
    chrome = DEFAULT_CHROME
    if not Path(chrome).exists() and shutil.which("google-chrome") is None:
        raise RuntimeError(f"Chrome not found at {chrome}")
    NODE_DIR.mkdir(parents=True, exist_ok=True)
    pkg = NODE_DIR / "package.json"
    if not pkg.exists():
        subprocess.run(["npm", "init", "-y"], cwd=str(NODE_DIR), check=True, capture_output=True)
    if not (NODE_DIR / "node_modules" / "puppeteer-core").exists():
        subprocess.run(
            ["npm", "install", "puppeteer-core@23", "--silent"],
            cwd=str(NODE_DIR),
            check=True,
        )


def load_cache(path: Path | None = None) -> dict[str, Any]:
    path = path or CACHE_PATH
    if not path.exists():
        return {"results": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"results": {}}
    if not isinstance(data.get("results"), dict):
        data["results"] = {}
    return data


def save_cache(cache: dict[str, Any], path: Path | None = None) -> None:
    path = path or CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_specs(
    spec_ids: list[int],
    *,
    cache_path: Path | None = None,
    force: bool = False,
    delay_ms: int = 800,
    out_path: Path | None = None,
) -> dict[int, dict[str, Any]]:
    """Return {spec_id: {ok, rows, ...}} for the requested ids."""
    ids = sorted({int(x) for x in spec_ids})
    if not ids:
        return {}
    cache = load_cache(cache_path)
    results: dict[int, dict[str, Any]] = {}
    missing: list[int] = []
    for sid in ids:
        hit = cache.get("results", {}).get(str(sid))
        if not force and isinstance(hit, dict) and hit.get("ok") and isinstance(hit.get("rows"), dict) and len(hit["rows"]) >= 30:
            results[sid] = hit
        else:
            missing.append(sid)
    if not missing:
        return results

    ensure_runtime()
    out_path = out_path or (ROOT / ".tmp" / f"autohome-live-{int(time.time())}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ids_file = out_path.with_suffix(".ids.txt")
    ids_file.write_text("\n".join(str(x) for x in missing) + "\n", encoding="utf-8")
    cmd = [
        "node",
        str(FETCH_JS),
        "--out",
        str(out_path),
        "--ids-file",
        str(ids_file),
        "--delay-ms",
        str(delay_ms),
        "--chrome",
        DEFAULT_CHROME if Path(DEFAULT_CHROME).exists() else "google-chrome",
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    fetched = payload.get("results") or {}
    cache.setdefault("results", {})
    for key, value in fetched.items():
        cache["results"][str(key)] = value
        if value.get("ok"):
            results[int(key)] = value
    cache["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    cache["source"] = "car.autohome.com.cn/config/spec"
    save_cache(cache, cache_path)
    return results


def rows_for_spec(spec_id: int, live: dict[int, dict[str, Any]] | None = None) -> dict[str, str] | None:
    """Return decoded rows for one spec, or None if unavailable."""
    blob = (live or {}).get(int(spec_id))
    if blob is None:
        cache = load_cache()
        blob = cache.get("results", {}).get(str(spec_id))
    if not isinstance(blob, dict) or not blob.get("ok"):
        return None
    rows = blob.get("rows") or {}
    if len(rows) < 30:
        return None
    return {str(k): str(v) for k, v in rows.items() if str(k).strip()}


def apply_live_rows(candidate: Any, live_rows: dict[str, str], *, snapshot_label: str = "live") -> Any:
    """Replace candidate.rows with live page rows; keep identity metadata."""
    return replace(
        candidate,
        rows=dict(live_rows),
        snapshot=snapshot_label,
        source_path=f"live:config/spec/{candidate.spec_id}.html",
    )


def merge_prefer_live(vault_rows: dict[str, str], live_rows: dict[str, str]) -> dict[str, str]:
    """Prefer live values; keep vault-only keys as fallback."""
    merged = dict(vault_rows or {})
    for key, value in (live_rows or {}).items():
        if value not in (None, ""):
            merged[key] = value
    return merged
