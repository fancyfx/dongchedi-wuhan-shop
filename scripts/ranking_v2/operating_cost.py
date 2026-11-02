from __future__ import annotations

from typing import Any

from .anchors import interpolate
from .config import ENERGY_COST_POINTS
from .energy import energy_cost_yuan_100km


def operating_cost_score(specs: dict[str, Any] | None, cfg=None, scenario=None) -> dict[str, Any]:
    info = energy_cost_yuan_100km(specs or {}, cfg=cfg, scenario=scenario)
    cost = info.get("energy_cost_yuan_100km")
    conf = float(info.get("confidence") or 0.0)
    if cost is None or conf <= 0:
        return {
            **info,
            "operating_cost_score": 50.0,  # neutral shrink
            "operating_cost_raw": 50.0,
            "note": "能源成本未知，使用成本分收缩到中性50",
        }
    raw = interpolate(float(cost), ENERGY_COST_POINTS)
    # low-confidence energy (legacy/official guess) shrinks toward neutral 50
    score = 50.0 + conf * (raw - 50.0)
    return {
        **info,
        "operating_cost_score": round(score, 2),
        "operating_cost_raw": round(raw, 2),
    }
