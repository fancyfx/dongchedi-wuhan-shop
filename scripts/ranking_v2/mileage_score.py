from __future__ import annotations

from .anchors import interpolate
from .config import MILEAGE_POINTS


def mileage_score(mileage_wan_km: float | None) -> float:
    if mileage_wan_km is None:
        return 50.0
    if mileage_wan_km > 10:
        return 0.0
    return round(interpolate(float(mileage_wan_km), MILEAGE_POINTS), 2)
