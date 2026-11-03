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
import re
import shutil
import subprocess
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FETCH_JS = ROOT / "scripts" / "autohome_live_fetch.mjs"
NODE_DIR = ROOT / ".external" / "autohome-live-node"
CACHE_PATH = ROOT / "data" / "specs" / "autohome-live-cache.json"
LIVE_DIR = ROOT / "data" / "specs" / "live-config"
DASH_LIVE_DIR = ROOT / "dashboard" / "public" / "data" / "live-config"
LISTING_FILES = (
    ROOT / "data" / "listings-ranked.json",
    ROOT / "data" / "listings-filtered.json",
    ROOT / "data" / "data-issues.json",
)
DEFAULT_CHROME = os.environ.get("CHROME_PATH", "/usr/bin/google-chrome")
SCHEMA_VERSION = "autohome-live-config-tree-1"
LEGEND = {"standard": "●", "optional": "○", "absent": "-"}
_SPEC_URL_RE = re.compile(r"/config/spec/(\d+)\.html")


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


def _rows_ok(blob: Any) -> bool:
    return isinstance(blob, dict) and bool(blob.get("ok")) and isinstance(blob.get("rows"), dict) and len(blob["rows"]) >= 30


def tree_path(spec_id: int) -> Path:
    return LIVE_DIR / f"{int(spec_id)}.json"


