#!/usr/bin/env python3
"""Chrome-free AutoHome exact-trim synchronization via public getParamConf API.

Downloads/caches AutoHome brands.csv for series lookup, pulls full year param
trees from https://car-web-api.autohome.com.cn/car/param/getParamConf, matches
listings strictly (via title_score / autohome_exact_rules), writes standard
autohome-live-config-tree-1 JSON files, exports index.json, and returns
V3 verified trim records compatible with vehicle-specs-verified.json.
"""
from __future__ import annotations

import concurrent.futures
import csv
import hashlib
import io
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import autohome_exact_rules as rules
import autohome_live_config as live_cfg
import sync_exact_trim_specs as base

ROOT = Path(__file__).resolve().parents[1]
BRANDS_CSV = ROOT / "data" / "specs" / "autohome-brands.csv"
BRANDS_URL = "https://raw.githubusercontent.com/swoiow/autohome/main/brands.csv"
PARAM_CACHE = ROOT / ".tmp" / "ah-param-cache"
MIN_MATCH = 0.86
MIN_GAP = 0.045
MIN_FEATURES = 18

SERIES_ALIASES: dict[str, int] = {
    "秦plusdm": 5964,
    "秦plus": 5964,
    "唐dm": 3430,
    "唐": 3430,
    "领克03": 4916,
    "长安cs75plus": 5379,
    "长安cs75": 3204,
    "哈弗h6": 2123,
    "迈锐宝xl": 4031,
    "迈锐宝": 2313,
    "君威": 164,
    "宝马1系": 3948,
    "红旗hs5": 5067,
    "本田xrv": 3460,
    "xrv": 3460,
    "轩逸": 448,
    "朗逸": 614,
    "宝来": 633,
    "速腾": 442,
    "奥迪a3": 3170,
    "奥迪q2l": 4565,
    "奥迪q3": 2951,
    "探歌": 4674,
    "troc探歌": 4674,
    "威朗": 3751,
    "科沃兹": 4105,
    "阅朗": 4552,
    "雅阁": 78,
    "标致4008": 4167,
    "荣威rx5": 4080,
    "一汽大众cc": 905,
    "瑞虎3x": 4099,
    "北京bj20": 3800,
    "昂科威": 3554,
}

BRAND_PREFIXES = (
    "一汽大众", "上汽大众", "一汽奥迪", "华晨宝马", "北京奔驰", "上汽通用别克",
    "上汽通用雪佛兰", "广汽本田", "东风本田", "广汽丰田", "一汽丰田", "东风日产",
    "广汽传祺", "上汽名爵", "上汽荣威", "吉利银河", "一汽奔腾", "东风风神",
    "奇瑞新能源", "比亚迪", "吉利", "长安", "哈弗", "领克", "奇瑞", "红旗",
    "荣威", "名爵", "本田", "丰田", "日产", "大众", "别克", "雪佛兰", "现代",
    "起亚", "马自达", "福特", "标致", "雪铁龙", "宝马", "奥迪", "奔驰",
    "凯迪拉克", "林肯", "沃尔沃", "英菲尼迪", "捷豹", "路虎", "斯柯达", "五菱", "宝骏",
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ParamSpec:
    spec_id: int
    series_id: int
    title: str
    model_year: int | None
    rows: dict[str, str]
    sections: list[dict[str, Any]]
    wheelbase: int | None = None


def norm_key(text: Any) -> str:
    s = str(text or "").lower()
    for a, b in (
        ("dm-i", "dmi"),
        ("dm i", "dmi"),
        ("max版", "max"),
        ("pro版", "pro"),
        ("plus版", "plus"),
        ("旗舰型", "旗舰版"),
        ("尊贵型", "尊贵版"),
        ("豪华型", "豪华版"),
        ("精英型", "精英版"),
    ):
        s = s.replace(a, b)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)


def year_of(text: Any) -> int | None:
    m = re.search(r"(20\d{2})款", str(text or ""))
    return int(m.group(1)) if m else None


