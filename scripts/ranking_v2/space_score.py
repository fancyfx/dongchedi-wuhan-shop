from __future__ import annotations

from typing import Any

from .anchors import interpolate
from .config import LENGTH_POINTS, SPACE_WEIGHTS, TRUNK_POINTS, WHEELBASE_POINTS, WIDTH_POINTS


def space_score(specs: dict[str, Any] | None) -> dict[str, Any]:
    specs = specs or {}
    wb = specs.get("wheelbase_mm")
    width = specs.get("width_mm")
    length = specs.get("length_mm")
    trunk = specs.get("trunk_l") or specs.get("trunk_volume_l")

    parts = {}
    conf_bits = []

    if wb is not None:
        parts["wheelbase"] = interpolate(float(wb), WHEELBASE_POINTS)
        conf_bits.append(1.0)
    else:
        parts["wheelbase"] = 50.0
        conf_bits.append(0.0)

    if width is not None:
        parts["width"] = interpolate(float(width), WIDTH_POINTS)
        conf_bits.append(1.0)
    else:
        parts["width"] = 50.0
        conf_bits.append(0.0)

    if length is not None:
        parts["length"] = interpolate(float(length), LENGTH_POINTS)
        conf_bits.append(1.0)
    else:
        parts["length"] = 50.0
        conf_bits.append(0.0)

    if trunk is not None:
        parts["trunk"] = interpolate(float(trunk), TRUNK_POINTS)
        conf_bits.append(1.0)
    else:
        parts["trunk"] = 50.0  # missing trunk -> 50 per doc
        conf_bits.append(0.3)

    score = sum(parts[k] * SPACE_WEIGHTS[k] for k in SPACE_WEIGHTS)
    confidence = sum(conf_bits) / len(conf_bits) if conf_bits else 0.0
    return {
        "space_score": round(score, 2),
        "parts": {k: round(v, 2) for k, v in parts.items()},
        "confidence": round(confidence, 3),
        "trunk_missing": trunk is None,
    }
