"""V3 powertrain reliability, four iron-law vetoes, and buyer profile builder."""
from __future__ import annotations

import re
from typing import Any

LUXURY_HIGH_COST_BRANDS = (
    "奔驰", "宝马", "奥迪", "林肯", "凯迪拉克", "沃尔沃",
    "捷豹", "路虎", "英菲尼迪", "讴歌", "DS", "MINI", "Jeep", "自由侠",
)
DEFUNCT_OR_RARE_BRANDS = (
    "猎豹", "众泰", "力帆", "汉腾", "宝沃", "海马", "观致", "纳智捷", "雷诺", "卡缤", "铃木", "东南",
)
OLD_HIGH_RISK_MODELS = ("魏牌 VV5", "魏牌 VV6", "魏牌 VV7", "VV5", "VV6", "VV7")
HIDDEN_HANDLE_MODELS = ("逸达", "UNI-T", "UNI-V")
NISSAN_CVT_MODELS = ("轩逸", "逍客", "奇骏", "蓝鸟", "天籁", "骐达")
TOYOTA_CVT_MODELS = ("丰田", "奕泽", "C-HR", "卡罗拉", "雷凌", "致炫", "威驰", "凌尚")
MAINSTREAM_WET_DCT_MODELS = (
    "哈弗H6", "哈弗F7", "哈弗初恋", "哈弗赤兔", "哈弗大狗", "锐程", "长安CS75", "长安CS85",
    "星瑞", "领克", "博越", "瑞虎", "逸达", "逸动", "UNI-", "迈腾", "帕萨特", "途岳", "探岳",
)


def _infer_model_year(item: dict[str, Any], specs: dict[str, Any]) -> int | None:
    for raw in (item.get("model_year"), specs.get("model_year")):
        if isinstance(raw, (int, float)) and 2005 <= int(raw) <= 2030:
            return int(raw)
    m = re.search(r"(20\d{2})款", str(item.get("title") or specs.get("canonical_title") or ""))
    return int(m.group(1)) if m else None


def _is_phev_or_reev(item: dict[str, Any], specs: dict[str, Any], live: dict[str, Any]) -> bool:
    energy = str(live.get("energy_type") or specs.get("energy_type") or "")
    pt = str(specs.get("powertrain") or specs.get("powertrain_type") or "").lower()
    fuel_form = str(item.get("fuel_form") or "").strip().lower()
    title = str(item.get("title") or "")
    return (
        any(k in energy for k in ("插电", "增程"))
        or pt in ("phev", "reev", "插混", "增程")
        or fuel_form in ("6", "phev", "reev")
        or bool(re.search(r"\bDM(?:-i|-p)?\b", title, re.IGNORECASE))
    )


