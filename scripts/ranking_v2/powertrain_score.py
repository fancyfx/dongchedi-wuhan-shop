"""V3 powertrain reliability, four iron-law vetoes, and buyer profile builder."""
from __future__ import annotations

import re
from typing import Any

LUXURY_HIGH_COST_BRANDS = (
    "奔驰", "宝马", "奥迪", "林肯", "凯迪拉克", "沃尔沃",
    "捷豹", "路虎", "英菲尼迪", "讴歌", "DS", "MINI", "Jeep", "自由侠",
)
DEFUNCT_OR_RARE_BRANDS = (
    "猎豹", "众泰", "力帆", "汉腾", "宝沃", "海马", "观致", "纳智捷", "雷诺", "卡缤", "铃木",
)
OLD_HIGH_RISK_MODELS = ("魏牌 VV5", "魏牌 VV6", "魏牌 VV7", "VV5", "VV6", "VV7")
HIDDEN_HANDLE_MODELS = ("逸达", "UNI-T", "UNI-V")
NISSAN_CVT_MODELS = ("轩逸", "逍客", "奇骏", "蓝鸟", "天籁", "骐达")
TOYOTA_CVT_MODELS = ("丰田", "奕泽", "C-HR", "卡罗拉", "雷凌", "致炫", "威驰", "凌尚")
MAINSTREAM_WET_DCT_MODELS = (
    "哈弗H6", "哈弗F7", "锐程", "长安CS75", "长安CS85", "星瑞", "博越", "瑞虎", "逸达", "UNI-",
)


