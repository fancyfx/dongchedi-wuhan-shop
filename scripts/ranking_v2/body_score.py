from __future__ import annotations

from typing import Any


def body_preference_score(specs: dict[str, Any] | None, is_suv_fallback: bool = False) -> float:
    specs = specs or {}
    bt = str(specs.get("body_type") or "")
    bt_u = bt.upper()

    if "微型" in bt or "小型两厢" in bt:
        return 30.0
    if "中型SUV" in bt or "紧凑型SUV" in bt or "中大型SUV" in bt:
        return 100.0
    if "小型SUV" in bt:
        return 85.0
    if "SUV" in bt_u:
        return 100.0
    if "MPV" in bt_u:
        return 90.0
    if "旅行" in bt:
        return 75.0
    if "掀背" in bt or "两厢" in bt:
        return 55.0
    if "轿" in bt or "SEDAN" in bt_u:
        return 40.0
    if is_suv_fallback:
        return 100.0
    return 40.0
