"""Load and parse AutoHome live-config parameter trees for V3 scoring."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LIVE_DIR = ROOT / "data" / "specs" / "live-config"
INDEX_PATH = LIVE_DIR / "index.json"
_SPEC_URL_RE = re.compile(r"/config/spec/(\d+)\.html")
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")
_DIMS_RE = re.compile(r"(\d{4})\s*\*\s*(\d{4})\s*\*\s*(\d{4})")
_INCH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*英寸")


def normalize_title_key(title: str | None) -> str:
    s = re.sub(r"[\s\-·•/()（）]+", "", str(title or "").lower())
    return s.replace("国vi", "").replace("国v", "").replace("版", "").replace("型", "")


@lru_cache(maxsize=1)
def _load_index() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _title_to_spec_map() -> dict[str, str]:
    idx = _load_index()
    specs = idx.get("specs") or {}
    out: dict[str, str] = {}
    for sid, meta in specs.items():
        if not isinstance(meta, dict):
            continue
        key = normalize_title_key(meta.get("title"))
        if key and key not in out:
            out[key] = str(sid)
    return out


def clear_live_spec_caches() -> None:
    _load_index.cache_clear()
    _title_to_spec_map.cache_clear()
    _load_tree.cache_clear()
    extract_live_profile.cache_clear()


@lru_cache(maxsize=512)
def _load_tree(spec_id: str) -> dict[str, Any] | None:
    path = LIVE_DIR / f"{spec_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("sections") else None


def resolve_spec_id(item: dict[str, Any], *, allow_title_match: bool = True) -> str | None:
    specs = item.get("specs") if isinstance(item.get("specs"), dict) else {}
    for src in specs.get("verification_sources") or []:
        if not isinstance(src, dict):
            continue
        sid = src.get("spec_id")
        if sid is not None and not isinstance(sid, bool) and str(sid).isdigit():
            return str(sid)
        m = _SPEC_URL_RE.search(str(src.get("url") or ""))
        if m:
            return m.group(1)

    sku = str(item.get("sku") or "").strip()
    idx = _load_index()
    sku_map = idx.get("sku_to_spec") or {}
    if sku and sku in sku_map:
        return str(sku_map[sku])

    if not allow_title_match:
        return None
    title_key = normalize_title_key(item.get("title"))
    if not title_key:
        return None
    return _title_to_spec_map().get(title_key)


def _has_mark(val: Any) -> bool:
    return "●" in str(val or "")


def _clean_mark(val: Any) -> str:
    text = str(val or "").strip()
    if text in ("", "-"):
        return ""
    return re.sub(r"^[●○]\s*", "", text).strip()


def _parse_float(val: Any) -> float | None:
    m = _NUM_RE.search(str(val or ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _parse_int(val: Any) -> int | None:
    f = _parse_float(val)
    return int(round(f)) if f is not None else None


def _parse_airbags(rows: dict[str, str]) -> int | None:
    front = rows.get("被动安全::主/副驾驶座安全气囊", "")
    side = rows.get("被动安全::前/后排侧气囊", "")
    curtain = rows.get("被动安全::前/后排头部气囊(气帘)", "")
    if not any((front, side, curtain)):
        return None
    count = 0
    if "主●" in front or _has_mark(front):
        count += 1
    if "副●" in front or _has_mark(front):
        count += 1
    if "前●" in side:
        count += 2
    if "后●" in side:
        count += 2
    if "前●" in curtain or "后●" in curtain:
        count += 2
    return count


def _parse_cruise(raw: str) -> tuple[bool | None, str | None]:
    if not raw or raw == "-":
        return None, None
    if "全速自适应" in raw and _has_mark(raw):
        return True, "全速自适应巡航"
    if "自适应" in raw and _has_mark(raw):
        return True, "ACC自适应巡航"
    if "定速" in raw and _has_mark(raw):
        return False, "定速巡航"
    if _has_mark(raw):
        return False, _clean_mark(raw)
    return False, None


def _build_tree_features(rows: dict[str, str]) -> dict[str, Any]:
    cruise_acc, cruise_str = _parse_cruise(rows.get("驾驶功能::巡航系统", ""))
    assist_img = rows.get("驾驶硬件::驾驶辅助影像", "")
    radar = rows.get("驾驶硬件::前/后驻车雷达", "")
    seat_fn = rows.get("座椅配置::前排座椅功能", "")
    seat_adj = rows.get("座椅配置::主/副驾驶座电动调节", "")
    sunroof = rows.get("天窗/玻璃::天窗类型", "")
    climate = rows.get("空调/冰箱::空调温度控制方式", "")
    phone = rows.get("多媒体配置::手机互联/映射", "")
    screen_s = rows.get("内部配置::中控台屏幕尺寸", "") or rows.get("多媒体配置::中控彩色屏幕", "")
    screen_m = _INCH_RE.search(screen_s) or _NUM_RE.search(screen_s)
    screen_inch = float(screen_m.group(1)) if screen_m else None

    carplay = ("CarPlay" in phone and _has_mark(phone)) if phone and phone != "-" else None
    carlife = ("CarLife" in phone and _has_mark(phone)) if phone and phone != "-" else None
    phone_link = _has_mark(phone) if phone and phone != "-" else None

    def tri(key: str) -> bool | None:
        raw = rows.get(key)
        if raw is None or raw == "":
            return None
        if raw == "-":
            return False
        if _has_mark(raw):
            return True
        return False

    return {
        "airbags": _parse_airbags(rows),
        "esp": tri("主动安全::车身稳定控制(ESC/ESP/DSC等)"),
        "aeb": tri("主动安全::主动刹车/主动安全系统"),
        "fcw": tri("主动安全::前方碰撞预警"),
        "ldw": tri("主动安全::车道偏离预警系统"),
        "lka": tri("驾驶功能::车道保持辅助系统"),
        "lane_centering": tri("驾驶功能::车道居中保持"),
        "bsd": tri("驾驶功能::并线辅助"),
        "dow": tri("主动安全::DOW开门预警"),
        "acc": cruise_acc,
        "cruise": cruise_str,
        "camera_360": ("360" in assist_img and _has_mark(assist_img)) if assist_img and assist_img != "-" else False,
        "transparent_chassis": ("透明底盘" in assist_img and _has_mark(assist_img)) if assist_img and assist_img != "-" else False,
        "front_radar": ("前●" in radar) if radar and radar != "-" else False,
        "rear_radar": ("后●" in radar) if radar and radar != "-" else False,
        "auto_park": tri("驾驶功能::自动泊车入位"),
        "remote_park": tri("驾驶功能::遥控泊车"),
        "power_driver_seat": ("主●" in seat_adj) if seat_adj and seat_adj != "-" else False,
        "power_passenger_seat": ("副●" in seat_adj) if seat_adj and seat_adj != "-" else False,
        "seat_heating": ("加热" in seat_fn and _has_mark(seat_fn)) if seat_fn and seat_fn != "-" else False,
        "seat_ventilation": ("通风" in seat_fn and _has_mark(seat_fn)) if seat_fn and seat_fn != "-" else False,
        "panoramic_sunroof": ("全景" in sunroof and _has_mark(sunroof)) if sunroof and sunroof != "-" else False,
        "power_tailgate": tri("外观/防盗::电动后备厢"),
        "keyless_entry": tri("外观/防盗::无钥匙进入功能"),
        "remote_start": tri("外观/防盗::远程启动功能"),
        "rear_ac_vents": tri("空调/冰箱::后座出风口"),
        "dual_zone_climate": tri("空调/冰箱::温度分区控制") or ("双区" in climate or "多区" in climate),
        "leather_seats": ("真皮" in rows.get("座椅配置::座椅材质", "") and _has_mark(rows.get("座椅配置::座椅材质", ""))),
        "full_lcd_cluster": tri("内部配置::全液晶仪表盘"),
        "screen_inch": screen_inch,
        "carplay": carplay,
        "carlife": carlife,
        "phone_link": phone_link,
        "wireless_charge": tri("内部配置::手机无线充电功能"),
        "voice_control": tri("多媒体配置::语音识别控制系统"),
        "ota": tri("多媒体配置::OTA升级"),
        "hud": tri("方向盘/内后视镜::HUD抬头数字显示"),
        "chip_8155": ("8155" in rows.get("智能化配置::车载智能芯片", "")),
    }


@lru_cache(maxsize=512)
def extract_live_profile(spec_id: str | None) -> dict[str, Any] | None:
    if not spec_id:
        return None
    tree = _load_tree(str(spec_id))
    if not tree:
        return None
    rows: dict[str, str] = {}
    for sec in tree.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        sname = str(sec.get("name") or "").strip()
        for it in sec.get("items") or []:
            if not isinstance(it, dict):
                continue
            iname = str(it.get("name") or "").strip()
            val = str(it.get("value") or "").strip()
            if val in ("", "-") and isinstance(it.get("lines"), list):
                parts = []
                for ln in it["lines"]:
                    if isinstance(ln, dict):
                        lv = str(ln.get("value") or "").strip()
                        ln_n = str(ln.get("name") or "").strip()
                        if lv and lv != "-":
                            parts.append(f"{ln_n}:{lv}" if ln_n else lv)
                if parts:
                    val = " / ".join(parts)
            rows[f"{sname}::{iname}"] = val
            if iname not in rows or rows[iname] in ("", "-"):
                rows[iname] = val

    msrp_raw = rows.get("基本参数::厂商指导价(元)") or rows.get("厂商指导价(元)") or ""
    msrp_wan = _parse_float(msrp_raw) if "万" in msrp_raw else None
    energy_type = rows.get("基本参数::能源类型") or rows.get("发动机::能源类型") or ""
    engine_text = rows.get("基本参数::发动机") or ""
    cylinders = _parse_int(rows.get("发动机::气缸数(个)"))
    if cylinders is None:
        if "L3" in engine_text:
            cylinders = 3
        elif "L4" in engine_text:
            cylinders = 4

    dims_m = _DIMS_RE.search(rows.get("基本参数::长*宽*高(mm)", ""))
    length_mm = int(dims_m.group(1)) if dims_m else _parse_int(rows.get("车身::长度(mm)"))
    width_mm = int(dims_m.group(2)) if dims_m else _parse_int(rows.get("车身::宽度(mm)"))
    height_mm = int(dims_m.group(3)) if dims_m else _parse_int(rows.get("车身::高度(mm)"))
    wheelbase_mm = _parse_int(rows.get("车身::轴距(mm)"))

    fuel_raw = rows.get("发动机::燃油标号") or ""
    fuel_grade = "95" if "95" in fuel_raw else ("92" if "92" in fuel_raw else (fuel_raw or "92"))
    seats_m = re.search(r"(\d+)\s*座", rows.get("基本参数::车身结构", ""))
    seats = int(seats_m.group(1)) if seats_m else None

    wltc = _parse_float(rows.get("基本参数::WLTC综合油耗(L/100km)"))
    nedc = _parse_float(rows.get("基本参数::NEDC综合油耗(L/100km)"))
    official_fuel = wltc if wltc is not None else nedc
    official_std = "WLTC" if wltc is not None else ("NEDC" if nedc is not None else None)
    ev_range = _parse_float(rows.get("基本参数::CLTC纯电续航里程(km)")) or _parse_float(
        rows.get("基本参数::NEDC纯电续航里程(km)")
    )

    assist_img = rows.get("驾驶硬件::驾驶辅助影像", "")
    cruise_raw = rows.get("驾驶功能::巡航系统", "")

    return {
        "spec_id": int(spec_id) if str(spec_id).isdigit() else str(spec_id),
        "canonical_title": str(tree.get("title") or "").strip(),
        "url": str(tree.get("url") or f"https://car.autohome.com.cn/config/spec/{spec_id}.html"),
        "msrp_wan": msrp_wan,
        "energy_type": energy_type,
        "engine_text": engine_text,
        "engine_model": _clean_mark(rows.get("发动机::发动机型号")),
        "cylinders": cylinders,
        "intake": _clean_mark(rows.get("发动机::进气形式")),
        "fuel_injection": _clean_mark(rows.get("发动机::供油方式")),
        "horsepower_ps": _parse_int(rows.get("发动机::最大马力(Ps)") or engine_text),
        "torque_nm": _parse_int(rows.get("发动机::最大扭矩(N·m)")),
        "fuel_grade": fuel_grade,
        "transmission_type": _clean_mark(rows.get("变速箱::变速箱类型") or rows.get("基本参数::变速箱")),
        "transmission_short": _clean_mark(rows.get("变速箱::简称") or rows.get("基本参数::变速箱")),
        "rear_suspension": _clean_mark(rows.get("底盘转向::后悬架类型")),
        "drive_type": _clean_mark(rows.get("底盘转向::驱动方式")),
        "body_type": _clean_mark(rows.get("基本参数::级别")),
        "seats": seats,
        "length_mm": length_mm,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "wheelbase_mm": wheelbase_mm,
        "official_fuel_l_100km": official_fuel,
        "official_standard": official_std,
        "ev_range_km": ev_range,
        "knee_airbag": _has_mark(rows.get("被动安全::膝部气囊")),
        "has_reverse_camera": ("倒车影像" in assist_img and _has_mark(assist_img)),
        "has_fixed_cruise": ("定速巡航" in cruise_raw and _has_mark(cruise_raw)),
        "features": _build_tree_features(rows),
    }


def build_specs_from_live_profile(profile: dict[str, Any]) -> dict[str, Any]:
    en = str(profile.get("energy_type") or "")
    if "纯电动" in en:
        powertrain = "bev"
    elif "插电" in en or "增程" in en:
        powertrain = "phev"
    else:
        powertrain = "ice"
    official_fuel = profile.get("official_fuel_l_100km")
    official_std = profile.get("official_standard")
    ranking_energy: dict[str, Any] | None = None
    if powertrain == "ice" and official_fuel is not None:
        ranking_energy = {
            "type": f"official_{(official_std or 'wltc').lower()}_with_uncertainty",
            "value": official_fuel,
            "unit": "L/100km",
            "fallback_multiplier_recommended": 1.15 if official_std == "WLTC" else 1.2,
        }

    spec_id = profile["spec_id"]
    feats = dict(profile.get("features") or {})
    return {
        "length_mm": profile.get("length_mm"),
        "width_mm": profile.get("width_mm"),
        "height_mm": profile.get("height_mm"),
        "wheelbase_mm": profile.get("wheelbase_mm"),
        "seats": profile.get("seats"),
        "body_type": profile.get("body_type"),
        "engine": profile.get("engine_text") or "●",
        "transmission": profile.get("transmission_type") or profile.get("transmission_short"),
        "fuel_grade": profile.get("fuel_grade") or "92",
        "official_fuel_l_100km": official_fuel,
        "official_standard": official_std,
        "low_soc_fuel_l_100km": None,
        "real_world_fuel_l_100km": None,
        "real_world_sample_n": None,
        "electric_kwh_100km": None,
        "ev_range_km": profile.get("ev_range_km"),
        "ev_range_standard": None,
        "ranking_energy": ranking_energy,
        "powertrain": powertrain,
        "powertrain_type": powertrain,
        "msrp_wan": profile.get("msrp_wan"),
        "features": feats,
        "airbags": feats.get("airbags"),
        "screen_inch": feats.get("screen_inch"),
        "match_level": "exact_trim",
        "trim_id": f"trim_live_{spec_id}",
        "canonical_title": profile.get("canonical_title"),
        "specs_found": True,
        "specs_approx": False,
        "verified": True,
        "verification_schema": "3.0-exact-trim-detailed",
        "configuration_source": "exact_trim_v3",
        "core_confidence": 0.99,
        "feature_confidence": 0.95,
        "verification_issues": [],
        "verification_sources": [
            {
                "url": profile.get("url"),
                "source_type": "autohome_live_config",
                "authority_tier": 1,
                "spec_id": spec_id,
                "parameter_source": "live_page",
            }
        ],
    }