def title_score(target: str, candidate: str, series: str) -> float:
    ty, cy = year_of(target), year_of(candidate)
    if ty and cy and ty != cy:
        return 0.0
    tn, cn = norm_key(target), norm_key(candidate)
    ts = norm_key(base.trim_part(target, series))
    cs = norm_key(base.trim_part(candidate, series))
    score = max(
        SequenceMatcher(None, tn, cn).ratio(),
        SequenceMatcher(None, ts, cs).ratio() if ts and cs else 0.0,
    )
    if tn == cn or (ts and ts == cs):
        return 1.0
    if ts and cs and (ts in cs or cs in ts):
        score = max(score, 0.94)
    return max(0.0, min(1.0, score))


def _ensure_brands_csv() -> Path | None:
    if BRANDS_CSV.exists() and BRANDS_CSV.stat().st_size > 1024:
        return BRANDS_CSV
    try:
        req = urllib.request.Request(BRANDS_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read()
        if len(raw) > 1024:
            BRANDS_CSV.parent.mkdir(parents=True, exist_ok=True)
            BRANDS_CSV.write_bytes(raw)
            return BRANDS_CSV
    except Exception:
        return None
    return None


def _search_series_online(series: str) -> int | None:
    """Fallback online series_id lookup via AutoHome PC search/suggest or page."""
    try:
        q = urllib.parse.quote(series)
        url = f"https://sou.autohome.com.cn/zonghe?q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r"series[-_/](\d{2,6})", html)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def load_series_catalog() -> dict[str, int]:
    catalog: dict[str, int] = {}
    csv_path = _ensure_brands_csv()
    if csv_path and csv_path.exists():
        text = csv_path.read_text(encoding="utf-8-sig", errors="replace")
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 2:
                continue
            label = re.sub(r"\s*\(停售\)\s*", " ", row[0])
            label = re.sub(r"\s*\(\d+\)\s*$", "", label).strip()
            m = re.search(r"series_(\d+)", row[1])
            if m and label:
                key = norm_key(label)
                if key and key not in catalog:
                    catalog[key] = int(m.group(1))
    catalog.update(SERIES_ALIASES)
    return catalog


def _fallback_search_series(series: str) -> int | None:
    """Ask Dongchedi/AutoHome or HTML pages? Keep safe offline/HTTP fallback via brands.csv + aliases."""
    return None


def resolve_series_id(series: str, brand: str = "", catalog: dict[str, int] | None = None) -> int | None:
    cat = catalog if catalog is not None else load_series_catalog()
    candidates_str = [str(series or "").strip()]
    s0 = candidates_str[0]
    for pref in BRAND_PREFIXES:
        if s0.startswith(pref) and len(s0) > len(pref):
            candidates_str.append(s0[len(pref) :].strip())
    if brand and not s0.startswith(brand):
        candidates_str.append(f"{brand}{s0}")
    # Strip trailing parentheses like 奔驰CLA(进口) -> 奔驰CLA
    if "(" in s0 or "（" in s0:
        candidates_str.append(re.sub(r"[（(][^）)]*[)）]", "", s0).strip())

    for cand in candidates_str:
        nk = norm_key(cand)
        if nk in cat:
            return cat[nk]

    # High-confidence unique fuzzy match on shortest cleaned series name
    best_nk = norm_key(candidates_str[-1] if len(candidates_str) > 1 else s0)
    if not best_nk:
        return None
    ranked: list[tuple[float, int]] = []
    for k, sid in cat.items():
        sc = SequenceMatcher(None, best_nk, k).ratio()
        if best_nk == k:
            return sid
        if len(best_nk) >= 3 and (best_nk in k or k in best_nk):
            sc = max(sc, 0.91)
        if sc >= 0.90:
            ranked.append((sc, sid))
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[0], reverse=True)
    # Deduplicate same series_id keeping highest score
    dedup: list[tuple[float, int]] = []
    seen_ids: set[int] = set()
    for sc, sid in ranked:
        if sid not in seen_ids:
            seen_ids.add(sid)
            dedup.append((sc, sid))
    if len(dedup) > 1 and dedup[0][0] - dedup[1][0] < 0.03:
        return None
    if dedup:
        return dedup[0][1]
    return None


def resolve_series_id_with_online(series: str, brand: str = "", catalog: dict[str, int] | None = None) -> int | None:
    sid = resolve_series_id(series, brand=brand, catalog=catalog)
    if sid is not None:
        return sid
    if not series:
        return None
    # Guard: avoid slow web searches unless clearly helpful; cache negative results per series in catalog.
    return None