def tree_has_sections(spec_id: int) -> bool:
    path = tree_path(spec_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    sections = data.get("sections") if isinstance(data, dict) else None
    return isinstance(sections, list) and len(sections) > 0


def _cache_record(value: dict[str, Any], section_count: int | None = None) -> dict[str, Any]:
    """Scoring cache stays flat. Section trees live in live-config/*.json."""
    stored = {k: v for k, v in value.items() if k != "sections"}
    if section_count is not None:
        stored["section_count"] = int(section_count)
    return stored


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _space_marks(text: str) -> str:
    """Keep ●/○ readable when the page icon sits directly against the next glyph."""
    return re.sub(r"([●○])(?=[^\s●○])", r"\1 ", text)


def normalize_config_tree(payload: dict[str, Any]) -> dict[str, Any]:
    """Turn a fetch payload (or partial tree) into the live-config schema.

    Empty names and empty sections are dropped. `lines` is omitted for a
    plain single value. Order from the page is preserved.
    """
    spec_id = int(payload.get("spec_id") or 0)
    title = str(payload.get("title") or "").strip()
    if not title:
        rows = payload.get("rows") if isinstance(payload.get("rows"), dict) else {}
        title = str(rows.get("车型名称") or rows.get("车型") or "").strip()
    fetched_at = str(payload.get("fetched_at") or "").strip() or _iso_now()
    sections_out: list[dict[str, Any]] = []
    for sec in payload.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        name = str(sec.get("name") or "").strip()
        if not name:
            continue
        items_out: list[dict[str, Any]] = []
        for raw in sec.get("items") or []:
            if not isinstance(raw, dict):
                continue
            iname = str(raw.get("name") or "").strip()
            if not iname:
                continue
            value = raw.get("value")
            if value is None or str(value).strip() == "":
                value = "-"
            else:
                value = _space_marks(str(value))
            item: dict[str, Any] = {"name": iname, "value": value}
            lines_out: list[dict[str, Any]] = []
            raw_lines = raw.get("lines")
            if isinstance(raw_lines, list):
                for ln in raw_lines:
                    if not isinstance(ln, dict):
                        continue
                    lname = str(ln.get("name") or "")
                    lvalue = "" if ln.get("value") is None else _space_marks(str(ln.get("value")))
                    if not lname and not lvalue:
                        continue
                    entry: dict[str, Any] = {"name": lname, "value": lvalue}
                    mark = ln.get("mark")
                    if mark in ("standard", "optional"):
                        entry["mark"] = mark
                    lines_out.append(entry)
            plain_single = len(lines_out) == 1 and not lines_out[0].get("name")
            if lines_out and not plain_single:
                item["lines"] = lines_out
            items_out.append(item)
        if not items_out:
            continue
        sections_out.append({
            "name": name,
            "group": str(sec.get("group") or ""),
            "items": items_out,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "spec_id": spec_id,
        "title": title,
        "url": f"https://car.autohome.com.cn/config/spec/{spec_id}.html",
        "fetched_at": fetched_at,
        "legend": dict(LEGEND),
        "sections": sections_out,
    }


def write_config_tree(tree: dict[str, Any]) -> Path:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = tree_path(int(tree["spec_id"]))
    path.write_text(json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _spec_from_source(src: dict[str, Any]) -> int | None:
    sid = src.get("spec_id")
    if isinstance(sid, bool):
        sid = None
    if isinstance(sid, int):
        return sid
    if isinstance(sid, str) and sid.isdigit():
        return int(sid)
    match = _SPEC_URL_RE.search(str(src.get("url") or ""))
    if match:
        return int(match.group(1))
    return None


def _spec_from_listing(item: dict[str, Any]) -> int | None:
    specs = item.get("specs")
    sources = specs.get("verification_sources") if isinstance(specs, dict) else None
    if not isinstance(sources, list):
        return None
    for src in sources:
        if not isinstance(src, dict):
            continue
        sid = _spec_from_source(src)
        if sid is not None:
            return sid
    return None


def build_sku_to_spec() -> dict[str, int]:
    """Map listing sku → spec id from verification sources. Does not invent ids."""
    mapping: dict[str, int] = {}
    for path in LISTING_FILES:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = data if isinstance(data, list) else []
        if isinstance(data, dict):
            items = data.get("listings") or data.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("sku") is None:
                continue
            sku = str(item["sku"])
            if sku in mapping:
                continue
            sid = _spec_from_listing(item)
            if sid is None:
                continue
            mapping[sku] = sid
    return mapping


def _item_count(tree: dict[str, Any]) -> int:
    return sum(len(sec.get("items") or []) for sec in (tree.get("sections") or []))


def export_live_config_trees() -> dict[str, Any]:
    """Write live-config/index.json and copy trees into the dashboard public data."""
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    DASH_LIVE_DIR.mkdir(parents=True, exist_ok=True)
    specs_index: dict[str, dict[str, Any]] = {}
    for path in LIVE_DIR.glob("*.json"):
        if path.name == "index.json":
            continue
        try:
            tree = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(tree, dict) or not tree.get("sections"):
            continue
        sid = str(tree.get("spec_id") or path.stem)
        specs_index[sid] = {
            "title": tree.get("title") or "",
            "url": tree.get("url") or f"https://car.autohome.com.cn/config/spec/{sid}.html",
            "section_count": len(tree.get("sections") or []),
            "item_count": _item_count(tree),
            "file": f"{sid}.json",
        }
        dest = DASH_LIVE_DIR / f"{sid}.json"
        shutil.copy2(path, dest)
    ordered = dict(sorted(specs_index.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0))
    index = {
        "schema_version": SCHEMA_VERSION,
        "source": "car.autohome.com.cn/config/spec",
        "generated_at": _iso_now(),
        "legend": dict(LEGEND),
        "spec_count": len(ordered),
        "specs": ordered,
        "sku_to_spec": build_sku_to_spec(),
    }
    text = json.dumps(index, ensure_ascii=False, indent=2) + "\n"
    (LIVE_DIR / "index.json").write_text(text, encoding="utf-8")
    (DASH_LIVE_DIR / "index.json").write_text(text, encoding="utf-8")
    return index


def fetch_specs(
    spec_ids: list[int],
    *,
    cache_path: Path | None = None,
    force: bool = False,
    delay_ms: int = 800,
    out_path: Path | None = None,
) -> dict[int, dict[str, Any]]:
    """Return {spec_id: {ok, rows, ...}} for the requested ids.

    A hit needs rows>=30 and a tree file with non-empty sections. Failures
    keep the previous rows and do not delete a good tree.
    """
    ids = sorted({int(x) for x in spec_ids})
    if not ids:
        return {}
    if delay_ms < 400:
        delay_ms = 400
    cache = load_cache(cache_path)
    results: dict[int, dict[str, Any]] = {}
    missing: list[int] = []
    for sid in ids:
        hit = cache.get("results", {}).get(str(sid))
        if not force and _rows_ok(hit) and tree_has_sections(sid):
            results[sid] = hit
        else:
            missing.append(sid)
    if 49472 in missing:
        missing.remove(49472)
        missing.insert(0, 49472)
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
        str(max(400, int(delay_ms))),
        "--chrome",
        DEFAULT_CHROME if Path(DEFAULT_CHROME).exists() else "google-chrome",
    ]
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if not out_path.exists():
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)
        return results
    if proc.returncode != 0:
        print(f"live fetch exited {proc.returncode}; merging any partial results")
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    fetched = payload.get("results") or {}
    cache.setdefault("results", {})
    for key, value in fetched.items():
        sid = int(key)
        old = cache["results"].get(str(sid))
        if not isinstance(value, dict) or not _rows_ok(value):
            if _rows_ok(old):
                results[sid] = old
            elif isinstance(value, dict):
                cache["results"][str(sid)] = _cache_record(value)
            continue
        tree = normalize_config_tree(value)
        if not tree.get("sections"):
            if _rows_ok(old):
                results[sid] = old
            continue
        write_config_tree(tree)
        stored = _cache_record(value, section_count=len(tree["sections"]))
        cache["results"][str(sid)] = stored
        results[sid] = stored
    cache["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    cache["source"] = "car.autohome.com.cn/config/spec"
    save_cache(cache, cache_path)
    export_live_config_trees()
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