def evaluate_veto(
    item: dict[str, Any],
    specs: dict[str, Any],
    live: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply the three hard elimination rules for holiday low-frequency drivers."""
    live = live or {}
    reasons: list[str] = []
    title = str(item.get("title") or "")
    energy = str(live.get("energy_type") or "")
    pt = str(specs.get("powertrain") or specs.get("powertrain_type") or "").lower()
    fuel_form = str(item.get("fuel_form") or "").strip().lower()

    if (
        any(k in energy for k in ("纯电动", "插电", "增程"))
        or pt in ("bev", "phev", "reev", "纯电", "插混", "增程")
        or fuel_form in ("4", "6", "bev", "phev", "reev")
    ):
        reasons.append("纯电/插混不适合长期静置（亏电与三电过保/高保费风险）")

    cylinders = live.get("cylinders")
    if cylinders is None:
        cylinders = specs.get("cylinders")
    engine_text = str(live.get("engine_text") or specs.get("engine") or "")
    if cylinders == 3 or "L3" in engine_text:
        reasons.append("三缸发动机（抖动与长期维保顾虑）")

    tt = str(live.get("transmission_type") or specs.get("transmission") or "")
    ts = str(live.get("transmission_short") or "")
    if "干式" in tt or "干式" in ts or "DQ200" in title.upper():
        reasons.append("干式双离合（久停粘连与拥堵过热风险）")

    return {"vetoed": bool(reasons), "reasons": reasons}


def score_powertrain_reliability(
    item: dict[str, Any],
    specs: dict[str, Any],
    live: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score mechanical durability and maintenance friendliness on a 0-100 scale."""
    live = live or {}
    title = str(item.get("title") or "")
    tt = str(live.get("transmission_type") or specs.get("transmission") or "")
    ts = str(live.get("transmission_short") or tt or "")
    intake = str(live.get("intake") or "")
    fuel_inj = str(live.get("fuel_injection") or "")
    fuel_grade = str(live.get("fuel_grade") or specs.get("fuel_grade") or "92")
    rear_susp = str(live.get("rear_suspension") or "")
    drive = str(live.get("drive_type") or "")
    engine_text = str(live.get("engine_text") or specs.get("engine") or "")
    notes: list[str] = []

    if "手自一体" in tt or "自动变速箱(AT)" in tt or re.search(r"\bAT\b", tt):
        gearbox_tier = "AT"
        if "4挡" in ts:
            score = 68.0
        elif any(g in ts for g in ("8挡", "9挡", "10挡")):
            score = 93.0
        else:
            score = 90.0
        gearbox_label = ts or "AT手自一体"
    elif "CVT" in tt or "无级" in tt:
        gearbox_tier = "CVT"
        if any(b in title for b in TOYOTA_CVT_MODELS):
            score = 88.0
            gearbox_label = "丰田CVT"
            notes.append("丰田系成熟CVT，带机械起步/高稳定性")
        elif any(b in title for b in NISSAN_CVT_MODELS):
            score = 65.0
            gearbox_label = "日产CVT"
            notes.append("日产系早期CVT需关注冷保护与钢带打滑检查")
        else:
            score = 82.0
            gearbox_label = "成熟CVT"
    elif "湿式" in tt or "湿式" in ts:
        gearbox_tier = "WET_DCT"
        score = 73.0 if any(b in title for b in MAINSTREAM_WET_DCT_MODELS) else 68.0
        gearbox_label = ts or "湿式双离合"
    elif "手动" in tt or "MT" in tt:
        gearbox_tier = "MT"
        score = 45.0
        gearbox_label = ts or "手动挡"
    elif "双离合" in tt or "DCT" in tt:
        gearbox_tier = "WET_DCT"
        score = 72.0
        gearbox_label = ts or "双离合"
    else:
        gearbox_tier = "OTHER"
        score = 65.0
        gearbox_label = ts or "自动"

    if "自然吸气" in intake:
        if "多点电喷" in fuel_inj or "混合喷射" in fuel_inj:
            score += 8.0
            notes.append(f"自然吸气+{fuel_inj}，积碳少且耐静置")
        else:
            score += 5.0
            notes.append("自然吸气四缸，结构简单好维护")
    elif "涡轮" in intake:
        score += 2.0

    if "95" in fuel_grade:
        score -= 3.0
        notes.append("需加注95号汽油")

    if "独立悬架" in rear_susp and "非独立" not in rear_susp:
        score += 3.0
    if "四驱" in drive:
        score += 3.0

    if any(b in title for b in LUXURY_HIGH_COST_BRANDS):
        score -= 28.0
        notes.append("豪华/进口品牌零整比与单次维保成本偏高")
    if any(b in title for b in DEFUNCT_OR_RARE_BRANDS):
        score -= 28.0
        notes.append("冷门或已退市品牌，后期配件供应与维修便利性差")
    if any(m in title for m in OLD_HIGH_RISK_MODELS):
        score -= 20.0
        notes.append("老平台停产车系，车质网反馈天窗排水管渗漏与烧机油投诉偏高")
    if any(m in title for m in HIDDEN_HANDLE_MODELS):
        score -= 5.0
        notes.append("隐藏式门把手在长期停放亏电时存在开启不便隐患")
    if any(m in title for m in ("领克03", "星瑞")) and "2.0T" in title:
        score -= 3.0
        notes.append("CMA架构静置暗电流偏大，建议常备搭电宝或断电开关")

    score = round(max(0.0, min(100.0, score)), 2)

    if any(b in title for b in LUXURY_HIGH_COST_BRANDS):
        maint = "约 800-1400 元/年"
    elif "95" in fuel_grade:
        maint = "约 550-750 元/年"
    elif "自然吸气" in intake:
        maint = "约 300-450 元/年"
    else:
        maint = "约 400-550 元/年"

    susp_short = "独立后悬" if ("独立悬架" in rear_susp and "非独立" not in rear_susp) else ("扭力梁后悬" if rear_susp else "")
    drive_short = "四驱" if "四驱" in drive else ("两驱" if drive else "")

    return {
        "powertrain_score": score,
        "gearbox_tier": gearbox_tier,
        "gearbox_label": gearbox_label,
        "engine_summary": engine_text or str(specs.get("engine") or ""),
        "intake": intake,
        "fuel_injection": fuel_inj,
        "fuel_grade": "95#" if "95" in fuel_grade else "92#",
        "rear_suspension": rear_susp,
        "rear_suspension_short": susp_short,
        "drive_type": drive,
        "drive_short": drive_short,
        "maintenance_estimate": maint,
        "notes": notes,
    }


def build_v3_profile(
    item: dict[str, Any],
    specs: dict[str, Any],
    live: dict[str, Any] | None,
    pt_info: dict[str, Any],
    scores: dict[str, float],
) -> dict[str, Any]:
    """Assemble structured buyer metadata for dashboard cards and inspection drawers."""
    live = live or {}
    feats = specs.get("features") or {}
    title = str(item.get("title") or "")
    eff_price = float(item.get("effective_price_wan") or item.get("price") or 0)
    msrp = live.get("msrp_wan") or specs.get("msrp_wan")
    discount_fold = round(eff_price / msrp * 10, 1) if (msrp and msrp > 0) else None
    saved_wan = round(msrp - eff_price, 2) if (msrp and msrp > eff_price) else None

    ab = feats.get("airbags") or 0
    knee = bool(live.get("knee_airbag"))
    has_l2 = bool(feats.get("acc")) and bool(feats.get("aeb")) and (
        bool(feats.get("lka")) or bool(feats.get("lane_centering"))
    )

    highlights: list[str] = []
    if ab >= 6:
        highlights.append(f"{int(ab) + (1 if knee else 0)}气囊" if knee else f"{int(ab)}气囊")
    if has_l2:
        highlights.append("L2辅助驾驶")
    else:
        if feats.get("acc"):
            highlights.append("全速ACC")
        if feats.get("aeb"):
            highlights.append("AEB主动刹车")
    if feats.get("camera_360"):
        highlights.append("360全景")
    elif live.get("has_reverse_camera"):
        highlights.append("倒车影像")
    if feats.get("seat_heating"):
        highlights.append("座椅加热")
    if feats.get("seat_ventilation"):
        highlights.append("座椅通风")
    if feats.get("carplay"):
        highlights.append("CarPlay")
    elif feats.get("phone_link"):
        highlights.append("手机互联")
    if feats.get("power_tailgate"):
        highlights.append("电动尾门")
    if feats.get("hud"):
        highlights.append("HUD抬显")
    if feats.get("power_driver_seat") and feats.get("power_passenger_seat"):
        highlights.append("双电动座椅")
    elif feats.get("power_driver_seat"):
        highlights.append("主驾电调")

    # Archetype badge for quick scanning
    mile = float(item.get("mileage_wan") if item.get("mileage_wan") is not None else 99)
    bt = str(specs.get("body_type") or live.get("body_type") or "")
    if "四驱" in pt_info["drive_short"] and "SUV" in bt.upper():
        archetype = "四驱长途SUV"
    elif "中型车" in bt and pt_info["gearbox_tier"] == "AT":
        archetype = "高速巡航B级AT"
    elif pt_info["gearbox_tier"] == "AT" and scores.get("config", 0) >= 78:
        archetype = "AT高配全能选"
    elif pt_info["gearbox_tier"] == "AT" and mile <= 3.5:
        archetype = "AT低里程稳妥选"
    elif pt_info["gearbox_tier"] == "AT":
        archetype = "AT省心耐造"
    elif pt_info["gearbox_tier"] == "CVT" and "自然吸气" in pt_info["intake"]:
        archetype = "自吸CVT地板养车"
    elif scores.get("config", 0) >= 85:
        archetype = "满配性价比"
    elif discount_fold is not None and discount_fold <= 2.8:
        archetype = "高折旧捡漏"
    else:
        archetype = "均衡严选"

    # Tailored inspection checklist
    checklist: list[str] = []
    if item.get("is_local_wuhan") is False or int(item.get("landed_extra_yuan") or 0) > 0:
        shop_lbl = str(item.get("shop_short_name") or item.get("city") or "外地直营店")
        logi_yuan = int(item.get("logistics_fee_yuan") or 0)
        plate_yuan = int(item.get("plate_service_fee_yuan") or 1000)
        checklist.append(
            f"异地直营调拨（{shop_lbl}→武汉）：到汉物流 {logi_yuan} 元 + 上牌服务费 {plate_yuan} 元，"
            "锁单前核对官方漆面/底盘检测视频与托运保险条款"
        )
    if any(k in title for k in ("迈锐宝", "君威")):
        checklist.extend([
            "冷车测试一枪着火（排查高压油泵延迟）",
            "挂P挡熄火确认仪表无提示（排查换挡微动开关）",
            "检查高位刹车灯灯罩有无老化开裂",
        ])
    elif "伊兰特" in title:
        checklist.append("直线微调方向盘测试转向柱阻尼与回正顺滑度")
    elif "探界者" in title:
        checklist.append("反复开关全景天窗及遮阳帘，确认卷帘轴卡扣完好")
    elif "传祺GS4" in title:
        checklist.append("举升检查底盘边角防锈，测试车机远程控车状态")
    elif "欧蓝德" in title:
        checklist.append("举升检查四驱分动箱与后差速器有无油渍渗漏")
    elif "名图" in title:
        checklist.append("测试转向管柱低速打方向有无异响与发卡感")
    elif any(k in title for k in ("领克03", "星瑞")) and "2.0T" in title:
        checklist.append("因CMA平台静置暗电流偏大，建议提车配150元锂电应急搭电宝或电瓶断电开关")
    elif pt_info["gearbox_tier"] == "WET_DCT":
        checklist.append("低速1-2挡跟车测试换挡平顺度，举升看变速箱油底壳及阀体插头有无油迹")
    elif pt_info["gearbox_tier"] == "AT":
        checklist.append("热车切换R/D挡感受结合冲击，急加速测试降挡响应")
    elif "日产" in pt_info["gearbox_label"]:
        checklist.append("上路连续加速测试CVT有无打滑或异响，查看变速箱油保养记录")

    if "四驱" in pt_info["drive_short"] and not any("分动箱" in x for x in checklist):
        checklist.append("举升检查四驱分动箱及半轴防尘套是否渗油")
    if feats.get("panoramic_sunroof") and not any("天窗" in x for x in checklist):
        checklist.append("泼水测试全景天窗排水孔，确认遮阳帘开合无异响")

    checklist.append("节假日低频停放必查：现场测12V电瓶健康度SOH（低于60%要求更换），排查有无私接常电记录仪")

    # Concise advisor one-liner
    bits: list[str] = []
    if discount_fold is not None:
        bits.append(f"{discount_fold}折捡漏（原指导价{msrp:.2f}万）")
    bits.append(f"{pt_info['gearbox_label']}" + (f"+{pt_info['intake']}" if pt_info["intake"] else ""))
    if pt_info["rear_suspension_short"]:
        bits.append(pt_info["rear_suspension_short"])
    if has_l2:
        bits.append("配齐L2辅助驾驶")
    elif highlights:
        bits.append("配" + "/".join(highlights[:3]))
    if mile <= 3.5:
        bits.append(f"实表仅{mile:.2f}万km")
    recommend_reason = "，".join(bits) + "。"

    pt_summary_parts = [
        pt_info["engine_summary"],
        pt_info["gearbox_label"],
        pt_info["rear_suspension_short"],
        pt_info["drive_short"],
        pt_info["fuel_grade"],
    ]
    powertrain_summary = " · ".join(p for p in pt_summary_parts if p)

    return {
        "archetype_badge": archetype,
        "msrp_wan": msrp,
        "discount_fold": discount_fold,
        "saved_wan": saved_wan,
        "powertrain_summary": powertrain_summary,
        "gearbox_tier": pt_info["gearbox_tier"],
        "gearbox_label": pt_info["gearbox_label"],
        "engine_summary": pt_info["engine_summary"],
        "intake": pt_info["intake"],
        "fuel_injection": pt_info["fuel_injection"],
        "rear_suspension": pt_info["rear_suspension"],
        "rear_suspension_short": pt_info["rear_suspension_short"],
        "drive_type": pt_info["drive_type"],
        "drive_short": pt_info["drive_short"],
        "fuel_grade": pt_info["fuel_grade"],
        "feature_highlights": highlights[:8],
        "recommend_reason": recommend_reason,
        "inspection_checklist": checklist[:5],
        "maintenance_estimate": pt_info["maintenance_estimate"],
        "reliability_notes": pt_info["notes"],
    }
