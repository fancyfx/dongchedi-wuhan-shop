from __future__ import annotations

from datetime import date

from .anchors import interpolate
from .config import AGE_POINTS_YEARS


def age_years_from_plate(
    plate_year: int | None,
    plate_date: str | None = None,
    today: date | None = None,
) -> tuple[float | None, float]:
    """Return (age_years, confidence). plate_date ISO preferred; else year mid-point."""
    today = today or date.today()
    if plate_date:
        try:
            y, m, d = (int(x) for x in plate_date[:10].split("-"))
            pd = date(y, m, d)
            months = (today.year - pd.year) * 12 + (today.month - pd.month)
            return max(0.0, months / 12.0), 0.95
        except Exception:
            pass
    if plate_year:
        # mid-year estimate: July 1
        pd = date(int(plate_year), 7, 1)
        months = (today.year - pd.year) * 12 + (today.month - pd.month)
        return max(0.0, months / 12.0), 0.7
    return None, 0.0


def age_score(age_years: float | None) -> float:
    if age_years is None:
        return 50.0
    if age_years > 10:
        return 0.0
    return round(interpolate(float(age_years), AGE_POINTS_YEARS), 2)
