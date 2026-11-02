"""Effective price + fixed-anchor price score."""
from __future__ import annotations

from .anchors import clamp
from .config import BUDGET


def price_score(effective_price_wan: float, budget: dict | None = None) -> float:
    budget = budget or BUDGET
    hard_max = float(budget["hard_max_wan"])
    full_at = float(budget["full_price_score_wan"])
    # 3万=100, 6万=0  => (6 - p) / 3 * 100
    span = hard_max - full_at
    if span <= 0:
        return 50.0
    return round(clamp((hard_max - float(effective_price_wan)) / span * 100.0), 2)
