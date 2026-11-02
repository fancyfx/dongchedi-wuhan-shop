#!/usr/bin/env python3
"""Fast/fail-safe entrypoint for the resilient exact-trim synchronizer.

Network routes that are blocked from GitHub-hosted runners are circuit-broken
after repeated failures so one external endpoint cannot consume the whole job.
"""
from __future__ import annotations

import json
import re
import time
from urllib.request import Request, urlopen

import sync_exact_trim_specs_resilient as impl


def fast_json_get(url: str, *, referer: str, mobile: bool = False, retries: int = 1) -> dict:
    timeout = 5.0 if mobile else 10.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            headers = {
                "User-Agent": impl.MOBILE_UA if mobile else impl.DESKTOP_UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Referer": referer,
                "Cookie": f"city_name={impl.CITY_COOKIE}",
            }
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace").strip()
                content_type = resp.headers.get("Content-Type", "")
                if not text or text[:1] not in ("{", "["):
                    prefix = re.sub(r"\s+", " ", text[:120])
                    raise RuntimeError(
                        f"non_json_response status={getattr(resp, 'status', '?')} "
                        f"content_type={content_type!r} body={prefix!r}"
                    )
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise RuntimeError(f"unexpected_json_root:{type(data).__name__}")
                return data
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(0.35 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}: {last}")


impl._json_get = fast_json_get

_original_used_detail = impl.used_detail
_sku_failures = 0
_sku_open = False


def used_detail_with_breaker(item: dict) -> dict:
    global _sku_failures, _sku_open
    if _sku_open:
        raise RuntimeError("sku_detail_circuit_open")
    try:
        result = _original_used_detail(item)
        _sku_failures = 0
        return result
    except Exception:
        _sku_failures += 1
        if _sku_failures >= 3:
            _sku_open = True
        raise


impl.used_detail = used_detail_with_breaker

_original_car_list = impl.car_candidates_from_car_list
_car_list_failures = 0
_car_list_open = False


def car_list_with_breaker(series_id: int):
    global _car_list_failures, _car_list_open
    if _car_list_open:
        return []
    try:
        result = _original_car_list(series_id)
        _car_list_failures = 0
        return result
    except Exception:
        _car_list_failures += 1
        if _car_list_failures >= 3:
            _car_list_open = True
        raise


impl.car_candidates_from_car_list = car_list_with_breaker

if __name__ == "__main__":
    impl.main()
