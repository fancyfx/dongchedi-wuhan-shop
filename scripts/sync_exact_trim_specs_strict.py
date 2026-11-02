#!/usr/bin/env python3
"""Strict exact-trim sync with resilient Dongchedi identity/config discovery.

Resolution order for an unverified used-car listing:
1. Read the used-car SKU detail and accept a series_id + car_id only when the
   same payload node also matches the listing title strongly.
2. Resolve the series from search. Real series cards are preferred; a content
   association is allowed only when it explicitly carries series_id and the
   requested series name occurs in a short title.
3. Resolve the exact trim from car_list. If car_list is blocked/non-JSON, use
   get_full_config_info as the trim catalogue instead (the public endpoint
   currently returns the whole series even when car_ids is supplied).
4. Score only exact title matches with enough detailed config fields. Anything
   uncertain remains unmapped and is routed to data-issues.json by rerank_v2.

No legacy series/year/tier configuration fallback is permitted.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import sync_exact_trim_specs as base

ROOT = Path(__file__).resolve().parents[1]
DCD = "https://www.dongchedi.com"
USED_DETAIL = "https://m.dcdapp.com/motor/ecom/sophon/guide/card/detail"
CITY = "武汉"
CITY_COOKIE = "%E6%AD%A6%E6%B1%89"
COMMON = {"aid": "1839", "app_name": "auto_web_pc", "version_code": "476"}
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)


def _json_get(url: str, *, referer: str, mobile: bool = False, retries: int = 2) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            headers = {
                "User-Agent": MOBILE_UA if mobile else DESKTOP_UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Referer": referer,
                "Cookie": f"city_name={CITY_COOKIE}",
            }
            req = Request(url, headers=headers)
            with urlopen(req, timeout=25) as resp:
                body = resp.read()
                text = body.decode("utf-8", errors="replace").strip()
                content_type = resp.headers.get("Content-Type", "")
                if not text or text[:1] not in ("{", "["):
                    prefix = re.sub(r"\s+", " ", text[:160])
                    raise RuntimeError(
                        f"non_json_response status={getattr(resp, 'status', '?')} "
                        f"content_type={content_type!r} body={prefix!r}"
                    )
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise RuntimeError(f"unexpected_json_root:{type(parsed).__name__}")
                return parsed
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}: {last}")


def request_json(path: str, params: dict[str, Any], retries: int = 2) -> dict[str, Any]:
    query = {**COMMON, **{k: v for k, v in params.items() if v is not None}}
    url = f"{DCD}{path}?{urlencode(query)}"
    sid = params.get("series_id")
    referer = f"{DCD}/auto/series/{sid}" if sid else f"{DCD}/"
    return _json_get(url, referer=referer, retries=retries)


def used_detail(item: dict[str, Any]) -> dict[str, Any]:
    params = {
        "sku_id": str(item.get("sku") or ""),
        "shop_id": str(item.get("shop_id") or "118608"),
    }
    return _json_get(
        f"{USED_DETAIL}?{urlencode(params)}",
        referer=str(item.get("detail_url") or "https://m.dcdapp.com/"),
        mobile=True,
        retries=1,
    )


def _int(value: Any) -> int | None:
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _pick(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = d.get(key)
        if value not in (None, ""):
            return value
    return None


def _node_name(d: dict[str, Any]) -> str:
    return base.scalar_text(
        _pick(
            d,
            (
                "car_name",
                "carName",
                "model_name",
                "modelName",
                "sku_name",
                "skuName",
                "vehicle_name",
                "vehicleName",
                "series_name",
                "seriesName",
                "title",
                "name",
            ),
        )
    ).strip()


def _year(text: str) -> str:
    m = re.search(r"(20\d{2})款", str(text or ""))
    return m.group(1) if m else ""


def title_similarity(target: str, candidate: str, *, series: str = "") -> float:
    if not target or not candidate:
        return 0.0
    tn = base.norm(target)
    cn = base.norm(candidate)
    target_trim = base.norm(base.trim_part(target, series)) if series else tn
    cand_trim = base.norm(base.trim_part(candidate, series)) if series else cn
    score = max(
        SequenceMatcher(None, tn, cn).ratio(),
        SequenceMatcher(None, target_trim, cand_trim).ratio(),
    )
    if tn == cn or (target_trim and target_trim == cand_trim):
        score = 1.0
    elif target_trim and (target_trim in cand_trim or cand_trim in target_trim):
        score = max(score, 0.93)
    ty, cy = _year(target), _year(candidate)
    if ty and cy and ty != cy:
        score -= 0.18
    return max(0.0, min(1.0, score))


def identity_from_used_detail(item: dict[str, Any]) -> tuple[int | None, int | None, str, float]:
    """Extract only same-node series_id + car_id pairs from the current SKU detail."""
    raw = used_detail(item)
    title = str(item.get("title") or "")
    series = str(item.get("series") or "")
    candidates: list[tuple[float, int, int, str]] = []
    nameless_pairs: set[tuple[int, int]] = set()

    for node in base.walk(raw.get("data", raw)):
        sid = _int(_pick(node, ("series_id", "seriesId")))
        cid = _int(_pick(node, ("car_id", "carId")))
        if not sid or not cid:
            continue
        name = _node_name(node)
        if name:
            score = title_similarity(title, name, series=series)
            candidates.append((score, sid, cid, name))
        else:
            nameless_pairs.add((sid, cid))

    if candidates:
        score, sid, cid, name = max(candidates)
        if score >= 0.80:
            return sid, cid, name, score
    if len(nameless_pairs) == 1:
        sid, cid = next(iter(nameless_pairs))
        return sid, cid, "", 0.72
    return None, None, "", 0.0


def _explicit_series_pair(node: dict[str, Any], *, trusted_card: bool = False) -> tuple[int, str] | None:
    sid = _int(_pick(node, ("series_id", "seriesId")))
    name = base.scalar_text(_pick(node, ("series_name", "seriesName"))).strip()
    if sid and name:
        return sid, name
    if trusted_card and sid:
        generic = base.scalar_text(_pick(node, ("name", "title"))).strip()
        if generic:
            return sid, generic
    return None


def best_series(query: str) -> tuple[int | None, str, float]:
    raw = request_json(
        "/motor/searchapi/search_content",
        {"keyword": query, "cur_tab": 2, "offset": 0, "count": 30},
    )
    nq = base.norm(query)
    ranked: list[tuple[float, int, str]] = []

    for node in base.walk(raw.get("data", raw)):
        if str(node.get("cell_type", "")) != "5002":
            continue
        for child in base.walk(node):
            pair = _explicit_series_pair(child, trusted_card=True)
            if not pair:
                continue
            sid, name = pair
            nn = base.norm(name)
            ratio = SequenceMatcher(None, nq, nn).ratio()
            if nq == nn:
                ratio = 1.0
            elif nq and (nq in nn or nn in nq):
                ratio = max(ratio, 0.94)
            ranked.append((ratio, sid, name))

    if not ranked:
        for node in base.walk(raw.get("data", raw)):
            sid = _int(_pick(node, ("series_id", "seriesId")))
            if not sid:
                continue
            name = _node_name(node)
            nn = base.norm(name)
            if not nn or not nq or nq not in nn:
                continue
            extra = max(0, len(nn) - len(nq))
            if extra > 12:
                continue
            ratio = SequenceMatcher(None, nq, nn).ratio()
            ratio = max(ratio, 0.80 if extra <= 8 else 0.76)
            ranked.append((ratio, sid, query))

    if not ranked:
        return None, "", 0.0
    ratio, sid, name = max(ranked)
    return sid, name, ratio


def car_candidates_from_car_list(series_id: int) -> list[tuple[int, str]]:
    raw = request_json(
        "/motor/pc/car/series/car_list",
        {"series_id": series_id, "city_name": CITY},
    )
    out: dict[int, str] = {}
    data = raw.get("data") or {}
    for node in base.walk(data.get("tab_list", data)):
        if str(node.get("type", "")) == "1068":
            continue
        cid = _int(_pick(node, ("car_id", "carId")))
        if not cid:
            continue
        name = base.scalar_text(_pick(node, ("car_name", "carName", "name", "title"))).strip()
        if name:
            out[cid] = name
    return list(out.items())


def config_catalog(series_id: int, car_id: int | None = None) -> tuple[dict[str, Any], list[tuple[int, str]]]:
    raw = request_json(
        "/motor/pc/car/get_full_config_info",
        {"series_id": series_id, "car_ids": car_id if car_id else ""},
    )
    out: dict[int, str] = {}
    data = raw.get("data") or {}
    for node in data.get("car_info") or []:
        if not isinstance(node, dict):
            continue
        cid = _int(_pick(node, ("car_id", "carId", "id")))
        if not cid:
            continue
        name = base.scalar_text(
            _pick(node, ("car_name", "carName", "name", "title", "car_series_name"))
        ).strip()
        if not name:
            info = node.get("info")
            if isinstance(info, dict):
                for key in ("car_name", "model_name", "车型名称", "name"):
                    name = base.scalar_text(info.get(key)).strip()
                    if name:
                        break
        if name:
            out[cid] = name
    return raw, list(out.items())


def choose_car(title: str, series: str, cars: list[tuple[int, str]]) -> tuple[int | None, str, float]:
    ranked: list[tuple[float, int, str]] = []
    for cid, name in cars:
        ranked.append((title_similarity(title, name, series=series), cid, name))
    if not ranked:
        return None, "", 0.0
    score, cid, name = max(ranked)
    return cid, name, score


def validate_and_store(
    *,
    title: str,
    sid: int,
    cid: int,
    cscore: float,
    raw_config: dict[str, Any],
    auto: dict[str, Any],
    existing_map: dict[str, str],
    sku: str,
    row: dict[str, Any],
) -> tuple[bool, str]:
    rows = base.config_rows(raw_config, cid)
    if len(rows) < 20:
        return False, f"detailed_config_rows_insufficient:{len(rows)}"
    trim = base.build_trim(title, cid, sid, rows, cscore)
    leaf_n = int((trim.get("data_quality") or {}).get("verified_non_null_feature_leaf_count") or 0)
    if leaf_n < 18:
        return False, f"verified_feature_fields_insufficient:{leaf_n}"

    trim_id = "trim_dcd_" + hashlib.sha1(f"{sid}:{cid}".encode()).hexdigest()[:12]
    trim["trim_id"] = trim_id
    dq = trim.setdefault("data_quality", {})
    dq["identity_source"] = row.get("identity_source")
    dq["series_match"] = row.get("series_match")
    dq["trim_match"] = round(cscore, 3)
    auto["trims"][trim_id] = trim
    existing_map[sku] = trim_id
    row.update(
        {
            "status": "matched",
            "trim_id": trim_id,
            "config_rows": len(rows),
            "verified_feature_fields": leaf_n,
        }
    )
    return True, ""


def main() -> None:
    src = next((p for p in base.SOURCE_CANDIDATES if p.exists()), None)
    if src is None:
        raise SystemExit("no filtered listing source")
    listings = json.loads(src.read_text(encoding="utf-8"))
    index = json.loads(base.INDEX.read_text(encoding="utf-8"))
    existing_map = {str(k): str(v) for k, v in (index.get("sku_to_trim") or {}).items()}
    auto: dict[str, Any] = {"schema_version": "3.0-exact-trim", "trims": {}}
    if base.AUTO_SHARD.exists():
        try:
            old = json.loads(base.AUTO_SHARD.read_text(encoding="utf-8"))
            auto["trims"].update(old.get("trims") or {})
        except Exception:
            pass

    report_rows: list[dict[str, Any]] = []
    series_cache: dict[str, tuple[int | None, str, float]] = {}
    car_cache: dict[int, tuple[list[tuple[int, str]], str | None]] = {}
    config_cache: dict[int, dict[str, Any]] = {}
    matched = skipped = failed = 0
    source_counts: dict[str, int] = {}

    for idx, item in enumerate(listings, 1):
        sku = str(item.get("sku") or "")
        title = str(item.get("title") or "")
        if not sku or not title:
            continue
        if sku in existing_map:
            skipped += 1
            continue

        series = str(item.get("series") or base.series_key(title))
        row: dict[str, Any] = {"sku": sku, "title": title, "series": series, "status": "unmatched"}
        try:
            sid: int | None = None
            cid: int | None = None
            cname = ""
            cscore = 0.0
            raw_config: dict[str, Any] | None = None

            try:
                dsid, dcid, dname, dscore = identity_from_used_detail(item)
                row["sku_detail_match"] = round(dscore, 3)
                if dsid and dcid and dscore >= 0.80:
                    sid, cid, cname, cscore = dsid, dcid, dname, dscore
                    row["identity_source"] = "usedcar_sku_detail"
            except Exception as exc:
                row["sku_detail_error"] = f"{type(exc).__name__}:{exc}"

            if not sid:
                if series not in series_cache:
                    series_cache[series] = best_series(series)
                    time.sleep(0.10)
                sid, sname, sscore = series_cache[series]
                row.update({"series_id": sid, "matched_series": sname, "series_match": round(sscore, 3)})
                if sid is None or sscore < 0.72:
                    row["reason"] = "series_exact_match_not_found"
                    failed += 1
                    report_rows.append(row)
                    continue
                row["identity_source"] = "series_search"
            else:
                row.update({"series_id": sid, "car_id": cid, "matched_trim": cname, "trim_match": round(cscore, 3)})

            if cid:
                try:
                    raw_config, _ = config_catalog(sid, cid)
                    rows = base.config_rows(raw_config, cid)
                    if len(rows) < 20:
                        cid = None
                        raw_config = None
                        row["sku_detail_id_rejected"] = "car_id_not_present_in_exact_config"
                except Exception as exc:
                    row["sku_detail_config_error"] = f"{type(exc).__name__}:{exc}"
                    cid = None
                    raw_config = None

            if not cid:
                if sid not in car_cache:
                    cars: list[tuple[int, str]] = []
                    car_error: str | None = None
                    try:
                        cars = car_candidates_from_car_list(sid)
                    except Exception as exc:
                        car_error = f"{type(exc).__name__}:{exc}"
                    car_cache[sid] = (cars, car_error)
                    time.sleep(0.10)
                cars, car_error = car_cache[sid]
                if car_error:
                    row["car_list_error"] = car_error

                if cars:
                    cid, cname, cscore = choose_car(title, series, cars)
                    row["trim_candidate_source"] = "car_list"

                if cid is None or cscore < 0.84:
                    if sid not in config_cache:
                        try:
                            config_cache[sid], config_cars = config_catalog(sid)
                            car_cache[sid] = (config_cars or cars, car_error)
                        except Exception as exc:
                            row["config_catalog_error"] = f"{type(exc).__name__}:{exc}"
                            config_cache[sid] = {}
                    raw_catalog = config_cache.get(sid) or {}
                    config_cars = car_cache[sid][0]
                    ccid, ccname, ccscore = choose_car(title, series, config_cars)
                    if ccid and ccscore > cscore:
                        cid, cname, cscore = ccid, ccname, ccscore
                        row["trim_candidate_source"] = "full_config_catalog"
                        raw_config = raw_catalog

                row.update({"car_id": cid, "matched_trim": cname, "trim_match": round(cscore, 3)})
                if cid is None or cscore < 0.84:
                    row["reason"] = "exact_trim_match_not_found"
                    failed += 1
                    report_rows.append(row)
                    continue

            if raw_config is None:
                if sid not in config_cache:
                    config_cache[sid], _ = config_catalog(sid, cid)
                    time.sleep(0.10)
                raw_config = config_cache[sid]

            ok, reason = validate_and_store(
                title=title,
                sid=sid,
                cid=cid,
                cscore=cscore,
                raw_config=raw_config,
                auto=auto,
                existing_map=existing_map,
                sku=sku,
                row=row,
            )
            if ok:
                matched += 1
                source = str(row.get("identity_source") or "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1
            else:
                row["reason"] = reason
                failed += 1
        except Exception as exc:
            row["reason"] = f"sync_error:{type(exc).__name__}:{exc}"
            failed += 1

        report_rows.append(row)
        print(f"[{idx}/{len(listings)}] {row['status']:9} {title} {row.get('reason', '')}")

    trim_files = list(index.get("trim_files") or [])
    rel_auto = "specs/exact-trims-auto.json"
    if rel_auto not in trim_files:
        trim_files.append(rel_auto)
    index["trim_files"] = trim_files
    index["sku_to_trim"] = dict(sorted(existing_map.items()))
    index["generated_at"] = time.strftime("%Y-%m-%d")
    index["configuration_policy"] = (
        "exact-trim-only; SKU-detail + Dongchedi public exact-trim sync; no approximate fallback"
    )

    base.dump(base.AUTO_SHARD, auto)
    base.dump(base.INDEX, index)
    base.dump(
        base.REPORT,
        {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": str(src.relative_to(ROOT)),
            "strategy": "sku_detail -> series_search -> car_list/full_config_catalog -> exact config",
            "total_listings": len(listings),
            "existing_verified_skipped": skipped,
            "new_exact_matches": matched,
            "unmatched_or_insufficient": failed,
            "new_match_sources": source_counts,
            "rows": report_rows,
        },
    )
    print(
        f"SYNC total={len(listings)} existing={skipped} new={matched} "
        f"insufficient={failed} sources={source_counts}"
    )


base.request_json = request_json

if __name__ == "__main__":
    main()
