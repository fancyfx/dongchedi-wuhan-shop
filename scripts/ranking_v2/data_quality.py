from __future__ import annotations

from typing import Any


def data_quality_score(specs: dict[str, Any] | None, energy_conf: float = 0.0) -> dict[str, Any]:
    specs = specs or {}
    ml = (specs.get("match_level") or "").lower()
    core_c = specs.get("core_confidence")
    feat_c = specs.get("feature_confidence")

    if specs.get("verified") and ml in ("exact", "exact_trim"):
        if energy_conf >= 0.95:
            base = 100.0
        elif energy_conf >= 0.6:
            base = 90.0
        else:
            base = 75.0
    elif ml in ("exact", "exact_trim"):
        base = 90.0 if energy_conf >= 0.6 else 75.0
    elif ml in ("same_powertrain_core",):
        base = 60.0
    elif ml in ("series_year_tier", "series_year"):
        base = 35.0
    elif ml in ("series_only",):
        base = 20.0
    elif specs.get("specs_found"):
        base = 40.0
    else:
        base = 0.0

    # blend mild adjustment from declared confidences
    if isinstance(core_c, (int, float)) and isinstance(feat_c, (int, float)):
        adj = (float(core_c) * 0.6 + float(feat_c) * 0.4) * 100
        base = 0.7 * base + 0.3 * adj

    return {
        "data_quality": round(max(0.0, min(100.0, base)), 2),
        "match_level": ml or "unknown",
        "core_confidence": core_c,
        "feature_confidence": feat_c,
        "energy_confidence": energy_conf,
    }