def fetch_param_year(series_id: int, model_year: int) -> dict[str, Any]:
    PARAM_CACHE.mkdir(parents=True, exist_ok=True)
    path = PARAM_CACHE / f"{series_id}-{model_year}.json"
    if path.exists() and path.stat().st_size > 80:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    url = (
        "https://car-web-api.autohome.com.cn/car/param/getParamConf"
        f"?mode=1&site=1&seriesid={series_id}&year={model_year}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read()
    if len(raw) > 80:
        path.write_bytes(raw)
    time.sleep(0.08)
    return json.loads(raw)


def _format_price_suffix(priceinfo: Any) -> str:
    txt = str(priceinfo or "").strip()
    if not txt or txt in ("0", "None", "null"):
        return ""
    if txt.startswith("("):
        return f" {txt}"
    return f" ({txt})"


def _build_sections_and_rows_from_param_spec(
    titlelist: list[dict[str, Any]],
    spec_obj: dict[str, Any],
    series_name: str,
) -> tuple[str, list[dict[str, Any]], dict[str, str]]:
    """Convert one datalist entry from getParamConf into live-config sections & flat rows."""
    val_by_tid: dict[int, dict[str, Any]] = {}
    for entry in spec_obj.get("paramconflist") or []:
        tid = entry.get("titleid")
        if tid is not None:
            val_by_tid[int(tid)] = entry

    sections: list[dict[str, Any]] = []
    flat_rows: dict[str, str] = {}

    for grp in titlelist:
        sec_name = str(grp.get("itemtype") or grp.get("groupname") or "").strip()
        if not sec_name:
            continue
        group_tag = "param" if str(grp.get("groupname") or "").strip() == "参数信息" else "config"
        items_out: list[dict[str, Any]] = []

        for meta in grp.get("items") or []:
            iname = str(meta.get("itemname") or "").strip()
            tid = meta.get("titleid")
            if not iname or tid is None:
                continue
            raw_entry = val_by_tid.get(int(tid)) or {}
            subs = raw_entry.get("sublist") or []
            scalar = str(raw_entry.get("itemname") or "").strip()

            if subs:
                lines_out: list[dict[str, Any]] = []
                displays: list[str] = []
                row_tokens: list[str] = []
                for sub in subs:
                    sname = str(sub.get("name") or "").strip()
                    sval = str(sub.get("value") or "").strip()
                    p_sfx = _format_price_suffix(sub.get("priceinfo"))
                    if not sname and not sval:
                        continue
                    mark: str | None = None
                    if sval == "●" or sval == "1":
                        mark = "standard"
                        sym = "●"
                    elif sval == "○" or sval == "2":
                        mark = "optional"
                        sym = "○"
                    elif sval in ("-", "0", ""):
                        sym = "-"
                    else:
                        sym = sval

                    if sym in ("●", "○"):
                        disp = f"{sym} {sname}".strip() + p_sfx
                        l_entry: dict[str, Any] = {
                            "name": "" if sname in ("标配", "选配") else sname,
                            "value": sym + p_sfx if sname in ("标配", "选配") else f"{sym} {sname}".strip() + p_sfx,
                            "mark": mark,
                        }
                        if sname not in ("标配", "选配") and sname:
                            l_entry["name"] = sname
                            l_entry["value"] = sym + p_sfx
                        lines_out.append(l_entry)
                        displays.append(disp if sname not in ("标配", "选配") else sym + p_sfx)
                        row_tokens.append(disp if sname not in ("标配", "选配") else sym)
                    else:
                        text_v = f"{sname}:{sym}" if sname and sym != "-" else (sname or "-")
                        lines_out.append({"name": sname, "value": sym})
                        displays.append(text_v)
                        row_tokens.append(text_v)

                val_str = " / ".join(displays) if displays else (scalar or "-")
                item_obj: dict[str, Any] = {"name": iname, "value": val_str}
                plain_single = len(lines_out) == 1 and not lines_out[0].get("name")
                if lines_out and not plain_single:
                    item_obj["lines"] = lines_out
                items_out.append(item_obj)
                # For sublist with 1 sub-item like [{'name':'自动空调','value':'●'}] or multiple sub-items
                # without sub-names having '-', derive combined canonical row cleanly.
                if all(t == "-" for t in row_tokens):
                    flat_rows[iname] = "-"
                elif len(subs) == 1 and subs[0].get("value") in ("●", "○") and subs[0].get("name") not in ("标配", "选配"):
                    # Keep both the option token and explicit ●/○ marker for build_trim/rules
                    s_name = str(subs[0].get("name") or "")
                    s_val = str(subs[0].get("value") or "")
                    flat_rows[iname] = f"{s_val} {s_name}"
                    if s_name and s_name not in flat_rows:
                        flat_rows[s_name] = s_val
                else:
                    flat_rows[iname] = "|".join(row_tokens) if row_tokens else val_str
                    # Expose each ●/○ sub-option as its own row so enrich_trim/canonicalize_rows picks it up!
                    for sub in subs:
                        s_name = str(sub.get("name") or "").strip()
                        s_val = str(sub.get("value") or "").strip()
                        if s_name and s_name not in ("标配", "选配") and s_val in ("●", "○", "-"):
                            flat_rows.setdefault(s_name, s_val)
            else:
                val_str = scalar if scalar else "-"
                if val_str in ("", "0", "--"):
                    val_str = "-"
                items_out.append({"name": iname, "value": val_str})
                flat_rows[iname] = val_str

        if items_out:
            sections.append({"name": sec_name, "group": group_tag, "items": items_out})

    spec_name = str(spec_obj.get("specname") or "").strip()
    canonical_title = str(flat_rows.get("车型名称") or "").strip()
    if not canonical_title or canonical_title == "-":
        canonical_title = f"{series_name} {spec_name}".strip() if series_name and series_name not in spec_name else spec_name
        if canonical_title:
            flat_rows["车型名称"] = canonical_title

    # Map API sublist/legacy names -> canonical wording consumed by build_trim & canonicalize_rows
    if "副座椅调节方式" in flat_rows or "主座椅调节方式" in flat_rows:
        seat_adj = flat_rows.get("主/副驾驶座电动调节") or ""
        if "副-" in seat_adj and "副驾驶座电动调节" not in flat_rows:
            flat_rows["副驾驶座电动调节"] = "-"
        if "主-" in seat_adj and "主驾驶座电动调节" not in flat_rows:
            flat_rows["主驾驶座电动调节"] = "-"
    # Absent markers for common sub-item booleans when parent row is '-' or only lists partial options
    if "驾驶辅助影像" in flat_rows:
        img_v = flat_rows["驾驶辅助影像"]
        if "倒车影像" not in flat_rows:
            flat_rows["倒车影像"] = "●" if "倒车影像" in img_v and "●" in img_v else ("-" if img_v == "-" else "-")
        if "360" not in img_v and "全景" not in img_v and "360度全景影像" not in flat_rows:
            flat_rows["360度全景影像"] = "-"
        if "透明底盘" not in img_v and "540" not in img_v and "透明底盘" not in flat_rows:
            flat_rows["透明底盘"] = "-"
    if "前排座椅功能" in flat_rows:
        sf = flat_rows["前排座椅功能"]
        if "加热" not in sf and "前排座椅加热" not in flat_rows:
            flat_rows["前排座椅加热"] = "-"
        if "通风" not in sf and "前排座椅通风" not in flat_rows:
            flat_rows["前排座椅通风"] = "-"
    if "手机互联/映射" in flat_rows:
        ph = flat_rows["手机互联/映射"]
        if ph == "-":
            flat_rows.setdefault("CarPlay", "-")
            flat_rows.setdefault("CarLife", "-")
        else:
            flat_rows.setdefault("CarPlay", "●" if "CarPlay" in ph and "●" in ph else "-")
            flat_rows.setdefault("CarLife", "●" if "CarLife" in ph and "●" in ph else "-")
    if "巡航系统" in flat_rows:
        flat_rows["巡航系统"] = flat_rows["巡航系统"].replace("● ", "").replace("○ ", "")
    if "天窗类型" in flat_rows:
        flat_rows["天窗类型"] = flat_rows["天窗类型"].replace("● ", "").replace("○ ", "")
    if "中控屏幕尺寸" in flat_rows:
        flat_rows["中控屏幕尺寸"] = flat_rows["中控屏幕尺寸"].replace("● ", "")
    if "空调温度控制方式" in flat_rows and "自动空调" not in flat_rows:
        ac = flat_rows["空调温度控制方式"]
        if "自动空调" in ac and "●" in ac:
            flat_rows["自动空调"] = "●"
        elif ac == "-" or ("手动空调" in ac and "●" in ac and "自动" not in ac):
            flat_rows["自动空调"] = "-"
    if "语音识别控制系统" in flat_rows:
        vc = flat_rows["语音识别控制系统"]
        if "○" in vc and "●" not in vc:
            flat_rows["语音识别控制系统"] = "○"
        elif vc != "-":
            flat_rows["语音识别控制系统"] = "●"

    # Also treat explicit Chinese parenthesis mismatches / factory customization suffixes softly via rules
    return canonical_title, sections, rules.canonicalize_rows(flat_rows)


def extract_specs_from_param_payload(payload: dict[str, Any], series_id: int, series_name: str) -> list[ParamSpec]:
    res = payload.get("result") or {}
    tlist = res.get("titlelist") or []
    dlist = res.get("datalist") or []
    out: list[ParamSpec] = []
    for sp in dlist:
        try:
            spec_id = int(sp.get("specid"))
        except (TypeError, ValueError):
            continue
        title, sections, flat_rows = _build_sections_and_rows_from_param_spec(tlist, sp, series_name)
        if not title or len(flat_rows) < 30 or not sections:
            continue
        yr = year_of(title) or (int(sp["year"]) if str(sp.get("year") or "").isdigit() else None)
        wb_raw = re.sub(r"[^0-9]", "", str(flat_rows.get("轴距(mm)") or flat_rows.get("轴距") or ""))
        wb = int(wb_raw) if wb_raw.isdigit() else None
        out.append(
            ParamSpec(
                spec_id=spec_id,
                series_id=series_id,
                title=title,
                model_year=yr,
                rows=flat_rows,
                sections=sections,
                wheelbase=wb,
            )
        )
    return out


@dataclass
class _RuleCandidateShim:
    spec_id: int
    title: str
    rows: dict[str, str]
    source_path: str
    snapshot: str
    series_id: int


def choose_param_spec(item: dict[str, Any], series: str, specs: list[ParamSpec]) -> tuple[ParamSpec | None, float, str]:
    title = str(item.get("title") or "").strip()
    ty = int(item.get("model_year") or year_of(title) or 0)
    if not ty:
        return None, 0.0, "listing_model_year_missing"
    same_year = [s for s in specs if s.model_year == ty]
    if not same_year:
        return None, 0.0, "model_year_not_found"

    # First pass: strict title similarity + critical identity compatibility check
    scored: list[tuple[float, ParamSpec]] = []
    for s in same_year:
        sc = title_score(title, s.title, series)
        scored.append((sc, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_sc, best = scored[0]
    if best_sc >= MIN_MATCH and (len(scored) == 1 or best_sc - scored[1][0] >= MIN_GAP):
        if rules.critical_identity_compatible(title, best.title):
            return best, best_sc, ""

    # Second pass: strict autohome_exact_rules identity matcher (handles generation & grade qualifiers)
    shims = [
        _RuleCandidateShim(
            spec_id=s.spec_id,
            title=s.title,
            rows=s.rows,
            source_path=f"autohome:param:{s.series_id}:{ty}",
            snapshot=f"live_param:{s.series_id}:{ty}",
            series_id=s.series_id,
        )
        for s in same_year
    ]
    chosen, reason, _basis = rules.identity_choose(title, series, shims, listing_wheelbase=None)
    if chosen is not None:
        match = next(s for s in same_year if s.spec_id == chosen.spec_id)
        return match, title_score(title, match.title, series), ""
    return None, best_sc, reason or "exact_trim_match_not_found"


def build_verified_trim_from_param(spec: ParamSpec, match_score: float) -> tuple[str, dict[str, Any]]:
    trim = base.build_trim(spec.title, spec.spec_id, spec.series_id, spec.rows, match_score)
    trim = rules.enrich_trim(trim, spec.rows)
    leaf_n = int((trim.get("data_quality") or {}).get("verified_non_null_feature_leaf_count") or 0)
    trim_id = "trim_ah_" + hashlib.sha1(str(spec.spec_id).encode()).hexdigest()[:12]
    trim["trim_id"] = trim_id
    trim["canonical_title"] = spec.title
    dq = trim.setdefault("data_quality", {})
    dq["identity_source"] = "autohome_exact_trim"
    dq["series_match"] = 1.0
    dq["trim_match"] = round(match_score, 3)
    dq["source_snapshot"] = f"live_param:{spec.series_id}:{spec.model_year}"
    dq["known_issues"] = [] if leaf_n >= 25 else ["汽车之家该车型可核验配置字段较少"]
    trim["sources"] = [
        {
            "url": f"https://car.autohome.com.cn/config/spec/{spec.spec_id}.html",
            "source_type": "autohome_live_config",
            "authority_tier": 1,
            "series_id": spec.series_id,
            "spec_id": spec.spec_id,
            "parameter_source": "getParamConf",
        }
    ]
    return trim_id, trim


def param_spec_to_live_tree(spec: ParamSpec) -> dict[str, Any]:
    return live_cfg.normalize_config_tree(
        {
            "spec_id": spec.spec_id,
            "title": spec.title,
            "sections": spec.sections,
        }
    )


def _persist_verified_and_trees(
    newly_verified: dict[str, dict[str, Any]],
    matched_specs: dict[int, ParamSpec],
) -> None:
    for sid, spec in matched_specs.items():
        tree = param_spec_to_live_tree(spec)
        if tree.get("sections"):
            live_cfg.write_config_tree(tree)

    if newly_verified:
        index_path = base.INDEX
        auto_path = base.AUTO_SHARD
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {
            "schema_version": "3.0-exact-trim",
            "trim_files": ["specs/exact-trims-auto.json"],
            "sku_to_trim": {},
        }
        auto = json.loads(auto_path.read_text(encoding="utf-8")) if auto_path.exists() else {
            "schema_version": "3.0-exact-trim",
            "trims": {},
        }
        auto.setdefault("trims", {})
        mapping = {str(k): str(v) for k, v in (index.get("sku_to_trim") or {}).items()}
        for sku, record in newly_verified.items():
            trim = record["trim"]
            tid = trim["trim_id"]
            auto["trims"][tid] = trim
            mapping[str(sku)] = tid
        index["sku_to_trim"] = dict(sorted(mapping.items()))
        index["generated_at"] = time.strftime("%Y-%m-%d")
        base.dump(auto_path, auto)
        base.dump(index_path, index)

    if matched_specs:
        live_cfg.export_live_config_trees()


def sync_listings_via_param_api(
    listings: list[dict[str, Any]],
    *,
    live: bool = True,
    persist: bool = True,
    write_trees: bool | None = None,
) -> dict[str, Any]:
    """Match listings using AutoHome getParamConf API without needing Chrome or .external."""
    if not live or not listings:
        return {"verified": {}, "matched": 0, "failed": 0}
    should_write_trees = bool(persist) if write_trees is None else bool(write_trees)

    catalog = load_series_catalog()
    key_pairs: dict[tuple[str, int], tuple[int, str]] = {}
    unresolved_series: set[str] = set()

    for item in listings:
        title = str(item.get("title") or "").strip()
        series = str(item.get("series") or base.series_key(title)).strip()
        brand = str(item.get("brand") or "").strip()
        yr = int(item.get("model_year") or year_of(title) or 0)
        if not series or not yr:
            continue
        if (series, yr) in key_pairs or series in unresolved_series:
            continue
        sid = resolve_series_id_with_online(series, brand=brand, catalog=catalog)
        if sid:
            key_pairs[(series, yr)] = (sid, series)
        else:
            unresolved_series.add(series)

    # Fetch unique (series_id, year) param payloads concurrently
    fetch_jobs = sorted({(sid, yr, sname) for (_s, yr), (sid, sname) in key_pairs.items()})
    payload_cache: dict[tuple[int, int], list[ParamSpec]] = {}

    def _job(job: tuple[int, int, str]) -> tuple[int, int, list[ParamSpec]]:
        sid, yr, sname = job
        try:
            payload = fetch_param_year(sid, yr)
            return sid, yr, extract_specs_from_param_payload(payload, sid, sname)
        except Exception:
            return sid, yr, []

    if fetch_jobs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            for sid, yr, specs_list in ex.map(_job, fetch_jobs):
                payload_cache[(sid, yr)] = specs_list

    newly_verified: dict[str, dict[str, Any]] = {}
    matched_specs: dict[int, ParamSpec] = {}
    matched_cnt = 0
    failed_cnt = 0

    for item in listings:
        sku = str(item.get("sku") or "").strip()
        title = str(item.get("title") or "").strip()
        if not sku or not title:
            continue
        series = str(item.get("series") or base.series_key(title)).strip()
        yr = int(item.get("model_year") or year_of(title) or 0)
        pair = key_pairs.get((series, yr))
        if not pair:
            failed_cnt += 1
            continue
        sid, _ = pair
        candidates = payload_cache.get((sid, yr), [])
        chosen, sc, _reason = choose_param_spec(item, series, candidates)
        if chosen is None:
            failed_cnt += 1
            continue
        leaf_probe = base.build_trim(chosen.title, chosen.spec_id, chosen.series_id, chosen.rows, sc)
        leaf_n = int((leaf_probe.get("data_quality") or {}).get("verified_non_null_feature_leaf_count") or 0)
        if len(chosen.rows) < 20 or leaf_n < MIN_FEATURES:
            failed_cnt += 1
            continue
        tid, trim = build_verified_trim_from_param(chosen, sc)
        newly_verified[sku] = {"listing": {"sku": sku, "trim_id": tid}, "trim": trim}
        matched_specs[chosen.spec_id] = chosen
        matched_cnt += 1

    if persist and (newly_verified or matched_specs):
        _persist_verified_and_trees(newly_verified, matched_specs)
    elif should_write_trees and matched_specs:
        for _sid, spec in matched_specs.items():
            tree = param_spec_to_live_tree(spec)
            if tree.get("sections"):
                live_cfg.write_config_tree(tree)
        live_cfg.export_live_config_trees()

    print(
        f"AutoHome param API sync: input={len(listings)} matched={matched_cnt} "
        f"failed={failed_cnt} specs={len(matched_specs)} persist={persist} write_trees={should_write_trees}"
    )
    return {
        "verified": newly_verified,
        "matched": matched_cnt,
        "failed": failed_cnt,
        "unresolved_series": sorted(unresolved_series),
    }


def backfill_catalog_missing(catalog_path: Path | None = None, *, resync_verified_via_param: bool = False) -> dict[str, Any]:
    """Backfill live-config/*.json and vehicle-specs-verified.json for any missing inventory rows."""
    target_path = catalog_path or (ROOT / "data" / "listings-filtered.json")
    rows = json.loads(target_path.read_text(encoding="utf-8"))
    idx_data = json.loads(base.INDEX.read_text(encoding="utf-8")) if base.INDEX.exists() else {"sku_to_trim": {}}
    known_skus = set((idx_data.get("sku_to_trim") or {}).keys())
    need: list[dict[str, Any]] = []
    for item in rows:
        sku = str(item.get("sku") or "")
        specs = item.get("specs") or {}
        live_sid = specs.get("live_spec_id")
        has_tree = bool(live_sid and live_cfg.tree_has_sections(int(live_sid))) if str(live_sid or "").isdigit() else False
        needs_resync = resync_verified_via_param and item.get("condition_gate") == "DATA_ISSUE"
        if sku not in known_skus or not has_tree or needs_resync:
            need.append(item)
    if not need:
        live_cfg.export_live_config_trees()
        print("All inventory listings already have verified trim + live-config tree.")
        return {"verified": {}, "matched": 0, "failed": 0, "unresolved_series": []}
    return sync_listings_via_param_api(need, live=True, persist=True, write_trees=True)


if __name__ == "__main__":
    res = backfill_catalog_missing(resync_verified_via_param=True)
    if res.get("unresolved_series"):
        print("UNRESOLVED_SERIES:", res["unresolved_series"])
