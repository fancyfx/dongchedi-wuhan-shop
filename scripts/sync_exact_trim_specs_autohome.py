#!/usr/bin/env python3
"""AutoHome-backed exact-trim V3 synchronizer.

The source repository is https://github.com/swoiow/autohome:
- main: current per-series parameter CSVs
- vaults: historical monthly snapshots

Only a unique year+trim match is accepted. Ambiguous or sparse matches remain
unverified; no series/year/tier fallback is ever produced.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import time
import urllib.request
import zlib
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import sync_exact_trim_specs as base

ROOT = Path(__file__).resolve().parents[1]
AUTOHOME_MAIN = Path(os.environ.get("AUTOHOME_MAIN_REPO", ROOT / ".external" / "autohome-main"))
AUTOHOME_VAULTS = Path(os.environ.get("AUTOHOME_VAULTS_REPO", ROOT / ".external" / "autohome-vaults"))
MIN_MATCH = 0.86
MIN_GAP = 0.045
MIN_FEATURES = 18
PARAM_CACHE = ROOT / ".tmp" / "ah-param-cache"
# 参配页年款目录用的 series id。模糊匹配会把「唐DM」收成汽油「唐」、
# 「秦PLUS DM」对不上「秦PLUS」。只影响补匹配，不改第一轮标题分。
LIVE_SERIES_ALIASES = {
    "秦plusdm": 5964,
    "秦plus": 5964,
    "唐dm": 3430,
}


@dataclass(frozen=True)
class Candidate:
    spec_id: int
    title: str
    rows: dict[str, str]
    source_path: str
    snapshot: str
    series_id: int | None = None


def run_git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    # core.quotepath=false keeps Chinese CSV names as UTF-8 instead of
    # C-quoted octal escapes, which otherwise breaks series matching and
    # forces every listing into historical vaults (main=0).
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotepath=false", *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    return proc.stdout


def repo_paths(repo: Path, prefix: str) -> list[str]:
    out = str(run_git(repo, "ls-tree", "-r", "--name-only", "HEAD", prefix))
    return [line.strip() for line in out.splitlines() if line.strip()]


def git_bytes(repo: Path, path: str) -> bytes:
    return bytes(run_git(repo, "show", f"HEAD:{path}", text=False))


def norm(text: Any) -> str:
    s = str(text or "").lower()
    replacements = {
        "dm-i": "dmi",
        "dm i": "dmi",
        "max版": "max",
        "pro版": "pro",
        "plus版": "plus",
        "旗舰型": "旗舰版",
        "尊贵型": "尊贵版",
        "豪华型": "豪华版",
        "精英型": "精英版",
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)


def year_of(text: str) -> int | None:
    m = re.search(r"(20\d{2})款", str(text or ""))
    return int(m.group(1)) if m else None


def series_from_filename(path: str) -> str:
    name = Path(path).stem
    return name.split("_", 1)[1] if "_" in name else name


def title_score(target: str, candidate: str, series: str) -> float:
    ty, cy = year_of(target), year_of(candidate)
    if ty and cy and ty != cy:
        return 0.0
    tn, cn = norm(target), norm(candidate)
    ts = norm(base.trim_part(target, series))
    cs = norm(base.trim_part(candidate, series))
    score = max(
        SequenceMatcher(None, tn, cn).ratio(),
        SequenceMatcher(None, ts, cs).ratio() if ts and cs else 0.0,
    )
    if tn == cn or (ts and ts == cs):
        return 1.0
    if ts and cs and (ts in cs or cs in ts):
        score = max(score, 0.94)
    return max(0.0, min(1.0, score))


def parse_matrix_csv(blob: bytes, source_path: str, snapshot: str, series_id: int | None = None) -> list[Candidate]:
    text = blob.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2:
        return []
    spec_ids = rows[0][1:]
    by_feature: dict[str, list[str]] = {}
    for row in rows[1:]:
        if not row:
            continue
        label = str(row[0]).strip()
        if not label:
            continue
        values = list(row[1:])
        if len(values) < len(spec_ids):
            values.extend([""] * (len(spec_ids) - len(values)))
        by_feature[label] = values[: len(spec_ids)]
    title_values = by_feature.get("车型名称") or []
    result: list[Candidate] = []
    for idx, raw_id in enumerate(spec_ids):
        try:
            spec_id = int(str(raw_id).strip())
        except (TypeError, ValueError):
            continue
        title = str(title_values[idx] if idx < len(title_values) else "").strip()
        if not title:
            continue
        config: dict[str, str] = {}
        for label, values in by_feature.items():
            value = str(values[idx] if idx < len(values) else "").strip()
            if value:
                config[label] = value
        result.append(Candidate(spec_id, title, config, source_path, snapshot, series_id))
    return result


class AutoHomeSource:
    def __init__(self, main_repo: Path, vault_repo: Path):
        if not (main_repo / ".git").exists():
            raise RuntimeError(f"AutoHome main repository missing: {main_repo}")
        if not (vault_repo / ".git").exists():
            raise RuntimeError(f"AutoHome vault repository missing: {vault_repo}")
        self.main_repo = main_repo
        self.vault_repo = vault_repo
        self.main_paths = [p for p in repo_paths(main_repo, "data") if p.endswith(".csv")]
        self.series_paths: dict[str, list[str]] = {}
        for path in self.main_paths:
            self.series_paths.setdefault(norm(series_from_filename(path)), []).append(path)
        self.series_ids = self._load_series_ids()
        self.vault_months = self._load_vault_months()
        self.vault_cache: dict[str, dict[str, bytes]] = {}

    def _load_series_ids(self) -> dict[str, int]:
        out: dict[str, int] = {}
        try:
            text = git_bytes(self.main_repo, "brands.csv").decode("utf-8-sig", errors="replace")
        except Exception:
            return out
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 2:
                continue
            label = re.sub(r"\s*\(停售\)\s*", " ", row[0])
            label = re.sub(r"\s*\(\d+\)\s*$", "", label).strip()
            m = re.search(r"series_(\d+)", row[1])
            if m and label:
                out[norm(label)] = int(m.group(1))
        return out

    def _load_vault_months(self) -> list[str]:
        paths = repo_paths(self.vault_repo, "vaults")
        months = {
            m.group(1)
            for p in paths
            if (m := re.match(r"vaults/(\d{6})/data\.vault$", p))
        }
        return sorted(months)

    def _series_id(self, series: str) -> int | None:
        ns = norm(series)
        if ns in self.series_ids:
            return self.series_ids[ns]
        ranked: list[tuple[float, int]] = []
        for name, sid in self.series_ids.items():
            score = SequenceMatcher(None, ns, name).ratio()
            if ns and (ns in name or name in ns):
                score = max(score, 0.92)
            if score >= 0.90:
                ranked.append((score, sid))
        if not ranked:
            return None
        ranked.sort(reverse=True)
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.03:
            return None
        return ranked[0][1]

    def _main_files(self, series: str) -> list[str]:
        ns = norm(series)
        exact = self.series_paths.get(ns) or []
        if exact:
            return exact
        ranked: list[tuple[float, str]] = []
        for key, paths in self.series_paths.items():
            score = SequenceMatcher(None, ns, key).ratio()
            if ns and (ns in key or key in ns):
                score = max(score, 0.92)
            if score >= 0.90:
                ranked.extend((score, p) for p in paths)
        if not ranked:
            return []
        ranked.sort(reverse=True)
        best = ranked[0][0]
        return [p for score, p in ranked if best - score < 0.015]

    def current_candidates(self, series: str) -> list[Candidate]:
        sid = self._series_id(series)
        out: list[Candidate] = []
        for path in self._main_files(series):
            out.extend(parse_matrix_csv(git_bytes(self.main_repo, path), path, "main", sid))
        return out

    def _snapshot_rank(self, model_year: int) -> list[str]:
        # Prefer late in the model year. Early next-year snapshots often already
        # replaced that year with the newer generation (e.g. 2025 海鸥 wiping
        # 2024 rows from 202501+ archives). When the vault timeline has gaps
        # (e.g. no 2020/2021 archives), still allow later months so a surviving
        # year can be found before giving up.
        target = model_year * 12 + 11
        scored = []
        for month in self.vault_months:
            y, m = int(month[:4]), int(month[4:])
            ordinal = y * 12 + m
            if y < model_year:
                before_penalty = 220 + (model_year - y) * 80
            elif ordinal < target - 10:
                before_penalty = 20
            else:
                before_penalty = 0
            after_penalty = 0
            if y == model_year + 1 and m >= 7:
                after_penalty = 24 + m
            elif y > model_year + 1:
                after_penalty = (y - model_year) * 36 + m
            scored.append((abs(ordinal - target) + before_penalty + after_penalty, month))
        return [m for _, m in sorted(scored)]

    @staticmethod
    def _decompress_zstd(payload: bytes) -> bytes:
        import zstandard as zstd
        with zstd.ZstdDecompressor().stream_reader(io.BytesIO(payload)) as reader:
            return reader.read()

    @classmethod
    def decode_vault(cls, raw: bytes) -> bytes:
        payloads = [raw.strip()]
        try:
            payloads.insert(0, base64.b85decode(raw.strip()))
        except Exception:
            pass
        expanded: list[bytes] = []
        for payload in payloads:
            expanded.append(payload)
            try:
                expanded.append(zlib.decompress(payload))
            except Exception:
                pass
        for payload in list(expanded):
            if payload.startswith(b"\x28\xb5\x2f\xfd"):
                try:
                    expanded.append(cls._decompress_zstd(payload))
                except Exception:
                    pass
        for payload in expanded:
            try:
                with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*"):
                    return payload
            except tarfile.TarError:
                continue
        raise RuntimeError("unsupported AutoHome vault payload")

    def _vault_files(self, month: str) -> dict[str, bytes]:
        if month in self.vault_cache:
            return self.vault_cache[month]
        raw = git_bytes(self.vault_repo, f"vaults/{month}/data.vault")
        tar_bytes = self.decode_vault(raw)
        files: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile() or not member.name.endswith(".csv"):
                    continue
                fh = tf.extractfile(member)
                if fh is not None:
                    files[Path(member.name).name] = fh.read()
        self.vault_cache[month] = files
        return files

    def historical_candidates(self, series: str, model_year: int) -> list[Candidate]:
        sid = self._series_id(series)
        ns = norm(series)
        for month in self._snapshot_rank(model_year):
            files = self._vault_files(month)
            ranked: list[tuple[float, str]] = []
            for name in files:
                sname = series_from_filename(name)
                key = norm(sname)
                score = SequenceMatcher(None, ns, key).ratio()
                if ns == key:
                    score = 1.0
                elif ns and (ns in key or key in ns):
                    score = max(score, 0.92)
                if score >= 0.90:
                    ranked.append((score, name))
            if not ranked:
                continue
            ranked.sort(reverse=True)
            best_score = ranked[0][0]
            candidates: list[Candidate] = []
            for score, name in ranked:
                if best_score - score >= 0.015:
                    break
                candidates.extend(parse_matrix_csv(files[name], name, month, sid))
            if any(year_of(c.title) == model_year for c in candidates):
                return candidates
        return []

    def live_series_id(self, series: str) -> int | None:
        key = norm(series)
        if key in LIVE_SERIES_ALIASES:
            return LIVE_SERIES_ALIASES[key]
        return self._series_id(series)

    def live_year_candidates(self, series: str, model_year: int) -> list[Candidate]:
        """Same-year specs from the autohome.com.cn parameter catalog.

        Vault snapshots only keep the years on sale that month, so a 2016
        trim is often absent. The catalog is the same source as the config
        page; full parameter rows still come from the live config fetch.
        """
        sid = self.live_series_id(series)
        if not sid or not model_year:
            return []
        payload = _load_param_year(sid, model_year)
        result = payload.get("result") or {}
        title_ids: dict[str, int] = {}
        for group in result.get("titlelist") or []:
            for item in group.get("items") or []:
                name = str(item.get("itemname") or "")
                if name and item.get("titleid") is not None:
                    title_ids[name] = int(item["titleid"])

        def cell(spec: dict, *names: str) -> str:
            wanted = {title_ids[name] for name in names if name in title_ids}
            if not wanted:
                return ""
            for row in spec.get("paramconflist") or []:
                if int(row.get("titleid") or 0) not in wanted:
                    continue
                if row.get("itemname"):
                    return str(row["itemname"])
                parts = [str(sub.get("name")) for sub in (row.get("sublist") or []) if sub.get("name")]
                return " ".join(parts)
            return ""

        out: list[Candidate] = []
        for spec in result.get("datalist") or []:
            try:
                spec_id = int(spec.get("specid"))
            except (TypeError, ValueError):
                continue
            title = cell(spec, "车型名称") or str(spec.get("specname") or "").strip()
            if not title:
                continue
            if "款" not in title:
                specname = str(spec.get("specname") or "").strip()
                title = f"{series} {specname}".strip()
            rows = {
                "车型名称": title,
                "发动机": cell(spec, "发动机"),
                "变速箱": cell(spec, "变速箱"),
                "轴距(mm)": cell(spec, "轴距(mm)", "轴距"),
                "驱动方式": cell(spec, "驱动方式"),
                "排量(mL)": cell(spec, "排量(mL)"),
            }
            rows = {k: v for k, v in rows.items() if v}
            out.append(
                Candidate(
                    spec_id,
                    title,
                    rows,
                    f"autohome:param:{sid}:{model_year}",
                    f"param:{sid}:{model_year}",
                    sid,
                )
            )
        return out


def _load_param_year(series_id: int, model_year: int) -> dict[str, Any]:
    PARAM_CACHE.mkdir(parents=True, exist_ok=True)
    path = PARAM_CACHE / f"{series_id}-{model_year}.json"
    if path.exists() and path.stat().st_size > 80:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    url = (
        "https://car-web-api.autohome.com.cn/car/param/getParamConf"
        f"?mode=1&site=1&seriesid={series_id}&year={model_year}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        raw = resp.read()
    path.write_bytes(raw)
    time.sleep(0.12)
    return json.loads(raw)


def _dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    best: dict[int, Candidate] = {}
    for cand in candidates:
        old = best.get(cand.spec_id)
        if old is None or len(cand.rows) > len(old.rows):
            best[cand.spec_id] = cand
    return list(best.values())


def _listing_wheelbase(item: dict[str, Any]) -> int | None:
    specs = item.get("specs") or item.get("detailed_config") or {}
    try:
        value = int(specs.get("wheelbase_mm") or 0)
    except (TypeError, ValueError):
        return None
    if 2000 <= value <= 4000:
        return value
    return None


def _candidate_source_kind(chosen: Candidate, main_pool: list[Candidate], hist_pool: list[Candidate]) -> str:
    if any(c.spec_id == chosen.spec_id and c.snapshot == "main" for c in main_pool):
        return "main"
    if any(c.spec_id == chosen.spec_id and not str(c.snapshot).startswith("param") for c in hist_pool):
        return "historical"
    return "live_catalog"


def choose_exact(title: str, series: str, candidates: list[Candidate]) -> tuple[Candidate | None, float, str]:
    target_year = year_of(title)
    if target_year is None:
        return None, 0.0, "listing_model_year_missing"
    same_year = [c for c in candidates if year_of(c.title) == target_year]
    if not same_year:
        return None, 0.0, "model_year_not_found"
    ranked = sorted(
        ((title_score(title, c.title, series), c) for c in same_year),
        key=lambda x: x[0],
        reverse=True,
    )
    best_score, best = ranked[0]
    if best_score < MIN_MATCH:
        return None, best_score, "exact_trim_similarity_below_threshold"
    if len(ranked) > 1 and best_score - ranked[1][0] < MIN_GAP:
        return None, best_score, "ambiguous_exact_trim_match"
    return best, best_score, ""


def build_autohome_trim(candidate: Candidate, score: float) -> tuple[str, dict[str, Any]]:
    sid = candidate.series_id or 0
    trim = base.build_trim(candidate.title, candidate.spec_id, sid, candidate.rows, score)
    leaf_n = int((trim.get("data_quality") or {}).get("verified_non_null_feature_leaf_count") or 0)
    trim_id = "trim_ah_" + hashlib.sha1(str(candidate.spec_id).encode()).hexdigest()[:12]
    trim["trim_id"] = trim_id
    trim["canonical_title"] = candidate.title
    dq = trim.setdefault("data_quality", {})
    dq["identity_source"] = "autohome_exact_trim"
    dq["series_match"] = 1.0
    dq["trim_match"] = round(score, 3)
    dq["source_snapshot"] = candidate.snapshot
    dq["known_issues"] = [] if leaf_n >= 25 else ["汽车之家该车型可核验配置字段较少"]
    live = str(candidate.snapshot).startswith("live") or str(candidate.source_path).startswith("live:")
    sources = [
        {
            "url": f"https://car.autohome.com.cn/config/spec/{candidate.spec_id}.html",
            "source_type": "autohome_live_config" if live else "autohome_exact_trim",
            "authority_tier": 1 if live else 2,
            "series_id": candidate.series_id,
            "spec_id": candidate.spec_id,
            "parameter_source": "live_page" if live else "vault_or_main_csv",
        }
    ]
    if not live:
        sources.append(
            {
                "url": "https://github.com/swoiow/autohome",
                "source_type": "autohome_parameter_dataset",
                "authority_tier": 2,
                "snapshot": candidate.snapshot,
                "source_path": candidate.source_path,
            }
        )
    else:
        sources.append(
            {
                "url": "https://github.com/swoiow/autohome",
                "source_type": "autohome_parameter_dataset",
                "authority_tier": 3,
                "snapshot": "identity_match_only",
                "source_path": candidate.source_path,
                "note": "vault/main used for exact-trim identity; parameters from live page",
            }
        )
    trim["sources"] = sources
    return trim_id, trim


def enrich_candidates_from_live(
    matched: list[tuple[Any, Candidate, float, str]],
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """Prefer live config-page rows for every matched spec_id.

    Identity still comes from vault/main exact-trim matching. When a live fetch
    fails, the original vault/main rows are kept unchanged (nulls stay null).
    """
    stats = {"enabled": enabled, "attempted": 0, "enriched": 0, "failed": 0, "skipped": 0}
    if not enabled or not matched:
        stats["skipped"] = len(matched)
        return stats
    try:
        import autohome_live_config as live
    except Exception as exc:
        print(f"live config module unavailable: {exc}")
        stats["failed"] = len(matched)
        return stats

    spec_ids = sorted({c.spec_id for _, c, _, _ in matched})
    stats["attempted"] = len(spec_ids)
    try:
        fetched = live.fetch_specs(spec_ids)
    except Exception as exc:
        print(f"live config fetch failed, keeping vault rows: {type(exc).__name__}: {exc}")
        stats["failed"] = len(spec_ids)
        return stats

    enriched_ids: set[int] = set()
    for idx, (item_meta, candidate, score, source_kind) in enumerate(matched):
        rows = live.rows_for_spec(candidate.spec_id, fetched)
        if not rows:
            continue
        merged = live.merge_prefer_live(candidate.rows, rows)
        try:
            import autohome_exact_rules as _rules
            merged = _rules.canonicalize_rows(merged)
        except Exception:
            pass
        matched[idx] = (item_meta, live.apply_live_rows(candidate, merged), score, source_kind)
        enriched_ids.add(candidate.spec_id)
    stats["enriched"] = len(enriched_ids)
    stats["failed"] = stats["attempted"] - stats["enriched"]
    print(
        f"live config enrichment: specs={stats['attempted']} "
        f"enriched={stats['enriched']} failed={stats['failed']}"
    )
    return stats


def sync_listings(
    listings: list[dict[str, Any]],
    *,
    live: bool | None = None,
    persist: bool = True,
    write_report: bool = True,
    source_label: str = "listings",
) -> dict[str, Any]:
    """Match listings missing from sku_to_trim. Does not reset the store.

    persist=False returns new trims in memory and leaves the index untouched.
    """
    index = json.loads(base.INDEX.read_text(encoding="utf-8"))
    existing_map = {str(k): str(v) for k, v in (index.get("sku_to_trim") or {}).items()}
    auto: dict[str, Any] = {"schema_version": "3.0-exact-trim", "trims": {}}
    if base.AUTO_SHARD.exists():
        try:
            auto["trims"].update(json.loads(base.AUTO_SHARD.read_text(encoding="utf-8")).get("trims") or {})
        except Exception:
            pass

    source = AutoHomeSource(AUTOHOME_MAIN, AUTOHOME_VAULTS)
    report_rows: list[dict[str, Any]] = []
    matched = skipped = failed = 0
    source_counts = {"main": 0, "historical": 0, "live_catalog": 0, "live_enriched": 0}
    current_cache: dict[str, list[Candidate]] = {}
    history_cache: dict[tuple[str, int], list[Candidate]] = {}
    pending: list[tuple[dict[str, Any], Candidate, float, str]] = []
    newly_verified: dict[str, dict[str, Any]] = {}
    if live is None:
        live_enabled = os.environ.get("AUTOHOME_LIVE_CONFIG", "1") not in ("0", "false", "False")
    else:
        live_enabled = bool(live)

    # Phase 1: exact-trim identity match against vault/main only.
    for idx, item in enumerate(listings, 1):
        sku = str(item.get("sku") or "")
        title = str(item.get("title") or "")
        if not sku or not title:
            continue
        if sku in existing_map:
            skipped += 1
            continue
        series = str(item.get("series") or base.series_key(title))
        model_year = int(item.get("model_year") or year_of(title) or 0)
        row: dict[str, Any] = {
            "sku": sku,
            "title": title,
            "series": series,
            "model_year": model_year or None,
            "status": "unmatched",
        }
        try:
            if series not in current_cache:
                current_cache[series] = source.current_candidates(series)
            candidate, score, reason = choose_exact(title, series, current_cache[series])
            source_kind = "main"
            if candidate is None and model_year:
                key = (series, model_year)
                if key not in history_cache:
                    history_cache[key] = source.historical_candidates(series, model_year)
                hc, hs, hr = choose_exact(title, series, history_cache[key])
                if hc is not None:
                    candidate, score, reason = hc, hs, ""
                    source_kind = "historical"
                elif reason in ("model_year_not_found", "exact_trim_similarity_below_threshold"):
                    reason = hr or reason

            if candidate is None and model_year:
                import autohome_exact_rules as rules

                listing_wb = _listing_wheelbase(item)
                try:
                    live = source.live_year_candidates(series, model_year)
                except Exception as exc:
                    live = []
                    print(f"param catalog {series} {model_year} skipped: {type(exc).__name__}: {exc}")
                pool = _dedupe_candidates(
                    [c for c in current_cache[series] if year_of(c.title) == model_year]
                    + [c for c in history_cache.get((series, model_year), []) if year_of(c.title) == model_year]
                    + live
                )
                fc, fr, basis = rules.identity_choose(title, series, pool, listing_wb)
                if fc is not None:
                    candidate, score, reason = fc, title_score(title, fc.title, series), ""
                    source_kind = _candidate_source_kind(fc, current_cache[series], history_cache.get((series, model_year), []))
                    row["match_basis"] = basis
                    row["identity_link"] = True
                elif fr:
                    reason = fr

            if candidate is None:
                row.update({"reason": reason or "exact_trim_match_not_found", "trim_match": round(score, 3)})
                failed += 1
                report_rows.append(row)
                print(f"[{idx}/{len(listings)}] unmatched {title} {row['reason']}")
                continue

            pending.append((row, candidate, score, source_kind))
            print(f"[{idx}/{len(listings)}] identity  {title} spec={candidate.spec_id} via {source_kind}")
        except Exception as exc:
            failed += 1
            row["reason"] = f"sync_error:{type(exc).__name__}:{exc}"
            report_rows.append(row)
            print(f"[{idx}/{len(listings)}] unmatched {title} {row['reason']}")

    # Phase 2: prefer live config-page parameters for every matched spec_id.
    live_stats = enrich_candidates_from_live(pending, enabled=live_enabled)
    source_counts["live_enriched"] = int(live_stats.get("enriched") or 0)

    # Phase 3: coverage gate + trim build after live merge.
    for row, candidate, score, source_kind in pending:
        try:
            leaf_probe = base.build_trim(
                candidate.title,
                candidate.spec_id,
                candidate.series_id or 0,
                candidate.rows,
                score,
            )
            leaf_n = int((leaf_probe.get("data_quality") or {}).get("verified_non_null_feature_leaf_count") or 0)
            if len(candidate.rows) < 20 or leaf_n < MIN_FEATURES:
                row.update(
                    {
                        "reason": f"verified_feature_fields_insufficient:{leaf_n}",
                        "matched_trim": candidate.title,
                        "trim_match": round(score, 3),
                        "config_rows": len(candidate.rows),
                        "spec_id": candidate.spec_id,
                        "snapshot": candidate.snapshot,
                    }
                )
                failed += 1
                report_rows.append(row)
                print(f"build-skip {row['title']} {row['reason']}")
                continue

            trim_id, trim = build_autohome_trim(candidate, score)
            trim["trim_id"] = trim_id
            auto["trims"][trim_id] = trim
            existing_map[row["sku"]] = trim_id
            newly_verified[str(row["sku"])] = {
                "listing": {"sku": str(row["sku"]), "trim_id": trim_id},
                "trim": trim,
            }
            matched += 1
            source_counts[source_kind] = source_counts.get(source_kind, 0) + 1
            row.update(
                {
                    "status": "matched",
                    "trim_id": trim_id,
                    "matched_trim": candidate.title,
                    "trim_match": round(score, 3),
                    "spec_id": candidate.spec_id,
                    "series_id": candidate.series_id,
                    "source": f"autohome_{source_kind}",
                    "snapshot": candidate.snapshot,
                    "config_rows": len(candidate.rows),
                    "verified_feature_fields": leaf_n,
                    "live_enriched": str(candidate.snapshot).startswith("live"),
                }
            )
            report_rows.append(row)
            print(f"matched   {row['title']} rows={len(candidate.rows)} leaf={leaf_n} snap={candidate.snapshot}")
        except Exception as exc:
            failed += 1
            row["reason"] = f"sync_error:{type(exc).__name__}:{exc}"
            report_rows.append(row)
            print(f"build-fail {row.get('title')} {row['reason']}")

    rel_auto = "specs/exact-trims-auto.json"
    trim_files = list(index.get("trim_files") or [])
    if rel_auto not in trim_files:
        trim_files.append(rel_auto)
    index["trim_files"] = trim_files
    index["sku_to_trim"] = dict(sorted(existing_map.items()))
    index["generated_at"] = time.strftime("%Y-%m-%d")
    index["configuration_policy"] = (
        "exact-trim-only; AutoHome live config page preferred for parameters; "
        "vault/main CSV for identity only; no legacy/approximate fallback"
    )
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": source_label,
        "strategy": (
            "existing V3 -> AutoHome main/vault exact-trim identity -> "
            "live config page parameters -> unverified"
        ),
        "total_listings": len(listings),
        "existing_or_skipped": skipped,
        "newly_matched": matched,
        "unmatched": failed,
        "source_counts": source_counts,
        "live_enrichment": live_stats,
        "exact_match_threshold": MIN_MATCH,
        "ambiguity_gap": MIN_GAP,
        "rows": report_rows,
    }
    if persist:
        base.dump(base.AUTO_SHARD, auto)
        base.dump(base.INDEX, index)
        if write_report:
            base.dump(base.REPORT, report)
    print(
        f"AutoHome exact sync complete: total={len(listings)} existing={skipped} "
        f"matched={matched} unmatched={failed} main={source_counts['main']} "
        f"historical={source_counts['historical']} live_catalog={source_counts.get('live_catalog', 0)} "
        f"live={source_counts['live_enriched']} persist={persist}"
    )
    return {
        "verified": newly_verified,
        "matched": matched,
        "failed": failed,
        "skipped": skipped,
        "report": report,
    }


def commit_verified(verified_by_sku: dict[str, dict[str, Any]]) -> int:
    """Merge already-built trims into the on-disk index. Does not reset it."""
    if not verified_by_sku:
        return 0
    index = json.loads(base.INDEX.read_text(encoding="utf-8"))
    auto: dict[str, Any] = {"schema_version": "3.0-exact-trim", "trims": {}}
    if base.AUTO_SHARD.exists():
        auto.update(json.loads(base.AUTO_SHARD.read_text(encoding="utf-8")))
        auto.setdefault("trims", {})
    mapping = {str(k): str(v) for k, v in (index.get("sku_to_trim") or {}).items()}
    written = 0
    for sku, record in verified_by_sku.items():
        trim = dict((record or {}).get("trim") or {})
        trim_id = str(trim.get("trim_id") or (record.get("listing") or {}).get("trim_id") or "")
        if not trim_id:
            continue
        trim["trim_id"] = trim_id
        auto["trims"][trim_id] = trim
        mapping[str(sku)] = trim_id
        written += 1
    index["sku_to_trim"] = dict(sorted(mapping.items()))
    index["generated_at"] = time.strftime("%Y-%m-%d")
    base.dump(base.AUTO_SHARD, auto)
    base.dump(base.INDEX, index)
    return written


def main() -> None:
    src = next((p for p in base.SOURCE_CANDIDATES if p.exists()), None)
    if src is None:
        raise SystemExit("no filtered listing source")
    listings = json.loads(src.read_text(encoding="utf-8"))
    sync_listings(
        listings,
        persist=True,
        write_report=True,
        source_label=str(src.relative_to(ROOT)),
    )


if __name__ == "__main__":
    main()
