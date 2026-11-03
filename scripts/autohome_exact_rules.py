"""Strict AutoHome identity and legacy-field normalization rules.

These helpers translate AutoHome's historical/current parameter labels into the
canonical labels consumed by sync_exact_trim_specs.build_trim. They never infer
a feature from another trim: only explicit values in the exact matched column
are converted. Optional markers remain unknown.
"""
from __future__ import annotations

import html
import re
from dataclasses import replace
from typing import Any

import sync_exact_trim_specs as base


def _clean(value: Any) -> str:
    return html.unescape(str(value or "")).replace("\xa0", " ").strip()


def _marker(value: Any) -> str | None:
    s = _clean(value)
    if not s:
        return None
    if "○" in s or "选装" in s or "可选" in s:
        return "○"
    if "●" in s:
        return "●"
    if s in ("-", "--", "无", "否", "false", "0"):
        return "-"
    return None


def _pair_marker(value: Any, side: str) -> str | None:
    s = _clean(value)
    if not s:
        return None
    prefixes = {
        "front": ("前", "主"),
        "rear": ("后", "副"),
    }[side]
    for prefix in prefixes:
        m = re.search(re.escape(prefix) + r"\s*([●○-])", s)
        if m:
            return m.group(1)
    # A single explicit marker on a combined row applies to the combined item.
    if s in ("●", "○", "-", "--"):
        return "-" if s == "--" else s
    return None


def _first(rows: dict[str, str], *labels: str) -> str | None:
    for label in labels:
        value = rows.get(label)
        if value not in (None, ""):
            return str(value)
    return None


def _put(rows: dict[str, str], label: str, value: Any) -> None:
    if rows.get(label) not in (None, "") or value in (None, ""):
        return
    rows[label] = str(value)


