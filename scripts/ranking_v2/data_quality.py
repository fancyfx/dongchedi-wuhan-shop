from __future__ import annotations

from typing import Any

from .config_score import config_score
from .energy import resolve_ranking_energy


MIN_CONFIG_COVERAGE = 0.60
REQUIRED_SPACE_FIELDS = ("length_mm", "width_mm", "wheelbase_mm", "body_type")


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


def _issue(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "message": message, "severity": "blocking"}
    if field:
        out["field"] = field
    return out


def assess_score_eligibility(item: dict[str, Any]) -> dict[str, Any]:
    """Hard gate before ranking.

    Missing detailed configuration is not represented by a neutral score. A
    listing either has enough exact-trim evidence for every major scoring axis
    or it is routed to data-issues.json with no score/rank.
    """
    specs = item.get("specs") or item.get("detailed_config") or {}
    issues: list[dict[str, Any]] = []

    exact_verified = (
        specs.get("match_level") == "exact_trim"
        and specs.get("verified") is True
        and specs.get("specs_found") is True
        and specs.get("configuration_source") == "exact_trim_v3"
    )
    if not exact_verified:
        cfg = {"coverage": 0.0}
        issues.append(_issue("detailed_config_insufficient", "详细配置数据不足", "specs"))
    else:
        cfg = config_score(specs)
        coverage = float(cfg.get("coverage") or 0.0)
        if coverage < MIN_CONFIG_COVERAGE:
            issues.append(
                _issue(
                    "detailed_config_insufficient",
                    f"详细配置数据不足（核验覆盖率 {coverage:.0%}，要求至少 {MIN_CONFIG_COVERAGE:.0%}）",
                    "specs.features",
                )
            )

    for field in REQUIRED_SPACE_FIELDS:
        if specs.get(field) in (None, ""):
            issues.append(_issue("space_data_insufficient", f"空间数据不足：缺少 {field}", field))
            break

    price = item.get("effective_price_wan", item.get("price"))
    try:
        if price is None or float(price) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        issues.append(_issue("price_data_invalid", "价格数据缺失或无效", "price"))

    mileage = item.get("mileage_wan")
    try:
        if mileage is None or float(mileage) < 0:
            raise ValueError
    except (TypeError, ValueError):
        issues.append(_issue("mileage_data_invalid", "里程数据缺失或无效", "mileage_wan"))

    if not (item.get("plate_date") or item.get("plate_year") or item.get("model_year")):
        issues.append(_issue("age_data_insufficient", "车龄数据不足", "plate_year"))

    energy = resolve_ranking_energy(specs)
    if energy.get("value") is None or float(energy.get("confidence") or 0.0) <= 0:
        issues.append(_issue("energy_data_insufficient", "能耗数据不足，无法可靠计算使用成本", "ranking_energy"))

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in issues:
        code = str(issue["code"])
        if code in seen:
            continue
        seen.add(code)
        deduped.append(issue)

    return {
        "eligible": not deduped,
        "issues": deduped,
        "config_coverage": float(cfg.get("coverage") or 0.0),
        "energy_confidence": float(energy.get("confidence") or 0.0),
    }