def evaluate_veto(
    item: dict[str, Any],
    specs: dict[str, Any],
    live: dict[str, Any] | None = None,
    age_years: float | None = None,
) -> dict[str, Any]:
    """Apply hard elimination rules: BEV, old/high-risk PHEV, 3-cyl, and dry DCT."""
    live = live or {}
    reasons: list[str] = []
    title = str(item.get("title") or "")
    energy = str(live.get("energy_type") or specs.get("energy_type") or "")
    pt = str(specs.get("powertrain") or specs.get("powertrain_type") or "").lower()
    fuel_form = str(item.get("fuel_form") or "").strip().lower()
    tt = str(live.get("transmission_type") or specs.get("transmission") or "")
    ts = str(live.get("transmission_short") or "")

    is_bev = (
        "纯电动" in energy
        or pt in ("bev", "纯电")
        or fuel_form in ("4", "bev")
    )
    if is_bev:
        reasons.append("纯电车型（无固定家充且长期静置无法自发电补电，存在亏电风险）")
    elif _is_phev_or_reev(item, specs, live):
        my = _infer_model_year(item, specs)
        mile = float(item.get("mileage_wan") if item.get("mileage_wan") is not None else 0.0)
        eff_age = float(age_years) if age_years is not None else (
            max(0.8, 2026.9 - float(item.get("plate_year") or my or 2021))
        )
        annual_wan = mile / max(eff_age, 0.8)
        if "双离合" in tt or "DCT" in tt.upper() or "双离合" in ts or (my is not None and my < 2021):
            reasons.append("早期老架构/双离合插混（亏电油耗高且老三元锂过保维修风险大）")
        elif eff_age > 5.5 or mile > 7.5:
            reasons.append("高龄或高里程插混（二手过户无终身质保，临近8年/15万km法定三电质保边界）")
        elif annual_wan > 3.2:
            reasons.append(f"疑似高频营运插混（年均里程达{annual_wan:.1f}万km，三电高负荷损耗风险）")

    cylinders = live.get("cylinders")
    if cylinders is None:
        cylinders = specs.get("cylinders")
    engine_text = str(live.get("engine_text") or specs.get("engine") or "")
    if cylinders == 3 or "L3" in engine_text:
        reasons.append("三缸发动机（抖动与长期维保顾虑）")

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
    intake = str(live.get("intake") or specs.get("intake") or "")
    fuel_inj = str(live.get("fuel_injection") or specs.get("fuel_injection") or "")
    fuel_grade = str(live.get("fuel_grade") or specs.get("fuel_grade") or "92")
    rear_susp = str(live.get("rear_suspension") or specs.get("rear_suspension") or "")
    drive = str(live.get("drive_type") or specs.get("drive_type") or "")
    engine_text = str(live.get("engine_text") or specs.get("engine") or "")
    is_phev = _is_phev_or_reev(item, specs, live)
    notes: list[str] = []

    if "E-CVT" in tt.upper() or "E-CVT" in ts.upper() or "DHT" in tt.upper() or "DHT" in ts.upper() or is_phev:
        gearbox_tier = "E_CVT"
        score = 88.0
        gearbox_label = "E-CVT电混" if ("E-CVT" in tt.upper() or "E-CVT" in ts.upper() or "DM" in title.upper()) else (ts or "DHT混动")
        if is_phev:
            # Used PHEV loses first-owner lifetime warranty (reverts to 8y/150k km) and carries higher green-plate insurance.
            score -= 5.0
            notes.append("E-CVT串并联电混平顺静谧，但二手过户仅享8年/15万km法定三电质保且绿牌商险偏高")
    elif "手自一体" in tt or "自动变速箱(AT)" in tt or re.search(r"\bAT\b", tt):
        gearbox_tier = "AT"
        if "4挡" in ts:
            score = 68.0
        elif any(g in ts for g in ("8挡", "9挡", "10挡")):
            score = 91.0
        else:
            score = 89.0
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
        score = 82.0 if any(b in title for b in MAINSTREAM_WET_DCT_MODELS) else 74.0
        gearbox_label = ts or "湿式双离合"
    elif "手动" in tt or "MT" in tt:
        gearbox_tier = "MT"
        score = 45.0
        gearbox_label = ts or "手动挡"
    elif "双离合" in tt or "DCT" in tt:
        gearbox_tier = "WET_DCT"
        score = 80.0 if any(b in title for b in MAINSTREAM_WET_DCT_MODELS) else 73.0
        gearbox_label = ts or "双离合"
    else:
        gearbox_tier = "OTHER"
        score = 65.0
        gearbox_label = ts or "自动"

    if "自然吸气" in intake:
        if "多点电喷" in fuel_inj or "混合喷射" in fuel_inj:
            score += 5.0
            if not is_phev:
                notes.append(f"自然吸气+{fuel_inj}，积碳少且耐静置")
        else:
            score += 4.0
            if not is_phev:
                notes.append("自然吸气四缸，结构简单好维护")
    elif "涡轮" in intake:
        score += 2.0

    if "95" in fuel_grade:
        score -= 3.0
        notes.append("需加注95号汽油")

    if "独立悬架" in rear_susp and "非独立" not in rear_susp:
        score += 3.0
    if "四驱" in drive:
        score += 1.0

    if any(b in title for b in LUXURY_HIGH_COST_BRANDS):
        score -= 28.0
        notes.append("豪华/进口品牌零整比与单次维保成本偏高")
    if any(b in title for b in DEFUNCT_OR_RARE_BRANDS):
        score -= 28.0
        notes.append("冷门或已退市品牌，后期配件供应与维修便利性差")
    if any(m in title for m in OLD_HIGH_RISK_MODELS):
        score -= 20.0
        notes.append("老平台停产车系，车质网反馈天窗排水管渗漏与烧机油投诉偏高")
    if "远景X6" in title:
        score -= 9.0
        notes.append("早期GX7老架构多次改款车型，底盘代际偏老")
    if any(b in title for b in ("思皓", "东风风神", "奔腾", "风行")):
        score -= 6.0
        notes.append("二线小众车系，二手保值率与专修网点密度弱于一线主流")
    if any(m in title for m in HIDDEN_HANDLE_MODELS):
        score -= 5.0
        notes.append("隐藏式门把手在长期停放亏电时存在开启不便隐患")
    if any(m in title for m in ("领克03", "星瑞")) and "2.0T" in title:
        score -= 3.0
        notes.append("CMA架构静置暗电流偏大，建议常备搭电宝或断电开关")

    score = round(max(0.0, min(100.0, score)), 2)

    if any(b in title for b in LUXURY_HIGH_COST_BRANDS):
        maint = "约 800-1400 元/年"
    elif is_phev:
        maint = "保养约 400-550 元/年（绿牌商险略高）"
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
    is_suv_bt = "SUV" in bt.upper()
    is_phev = _is_phev_or_reev(item, specs, live)
    cfg_s = scores.get("config", 0)

    if pt_info["gearbox_tier"] == "E_CVT":
        archetype = "电混平顺SUV" if is_suv_bt else "准新电混备选"
    elif is_suv_bt and pt_info["gearbox_tier"] == "AT" and cfg_s >= 78:
        archetype = "AT高配SUV"
    elif is_suv_bt and cfg_s >= 88:
        archetype = "满配现代SUV"
    elif "四驱" in pt_info["drive_short"] and is_suv_bt:
        archetype = "四驱长途SUV"
    elif is_suv_bt and pt_info["gearbox_tier"] == "AT":
        archetype = "AT稳妥SUV"
    elif not is_suv_bt and mile <= 3.0 and cfg_s >= 80:
        archetype = "极品轿车备选"
    elif "中型车" in bt and pt_info["gearbox_tier"] == "AT":
        archetype = "B级AT备选"
    elif pt_info["gearbox_tier"] == "CVT" and "自然吸气" in pt_info["intake"]:
        archetype = "自吸CVT省心选"
    else:
        archetype = "均衡严选SUV" if is_suv_bt else "高性价备选"

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
    if is_phev:
        checklist.extend([
            "插混过户必核：确认行驶证非营运性质，核实8年/15万km法定三电质保剩余额度及底盘电池护板无托底",
            "低频停放铁律：长停前用强制保电将动力电池维持在50%–60% SOC，防止小电瓶与刀片电池深亏",
        ])
    elif any(k in title for k in ("迈锐宝", "君威")):
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
        checklist.append("低速1-2挡跟车测试换挡平顺度，若近6万km核查变速箱油更换记录及油底壳有无渗油")
    elif pt_info["gearbox_tier"] == "AT":
        checklist.append("热车切换R/D挡感受结合冲击，急加速测试降挡响应")
    elif "日产" in pt_info["gearbox_label"]:
        checklist.append("上路连续加速测试CVT有无打滑或异响，查看变速箱油保养记录")

    if "四驱" in pt_info["drive_short"] and not any("分动箱" in x for x in checklist):
        checklist.append("举升检查四驱分动箱及半轴防尘套是否渗油，6万km节点预留分动箱换油预算")
    if feats.get("panoramic_sunroof") and not any("天窗" in x for x in checklist):
        checklist.append("泼水测试全景天窗排水孔，确认遮阳帘开合无异响")

    if not is_phev:
        checklist.append("节假日低频停放必查：现场测12V电瓶健康度SOH（低于60%要求更换），排查有无私接常电记录仪")

    # Concise advisor one-liner (prioritize body class, cabin/ADAS value, powertrain, and real mileage)
    bits: list[str] = []
    if bt:
        bits.append(bt)
    bits.append(f"{pt_info['gearbox_label']}" + (f"+{pt_info['intake']}" if pt_info["intake"] else ""))
    if pt_info["rear_suspension_short"]:
        bits.append(pt_info["rear_suspension_short"])
    if has_l2 and feats.get("camera_360"):
        bits.append("配齐L2智驾+360全景")
    elif has_l2:
        bits.append("配齐L2辅助驾驶")
    elif highlights:
        bits.append("配" + "/".join(highlights[:3]))
    if mile <= 3.5:
        bits.append(f"实表仅{mile:.2f}万km")
    elif is_phev and specs.get("low_soc_fuel_l_100km"):
        bits.append(f"亏电油耗{specs['low_soc_fuel_l_100km']}L")
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
