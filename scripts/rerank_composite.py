#!/usr/bin/env python3
"""Apply hard filters (incl. short-range BEV) + composite total_score re-rank."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/workspace/dongchedi-wuhan-shop")
sys.path.insert(0, str(ROOT / "scripts"))
from filters import (  # noqa: E402
    FILTER_META,
    MAX_BEV_RANGE_KM,
    filter_listings,
)

SRC = ROOT / "data" / "listings-ranked.json"
WEIGHTS = {
    "config": 0.40,
    "space": 0.25,
    "fuel": 0.15,
    "price": 0.15,
    "suv": 0.05,
}

MANU_RULES: list[tuple[list[str], str, str, bool]] = [
    (["哈弗", "魏牌", "坦克", "欧拉", "长城大狗", "大狗"], "哈弗", "长城汽车", False),
    (["秦", "汉", "唐", "宋", "元", "海鸥", "海豹", "海豚", "驱逐舰"], "比亚迪", "比亚迪", False),
    (["逸动", "逸达", "锐程", "UNI-", "UNI‑", "CS35", "CS75", "欧尚", "Lumin", "长安"], "长安", "长安汽车", False),
    (["帝豪", "远景", "博越", "缤越", "星瑞", "星越", "星愿", "博瑞", "几何", "熊猫", "吉利"], "吉利", "吉利汽车", False),
    (["领克"], "领克", "领克（吉利控股）", False),
    (["荣威", "名爵", "MG"], "荣威/名爵", "上汽集团", False),
    (["传祺"], "传祺", "广汽传祺", False),
    (["轩逸", "天籁", "逍客", "奇骏", "骐达", "TIIDA"], "日产", "东风日产", False),
    (["卡罗拉"], "丰田", "一汽丰田", False),
    (["雷凌", "致炫", "YARIS", "威驰"], "丰田", "广汽丰田", False),
    (["奕泽", "IZOA"], "丰田", "一汽丰田", False),
    (["朗逸", "宝来", "速腾", "途铠", "探歌", "蔚领", "C-TREK", "高尔夫", "嘉旅", "Polo", "甲壳虫"], "大众", "一汽-大众", False),
    (["捷达"], "捷达", "一汽-大众", False),
    (["英朗", "君威", "昂科威", "君越"], "别克", "上汽通用别克", False),
    (["科沃兹", "迈锐宝", "科鲁泽", "探界者"], "雪佛兰", "上汽通用雪佛兰", False),
    (["飞度"], "本田", "广汽本田", False),
    (["雅阁", "思域"], "本田", "东风本田", False),
    (["零跑"], "零跑", "零跑汽车", False),
    (["五菱"], "五菱", "上汽通用五菱", False),
    (["奥迪"], "奥迪", "一汽奥迪", False),
    (["奔驰"], "奔驰", "北京奔驰", False),
    (["伊兰特", "名图", "ix35", "现代"], "现代", "北京现代", False),
    (["影豹"], "传祺", "广汽传祺", False),
    (["奕炫"], "奕炫", "东风风神", False),
    (["傲跑"], "起亚", "悦达起亚", False),
    (["欧蓝德"], "三菱", "广汽三菱", False),
    (["自由侠"], "Jeep", "广汽菲克", True),
    (["锐界"], "福特", "长安福特", False),
    (["瑞虎"], "奇瑞", "奇瑞汽车", False),
    (["标致", "天逸"], "标致", "东风标致", False),
    (["雪铁龙"], "雪铁龙", "东风雪铁龙", False),
    (["凌尚"], "丰田", "广汽丰田", True),
    (["柯迪亚克"], "斯柯达", "上汽大众斯柯达", False),
    (["马自达", "昂克赛拉"], "马自达", "长安马自达", False),
]


def map_manufacturer(title: str) -> tuple[str, str, bool]:
    specials = [
        (["魏牌"], "魏牌", "长城汽车", False),
        (["欧拉"], "欧拉", "长城汽车", False),
        (["哈弗"], "哈弗", "长城汽车", False),
        (["坦克"], "坦克", "长城汽车", False),
        (["长城大狗"], "长城", "长城汽车", False),
        (["几何"], "几何", "吉利汽车", False),
        (["熊猫"], "熊猫", "吉利汽车", False),
        (["MG", "名爵"], "名爵", "上汽集团", False),
        (["荣威"], "荣威", "上汽集团", False),
        (["影豹"], "传祺", "广汽传祺", False),
        (["UNI-"], "长安UNI", "长安汽车", False),
        (["欧尚"], "长安欧尚", "长安汽车", False),
        (["Lumin"], "长安Lumin", "长安汽车", False),
        (["秦PLUS", "秦 PLUS", "秦Plus"], "秦PLUS", "比亚迪", False),
        (["海豹"], "海豹", "比亚迪", False),
        (["海鸥"], "海鸥", "比亚迪", False),
        (["唐DM", "唐 DM"], "唐", "比亚迪", False),
        (["宋Pro", "宋PRO", "宋 Pro"], "宋", "比亚迪", False),
    ]
    for keys, brand, manu, inf in specials:
        if any(k in title for k in keys):
            return brand, manu, inf

    for keys, brand, manu, inf in MANU_RULES:
        if any(k in title for k in keys):
            return brand, manu, inf

    m = re.match(r"^(\S+)", title)
    token = m.group(1) if m else "未知"
    return token, token, True


def series_key(title: str) -> str:
    m = re.match(r"^(.+?)\s+20\d{2}", title)
    return m.group(1).strip() if m else title.split()[0]


def minmax(vals: list[float]) -> tuple[float, float]:
    return min(vals), max(vals)


def norm(v: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 50.0
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100.0))


def build_evaluation(item: dict) -> str:
    ss = item["sort_scores"]
    bits = []
    cfg = ss["config_norm"]
    sp = ss["space_norm"]
    fu = ss["fuel_norm"]
    pr = ss["price_score"]
    title = item["title"]
    is_suv = ss["is_suv"]

    if any(k in title for k in ("旗舰", "Max", "MAX", "尊贵", "智驾", "豪华")):
        bits.append("配置档位偏高（标题含顶配/高配词）")
    elif cfg >= 70:
        bits.append("配置代理分靠前（年款/配置词/检测分综合较好）")
    else:
        bits.append("配置代理分一般")

    if is_suv and sp >= 60:
        bits.append("SUV 空间更实用")
    elif sp >= 70:
        bits.append("空间维度占优")
    elif sp < 40:
        bits.append("空间偏家用轿车级")

    if fu >= 75:
        bits.append("油耗代理友好（纯电/混动或小排量）")
    elif fu <= 35:
        bits.append("油耗代理偏低（较大排量燃油）")

    if pr >= 70:
        bits.append(f"价格 {item['price']} 万更友好")
    elif pr <= 30:
        bits.append(f"价格 {item['price']} 万接近预算上限")

    mile = item.get("mileage_wan")
    if mile is not None and mile <= 2:
        bits.append("里程低")
    elif mile is not None and mile >= 8:
        bits.append("里程偏高需留意")

    year = item.get("plate_year") or item.get("model_year")
    if year and year >= 2024:
        bits.append("准新车龄")

    text = "；".join(bits[:4]) + "。"
    if len(bits) > 4:
        text += "；".join(bits[4:6]) + "。"
    return text


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    # Prefer enriched ranked snapshot; fall back to filtered/loaded.
    for candidate in (
        ROOT / "data" / "listings-ranked.json",
        ROOT / "listings-ranked.json",
        ROOT / "data" / "listings-filtered.json",
        ROOT / "listings-filtered.json",
    ):
        if candidate.exists():
            src = candidate
            break
    else:
        raise SystemExit("no listings source found")

    with open(src, encoding="utf-8") as f:
        raw = json.load(f)

    # If source already filtered, also try to recover excluded from a full snapshot.
    # Always re-apply filter for idempotency.
    listings, excluded = filter_listings(raw)
    n_before = len(raw)

    missing = []
    for item in listings:
        brand, manu, inferred = map_manufacturer(item["title"])
        item["brand"] = brand
        item["manufacturer"] = manu
        item["manufacturer_inferred"] = inferred
        if inferred:
            missing.append(item["title"])
        ss = item.setdefault("sort_scores", {})
        ss.setdefault("config_proxy", 0)
        ss.setdefault("space_proxy", 0)
        ss.setdefault("fuel_proxy", 0)
        ss.setdefault("is_suv", False)
        ss["price"] = item["price"]

    configs = [x["sort_scores"]["config_proxy"] for x in listings]
    spaces = [x["sort_scores"]["space_proxy"] for x in listings]
    fuels = [x["sort_scores"]["fuel_proxy"] for x in listings]
    c_lo, c_hi = minmax(configs)
    s_lo, s_hi = minmax(spaces)
    f_lo, f_hi = minmax(fuels)

    n = len(listings)
    for item in listings:
        ss = item["sort_scores"]
        config_norm = round(norm(ss["config_proxy"], c_lo, c_hi), 2)
        space_norm = round(norm(ss["space_proxy"], s_lo, s_hi), 2)
        fuel_norm = round(norm(ss["fuel_proxy"], f_lo, f_hi), 2)
        price_score = max(0.0, min(100.0, (6.0 - float(item["price"])) / 6.0 * 100.0))
        price_score = round(price_score, 2)
        suv_score = 100.0 if ss.get("is_suv") else 0.0
        total = (
            config_norm * WEIGHTS["config"]
            + space_norm * WEIGHTS["space"]
            + fuel_norm * WEIGHTS["fuel"]
            + price_score * WEIGHTS["price"]
            + suv_score * WEIGHTS["suv"]
        )
        total = round(total, 1)
        ss.update(
            {
                "config_norm": config_norm,
                "space_norm": space_norm,
                "fuel_norm": fuel_norm,
                "price_score": price_score,
                "suv_score": suv_score,
                "total_score": total,
                "weights": dict(WEIGHTS),
                "note": (
                    "综合总得分=config40%+space25%+fuel15%+price15%+suv5%；"
                    f"分项为过滤后集合(n={n})min-max归一化到0-100（price用(6-price)/6*100）；"
                    "卡片无完整参配，config/space/fuel 仍为标题启发式；"
                    f"已排除短续航纯电(≤{MAX_BEV_RANGE_KM}km/微型代步)"
                ),
            }
        )
        item["total_score"] = total
        item["evaluation"] = build_evaluation(item)
        item["series"] = series_key(item["title"])
        item.setdefault(
            "owner_reviews",
            {"summary": "", "sources": [], "found": False},
        )

    listings.sort(
        key=lambda x: (
            -x["total_score"],
            -x["sort_scores"]["config_norm"],
            -x["sort_scores"]["space_norm"],
            -x["sort_scores"]["price_score"],
        )
    )
    for i, item in enumerate(listings, 1):
        item["rank"] = i

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat(timespec="seconds")
    shortlist = listings[:30]
    cheapest = sorted(listings, key=lambda x: (float(x["price"]), -x.get("total_score", 0)))[:30]

    meta_path = ROOT / "data" / "meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    filters = dict(meta.get("filters") or {})
    filters.update(
        {
            "price": "<=6万",
            "price_param": "0,6",
            "mileage": "<=10万公里",
            "mileage_param": "0,10",
            "vehicle_age": "<=10年",
            "age_param": "0,10",
            "plate_or_model_year": ">=2016",
            "reference_year": 2026,
            **FILTER_META,
        }
    )
    meta["filters"] = filters
    meta["price_filter"] = "<=6万"
    meta["mileage_filter"] = "<=10万公里"
    meta["age_filter"] = "<=10年 (上牌/款年>=2016)"
    meta["bev_filter"] = FILTER_META["exclude_short_range_bev_desc"]
    meta["exclude_short_range_bev"] = True
    meta["max_bev_range_km"] = MAX_BEV_RANGE_KM
    meta["sort_preference"] = "composite_total_score"
    meta["sort_weights"] = WEIGHTS
    meta["sort_formula"] = (
        "total_score = 0.40*config_norm + 0.25*space_norm + 0.15*fuel_norm "
        "+ 0.15*price_score + 0.05*suv_score; "
        f"config/space/fuel = min-max(proxy) over filtered n={n}; "
        "price_score = clip((6-price_wan)/6*100,0,100); suv_score = 100 if SUV else 0"
    )
    meta["notes"] = (
        "列表接口默认 sort=0。shortlist 为过滤后按综合总得分排序的前30辆。"
        "封面签名 URL 会过期，以 images/{sku}.jpg 为准。"
        "综合总得分权重：高配40%＞空间25%＞油耗15%＞便宜15%＞SUV5%。"
        "主机厂商由标题映射；车主口碑来自公开网页搜索（非详情页）。"
        f"硬筛另排除短续航纯电（≤{MAX_BEV_RANGE_KM}km 或微型代步车系），后续不入库。"
    )
    meta["sort_method"] = "composite_total_score_heuristic"
    meta["ranked_at"] = now
    meta["ranked_count"] = len(listings)
    meta["filtered_count"] = len(listings)
    meta["loaded_cards_shop_118608"] = meta.get("loaded_cards_shop_118608", n_before)
    meta["passed_mileage_and_age"] = meta.get("passed_mileage_and_age", n_before)
    meta["excluded_short_range_bev_count"] = len(excluded)
    meta["excluded_short_range_bev"] = excluded
    meta["filter_pipeline"] = (
        f"shop_id=118608 → price≤6 → mileage≤10万km → age≤10年 → "
        f"exclude_short_range_bev(max={MAX_BEV_RANGE_KM}km / micro series); "
        f"before_bev_filter={n_before} after={n} excluded={len(excluded)}"
    )
    meta["manufacturer_coverage"] = {
        "total": len(listings),
        "inferred_count": sum(1 for x in listings if x.get("manufacturer_inferred")),
        "inferred_titles": missing[:20],
    }
    # Drop MINIEV from covered series list if present
    covered = [
        s
        for s in (meta.get("owner_reviews_series_covered") or [])
        if "MINIEV" not in s and "Lumin" not in s and "熊猫" not in s
    ]
    meta["owner_reviews_series_covered"] = covered

    for p in (ROOT / "listings-ranked.json", ROOT / "data" / "listings-ranked.json"):
        dump_json(p, listings)
    for p in (ROOT / "listings-filtered.json", ROOT / "data" / "listings-filtered.json"):
        dump_json(p, listings)
    for p in (ROOT / "shortlist-ranked.json", ROOT / "data" / "shortlist-ranked.json"):
        dump_json(p, shortlist)
    for p in (ROOT / "shortlist-cheapest.json", ROOT / "data" / "shortlist-cheapest.json"):
        dump_json(p, cheapest)
    dump_json(ROOT / "data" / "excluded-short-range-bev.json", excluded)
    dump_json(meta_path, meta)

    print(f"SRC {src}")
    print(f"BEFORE {n_before} AFTER {n} EXCLUDED {len(excluded)}")
    print("EXCLUDED")
    for e in excluded:
        print(f" - {e['reason']:40} | {e['price']} | {e['title']}")
    print("TOP15")
    for x in listings[:15]:
        rev = "Y" if (x.get("owner_reviews") or {}).get("found") else "N"
        print(
            f"{x['rank']:2} | {x['total_score']:5.1f} | {x['manufacturer']:14} | {x['brand']:10} | "
            f"{x['price']:.2f}万 | rev={rev} | {x['series']} | sku={x['sku']}"
        )
    print("INFERRED", len(missing))
    for t in missing:
        print(" -", t)
    print(
        "SERIES",
        json.dumps(list(dict.fromkeys(x["series"] for x in listings[:15])), ensure_ascii=False),
    )


if __name__ == "__main__":
    main()
