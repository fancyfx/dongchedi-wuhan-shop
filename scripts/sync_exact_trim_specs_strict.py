#!/usr/bin/env python3
"""Strict exact-trim sync entrypoint.

The first sync version recursively accepted any object carrying a series_id,
which let article/content search results contaminate series matching. Dongchedi's
current search response marks real vehicle-series cards with cell_type=5002.
This wrapper narrows candidate extraction to those cards and then delegates the
rest of the conservative exact-trim pipeline to sync_exact_trim_specs.py.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

import sync_exact_trim_specs as base


def _explicit_series_pair(node: dict[str, Any]) -> tuple[int, str] | None:
    """Return only an explicit series id/name pair, never generic title/name."""
    sid = node.get("series_id")
    if sid in (None, ""):
        sid = node.get("seriesId")
    name = node.get("series_name")
    if name in (None, ""):
        name = node.get("seriesName")

    # Some card payloads put the entity under info/data/series. We still require
    # explicit series_* fields inside that child; generic title/name is rejected.
    if sid in (None, "") or name in (None, ""):
        for key in ("info", "data", "series", "series_info"):
            child = node.get(key)
            if not isinstance(child, dict):
                continue
            pair = _explicit_series_pair(child)
            if pair:
                return pair
        return None

    try:
        sid_i = int(sid)
    except (TypeError, ValueError):
        return None
    name_s = base.scalar_text(name).strip()
    if sid_i <= 0 or not name_s:
        return None
    return sid_i, name_s


def strict_best_series(query: str) -> tuple[int | None, str, float]:
    raw = base.request_json(
        "/motor/searchapi/search_content",
        {"keyword": query, "cur_tab": 2, "offset": 0, "count": 20},
    )
    candidates: dict[int, str] = {}

    # Current public search API: real series cards use cell_type=5002.
    for node in base.walk(raw.get("data", raw)):
        if str(node.get("cell_type", "")) != "5002":
            continue
        pair = _explicit_series_pair(node)
        if pair:
            sid, name = pair
            candidates[sid] = name
            continue
        # The explicit pair can be nested more deeply inside the 5002 card.
        for child in base.walk(node):
            pair = _explicit_series_pair(child)
            if pair:
                sid, name = pair
                candidates[sid] = name

    nq = base.norm(query)
    ranked: list[tuple[float, int, str]] = []
    for sid, name in candidates.items():
        nn = base.norm(name)
        ratio = SequenceMatcher(None, nq, nn).ratio()
        if nq == nn:
            ratio = 1.0
        elif nq and (nq in nn or nn in nq):
            ratio = max(ratio, 0.92)
        ranked.append((ratio, sid, name))

    if not ranked:
        return None, "", 0.0
    ratio, sid, name = max(ranked)
    return sid, name, ratio


def strict_car_candidates(series_id: int) -> list[tuple[int, str]]:
    raw = base.request_json(
        "/motor/pc/car/series/car_list",
        {"series_id": series_id, "city_name": "武汉"},
    )
    out: dict[int, str] = {}
    data = raw.get("data") or {}

    # The documented payload is data.tab_list[]. Entries with real car_id are
    # accepted; type 1068 placeholder rows are explicitly ignored.
    for node in base.walk(data.get("tab_list", data)):
        if str(node.get("type", "")) == "1068":
            continue
        cid = node.get("car_id")
        if cid in (None, ""):
            cid = node.get("carId")
        if cid in (None, ""):
            continue
        try:
            cid_i = int(cid)
        except (TypeError, ValueError):
            continue
        if cid_i <= 0:
            continue
        name = base.scalar_text(
            node.get("car_name")
            or node.get("carName")
            or node.get("name")
            or node.get("title")
        ).strip()
        if name:
            out[cid_i] = name
    return list(out.items())


base.best_series = strict_best_series
base.car_candidates = strict_car_candidates

if __name__ == "__main__":
    base.main()
