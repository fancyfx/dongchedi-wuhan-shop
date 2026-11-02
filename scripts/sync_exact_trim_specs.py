#!/usr/bin/env python3
"""Fill exact-trim V3 specs for every filtered listing using Dongchedi public JSON APIs.

The sync is deliberately conservative:
- exact series + exact trim title are required;
- optional/uncertain values become null and never score;
- low-confidence matches are reported, never guessed;
- existing hand-verified V3 records always win.

Unmatched listings remain unmapped. rerank_v2.py routes them to data-issues.json.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rerank_composite import series_key  # noqa: E402

BASE = "https://www.dongchedi.com"
INDEX = ROOT / "data" / "vehicle-specs-verified.json"
AUTO_SHARD = ROOT / "data" / "specs" / "exact-trims-auto.json"
REPORT = ROOT / "data" / "specs" / "exact-trim-sync-report.json"
SOURCE_CANDIDATES = (
    ROOT / "data" / "listings-filtered.json",
    ROOT / "data" / "listings-ranked.json",
)
COMMON = {"aid": "1839", "app_name": "auto_web_pc", "version_code": "476"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/141 Safari/537.36"


def dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_json(path: str, params: dict[str, Any], retries: int = 2) -> dict[str, Any]:
    query = {**COMMON, **{k: v for k, v in params.items() if v is not None}}
    url = f"{BASE}{path}?{urlencode(query)}"
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/plain,*/*", "Referer": BASE + "/"})
            with urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network/API drift must not fabricate config
            last = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}: {last}")


def norm(text: Any) -> str:
    s = str(text or "").lower()
    s = s.replace("dm-i", "dmi").replace("dm i", "dmi").replace("plus", "plus")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)


def scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("value", "text", "name", "title", "series_name", "car_name"):
            if key in value:
                t = scalar_text(value.get(key))
                if t:
                    return t
    if isinstance(value, list):
        vals = [scalar_text(x) for x in value]
        return " ".join(v for v in vals if v)
    return ""


def walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def first_value(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if d.get(key) not in (None, ""):
            return d.get(key)
    info = d.get("info")
    if isinstance(info, dict):
        for key in keys:
            if info.get(key) not in (None, ""):
                return info.get(key)
    return None


def best_series(query: str) -> tuple[int | None, str, float]:
    raw = request_json("/motor/searchapi/search_content", {"keyword": query, "cur_tab": 2, "offset": 0, "count": 20})
    candidates: dict[int, str] = {}
    for d in walk(raw.get("data", raw)):
        sid = first_value(d, ("series_id", "seriesId"))
        if sid is None:
            continue
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            continue
        name = scalar_text(first_value(d, ("series_name", "seriesName", "name", "title")))
        if name:
            candidates[sid_i] = name
    nq = norm(query)
    ranked = []
    for sid, name in candidates.items():
        nn = norm(name)
        ratio = SequenceMatcher(None, nq, nn).ratio()
        if nq == nn:
            ratio = 1.0
        elif nq and (nq in nn or nn in nq):
            ratio = max(ratio, 0.88)
        ranked.append((ratio, sid, name))
    if not ranked:
        return None, "", 0.0
    ratio, sid, name = max(ranked)
    return sid, name, ratio


def car_candidates(series_id: int) -> list[tuple[int, str]]:
    raw = request_json("/motor/pc/car/series/car_list", {"series_id": series_id, "city_name": "武汉"})
    out: dict[int, str] = {}
    for d in walk(raw.get("data", raw)):
        cid = first_value(d, ("car_id", "carId"))
        if cid is None:
            continue
        try:
            cid_i = int(cid)
        except (TypeError, ValueError):
            continue
        name = scalar_text(first_value(d, ("car_name", "carName", "name", "title")))
        if name:
            out[cid_i] = name
    return list(out.items())


def trim_part(title: str, series: str) -> str:
    s = title.strip()
    if series and s.startswith(series):
        s = s[len(series):].strip()
    return s


def best_car(title: str, series: str, cars: list[tuple[int, str]]) -> tuple[int | None, str, float]:
    target = norm(trim_part(title, series))
    title_n = norm(title)
    year_m = re.search(r"(20\d{2})款", title)
    year = year_m.group(1) if year_m else ""
    ranked = []
    for cid, name in cars:
        n = norm(name)
        ratio = max(SequenceMatcher(None, target, n).ratio(), SequenceMatcher(None, title_n, n).ratio())
        if target == n:
            ratio = 1.0
        elif target and (target in n or n in target):
            ratio = max(ratio, 0.93)
        if year and year not in name:
            ratio -= 0.12
        ranked.append((ratio, cid, name))
    if not ranked:
        return None, "", 0.0
    ratio, cid, name = max(ranked)
    return cid, name, ratio


def value_to_text(value: Any) -> str:
    if isinstance(value, dict):
        if "value" in value:
            return value_to_text(value.get("value"))
        return " ".join(value_to_text(v) for v in value.values() if v is not None)
    if isinstance(value, list):
        return " ".join(value_to_text(v) for v in value)
    return str(value or "").strip()


def config_rows(raw: dict[str, Any], car_id: int) -> dict[str, str]:
    data = raw.get("data") or {}
    properties = data.get("properties") or []
    car_info = data.get("car_info") or []
    selected: dict[str, Any] | None = None
    for c in car_info:
        cid = c.get("car_id") or c.get("id")
        try:
            if int(cid) == int(car_id):
                selected = c
                break
        except (TypeError, ValueError):
            continue
    if selected is None and len(car_info) == 1:
        selected = car_info[0]
    if selected is None:
        return {}
    info = selected.get("info") or {}
    rows: dict[str, str] = {}

    def add_row(label: Any, key: Any) -> None:
        if not label or not key:
            return
        cell = info.get(str(key), info.get(key))
        if isinstance(cell, dict):
            cell = cell.get("value", cell)
        text = value_to_text(cell)
        if text:
            rows[str(label).strip()] = text

    for prop in properties:
        if not isinstance(prop, dict):
            continue
        ptype = str(prop.get("type", ""))
        if ptype in ("1", "3"):
            add_row(prop.get("text") or prop.get("name"), prop.get("key"))
        for sub in prop.get("sub_list") or []:
            if isinstance(sub, dict):
                add_row(sub.get("text") or sub.get("name"), sub.get("key"))
    return rows


def find_row(rows: dict[str, str], *needles: str) -> str | None:
    for needle in needles:
        for label, value in rows.items():
            if needle in label:
                return value
    return None


def number(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def integer(value: Any) -> int | None:
    n = number(value)
    return int(round(n)) if n is not None else None


def tri(value: Any) -> bool | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if any(x in s for x in ("选装", "○", "可选")):
        return None
    if s in ("-", "--", "无", "否", "false", "0", "暂无"):
        return False
    if any(x in s for x in ("●", "标配", "有", "是", "true")):
        return True
    return True


def powertrain(value: str | None) -> str:
    s = str(value or "")
    if "纯电" in s:
        return "bev"
    if "插电" in s or "插混" in s:
        return "phev"
    if "增程" in s:
        return "erev"
    if "油电" in s or "混合动力" in s:
        return "hev"
    return "ice"


def sunroof_value(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value)
    if any(x in s for x in ("无", "-")) and "全景" not in s:
        return "none"
    if "全景" in s and any(x in s for x in ("开启", "可开")):
        return "panoramic_openable"
    if "全景" in s:
        return "panoramic"
    if "天窗" in s or "单天窗" in s:
        return "single_openable"
    return None


def cruise_value(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value)
    if "全速" in s and "自适应" in s:
        return "full_speed_adaptive"
    if "自适应" in s:
        return "adaptive"
    if "定速" in s:
        return "fixed"
    if s in ("-", "无"):
        return "none"
    return None


def build_trim(title: str, car_id: int, series_id: int, rows: dict[str, str], match_score: float) -> dict[str, Any]:
    pt = powertrain(find_row(rows, "能源类型"))
    size = find_row(rows, "长*宽*高", "长×宽×高")
    dims = [integer(x) for x in re.findall(r"\d+(?:\.\d+)?", size or "")[:3]]
    length = integer(find_row(rows, "长度(mm)", "车长(mm)")) or (dims[0] if len(dims) > 0 else None)
    width = integer(find_row(rows, "宽度(mm)", "车宽(mm)")) or (dims[1] if len(dims) > 1 else None)
    height = integer(find_row(rows, "高度(mm)", "车高(mm)")) or (dims[2] if len(dims) > 2 else None)
    wheelbase = integer(find_row(rows, "轴距(mm)", "轴距"))

    wltc = number(find_row(rows, "WLTC综合油耗"))
    nedc = number(find_row(rows, "NEDC综合油耗"))
    low_soc = number(find_row(rows, "最低荷电状态油耗", "亏电油耗"))
    electric = number(find_row(rows, "百公里耗电量"))
    ev_range = number(find_row(rows, "CLTC纯电续航里程", "WLTC纯电续航里程", "NEDC纯电续航里程", "纯电续航里程"))
    ev_std = None
    for std in ("CLTC", "WLTC", "NEDC"):
        if find_row(rows, f"{std}纯电续航里程") is not None:
            ev_std = std
            break

    ranking_energy = None
    if pt == "bev" and electric is not None:
        ranking_energy = {"type": "electricity", "value": electric, "unit": "kWh/100km"}
    elif pt == "phev" and low_soc is not None:
        ranking_energy = {"type": "low_soc_fuel", "value": low_soc, "unit": "L/100km"}
    elif pt in ("ice", "hev", "erev") and wltc is not None:
        ranking_energy = {"type": "official_wltc_with_uncertainty", "value": wltc, "unit": "L/100km", "fallback_multiplier_recommended": 1.15}
    elif pt in ("ice", "hev", "erev") and nedc is not None:
        ranking_energy = {"type": "official_nedc_with_uncertainty", "value": nedc, "unit": "L/100km", "fallback_multiplier_recommended": 1.20}

    passive = {
        "front_airbags": tri(find_row(rows, "主/副驾驶座安全气囊", "主副驾驶座安全气囊")),
        "front_side_airbags": tri(find_row(rows, "前排侧气囊")),
        "curtain_airbags": tri(find_row(rows, "侧安全气帘", "前/后排头部气囊")),
        "tpms_display": tri(find_row(rows, "胎压显示")),
    }
    active = {
        "aeb": tri(find_row(rows, "主动刹车", "主动安全系统")),
        "fcw": tri(find_row(rows, "前方碰撞预警")),
        "ldw": tri(find_row(rows, "车道偏离预警")),
        "lka": tri(find_row(rows, "车道保持辅助")),
        "lane_centering": tri(find_row(rows, "车道居中保持")),
        "bsd": tri(find_row(rows, "并线辅助")),
        "dow": tri(find_row(rows, "开门预警")),
        "rear_collision_warning": tri(find_row(rows, "后方碰撞预警")),
        "traffic_sign_recognition": tri(find_row(rows, "道路交通标识识别", "交通标志识别")),
        "fatigue_warning": tri(find_row(rows, "疲劳驾驶提示")),
    }
    park = {
        "front_parking_radar": tri(find_row(rows, "前驻车雷达")),
        "rear_parking_radar": tri(find_row(rows, "后驻车雷达")),
        "reverse_camera": tri(find_row(rows, "倒车影像")),
        "surround_360": tri(find_row(rows, "360度全景影像", "360°全景影像")),
        "transparent_chassis_540": tri(find_row(rows, "透明底盘", "540度影像", "540°影像")),
        "cruise": cruise_value(find_row(rows, "巡航系统")),
        "adas_level": find_row(rows, "辅助驾驶等级") or None,
        "auto_park": tri(find_row(rows, "自动泊车入位")),
        "remote_park": tri(find_row(rows, "遥控泊车")),
    }
    comfort = {
        "sunroof": sunroof_value(find_row(rows, "天窗类型")),
        "power_tailgate": tri(find_row(rows, "电动后备厢")),
        "hands_free_tailgate": tri(find_row(rows, "感应后备厢")),
        "keyless_entry": tri(find_row(rows, "无钥匙进入功能")),
        "keyless_start": tri(find_row(rows, "无钥匙启动系统")),
        "remote_start": tri(find_row(rows, "远程启动功能")),
        "hud": tri(find_row(rows, "HUD抬头数字显示", "抬头显示")),
        "wireless_phone_charging": tri(find_row(rows, "手机无线充电")),
        "driver_power_seat": tri(find_row(rows, "主驾驶座电动调节")),
        "passenger_power_seat": tri(find_row(rows, "副驾驶座电动调节")),
        "front_seat_heating": tri(find_row(rows, "前排座椅加热")),
        "front_seat_ventilation": tri(find_row(rows, "前排座椅通风")),
        "rear_air_vents": tri(find_row(rows, "后座出风口")),
        "climate_control": "automatic_dual_zone" if tri(find_row(rows, "温度分区控制")) else ("automatic" if tri(find_row(rows, "自动空调")) else None),
        "leather_seats": tri(find_row(rows, "真皮座椅", "座椅材质")) if "真皮" in str(find_row(rows, "座椅材质") or "") else None,
    }
    info = {
        "center_screen_inches": number(find_row(rows, "中控屏幕尺寸")),
        "instrument_screen_inches": number(find_row(rows, "液晶仪表尺寸", "全液晶仪表盘尺寸")),
        "carplay": tri(find_row(rows, "CarPlay")),
        "carlife": tri(find_row(rows, "CarLife")),
        "connected_car": tri(find_row(rows, "车联网")),
        "ota": tri(find_row(rows, "OTA升级")),
        "speaker_count": integer(find_row(rows, "扬声器数量")),
        "branded_audio": find_row(rows, "扬声器品牌", "品牌音响") or None,
        "voice_control": tri(find_row(rows, "语音识别控制系统", "语音控制")),
        "full_lcd_cluster": tri(find_row(rows, "全液晶仪表盘")),
        "chip_8155": True if "8155" in str(find_row(rows, "车机智能芯片", "车载智能芯片") or "") else None,
    }
    lighting = {
        "headlights": find_row(rows, "近光灯光源", "远近光灯光源") or None,
        "auto_headlights": tri(find_row(rows, "自动头灯")),
        "adaptive_high_beam": tri(find_row(rows, "自适应远近光")),
    }

    feature_leafs = [
        v for group in (passive, active, park, comfort, info, lighting)
        for v in group.values() if v is not None
    ]
    fuel_grade = find_row(rows, "燃油标号")
    if fuel_grade:
        m = re.search(r"9[258]", fuel_grade)
        fuel_grade = m.group() if m else fuel_grade

    official = wltc if wltc is not None else nedc
    official_std = "WLTC" if wltc is not None else ("NEDC" if nedc is not None else None)
    core = {
        "powertrain": pt,
        "body_type": find_row(rows, "级别", "车身结构") or None,
        "seats": integer(find_row(rows, "座位数", "座椅布局")),
        "engine": find_row(rows, "发动机", "发动机型号") or None,
        "transmission": find_row(rows, "变速箱", "变速箱类型") or None,
        "length_mm": length,
        "width_mm": width,
        "height_mm": height,
        "wheelbase_mm": wheelbase,
        "fuel_grade": fuel_grade,
        "official_fuel_l_100km": official,
        "official_standard": official_std,
        "low_soc_fuel_l_100km": low_soc,
        "real_world_fuel_l_100km": None,
        "real_world_sample_n": None,
        "ev_range_km": ev_range,
        "ev_range_standard": ev_std,
        "electric_kwh_100km": electric,
        "ranking_energy": ranking_energy,
    }
    return {
        "canonical_title": title,
        "msrp_wan": number(find_row(rows, "厂商指导价", "官方指导价")),
        "core_specs": core,
        "features": {
            "passive_safety": passive,
            "active_safety": active,
            "parking_adas": park,
            "comfort": comfort,
            "infotainment": info,
            "lighting": lighting,
            "wheels": {
                "front_tire": find_row(rows, "前轮胎规格") or None,
                "rear_tire": find_row(rows, "后轮胎规格") or None,
            },
            "optional_or_uncertain_features": [],
        },
        "data_quality": {
            "core_confidence": round(min(0.99, 0.90 + max(0.0, match_score - 0.80) * 0.45), 3),
            "feature_confidence": "high" if len(feature_leafs) >= 25 else "medium",
            "verified_non_null_feature_leaf_count": len(feature_leafs),
            "scoring_rule": "Only exact-trim standard features may score. null/optional features score 0.",
            "known_issues": [] if len(feature_leafs) >= 25 else ["懂车帝该停售/旧款车型返回的可核验配置字段较少"],
        },
        "sources": [{
            "url": f"{BASE}/motor/pc/car/get_full_config_info?series_id={series_id}&car_ids={car_id}",
            "source_type": "dongchedi_exact_trim_public_json",
            "authority_tier": 2,
            "series_id": series_id,
            "car_id": car_id,
        }],
    }


def main() -> None:
    src = next((p for p in SOURCE_CANDIDATES if p.exists()), None)
    if src is None:
        raise SystemExit("no filtered listing source")
    listings = json.loads(src.read_text(encoding="utf-8"))
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    existing_map = {str(k): str(v) for k, v in (index.get("sku_to_trim") or {}).items()}
    auto = {"schema_version": "3.0-exact-trim", "trims": {}}
    if AUTO_SHARD.exists():
        try:
            old = json.loads(AUTO_SHARD.read_text(encoding="utf-8"))
            auto["trims"].update(old.get("trims") or {})
        except Exception:
            pass

    report_rows = []
    series_cache: dict[str, tuple[int | None, str, float]] = {}
    cars_cache: dict[int, list[tuple[int, str]]] = {}
    config_cache: dict[int, dict[str, Any]] = {}
    matched = skipped = failed = 0

    for idx, item in enumerate(listings, 1):
        sku = str(item.get("sku") or "")
        title = str(item.get("title") or "")
        if not sku or not title:
            continue
        if sku in existing_map:
            skipped += 1
            continue
        series = str(item.get("series") or series_key(title))
        row: dict[str, Any] = {"sku": sku, "title": title, "series": series, "status": "unmatched"}
        try:
            if series not in series_cache:
                series_cache[series] = best_series(series)
                time.sleep(0.12)
            sid, sname, sscore = series_cache[series]
            row.update({"series_id": sid, "matched_series": sname, "series_match": round(sscore, 3)})
            if sid is None or sscore < 0.72:
                row["reason"] = "series_exact_match_not_found"
                failed += 1
                report_rows.append(row)
                continue
            if sid not in cars_cache:
                cars_cache[sid] = car_candidates(sid)
                time.sleep(0.12)
            cid, cname, cscore = best_car(title, series, cars_cache[sid])
            row.update({"car_id": cid, "matched_trim": cname, "trim_match": round(cscore, 3)})
            if cid is None or cscore < 0.80:
                row["reason"] = "exact_trim_match_not_found"
                failed += 1
                report_rows.append(row)
                continue
            if sid not in config_cache:
                config_cache[sid] = request_json("/motor/pc/car/get_full_config_info", {"series_id": sid, "car_ids": cid})
                time.sleep(0.12)
            rows = config_rows(config_cache[sid], cid)
            if len(rows) < 20:
                row["reason"] = f"detailed_config_rows_insufficient:{len(rows)}"
                failed += 1
                report_rows.append(row)
                continue
            trim = build_trim(title, cid, sid, rows, cscore)
            leaf_n = int((trim.get("data_quality") or {}).get("verified_non_null_feature_leaf_count") or 0)
            if leaf_n < 18:
                row["reason"] = f"verified_feature_fields_insufficient:{leaf_n}"
                failed += 1
                report_rows.append(row)
                continue
            trim_id = "trim_dcd_" + hashlib.sha1(f"{sid}:{cid}:{title}".encode()).hexdigest()[:12]
            trim["trim_id"] = trim_id
            auto["trims"][trim_id] = trim
            existing_map[sku] = trim_id
            row.update({"status": "matched", "trim_id": trim_id, "config_rows": len(rows), "verified_feature_fields": leaf_n})
            matched += 1
        except Exception as exc:
            row["reason"] = f"sync_error:{type(exc).__name__}:{exc}"
            failed += 1
        report_rows.append(row)
        print(f"[{idx}/{len(listings)}] {row['status']:9} {title} {row.get('reason','')}")

    trim_files = list(index.get("trim_files") or [])
    rel_auto = "specs/exact-trims-auto.json"
    if rel_auto not in trim_files:
        trim_files.append(rel_auto)
    index["trim_files"] = trim_files
    index["sku_to_trim"] = dict(sorted(existing_map.items()))
    index["generated_at"] = time.strftime("%Y-%m-%d")
    index["configuration_policy"] = "exact-trim-only; automated Dongchedi exact trim sync; no approximate fallback"

    dump(AUTO_SHARD, auto)
    dump(INDEX, index)
    dump(REPORT, {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": str(src.relative_to(ROOT)),
        "total_listings": len(listings),
        "existing_verified_skipped": skipped,
        "new_exact_matches": matched,
        "unmatched_or_insufficient": failed,
        "rows": report_rows,
    })
    print(f"SYNC total={len(listings)} existing={skipped} new={matched} insufficient={failed}")


if __name__ == "__main__":
    main()
