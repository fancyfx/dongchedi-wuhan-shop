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
    _put(rows, "NEDC综合油耗", _first(rows, "工信部综合油耗(L/100km)", "工信部综合油耗", "NEDC综合油耗(L/100km)"))
    _put(rows, "NEDC纯电续航里程", _first(rows, "工信部续航里程(km)", "工信部续航里程"))
    _put(rows, "WLTC综合油耗", _first(rows, "WLTC综合油耗(L/100km)", "WLTC综合油耗"))

    # Live AutoHome page label variants.
    _put(rows, "车身稳定控制", _first(rows, "车身稳定控制(ESC/ESP/DSC等)", "车身稳定控制"))
    _put(rows, "主动刹车", _first(rows, "主动刹车/主动安全系统", "主动刹车"))
    _put(rows, "车道偏离预警", _first(rows, "车道偏离预警系统", "车道偏离预警"))
    _put(rows, "车道保持辅助", _first(rows, "车道保持辅助系统", "车道保持辅助"))
    _put(rows, "道路交通标识识别", _first(rows, "道路交通标识识别", "交通标志识别"))
    tpms = _first(rows, "胎压显示", "胎压监测功能")
    if tpms is not None:
        if "显示" in str(tpms) or tpms == "●":
            _put(rows, "胎压显示", "●")
        elif tpms in ("-", "--", "无"):
            _put(rows, "胎压显示", "-")
        else:
            _put(rows, "胎压显示", tpms)

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
    phone = _first(rows, "手机互联/映射", "手机互联")
    if phone not in (None, "", "-", "--", "无"):
        _put(rows, "手机互联/映射", "●" if "○" not in phone else phone)
        if "carplay" in phone.lower() or "CarPlay" in phone:
            _put(rows, "CarPlay", "●")
        if "carlife" in phone.lower() or "CarLife" in phone:
            _put(rows, "CarLife", "●")

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


# Live year-catalog fallback. These checks run only after the strict
# title-score matcher has already failed, so existing exact hits stay put.
_POWER_RE = re.compile(
    r"\d+(?:\.\d+)?(?:tsi|tdi|tgdi|tci|thp|gdit|gdi|dvvt|tfsi|td|[tl])(?![a-z0-9])"
    r"|\d{2}\s*tfsi"
    r"|\d+(?:\.\d+)?x[elv](?![a-z0-9])",
    re.I,
)
_NOISE_RE = re.compile(
    r"20\d{2}款"
    r"|\d+(?:\.\d+)?(?:tsi|tdi|tgdi|tci|thp|gdit|gdi|dvvt|tfsi|td|[tl])(?![a-z0-9])"
    r"|\d{2}\s*tfsi"
    r"|\d+(?:\.\d+)?(?=\s*x[elv])"
    r"|\d{2,4}\s*km"
    r"|国vi|国v|国六|国五"
    r"|dct|dsg|cvt|at|mt"
    r"|手自一体|双离合|自动|手动"
    r"|全时四驱|四驱|两驱|前驱"
    r"|[4-9]座"
    r"|两厢|三厢|sportback|limousine"
    r"|蓝鲸ne|蓝鲸"
    r"|第[一二三四五1-5]代"
    r"|改款三|改款二|改款"
    r"|dmi|电池",
    re.I,
)
_SUFFIX_PREFIXES = {"国潮版", "经典", "北京"}
# Listing series names that are not the AutoHome catalog name. Only the
# residual comparison uses these; the first-pass series id lookup stays as-is.
_SERIES_RESIDUAL_ALIASES = {
    "唐dm": ("唐新能源",),
}


def _norm_power_token(token: str) -> str:
    t = re.sub(r"\s+", "", str(token or "").lower())
    # 1.6XE / 1.6XV is Nissan's 1.6L grade code, not a different displacement.
    m = re.fullmatch(r"(\d+(?:\.\d+)?)x[elv]", t)
    if m:
        return m.group(1) + "l"
    if t.endswith(("tdi", "tgdi", "tci", "gdit")):
        return t
    if t.endswith("td"):
        return t[:-1]
    return t


def power_signature(text: str) -> set[str]:
    found = {_norm_power_token(raw) for raw in _POWER_RE.findall(str(text or ""))}
    return {t for t in found if t}


def emission_code(text: str) -> str | None:
    s = str(text or "").upper().replace("国六", "国VI").replace("国五", "国V")
    if "国VI" in s:
        return "vi"
    if re.search(r"国V(?!I)", s):
        return "v"
    return None


def drive_code(text: str) -> str | None:
    s = str(text or "")
    if any(x in s for x in ("四驱", "4驱", "全时四驱")) or re.search(r"\b(?:awd|4wd)\b", s, re.I):
        return "4"
    if any(x in s for x in ("两驱", "前驱", "2驱")):
        return "2"
    return None


