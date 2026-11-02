from __future__ import annotations

from typing import Any


def condition_gate(item: dict[str, Any]) -> dict[str, Any]:
    """Hard gate: PASS / MANUAL_REVIEW / REJECT. Listing cards rarely have damage flags."""
    flags = []
    blob = " ".join(
        str(x)
        for x in [
            item.get("title"),
            item.get("evaluation"),
            " ".join(item.get("tags") or []),
            " ".join(item.get("badges") or []),
            item.get("extra"),
        ]
        if x
    )
    reject_kw = ("水泡", "火烧", "报废", "重大事故", "结构件受损")
    review_kw = ("调表", "营运", "网约车", "抵押", "查封", "事故")

    for k in reject_kw:
        if k in blob:
            return {"condition_gate": "REJECT", "flags": [k], "reason": f"命中硬排除关键词:{k}"}
    for k in review_kw:
        if k in blob:
            flags.append(k)

    specs = item.get("specs") or {}
    pt = (specs.get("powertrain") or specs.get("powertrain_type") or "").lower()
    if pt in ("phev", "bev", "纯电", "插混") and not specs.get("battery_soh"):
        # unknown battery health — soft review flag only if also other issues
        pass

    # mileage anomaly
    mile = item.get("mileage_wan")
    age_years = item.get("_age_years")
    warnings = []
    if mile is not None and age_years and age_years > 0:
        annual = (float(mile) * 10000) / max(float(age_years), 0.5)
        if annual < 3000:
            warnings.append("very_low_mileage_check")
            flags.append("very_low_mileage_check")
        elif annual > 30000:
            warnings.append("high_usage_check")
            flags.append("high_usage_check")

    if item.get("needs_cash_quote"):
        warnings.append("needs_cash_quote")

    gate = "MANUAL_REVIEW" if flags and any(f in review_kw for f in flags) else "PASS"
    return {
        "condition_gate": gate,
        "flags": flags,
        "warnings": warnings,
    }