def canonicalize_rows(raw: dict[str, str]) -> dict[str, str]:
    """Add canonical aliases while preserving every original AutoHome field."""
    rows = {str(k): _clean(v) for k, v in raw.items()}

    # Official legacy energy labels.
    _put(rows, "NEDC综合油耗", _first(rows, "工信部综合油耗(L/100km)", "工信部综合油耗"))
    _put(rows, "NEDC纯电续航里程", _first(rows, "工信部续航里程(km)", "工信部续航里程"))

    # Historical naming variants.
    _put(rows, "中控屏幕尺寸", _first(rows, "中控台彩色大屏尺寸", "中控屏幕尺寸", "中控彩色液晶屏"))
    _put(rows, "无钥匙进入功能", _first(rows, "无钥匙进入系统", "无钥匙进入"))
    _put(rows, "远程启动功能", _first(rows, "远程启动", "遥控启动"))
    _put(rows, "自动泊车入位", _first(rows, "辅助泊车入位", "自动泊车"))
    _put(rows, "手机无线充电", _first(rows, "手机无线充电功能", "无线充电"))
    _put(rows, "倒车影像", _first(rows, "倒车视频影像", "倒车影像系统"))
    _put(rows, "语音识别控制系统", _first(rows, "语音识别控制系统", "语音控制", "语音助手"))
    _put(rows, "前方碰撞预警", _first(rows, "前方碰撞预警", "前方碰撞报警"))
    _put(rows, "车道保持辅助系统", _first(rows, "车道保持辅助系统", "车道保持辅助"))
    _put(rows, "CarPlay", _first(rows, "CarPlay", "Apple CarPlay"))
    _put(rows, "CarLife", _first(rows, "CarLife", "百度CarLife"))

    # 360 camera: only an explicit panoramic/360 source can map to 360.
    panorama = _first(rows, "全景摄像头")
    if panorama is not None:
        _put(rows, "360度全景影像", panorama)
    assist_image = _first(rows, "驾驶辅助影像")
    if assist_image and any(token in assist_image for token in ("360", "全景")):
        _put(rows, "360度全景影像", assist_image)

    # Split combined front/rear or driver/passenger fields.
    combined = _first(rows, "前/后驻车雷达")
    _put(rows, "前驻车雷达", _pair_marker(combined, "front"))
    _put(rows, "后驻车雷达", _pair_marker(combined, "rear"))

    combined = _first(rows, "主/副驾驶座电动调节")
    _put(rows, "主驾驶座电动调节", _pair_marker(combined, "front"))
    _put(rows, "副驾驶座电动调节", _pair_marker(combined, "rear"))

    combined = _first(rows, "前/后排侧气囊")
    _put(rows, "前排侧气囊", _pair_marker(combined, "front"))

    combined = _first(rows, "前/后排座椅加热")
    _put(rows, "前排座椅加热", _pair_marker(combined, "front"))
    combined = _first(rows, "前/后排座椅通风")
    _put(rows, "前排座椅通风", _pair_marker(combined, "front"))

    # Newer AutoHome sometimes folds seat functions into one textual field.
    front_seat = _first(rows, "前排座椅功能")
    if front_seat is not None:
        if front_seat in ("-", "--", "无"):
            _put(rows, "前排座椅加热", "-")
            _put(rows, "前排座椅通风", "-")
        else:
            if "加热" in front_seat:
                _put(rows, "前排座椅加热", "●")
            if "通风" in front_seat:
                _put(rows, "前排座椅通风", "●")

    # Historical cruise rows are separate booleans.
    if rows.get("巡航系统") in (None, ""):
        adaptive = _marker(_first(rows, "自适应巡航"))
        fixed = _marker(_first(rows, "定速巡航"))
        if adaptive == "●":
            rows["巡航系统"] = "自适应巡航"
        elif adaptive == "○":
            rows["巡航系统"] = "○"
        elif fixed == "●":
            rows["巡航系统"] = "定速巡航"
        elif fixed == "○":
            rows["巡航系统"] = "○"
        elif adaptive == "-" and fixed == "-":
            rows["巡航系统"] = "无"

    # Historical sunroof rows are separate booleans.
    if rows.get("天窗类型") in (None, ""):
        pano = _marker(_first(rows, "全景天窗"))
        normal = _marker(_first(rows, "电动天窗"))
        if pano == "●":
            rows["天窗类型"] = "全景天窗"
        elif pano == "○":
            rows["天窗类型"] = "○"
        elif normal == "●":
            rows["天窗类型"] = "单天窗"
        elif normal == "○":
            rows["天窗类型"] = "○"
        elif pano == "-" and normal == "-":
            rows["天窗类型"] = "无"

    # Auto climate aliases. A value of '-' means automatic climate is absent,
    # not that all climate control is absent.
    climate = _first(rows, "空调控制方式", "空调温度控制方式")
    if climate is not None and rows.get("自动空调") in (None, ""):
        if "自动" in climate:
            rows["自动空调"] = "●"
        elif climate in ("-", "--") or "手动" in climate:
            rows["自动空调"] = "-"

    return rows


def canonicalize_candidate(candidate):
    return replace(candidate, rows=canonicalize_rows(candidate.rows))


def _power_tokens(text: str) -> set[str]:
    s = str(text or "").lower().replace("dm-i", "dmi")
    tokens: set[str] = set()
    for pat in (
        r"\d+(?:\.\d+)?(?:tsi|tdi|td|tgdi|thp|turbo)(?![a-z0-9])",
        r"\d+(?:\.\d+)?[tl](?![a-z0-9])",
        r"(?<!\d)\d{3}(?!\d)",
    ):
        tokens.update(re.findall(pat, s, flags=re.I))
    # Years and electric-range numbers are separate identity dimensions.
    tokens = {t for t in tokens if not re.fullmatch(r"20\d{2}", t)}
    for rng in re.findall(r"\d{2,4}\s*km", s, flags=re.I):
        tokens.discard(re.sub(r"\s*km", "", rng, flags=re.I))
    return tokens