def facelift_level(text: str) -> int:
    s = str(text or "")
    if "改款三" in s:
        return 3
    if "改款二" in s:
        return 2
    if "改款" in s:
        return 1
    return 0


def generation_level(text: str) -> int:
    m = re.search(r"第([一二三四五1-5])代", str(text or ""))
    if not m:
        return 0
    return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}[m.group(1)]


def _soft_norm(text: str) -> str:
    s = str(text or "").lower().replace("dm-i", "dmi").replace("dm i", "dmi")
    for src, dst in {
        "旗舰型": "旗舰版",
        "尊贵型": "尊贵版",
        "豪华型": "豪华版",
        "精英型": "精英版",
    }.items():
        s = s.replace(src, dst)
    # 捷达等用「悦享型」，懂车帝标题常写「悦享版」。只统一这个字，Pro/+ 仍保留。
    s = s.replace("型", "版")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff+]+", "", s)


def trim_residual(title: str, series: str) -> str:
    s = re.sub(r"dm[\s-]*i", "dmi", str(title or ""), flags=re.I)
    series_tokens = [series, series.replace(" ", "")]
    if series.endswith(" DM"):
        series_tokens.append(series[:-3].strip())
    series_key = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(series or "").lower())
    series_tokens.extend(_SERIES_RESIDUAL_ALIASES.get(series_key, ()))
    for token in sorted({t for t in series_tokens if t}, key=len, reverse=True):
        s = s.replace(token, " ")
    s = _NOISE_RE.sub(" ", s)
    return _soft_norm(s)


def trim_alignment(listing: str, candidate: str, series: str) -> str:
    left = trim_residual(listing, series)
    right = trim_residual(candidate, series)
    if len(left) < 2:
        return ""
    if left == right:
        return "exact"
    if right.endswith(left):
        prefix = right[: len(right) - len(left)]
        if prefix in _SUFFIX_PREFIXES or re.fullmatch(r"[a-z0-9]+", prefix or ""):
            return "suffix"
    return ""


