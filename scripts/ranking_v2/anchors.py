"""Fixed-anchor piecewise linear interpolation helpers."""
from __future__ import annotations


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def interpolate(x: float, points: list[tuple[float, float]]) -> float:
    """Piecewise linear interpolation; clamp outside range to endpoint scores."""
    if not points:
        return 50.0
    pts = sorted(points, key=lambda p: p[0])
    if x <= pts[0][0]:
        return float(pts[0][1])
    if x >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return float(y0)
            t = (x - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return float(pts[-1][1])