def _normalize_power_token(token: str) -> str:
    t = str(token or "").lower()
    # AutoHome often writes 2.0TD while listings say 2.0T for the same family.
    if t.endswith("tdi"):
        return t[:-3] + "tsi" if t[:-3] else "tsi"
    if t.endswith("td"):
        return t[:-1]
    return t


def _power_compatible(target: set[str], candidate: set[str]) -> bool:
    if not target and not candidate:
        return True
    if target and not candidate:
        return False
    if not target and candidate:
        return True
    if target == candidate:
        return True
    nt = {_normalize_power_token(t) for t in target}
    nc = {_normalize_power_token(t) for t in candidate}
    return nt == nc


def _range_tokens(text: str) -> set[str]:
    return {re.sub(r"\s+", "", x.lower()) for x in re.findall(r"\d{2,4}\s*km", str(text or ""), flags=re.I)}


def _transmission(text: str) -> str | None:
    s = str(text or "").lower()
    if "手动" in s or re.search(r"\bmt\b", s):
        return "manual"
    if "dsg" in s:
        return "dsg"
    if "dct" in s or "双离合" in s:
        return "dct"
    if "cvt" in s:
        return "cvt"
    if "手自一体" in s or re.search(r"\bat\b", s):
        return "at"
    if "自动" in s:
        return "auto"
    return None


def _transmission_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True
    if a == b:
        return True
    if a == "auto":
        return b != "manual"
    if b == "auto":
        return a != "manual"
    return False


def critical_identity_compatible(target: str, candidate: str) -> bool:
    """Reject high textual-similarity matches with different mechanical identity."""
    target_power = _power_tokens(target)
    candidate_power = _power_tokens(candidate)
    if not _power_compatible(target_power, candidate_power):
        return False

    target_range = _range_tokens(target)
    candidate_range = _range_tokens(candidate)
    if target_range and candidate_range and target_range != candidate_range:
        return False
    if target_range and not candidate_range:
        return False

    if not _transmission_compatible(_transmission(target), _transmission(candidate)):
        return False

    for token in ("两厢", "三厢", "sportback", "limousine"):
        t_has = token in str(target).lower()
        c_has = token in str(candidate).lower()
        if t_has != c_has and (t_has or c_has):
            # Only enforce body-form qualifiers when either title explicitly uses one.
            other_tokens = ("两厢", "三厢", "sportback", "limousine")
            if any(x in str(target).lower() for x in other_tokens) and any(x in str(candidate).lower() for x in other_tokens):
                return False

    target_seats = set(re.findall(r"([4-9])座", str(target)))
    candidate_seats = set(re.findall(r"([4-9])座", str(candidate)))
    if target_seats and candidate_seats and target_seats != candidate_seats:
        return False
    return True


def enrich_trim(trim: dict[str, Any], rows: dict[str, str]) -> dict[str, Any]:
    """Expose exact AutoHome fields that the shared builder does not model yet."""
    features = trim.setdefault("features", {})
    active = features.setdefault("active_safety", {})
    comfort = features.setdefault("comfort", {})
    info = features.setdefault("infotainment", {})

    active["esp"] = base.tri(base.find_row(rows, "车身稳定控制"))
    phone = base.find_row(rows, "手机互联/映射")
    info["phone_link"] = base.tri(phone)

    material = base.find_row(rows, "座椅材质")
    if material not in (None, "", "-", "--"):
        comfort["leather_seats"] = "真皮" in str(material)
    else:
        comfort["leather_seats"] = None

    chip = base.find_row(rows, "车机智能芯片", "车载智能芯片")
    if chip not in (None, "", "-", "--"):
        info["chip_8155"] = "8155" in str(chip)

    zone = base.tri(base.find_row(rows, "温度分区控制"))
    climate = _first(rows, "空调控制方式", "空调温度控制方式")
    if zone is True:
        comfort["climate_control"] = "automatic_dual_zone"
    elif climate not in (None, ""):
        if "自动" in str(climate):
            comfort["climate_control"] = "automatic"
        elif str(climate) in ("-", "--") or "手动" in str(climate):
            comfort["climate_control"] = "manual"

    return trim