def _trans_ok(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return True
    if left == right:
        return True
    # DSG is Volkswagen's name for a dual-clutch box; titles rewrite it as DCT/双离合.
    if {left, right} <= {"dct", "dsg"}:
        return True
    if left == "auto" and right != "manual":
        return True
    if right == "auto" and left != "manual":
        return True
    return False


def _candidate_text(candidate, *labels: str) -> str:
    rows = getattr(candidate, "rows", None) or {}
    for label in labels:
        value = rows.get(label)
        if value:
            return str(value)
    for key, value in rows.items():
        if value and any(label in str(key) for label in labels):
            return str(value)
    return ""


def _wheelbase_mm(candidate) -> int | None:
    raw = _candidate_text(candidate, "轴距(mm)", "轴距")
    m = re.search(r"\d{3,4}", raw)
    if not m:
        return None
    value = int(m.group(0))
    if 2000 <= value <= 4000:
        return value
    return None


def _body_conflict(left: str, right: str) -> bool:
    forms = ("两厢", "三厢", "sportback", "limousine")
    a = {f for f in forms if f in left.lower()}
    b = {f for f in forms if f in right.lower()}
    return bool(a and b and a != b)


def _blocks(listing: str, candidate, series: str) -> list[str]:
    title = str(getattr(candidate, "title", "") or "")
    blocks: list[str] = []
    listed_power = power_signature(listing)
    cand_power = power_signature(title) or power_signature(_candidate_text(candidate, "发动机"))
    if listed_power and cand_power and listed_power != cand_power:
        blocks.append("power")
    gear = _candidate_text(candidate, "变速箱")
    if not _trans_ok(_transmission(listing), _transmission(title) or _transmission(gear)):
        blocks.append("trans")
    left_em, right_em = emission_code(listing), emission_code(title)
    if left_em and right_em and left_em != right_em:
        blocks.append("emission")
    drive_src = title + _candidate_text(candidate, "驱动方式")
    left_drive, right_drive = drive_code(listing), drive_code(drive_src)
    if left_drive and right_drive and left_drive != right_drive:
        blocks.append("drive")
    left_seats = set(re.findall(r"([4-9])座", listing))
    right_seats = set(re.findall(r"([4-9])座", title))
    if left_seats and right_seats and left_seats != right_seats:
        blocks.append("seats")
    if _body_conflict(listing, title):
        blocks.append("body")
    left_range = _range_tokens(listing)
    right_range = _range_tokens(title)
    if left_range and right_range and left_range != right_range:
        blocks.append("range")
    if facelift_level(listing) != facelift_level(title):
        blocks.append("facelift")
    cand_gen = generation_level(title)
    if cand_gen and generation_level(listing) != cand_gen:
        blocks.append("generation")
    if not trim_alignment(listing, title, series):
        blocks.append("trim")
    return blocks


def _alignment_basis(listing: str, candidate, listing_wb: int | None) -> str:
    title = str(candidate.title)
    tags = ["档位"]
    if power_signature(listing) and (power_signature(title) or power_signature(_candidate_text(candidate, "发动机"))):
        tags.append("动力")
    if _transmission(listing) and (_transmission(title) or _transmission(_candidate_text(candidate, "变速箱"))):
        tags.append("变速箱")
    if emission_code(listing) and emission_code(title) == emission_code(listing):
        tags.append("排放")
    if drive_code(listing) and drive_code(title + _candidate_text(candidate, "驱动方式")) == drive_code(listing):
        tags.append("驱动")
    if _range_tokens(listing) and _range_tokens(title) == _range_tokens(listing):
        tags.append("续航")
    cand_wb = _wheelbase_mm(candidate)
    if listing_wb and cand_wb and abs(cand_wb - int(listing_wb)) <= 15:
        tags.append("轴距")
    if "第二代" in listing and "国潮" in title:
        tags.append("第二代=国潮版")
    return "+".join(tags)


def identity_choose(title: str, series: str, candidates, listing_wheelbase: int | None = None):
    """Unique trim + power + gearbox (+ wheelbase / explicit title tokens).

    Returns (candidate, reason, basis). A candidate is returned only when one
    spec survives. Powertrain, gearbox and facelift conflicts never get forced
    through. Listing wheelbase is a tie-break only; it does not override the title.
    """
    target_year = None
    m = re.search(r"(20\d{2})款", str(title or ""))
    if m:
        target_year = int(m.group(1))
    same_year = []
    for cand in candidates:
        cm = re.search(r"(20\d{2})款", str(getattr(cand, "title", "") or ""))
        if target_year is None or (cm and int(cm.group(1)) == target_year):
            same_year.append(cand)
    if target_year is None:
        return None, "listing_model_year_missing", ""
    if not same_year:
        return None, "model_year_not_found", ""

    scored = []
    for cand in same_year:
        blocks = _blocks(title, cand, series)
        hit = trim_alignment(title, str(cand.title), series)
        scored.append((cand, blocks, hit))
    ok = [item for item in scored if not item[1]]

    def _fail() -> str:
        aligned = [item for item in scored if item[2]]
        if len(ok) > 1:
            return "ambiguous_exact_trim_match"
        if aligned and all(any(b in item[1] for b in ("power", "trans", "range")) for item in aligned):
            return "critical_identity_mismatch"
        if any(any(b in item[1] for b in ("facelift", "generation")) for item in aligned):
            return "generation_conflict"
        if any("trans" in item[1] or "power" in item[1] for item in aligned):
            return "critical_identity_mismatch"
        return "exact_trim_similarity_below_threshold"

    if not ok:
        return None, _fail(), ""

    series_key = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(series or "").lower())
    if "哈弗h6" in series_key and "第二代" in title and "第三代" not in title:
        # 2021 第二代同时有改款前都市版和国潮版，轴距都是 2680。
        # 用户确认「第二代 + 都市版」挂国潮版，不挂改款前那一档。
        guochao = [item for item in ok if "国潮" in str(item[0].title)]
        if len(guochao) == 1:
            ok = guochao

    exact = [item for item in ok if item[2] == "exact"]
    pool = exact or ok
    if len(pool) > 1 and emission_code(title):
        explicit = [item for item in pool if emission_code(item[0].title) == emission_code(title)]
        if len(explicit) == 1:
            pool = explicit
    if len(pool) > 1 and drive_code(title):
        explicit = [
            item
            for item in pool
            if drive_code(item[0].title + _candidate_text(item[0], "驱动方式")) == drive_code(title)
        ]
        if len(explicit) == 1:
            pool = explicit
    if len(pool) > 1 and listing_wheelbase:
        try:
            want = int(listing_wheelbase)
        except (TypeError, ValueError):
            want = 0
        if 2000 <= want <= 4000:
            close, far = [], False
            for item in pool:
                wb = _wheelbase_mm(item[0])
                if wb is None:
                    continue
                if abs(wb - want) <= 15:
                    close.append(item)
                elif abs(wb - want) >= 40:
                    far = True
            if len(close) == 1 and far:
                pool = close
    if len(pool) != 1:
        return None, "ambiguous_exact_trim_match" if len(pool) > 1 else _fail(), ""
    chosen = pool[0][0]
    return chosen, "", _alignment_basis(title, chosen, listing_wheelbase)


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
