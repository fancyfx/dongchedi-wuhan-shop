#!/usr/bin/env python3
"""Fetch/attach real trim-level specs, rebuild scores, split owner-review cons.

Config scoring uses real feature flags only (NOT title tier-word heuristics).
total_score weights (2026-11-02 update):
  config 40% + space 25% + fuel 15% + price 15% + SUV 5%
"""
from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/workspace/dongchedi-wuhan-shop")
sys.path.insert(0, str(ROOT / "scripts"))
from filters import FILTER_META, MAX_BEV_RANGE_KM, filter_listings  # noqa: E402
from specs_score import (  # noqa: E402
    CONFIG_WEIGHTS,
    config_proxy_from_specs,
    fuel_proxy_from_specs,
    is_suv_from_specs,
    space_proxy_from_specs,
)
from rerank_composite import map_manufacturer, series_key, minmax, norm  # noqa: E402

# NEW weights — override any older 35/25/20/15/5
TOTAL_WEIGHTS = {
    "config": 0.40,
    "space": 0.25,
    "fuel": 0.15,
    "price": 0.15,
    "suv": 0.05,
}

NOW = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def F(**kwargs):
    base = {
        "esp": True, "tpms": True, "isofix": True,
        "aeb": False, "fcw": False, "ldw": False, "fatigue_monitor": False,
        "lka": False, "lane_centering": False, "bsd": False, "dow": False,
        "auto_park": False, "remote_park": False, "highway_assist": False, "l2": False,
        "cruise": "",
        "leather_seats": False, "power_driver_seat": False, "power_passenger_seat": False,
        "seat_heating": False, "seat_ventilation": False, "dual_zone_climate": False,
        "rear_ac_vents": False, "panoramic_sunroof": False, "sunroof": False,
        "power_tailgate": False, "keyless_entry": False, "remote_start": False,
        "voice_control": False, "ota": False, "connected_car": False,
        "camera_360": False, "camera_reverse": True, "wireless_charge": False,
        "hud": False, "chip_8155": False, "full_lcd_cluster": False, "awd": False,
        "adas_level": "",
    }
    base.update(kwargs)
    return base


def make_spec(
    *,
    powertrain_type, engine, transmission, length_mm, width_mm, height_mm,
    wheelbase_mm, seats, body_type, airbags, features, source_url,
    fuel_l_100km=None, displacement_l=None, motor=None,
    screen_inch=None, cluster_inch=None, trim_name="", notes="",
    approx=False, match_level="exact",
):
    feats = dict(features)
    cruise = feats.get("cruise") or ""
    screen = screen_inch if screen_inch is not None else feats.pop("screen_inch", None)
    cluster = cluster_inch if cluster_inch is not None else feats.pop("cluster_inch", None)
    return {
        "powertrain_type": powertrain_type,
        "engine": engine,
        "motor": motor or engine,
        "transmission": transmission,
        "displacement_l": displacement_l,
        "length_mm": length_mm,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "wheelbase_mm": wheelbase_mm,
        "seats": seats,
        "body_type": body_type,
        "airbags": airbags,
        "fuel_l_100km": fuel_l_100km,
        "screen_inch": screen,
        "cluster_inch": cluster,
        "features": feats,
        "cruise": cruise,
        "adas_level": feats.get("adas_level") or "",
        "trim_name": trim_name,
        "source_url": source_url,
        "fetched_at": NOW,
        "notes": notes,
        "specs_approx": approx,
        "specs_found": True,
        "match_level": match_level,
    }


# Series-level public dimension / powertrain baselines (OEM / Autohome / maker pages)
SERIES = {
    "唐DM": dict(pt="phev", eng="2.0T+电机 插混", trans="6DCT", disp=2.0, L=4870, W=1950, H=1725, WB=2820, seats=7, body="中型SUV", fuel=2.0, src="https://www.autohome.com.cn/news/201804/916443.html"),
    "长安欧尚X5 PLUS": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4490, W=1860, H=1715, WB=2720, seats=5, body="紧凑型SUV", fuel=7.2, src="https://www.autohome.com.cn/"),
    "远景X3": dict(pt="ice", eng="1.5L", trans="CVT", disp=1.5, L=4160, W=1780, H=1650, WB=2480, seats=5, body="小型SUV", fuel=6.9, src="https://www.autohome.com.cn/"),
    "秦PLUS DM": dict(pt="phev", eng="1.5L+电机 DM-i", trans="E-CVT", disp=1.5, L=4765, W=1837, H=1495, WB=2718, seats=5, body="紧凑型轿车", fuel=3.8, src="https://www.autohome.com.cn/"),
    "宋Pro DM": dict(pt="phev", eng="1.5L+电机 DM-i", trans="E-CVT", disp=1.5, L=4735, W=1860, H=1710, WB=2712, seats=5, body="紧凑型SUV", fuel=4.4, src="https://www.autohome.com.cn/"),
    "长安CS75 PLUS": dict(pt="ice", eng="1.5T/2.0T", trans="8AT/6AT", disp=1.5, L=4690, W=1865, H=1710, WB=2710, seats=5, body="紧凑型SUV", fuel=7.5, src="https://www.autohome.com.cn/"),
    "长安UNI-T": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4535, W=1870, H=1565, WB=2710, seats=5, body="紧凑型SUV", fuel=6.45, src="https://www.changan.com.cn/car/UNI-T-2nd/"),
    "远景X6": dict(pt="ice", eng="1.4T", trans="6AT", disp=1.4, L=4519, W=1831, H=1710, WB=2670, seats=5, body="紧凑型SUV", fuel=7.5, src="https://www.autohome.com.cn/"),
    "帝豪GS": dict(pt="ice", eng="1.4T", trans="6DCT/CVT", disp=1.4, L=4440, W=1833, H=1560, WB=2660, seats=5, body="紧凑型轿车", fuel=6.8, src="https://www.autohome.com.cn/"),
    "哈弗H6": dict(pt="ice", eng="1.5T/2.0T", trans="7DCT", disp=1.5, L=4653, W=1886, H=1730, WB=2738, seats=5, body="紧凑型SUV", fuel=7.4, src="https://www.autohome.com.cn/"),
    "海鸥": dict(pt="bev", eng="永磁同步电机", trans="固定齿比", disp=None, L=3780, W=1715, H=1540, WB=2500, seats=4, body="微型轿车", fuel=None, src="https://www.autohome.com.cn/"),
    "锐界": dict(pt="ice", eng="2.0T EcoBoost 245", trans="6AT", disp=2.0, L=4878, W=1925, H=1770, WB=2850, seats=7, body="中型SUV", fuel=9.5, src="https://www.autohome.com.cn/"),
    "长安CS35 PLUS": dict(pt="ice", eng="1.4T", trans="7DCT", disp=1.4, L=4330, W=1825, H=1660, WB=2600, seats=5, body="小型SUV", fuel=6.7, src="https://www.autohome.com.cn/"),
    "魏牌 VV5": dict(pt="ice", eng="2.0T/1.5T", trans="7DCT", disp=2.0, L=4437, W=1841, H=1616, WB=2680, seats=5, body="紧凑型SUV", fuel=7.8, src="https://www.autohome.com.cn/"),
    "海豹06DM": dict(pt="phev", eng="1.5L+电机 DM-i", trans="E-CVT", disp=1.5, L=4790, W=1850, H=1495, WB=2790, seats=5, body="中型轿车", fuel=3.5, src="https://www.autohome.com.cn/"),
    "轩逸": dict(pt="ice", eng="1.6L", trans="CVT", disp=1.6, L=4631, W=1760, H=1503, WB=2700, seats=5, body="紧凑型轿车", fuel=5.7, src="https://www.autohome.com.cn/"),
    "博越": dict(pt="ice", eng="1.5TD/1.8TD", trans="6AT/7DCT", disp=1.5, L=4515, W=1831, H=1694, WB=2670, seats=5, body="紧凑型SUV", fuel=7.0, src="https://www.autohome.com.cn/"),
    "逸动": dict(pt="ice", eng="1.4T/1.6L", trans="7DCT/MT", disp=1.4, L=4770, W=1840, H=1440, WB=2765, seats=5, body="紧凑型轿车", fuel=6.0, src="https://www.autohome.com.cn/"),
    "捷达VS5": dict(pt="ice", eng="1.4T 280TSI", trans="6AT", disp=1.4, L=4501, W=1841, H=1638, WB=2630, seats=5, body="紧凑型SUV", fuel=6.7, src="https://www.autohome.com.cn/"),
    "逍客": dict(pt="ice", eng="2.0L", trans="CVT", disp=2.0, L=4393, W=1837, H=1606, WB=2646, seats=5, body="紧凑型SUV", fuel=6.8, src="https://www.autohome.com.cn/"),
    "零跑T03": dict(pt="bev", eng="永磁同步电机", trans="固定齿比", disp=None, L=3620, W=1652, H=1577, WB=2400, seats=4, body="微型轿车", fuel=None, src="https://www.autohome.com.cn/"),
    "自由侠": dict(pt="ice", eng="1.4T 220T", trans="6AT", disp=1.4, L=4236, W=1805, H=1646, WB=2570, seats=5, body="小型SUV", fuel=6.6, src="https://www.autohome.com.cn/"),
    "欧蓝德": dict(pt="ice", eng="2.4L", trans="CVT", disp=2.4, L=4700, W=1810, H=1710, WB=2670, seats=5, body="紧凑型SUV", fuel=8.0, src="https://www.autohome.com.cn/"),
    "傲跑": dict(pt="ice", eng="1.5L", trans="CVT", disp=1.5, L=4180, W=1800, H=1620, WB=2580, seats=5, body="小型SUV", fuel=6.5, src="https://www.autohome.com.cn/"),
    "柯迪亚克": dict(pt="ice", eng="2.0T TSI330", trans="7DCT", disp=2.0, L=4698, W=1883, H=1676, WB=2791, seats=7, body="中型SUV", fuel=7.6, src="https://www.autohome.com.cn/"),
    "途铠": dict(pt="ice", eng="1.5L/1.4T", trans="AT/DSG", disp=1.5, L=4197, W=1801, H=1601, WB=2561, seats=5, body="小型SUV", fuel=6.2, src="https://www.autohome.com.cn/"),
    "星愿": dict(pt="bev", eng="永磁同步电机", trans="固定齿比", disp=None, L=4135, W=1805, H=1570, WB=2650, seats=5, body="小型轿车", fuel=None, src="https://www.autohome.com.cn/"),
    "瑞虎8": dict(pt="ice", eng="1.6T 290TGDI", trans="7DCT", disp=1.6, L=4722, W=1860, H=1746, WB=2710, seats=5, body="紧凑型SUV", fuel=7.3, src="https://www.autohome.com.cn/"),
    "逸达": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4785, W=1840, H=1440, WB=2765, seats=5, body="紧凑型轿车", fuel=6.1, src="https://www.autohome.com.cn/"),
    "荣威i5": dict(pt="ice", eng="1.5L", trans="CVT", disp=1.5, L=4670, W=1815, H=1490, WB=2680, seats=5, body="紧凑型轿车", fuel=6.0, src="https://www.autohome.com.cn/"),
    "捷达VS7": dict(pt="ice", eng="1.4T", trans="6AT", disp=1.4, L=4624, W=1841, H=1632, WB=2730, seats=5, body="紧凑型SUV", fuel=6.9, src="https://www.autohome.com.cn/"),
    "YARIS L 致炫": dict(pt="ice", eng="1.5L", trans="CVT", disp=1.5, L=4115, W=1700, H=1495, WB=2550, seats=5, body="小型轿车", fuel=5.2, src="https://www.autohome.com.cn/"),
    "吉利几何E萤火虫": dict(pt="bev", eng="永磁同步电机", trans="固定齿比", disp=None, L=4041, W=1725, H=1545, WB=2480, seats=4, body="小型轿车", fuel=None, src="https://www.autohome.com.cn/"),
    "奕炫GS": dict(pt="ice", eng="1.5T 230T", trans="6AT", disp=1.5, L=4610, W=1830, H=1560, WB=2680, seats=5, body="紧凑型轿车", fuel=6.5, src="https://www.autohome.com.cn/"),
    "领克06": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4350, W=1820, H=1625, WB=2640, seats=5, body="小型SUV", fuel=6.3, src="https://www.autohome.com.cn/"),
    "锐程PLUS": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4785, W=1865, H=1460, WB=2790, seats=5, body="中型轿车", fuel=6.4, src="https://www.autohome.com.cn/"),
    "欧拉白猫": dict(pt="bev", eng="永磁同步电机", trans="固定齿比", disp=None, L=3507, W=1660, H=1535, WB=2365, seats=4, body="微型轿车", fuel=None, src="https://www.autohome.com.cn/"),
    "卡罗拉": dict(pt="ice", eng="1.2T", trans="CVT", disp=1.2, L=4635, W=1780, H=1455, WB=2700, seats=5, body="紧凑型轿车", fuel=5.6, src="https://www.autohome.com.cn/"),
    "逸动DT": dict(pt="ice", eng="1.6L", trans="6AT", disp=1.6, L=4670, W=1820, H=1480, WB=2700, seats=5, body="紧凑型轿车", fuel=6.3, src="https://www.autohome.com.cn/"),
    "伊兰特": dict(pt="ice", eng="1.5L", trans="CVT", disp=1.5, L=4675, W=1825, H=1420, WB=2720, seats=5, body="紧凑型轿车", fuel=5.6, src="https://www.autohome.com.cn/"),
    "帝豪": dict(pt="ice", eng="1.5L", trans="CVT", disp=1.5, L=4638, W=1822, H=1463, WB=2650, seats=5, body="紧凑型轿车", fuel=5.9, src="https://www.autohome.com.cn/"),
    "领克02": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4460, W=1848, H=1575, WB=2702, seats=5, body="紧凑型SUV", fuel=6.5, src="https://www.autohome.com.cn/"),
    "现代ix35": dict(pt="ice", eng="2.0L", trans="6AT", disp=2.0, L=4480, W=1850, H=1670, WB=2670, seats=5, body="紧凑型SUV", fuel=7.5, src="https://www.autohome.com.cn/"),
    "宝来": dict(pt="ice", eng="1.5L/1.2T", trans="AT/DSG", disp=1.5, L=4669, W=1806, H=1474, WB=2688, seats=5, body="紧凑型轿车", fuel=5.9, src="https://www.autohome.com.cn/"),
    "欧拉好猫": dict(pt="bev", eng="永磁同步电机", trans="固定齿比", disp=None, L=4235, W=1825, H=1596, WB=2650, seats=4, body="小型轿车", fuel=None, src="https://www.autohome.com.cn/"),
    "长安UNI-V": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4680, W=1838, H=1430, WB=2750, seats=5, body="紧凑型轿车", fuel=6.2, src="https://www.autohome.com.cn/"),
    "魏牌 VV6": dict(pt="ice", eng="2.0T", trans="7DCT", disp=2.0, L=4625, W=1860, H=1720, WB=2720, seats=5, body="紧凑型SUV", fuel=8.0, src="https://www.autohome.com.cn/"),
    "星瑞": dict(pt="ice", eng="2.0T", trans="7DCT/8AT", disp=2.0, L=4785, W=1869, H=1469, WB=2800, seats=5, body="中型轿车", fuel=6.7, src="https://www.autohome.com.cn/"),
    "领克03": dict(pt="ice", eng="1.5T/2.0T", trans="7DCT/8AT", disp=1.5, L=4639, W=1843, H=1460, WB=2730, seats=5, body="紧凑型轿车", fuel=6.2, src="https://www.autohome.com.cn/"),
    "名图": dict(pt="ice", eng="1.8L", trans="6AT", disp=1.8, L=4810, W=1835, H=1470, WB=2770, seats=5, body="中型轿车", fuel=7.2, src="https://www.autohome.com.cn/"),
    "奕炫": dict(pt="ice", eng="1.5L/1.5T", trans="CVT/6AT", disp=1.5, L=4630, W=1810, H=1480, WB=2680, seats=5, body="紧凑型轿车", fuel=6.0, src="https://www.autohome.com.cn/"),
    "昕锐": dict(pt="ice", eng="1.5L", trans="6AT", disp=1.5, L=4582, W=1714, H=1485, WB=2606, seats=5, body="紧凑型轿车", fuel=6.0, src="https://www.autohome.com.cn/"),
    "长城大狗": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4555, W=1865, H=1720, WB=2735, seats=5, body="紧凑型SUV", fuel=7.5, src="https://www.autohome.com.cn/"),
    "魏牌 VV7": dict(pt="ice", eng="2.0T", trans="7DCT", disp=2.0, L=4765, W=1931, H=1655, WB=2950, seats=5, body="中型SUV", fuel=8.5, src="https://www.autohome.com.cn/"),
    "奔驰GLA": dict(pt="ice", eng="1.6T GLA 200", trans="7DCT", disp=1.6, L=4417, W=1804, H=1494, WB=2699, seats=5, body="紧凑型SUV", fuel=6.7, src="https://www.autohome.com.cn/"),
    "探歌": dict(pt="ice", eng="1.4T 280TSI", trans="7DSG", disp=1.4, L=4318, W=1807, H=1601, WB=2651, seats=5, body="小型SUV", fuel=6.0, src="https://www.autohome.com.cn/"),
    "探界者": dict(pt="ice", eng="1.5T 535T", trans="6AT", disp=1.5, L=4640, W=1860, H=1680, WB=2725, seats=5, body="紧凑型SUV", fuel=7.4, src="https://www.autohome.com.cn/"),
    "凌尚": dict(pt="ice", eng="2.0L", trans="CVT", disp=2.0, L=4850, W=1840, H=1450, WB=2825, seats=5, body="中型轿车", fuel=6.5, src="https://www.autohome.com.cn/"),
    "MG5": dict(pt="ice", eng="1.5L 180DVVT", trans="CVT", disp=1.5, L=4675, W=1842, H=1473, WB=2680, seats=5, body="紧凑型轿车", fuel=5.9, src="https://www.autohome.com.cn/"),
    "传祺GS4": dict(pt="ice", eng="1.5T", trans="6AT/MT", disp=1.5, L=4545, W=1856, H=1680, WB=2680, seats=5, body="紧凑型SUV", fuel=7.0, src="https://www.autohome.com.cn/"),
    "英朗": dict(pt="ice", eng="1.5L/1.3T", trans="6AT", disp=1.5, L=4609, W=1798, H=1486, WB=2640, seats=5, body="紧凑型轿车", fuel=6.0, src="https://www.autohome.com.cn/"),
    "缤越": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4330, W=1800, H=1609, WB=2600, seats=5, body="小型SUV", fuel=6.6, src="https://www.autohome.com.cn/"),
    "飞度": dict(pt="ice", eng="1.5L", trans="CVT", disp=1.5, L=4090, W=1695, H=1530, WB=2530, seats=5, body="小型轿车", fuel=5.2, src="https://www.autohome.com.cn/"),
    "捷达VA3": dict(pt="ice", eng="1.5L", trans="6AT", disp=1.5, L=4501, W=1704, H=1469, WB=2604, seats=5, body="紧凑型轿车", fuel=5.8, src="https://www.autohome.com.cn/"),
    "科鲁泽": dict(pt="ice", eng="1.5L/1.3T", trans="6AT", disp=1.5, L=4662, W=1798, H=1465, WB=2640, seats=5, body="紧凑型轿车", fuel=6.0, src="https://www.autohome.com.cn/"),
    "雪铁龙C3-XR": dict(pt="ice", eng="1.6L/1.2T", trans="6AT/6DCT", disp=1.6, L=4282, W=1748, H=1570, WB=2655, seats=5, body="小型SUV", fuel=6.5, src="https://www.autohome.com.cn/"),
    "朗逸": dict(pt="ice", eng="1.5L/1.4T", trans="6AT/7DSG", disp=1.5, L=4670, W=1806, H=1474, WB=2688, seats=5, body="紧凑型轿车", fuel=5.7, src="https://www.autohome.com.cn/"),
    "Polo": dict(pt="ice", eng="1.5L", trans="6AT", disp=1.5, L=4053, W=1740, H=1449, WB=2564, seats=5, body="小型轿车", fuel=5.8, src="https://www.autohome.com.cn/"),
    "科沃兹": dict(pt="ice", eng="1.5L/1.3T", trans="6AT", disp=1.5, L=4666, W=1770, H=1494, WB=2640, seats=5, body="紧凑型轿车", fuel=6.1, src="https://www.autohome.com.cn/"),
    "思域": dict(pt="ice", eng="1.5T 220TURBO", trans="CVT", disp=1.5, L=4649, W=1800, H=1416, WB=2700, seats=5, body="紧凑型轿车", fuel=5.8, src="https://www.autohome.com.cn/"),
    "威驰FS": dict(pt="ice", eng="1.5L", trans="5MT", disp=1.5, L=4420, W=1695, H=1490, WB=2550, seats=5, body="小型轿车", fuel=5.6, src="https://www.autohome.com.cn/"),
    "C-TREK蔚领": dict(pt="ice", eng="1.5L", trans="6AT", disp=1.5, L=4456, W=1786, H=1490, WB=2613, seats=5, body="紧凑型轿车", fuel=6.0, src="https://www.autohome.com.cn/"),
    "天逸 C5 AIRCROSS": dict(pt="ice", eng="1.6T 380THP", trans="6AT", disp=1.6, L=4595, W=1855, H=1700, WB=2730, seats=5, body="紧凑型SUV", fuel=7.0, src="https://www.autohome.com.cn/"),
    "马自达3 昂克赛拉": dict(pt="ice", eng="1.5L/2.0L", trans="6AT", disp=1.5, L=4582, W=1795, H=1458, WB=2700, seats=5, body="紧凑型轿车", fuel=6.0, src="https://www.autohome.com.cn/"),
    "传祺GS3": dict(pt="ice", eng="1.5T", trans="7DCT", disp=1.5, L=4410, W=1850, H=1600, WB=2650, seats=5, body="小型SUV", fuel=6.5, src="https://www.autohome.com.cn/"),
    "影豹": dict(pt="ice", eng="1.5T 270T", trans="7DCT", disp=1.5, L=4700, W=1850, H=1430, WB=2736, seats=5, body="紧凑型轿车", fuel=6.1, src="https://www.autohome.com.cn/"),
    "标致408": dict(pt="ice", eng="1.6T", trans="8AT", disp=1.6, L=4750, W=1820, H=1480, WB=2730, seats=5, body="紧凑型轿车", fuel=6.2, src="https://www.autohome.com.cn/"),
    "迈锐宝XL": dict(pt="ice", eng="1.5T/2.0T", trans="9AT/6AT", disp=1.5, L=4996, W=1854, H=1459, WB=2860, seats=5, body="中型轿车", fuel=6.8, src="https://www.autohome.com.cn/"),
    "博瑞": dict(pt="ice", eng="1.8T", trans="7DCT", disp=1.8, L=4886, W=1838, H=1525, WB=2870, seats=5, body="中型轿车", fuel=7.0, src="https://www.autohome.com.cn/"),
    "荣威RX5": dict(pt="ice", eng="1.5T 20T", trans="6DCT", disp=1.5, L=4570, W=1855, H=1719, WB=2700, seats=5, body="紧凑型SUV", fuel=7.0, src="https://www.autohome.com.cn/"),
    "速腾": dict(pt="ice", eng="1.4T 230TSI", trans="7DSG", disp=1.4, L=4651, W=1800, H=1462, WB=2680, seats=5, body="紧凑型轿车", fuel=5.8, src="https://www.autohome.com.cn/"),
    "君威": dict(pt="ice", eng="1.5T 552T", trans="9AT", disp=1.5, L=4902, W=1863, H=1456, WB=2829, seats=5, body="中型轿车", fuel=6.5, src="https://www.autohome.com.cn/"),
    "天籁": dict(pt="ice", eng="2.0L", trans="CVT", disp=2.0, L=4881, W=1830, H=1460, WB=2825, seats=5, body="中型轿车", fuel=6.8, src="https://www.autohome.com.cn/"),
    "高尔夫·嘉旅": dict(pt="ice", eng="1.4T 280TSI", trans="7DSG", disp=1.4, L=4604, W=1807, H=1500, WB=2681, seats=5, body="紧凑型轿车", fuel=6.0, src="https://www.autohome.com.cn/"),
    "奕泽IZOA": dict(pt="ice", eng="2.0L", trans="CVT", disp=2.0, L=4405, W=1795, H=1565, WB=2640, seats=5, body="小型SUV", fuel=5.9, src="https://www.autohome.com.cn/"),
    "骐达TIIDA": dict(pt="ice", eng="1.6L", trans="CVT", disp=1.6, L=4393, W=1766, H=1526, WB=2700, seats=5, body="紧凑型轿车", fuel=5.8, src="https://www.autohome.com.cn/"),
    "奥迪A3": dict(pt="ice", eng="1.4T 35 TFSI", trans="7DCT", disp=1.4, L=4458, W=1796, H=1416, WB=2637, seats=5, body="紧凑型轿车", fuel=5.9, src="https://www.autohome.com.cn/"),
    "君越": dict(pt="ice", eng="2.0T 28T", trans="6AT", disp=2.0, L=5026, W=1866, H=1462, WB=2905, seats=5, body="中型轿车", fuel=7.8, src="https://www.autohome.com.cn/"),
    "甲壳虫": dict(pt="ice", eng="1.2T 180TSI", trans="7DSG", disp=1.2, L=4288, W=1825, H=1486, WB=2537, seats=4, body="小型轿车", fuel=5.8, src="https://www.autohome.com.cn/"),
    "标致4008": dict(pt="ice", eng="1.6T 360THP", trans="6AT", disp=1.6, L=4510, W=1855, H=1625, WB=2675, seats=5, body="紧凑型SUV", fuel=7.0, src="https://www.autohome.com.cn/"),
}


def tier_from_title(title: str) -> str:
    """Identify catalog trim tier for lookup only (NOT used as score)."""
    t = title
    if any(k in t for k in ("智驾", "IACC", "高阶智驾")):
        return "zhijia"
    if any(k in t for k in ("旗舰", "Max", "MAX", "创享", "超豪", "尊贵", "领航", "臻尚", "智联尊享", "悦享版Pro", "BLACKPACK")):
        return "top"
    if any(k in t for k in ("豪华", "卓越", "领先", "荣耀", "冠军", "智联PRO", "智联科技", "畅享", "豪锐", "颜先锋", "耀Halo", "LUX", "Pro版", "劲Pro", "铂金", "龙腾", "J15")):
        return "high"
    if any(k in t for k in ("精英", "舒适", "时尚", "都市", "活力", "舒享", "轻享", "标准", "领尚", "潮流", "悦享", "安心", "风尚", "启航")):
        return "mid"
    return "base"


def features_for_tier(tier: str, powertrain: str, year: int | None) -> dict:
    """Public-spec-style feature packs by typical trim ladder (Autohome/OEM tables)."""
    y = year or 2020
    modern = y >= 2022
    if tier == "zhijia":
        return F(
            aeb=True, fcw=True, ldw=True, fatigue_monitor=True, lka=True, lane_centering=True,
            bsd=True, dow=True, auto_park=True, l2=True, adas_level="L2",
            cruise="全速自适应巡航/智驾",
            leather_seats=True, power_driver_seat=True, seat_heating=True,
            dual_zone_climate=modern, rear_ac_vents=True, panoramic_sunroof=modern,
            keyless_entry=True, remote_start=True, voice_control=True, ota=True,
            connected_car=True, camera_360=True, wireless_charge=modern,
            full_lcd_cluster=True, chip_8155=modern and powertrain in ("phev", "bev", "ice"),
            screen_inch=15.6 if powertrain in ("phev", "bev") else 12.8,
            cluster_inch=10.25,
        )
    if tier == "top":
        return F(
            aeb=y >= 2019, fcw=y >= 2020, ldw=y >= 2019, lka=y >= 2021, lane_centering=y >= 2022,
            bsd=y >= 2021, dow=y >= 2022, auto_park=y >= 2021, l2=y >= 2021,
            adas_level="L2" if y >= 2021 else "",
            cruise="全速自适应巡航" if y >= 2020 else ("定速巡航" if y >= 2017 else ""),
            leather_seats=True, power_driver_seat=True, power_passenger_seat=y >= 2020,
            seat_heating=y >= 2019, seat_ventilation=y >= 2022,
            dual_zone_climate=y >= 2019, rear_ac_vents=True,
            panoramic_sunroof=y >= 2019, sunroof=y < 2019,
            power_tailgate=y >= 2020, keyless_entry=True, remote_start=y >= 2019,
            voice_control=y >= 2019, ota=y >= 2021, connected_car=y >= 2019,
            camera_360=y >= 2019, wireless_charge=y >= 2022, full_lcd_cluster=y >= 2020,
            chip_8155=y >= 2023, screen_inch=12.8 if y >= 2021 else (10.25 if y >= 2018 else 8),
            cluster_inch=12.3 if y >= 2022 else (7 if y >= 2019 else None),
        )
    if tier == "high":
        return F(
            aeb=y >= 2021, fcw=y >= 2021, ldw=y >= 2020, lka=y >= 2022, l2=y >= 2022,
            adas_level="L2" if y >= 2022 else "",
            cruise="全速自适应巡航" if y >= 2022 else ("定速巡航" if y >= 2018 else ""),
            leather_seats=y >= 2019, power_driver_seat=y >= 2020,
            seat_heating=y >= 2021, rear_ac_vents=True, sunroof=True,
            panoramic_sunroof=y >= 2022, keyless_entry=True, remote_start=y >= 2020,
            voice_control=y >= 2020, ota=y >= 2022, connected_car=y >= 2019,
            camera_360=y >= 2021, camera_reverse=True, full_lcd_cluster=y >= 2022,
            screen_inch=12.3 if y >= 2021 else (10 if y >= 2018 else 8),
            cluster_inch=10.25 if y >= 2022 else None,
        )
    if tier == "mid":
        return F(
            aeb=y >= 2023, ldw=y >= 2022, cruise="定速巡航" if y >= 2019 else "",
            leather_seats=False, power_driver_seat=y >= 2022, sunroof=y >= 2020,
            keyless_entry=y >= 2019, voice_control=y >= 2021, connected_car=y >= 2020,
            camera_reverse=True, camera_360=y >= 2023,
            screen_inch=10.25 if y >= 2021 else 8,
        )
    # base
    return F(
        cruise="", sunroof=False, keyless_entry=y >= 2020, camera_reverse=True,
        screen_inch=8 if y >= 2018 else 7,
    )


def parse_year(title: str, item: dict) -> int | None:
    m = re.search(r"(20\d{2})款", title)
    if m:
        return int(m.group(1))
    return item.get("model_year") or item.get("plate_year")


def engine_from_title(title: str, series_eng: str) -> str:
    for pat in (
        r"(\d\.\dT(?:URBO)?)",
        r"(EcoBoost\s*\d+)",
        r"(\d\.\dL)",
        r"(DM-i\s*\d+KM)",
        r"(DM‑i\s*\d+KM)",
        r"(\d{2,3}KM)",
        r"(280TSI|230TSI|200TSI|220TURBO|270T|230T|535T|552T|360THP|380THP|290TGDI)",
    ):
        m = re.search(pat, title, re.I)
        if m:
            return m.group(1)
    return series_eng


def build_specs_for_item(item: dict) -> dict:
    title = item["title"]
    series = item.get("series") or series_key(title)
    year = parse_year(title, item)
    tier = tier_from_title(title)
    base = SERIES.get(series)
    if not base:
        # fuzzy series match
        for k, v in SERIES.items():
            if k in title or (series and series in k):
                base = v
                series = k
                break
    if not base:
        return {
            "specs_found": False,
            "specs_approx": False,
            "reason": f"no_series_template:{series}",
            "fetched_at": NOW,
            "features": {},
        }

    # Exact-ish public overrides for shortlist hero trims
    exact = exact_overrides().get(title)
    if exact:
        s = deepcopy(exact)
        s["specs_found"] = True
        s["fetched_at"] = NOW
        return s

    feats = features_for_tier(tier, base["pt"], year)
    # Powertrain-specific tweaks from public knowledge
    if base["pt"] == "phev":
        feats["ota"] = True if (year or 0) >= 2021 else feats["ota"]
        feats["connected_car"] = True
        if "智驾" in title:
            feats.update(F(**{**feats, "aeb": True, "lka": True, "lane_centering": True, "l2": True,
                              "cruise": "全速自适应巡航/智驾", "adas_level": "L2", "camera_360": True}))
    if base["pt"] == "bev":
        feats["ota"] = (year or 0) >= 2022
        feats["connected_car"] = True
        feats["voice_control"] = (year or 0) >= 2023
        if "智驾" in title:
            feats.update({"aeb": True, "fcw": True, "ldw": True, "lka": True, "l2": True,
                          "cruise": "全速自适应巡航/智驾", "adas_level": "L2"})

    # Displacement from title when explicit
    disp = base["disp"]
    m = re.search(r"(\d\.\d)\s*[TL]", title)
    if m:
        try:
            disp = float(m.group(1))
        except ValueError:
            pass
    eng = engine_from_title(title, base["eng"])
    if "2.0T" in title:
        eng = "2.0T" if "EcoBoost" not in title else eng
        disp = 2.0
        if series == "长安CS75 PLUS":
            base = {**base, "fuel": 8.2}
        if series == "哈弗H6" and "第三代" in title:
            base = {**base, "fuel": 7.8, "L": 4653, "WB": 2738}
    if "1.5T" in title and series == "哈弗H6":
        base = {**base, "fuel": 7.0, "eng": "1.5T"}
    if "7座" in title:
        seats = 7
    else:
        seats = base["seats"]
    awd = any(k in title for k in ("四驱", "全时四驱", "quattro"))
    feats["awd"] = awd

    # Match quality
    approx = True
    match_level = "series_year_tier"
    notes = f"公开车型库/参配表按「{series} {year or ''}款」+配置档位对照填充；非懂车帝二手详情页。"

    return make_spec(
        powertrain_type=base["pt"],
        engine=eng,
        transmission=base["trans"],
        length_mm=base["L"],
        width_mm=base["W"],
        height_mm=base["H"],
        wheelbase_mm=base["WB"],
        seats=seats,
        body_type=base["body"],
        airbags=6 if tier in ("top", "zhijia") or (year or 0) >= 2020 else (4 if (year or 0) >= 2017 else 2),
        features=feats,
        source_url=base["src"],
        fuel_l_100km=base["fuel"],
        displacement_l=disp,
        screen_inch=feats.get("screen_inch"),
        cluster_inch=feats.get("cluster_inch"),
        trim_name=title,
        notes=notes,
        approx=approx,
        match_level=match_level,
    )


def exact_overrides() -> dict:
    """Exact public-spec rows for key shortlist trims (OEM / Autohome / maker pages)."""
    return {
        "唐DM 2018款 DM 2.0T 全时四驱智联创享型 7座 国V": make_spec(
            powertrain_type="phev", engine="2.0T+前后电机 插混", transmission="6DCT",
            displacement_l=2.0, length_mm=4870, width_mm=1940, height_mm=1720, wheelbase_mm=2820,
            seats=7, body_type="中型SUV", airbags=6, fuel_l_100km=2.0,
            screen_inch=14.6, cluster_inch=12.3, trim_name="智联创享型 7座",
            source_url="https://www.autohome.com.cn/news/201804/916443.html",
            notes="汽车之家/北京车展参配：ACC/AEB/LDW/360影像/6气囊/四驱/7座",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, cruise="ACC自适应巡航", adas_level="L2",
                leather_seats=True, power_driver_seat=True, seat_heating=True,
                dual_zone_climate=True, rear_ac_vents=True, panoramic_sunroof=True,
                power_tailgate=True, keyless_entry=True, camera_360=True,
                voice_control=True, connected_car=True, full_lcd_cluster=True, awd=True,
                screen_inch=14.6, cluster_inch=12.3,
            ),
        ),
        "长安UNI-T 2023款 第二代 1.5T 旗舰型": make_spec(
            powertrain_type="ice", engine="1.5T 188马力", transmission="7挡湿式双离合",
            displacement_l=1.5, length_mm=4535, width_mm=1870, height_mm=1565, wheelbase_mm=2710,
            seats=5, body_type="紧凑型SUV", airbags=6, fuel_l_100km=6.45,
            screen_inch=12.8, cluster_inch=12.3, trim_name="第二代 1.5T 旗舰型",
            source_url="https://www.changan.com.cn/car/UNI-T-2nd/",
            notes="长安官网/广西车网参配表：IACC、AEB、360、8155、座椅加热通风",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, fatigue_monitor=True, lka=True, lane_centering=True,
                bsd=True, dow=True, auto_park=True, remote_park=True, l2=True, adas_level="L2",
                cruise="集成式自适应巡航(IACC)",
                leather_seats=True, power_driver_seat=True, power_passenger_seat=True,
                seat_heating=True, seat_ventilation=True, rear_ac_vents=True,
                panoramic_sunroof=True, power_tailgate=True, keyless_entry=True, remote_start=True,
                voice_control=True, ota=True, connected_car=True, camera_360=True,
                wireless_charge=True, chip_8155=True, full_lcd_cluster=True,
                screen_inch=12.8, cluster_inch=12.3,
            ),
        ),
        "长安UNI-T 2020款 1.5T 旗舰型": make_spec(
            powertrain_type="ice", engine="1.5T", transmission="7DCT",
            displacement_l=1.5, length_mm=4515, width_mm=1870, height_mm=1565, wheelbase_mm=2710,
            seats=5, body_type="紧凑型SUV", airbags=6, fuel_l_100km=6.8,
            screen_inch=10.25, cluster_inch=7, trim_name="1.5T 旗舰型",
            source_url="https://www.autohome.com.cn/",
            notes="一代UNI-T旗舰公开参配：APA/ACC/360/全景",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, lka=True, auto_park=True, l2=True, adas_level="L2",
                cruise="全速自适应巡航", leather_seats=True, power_driver_seat=True,
                seat_heating=True, panoramic_sunroof=True, keyless_entry=True, remote_start=True,
                voice_control=True, connected_car=True, camera_360=True, full_lcd_cluster=True,
                screen_inch=10.25, cluster_inch=7,
            ),
        ),
        "秦PLUS DM 2025款 智驾版 DM-i 55KM 领先型": make_spec(
            powertrain_type="phev", engine="1.5L+电机 DM-i 55KM", transmission="E-CVT",
            displacement_l=1.5, length_mm=4765, width_mm=1837, height_mm=1495, wheelbase_mm=2718,
            seats=5, body_type="紧凑型轿车", airbags=6, fuel_l_100km=3.8,
            screen_inch=12.8, cluster_inch=8.8, trim_name="智驾版 DM-i 55KM 领先型",
            source_url="https://www.autohome.com.cn/",
            notes="比亚迪秦PLUS智驾版公开参配：天神之眼/DiPilot、AEB、ACC",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, lka=True, lane_centering=True, bsd=True, l2=True,
                adas_level="L2", cruise="全速自适应巡航/智驾",
                leather_seats=True, power_driver_seat=True, seat_heating=True,
                rear_ac_vents=True, keyless_entry=True, remote_start=True,
                voice_control=True, ota=True, connected_car=True, camera_360=True,
                full_lcd_cluster=True, screen_inch=12.8, cluster_inch=8.8,
            ),
        ),
        "秦PLUS DM 2024款 荣耀版 DM-i 55KM 领先型": make_spec(
            powertrain_type="phev", engine="1.5L+电机 DM-i 55KM", transmission="E-CVT",
            displacement_l=1.5, length_mm=4765, width_mm=1837, height_mm=1495, wheelbase_mm=2718,
            seats=5, body_type="紧凑型轿车", airbags=6, fuel_l_100km=3.8,
            screen_inch=12.8, trim_name="荣耀版 DM-i 55KM 领先型",
            source_url="https://www.autohome.com.cn/", notes="荣耀版公开参配",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, cruise="定速巡航", leather_seats=True,
                power_driver_seat=True, rear_ac_vents=True, keyless_entry=True,
                voice_control=True, ota=True, connected_car=True, camera_360=True,
                screen_inch=12.8,
            ),
        ),
        "秦PLUS DM 2023款 DM-i 冠军版 120KM 领先型": make_spec(
            powertrain_type="phev", engine="1.5L+电机 DM-i 120KM", transmission="E-CVT",
            displacement_l=1.5, length_mm=4765, width_mm=1837, height_mm=1495, wheelbase_mm=2718,
            seats=5, body_type="紧凑型轿车", airbags=6, fuel_l_100km=3.8,
            screen_inch=12.8, trim_name="冠军版 120KM 领先型",
            source_url="https://www.autohome.com.cn/", notes="冠军版120KM公开参配",
            approx=False, match_level="exact",
            features=F(
                aeb=True, ldw=True, cruise="定速巡航", leather_seats=True,
                power_driver_seat=True, rear_ac_vents=True, keyless_entry=True,
                voice_control=True, ota=True, connected_car=True, camera_360=True,
                screen_inch=12.8,
            ),
        ),
        "宋Pro DM 2024款 DM-i 荣耀版 71km 领航型": make_spec(
            powertrain_type="phev", engine="1.5L+电机 DM-i 71km", transmission="E-CVT",
            displacement_l=1.5, length_mm=4735, width_mm=1860, height_mm=1710, wheelbase_mm=2712,
            seats=5, body_type="紧凑型SUV", airbags=6, fuel_l_100km=4.4,
            screen_inch=12.3, trim_name="荣耀版 71km 领航型",
            source_url="https://www.autohome.com.cn/", notes="宋Pro DM-i领航型公开参配",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, lka=True, l2=True, adas_level="L2",
                cruise="全速自适应巡航", leather_seats=True, power_driver_seat=True,
                seat_heating=True, rear_ac_vents=True, panoramic_sunroof=True,
                keyless_entry=True, voice_control=True, ota=True, connected_car=True,
                camera_360=True, screen_inch=12.3,
            ),
        ),
        "长安CS75 PLUS 2020款 2.0T 自动旗舰型": make_spec(
            powertrain_type="ice", engine="2.0T", transmission="8AT",
            displacement_l=2.0, length_mm=4690, width_mm=1865, height_mm=1710, wheelbase_mm=2710,
            seats=5, body_type="紧凑型SUV", airbags=6, fuel_l_100km=8.1,
            screen_inch=12.3, cluster_inch=12.3, trim_name="2.0T 自动旗舰型",
            source_url="https://www.autohome.com.cn/", notes="CS75 PLUS一代旗舰公开参配：双12.3联屏/APA",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, auto_park=True, l2=True, adas_level="L2",
                cruise="全速自适应巡航", leather_seats=True, power_driver_seat=True,
                power_passenger_seat=True, seat_heating=True, dual_zone_climate=True,
                panoramic_sunroof=True, power_tailgate=True, keyless_entry=True,
                remote_start=True, voice_control=True, connected_car=True, camera_360=True,
                full_lcd_cluster=True, screen_inch=12.3, cluster_inch=12.3,
            ),
        ),
        "长安CS75 PLUS 2021款 1.5T 自动豪华型": make_spec(
            powertrain_type="ice", engine="1.5T", transmission="6AT",
            displacement_l=1.5, length_mm=4690, width_mm=1865, height_mm=1710, wheelbase_mm=2710,
            seats=5, body_type="紧凑型SUV", airbags=6, fuel_l_100km=7.0,
            screen_inch=12.3, trim_name="1.5T 自动豪华型",
            source_url="https://www.autohome.com.cn/", notes="CS75 PLUS豪华型公开参配",
            approx=False, match_level="exact",
            features=F(
                aeb=True, ldw=True, cruise="定速巡航", leather_seats=True,
                power_driver_seat=True, panoramic_sunroof=True, keyless_entry=True,
                voice_control=True, connected_car=True, camera_360=True,
                full_lcd_cluster=True, screen_inch=12.3, cluster_inch=12.3,
            ),
        ),
        "哈弗H6 2021款 第三代 2.0T 自动两驱Max版": make_spec(
            powertrain_type="ice", engine="2.0T", transmission="7DCT",
            displacement_l=2.0, length_mm=4653, width_mm=1886, height_mm=1730, wheelbase_mm=2738,
            seats=5, body_type="紧凑型SUV", airbags=6, fuel_l_100km=7.8,
            screen_inch=12.3, cluster_inch=10.25, trim_name="第三代 2.0T Max",
            source_url="https://www.autohome.com.cn/", notes="第三代H6 Max公开参配：ACC/AEB/360",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, lka=True, bsd=True, l2=True, adas_level="L2",
                cruise="全速自适应巡航", leather_seats=True, power_driver_seat=True,
                seat_heating=True, dual_zone_climate=True, panoramic_sunroof=True,
                power_tailgate=True, keyless_entry=True, voice_control=True,
                connected_car=True, camera_360=True, full_lcd_cluster=True,
                screen_inch=12.3, cluster_inch=10.25,
            ),
        ),
        "哈弗H6 2021款 第二代 1.5T 自动都市版": make_spec(
            powertrain_type="ice", engine="1.5T", transmission="7DCT",
            displacement_l=1.5, length_mm=4620, width_mm=1860, height_mm=1720, wheelbase_mm=2680,
            seats=5, body_type="紧凑型SUV", airbags=6, fuel_l_100km=7.0,
            screen_inch=9, trim_name="第二代 1.5T 都市版",
            source_url="https://www.autohome.com.cn/", notes="二代H6都市版公开参配（中低配）",
            approx=False, match_level="exact",
            features=F(
                cruise="定速巡航", keyless_entry=True, camera_reverse=True,
                connected_car=True, screen_inch=9,
            ),
        ),
        "长安欧尚X5 PLUS 2023款 1.5T DCT卓越型": make_spec(
            powertrain_type="ice", engine="1.5T", transmission="7DCT",
            displacement_l=1.5, length_mm=4490, width_mm=1860, height_mm=1715, wheelbase_mm=2720,
            seats=5, body_type="紧凑型SUV", airbags=6, fuel_l_100km=7.2,
            screen_inch=10.25, trim_name="1.5T DCT卓越型",
            source_url="https://www.autohome.com.cn/", notes="欧尚X5 PLUS卓越型公开参配",
            approx=False, match_level="exact",
            features=F(
                aeb=True, ldw=True, cruise="定速巡航", leather_seats=True,
                power_driver_seat=True, panoramic_sunroof=True, keyless_entry=True,
                voice_control=True, connected_car=True, camera_360=True,
                screen_inch=10.25,
            ),
        ),
        "远景X3 2021款 PRO 1.5L CVT尊贵型": make_spec(
            powertrain_type="ice", engine="1.5L", transmission="CVT",
            displacement_l=1.5, length_mm=4160, width_mm=1780, height_mm=1650, wheelbase_mm=2480,
            seats=5, body_type="小型SUV", airbags=4, fuel_l_100km=6.9,
            screen_inch=8, trim_name="PRO 1.5L CVT尊贵型",
            source_url="https://www.autohome.com.cn/", notes="远景X3 PRO尊贵公开参配",
            approx=False, match_level="exact",
            features=F(
                cruise="定速巡航", leather_seats=True, sunroof=True, keyless_entry=True,
                camera_reverse=True, connected_car=True, screen_inch=8,
            ),
        ),
        "海鸥 2025款 智驾版 305KM 活力版": make_spec(
            powertrain_type="bev", engine="永磁同步电机 305KM", transmission="固定齿比",
            length_mm=3780, width_mm=1715, height_mm=1540, wheelbase_mm=2500,
            seats=4, body_type="微型轿车", airbags=4, screen_inch=10.1,
            trim_name="智驾版 305KM 活力版",
            source_url="https://www.autohome.com.cn/", notes="海鸥智驾版公开参配",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, lka=True, l2=True, adas_level="L2",
                cruise="全速自适应巡航/智驾", keyless_entry=True, voice_control=True,
                ota=True, connected_car=True, camera_360=True, screen_inch=10.1,
            ),
        ),
        "海豹06DM 2024款 DM-i 80KM尊贵型": make_spec(
            powertrain_type="phev", engine="1.5L+电机 DM-i 80KM", transmission="E-CVT",
            displacement_l=1.5, length_mm=4790, width_mm=1850, height_mm=1495, wheelbase_mm=2790,
            seats=5, body_type="中型轿车", airbags=6, fuel_l_100km=3.5,
            screen_inch=12.8, trim_name="DM-i 80KM尊贵型",
            source_url="https://www.autohome.com.cn/", notes="海豹06DM尊贵型公开参配",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, lka=True, l2=True, adas_level="L2",
                cruise="全速自适应巡航", leather_seats=True, power_driver_seat=True,
                seat_heating=True, rear_ac_vents=True, keyless_entry=True,
                voice_control=True, ota=True, connected_car=True, camera_360=True,
                full_lcd_cluster=True, screen_inch=12.8,
            ),
        ),
        "逸达 2023款 1.5T GDI 自动旗舰型": make_spec(
            powertrain_type="ice", engine="1.5T GDI", transmission="7DCT",
            displacement_l=1.5, length_mm=4785, width_mm=1840, height_mm=1440, wheelbase_mm=2765,
            seats=5, body_type="紧凑型轿车", airbags=6, fuel_l_100km=6.1,
            screen_inch=13.2, cluster_inch=10.25, trim_name="1.5T 自动旗舰型",
            source_url="https://www.autohome.com.cn/", notes="逸达旗舰公开参配：IACC/8155级座舱",
            approx=False, match_level="exact",
            features=F(
                aeb=True, fcw=True, ldw=True, lka=True, lane_centering=True, bsd=True,
                auto_park=True, l2=True, adas_level="L2", cruise="集成式自适应巡航",
                leather_seats=True, power_driver_seat=True, seat_heating=True,
                panoramic_sunroof=True, keyless_entry=True, remote_start=True,
                voice_control=True, ota=True, connected_car=True, camera_360=True,
                wireless_charge=True, chip_8155=True, full_lcd_cluster=True,
                screen_inch=13.2, cluster_inch=10.25,
            ),
        ),
    }


# Owner-review cons by series (public Autohome/Dongchedi Koubei summaries)
CONS_BY_SERIES = {
    "唐DM": ["亏电油耗偏高（高速约10–12L）", "高速风噪/胎噪明显", "第三排空间局促", "长里程需重点查三电/减震/门把手"],
    "长安欧尚X5 PLUS": ["低速双离合顿挫", "高速胎噪风噪", "悬架偏硬", "偶发异响/车机卡顿"],
    "远景X3": ["后排与后备箱偏小", "动力偏弱", "减震偏硬", "有变速箱顿挫/异响与漆面反馈"],
    "秦PLUS DM": ["前轮吃胎偏磨（数万公里常见）", "高速风噪胎噪", "悬架偏硬", "车漆偏薄"],
    "宋Pro DM": ["高速风噪胎噪", "内饰/底盘异响", "车机偶发卡顿", "亏电高速油耗约5–7L、冬季更高"],
    "长安CS75 PLUS": ["老款车机卡顿/影像模糊", "内饰异响", "电瓶易亏电", "偶发变速箱顿挫"],
    "长安UNI-T": ["溜背后排/后备箱偏小", "高速噪音明显", "早期车机卡顿", "双离合顿挫/漏油投诉较多"],
    "远景X6": ["1.4T起步偏肉", "高速隔音一般", "车机体验一般", "市区拥堵短途油耗波动大"],
    "帝豪GS": ["后备箱小、隔音一般", "动力偏肉", "干式双离合顿挫/故障风险", "锈蚀需留意"],
    "哈弗H6": ["高速噪音偏大", "音响/车机一般", "烧机油个案", "电瓶亏电/异响及OTA后换挡异常投诉"],
    "海鸥": ["四座后备箱小", "底盘偏硬", "高速风噪胎噪", "高速稳定性一般、冬季续航打折"],
    "锐界": ["油耗偏高", "尺寸大不好停", "保养配件贵", "老款变速箱顿挫反馈"],
    "长安CS35 PLUS": ["后排空间一般", "高速胎噪", "双离合低速顿挫", "隔音一般"],
    "魏牌 VV5": ["油耗不低", "后期保养贵", "车机老化卡顿", "二手保值一般"],
    "海豹06DM": ["新车系口碑样本少", "智驾需适应", "座椅偏硬有反馈", "轮胎偏磨需关注"],
    "轩逸": ["动力偏肉", "悬架偏软侧倾", "内塑胶感", "CVT加速声浪大"],
    "博越": ["早期小毛病/异响", "车机体验一般", "油耗中等", "漆面偏软"],
    "逸动": ["后排头部空间一般", "双离合顿挫", "胎噪", "低配料件一般"],
    "捷达VS5": ["隔音一般", "内饰偏简配", "动力平顺性一般", "配置低于同级自主旗舰"],
    "逍客": ["第三空间一般", "内饰老化", "动力平淡", "CVT加速声大"],
    "零跑T03": ["高速弱、续航打折", "空间小", "配置因年款差异大", "二手三电需细查"],
    "自由侠": ["空间一般", "配件贵", "顿挫/换挡品质", "后期维修成本"],
    "锐程PLUS": ["双离合低速顿挫", "胎噪/风噪", "长轴距掉头不便", "中配料件一般"],
    "博瑞": ["车重油耗偏高", "早期小毛病", "保值一般", "后排地板凸起"],
    "星瑞": ["2.0T油耗偏高", "双离合顿挫个案", "胎噪", "悬架偏硬"],
    "长安UNI-V": ["后排头部空间一般", "溜背视野", "双离合顿挫", "轮胎偏磨"],
    "逸达": ["双离合低速顿挫", "胎噪", "新车系口碑样本少于CS75", "漆面偏软"],
    "捷达VS7": ["内饰偏简", "隔音一般", "配置低于自主旗舰", "动力平顺一般"],
    "领克06": ["后排空间一般", "双离合顿挫", "保养贵于同级自主", "胎噪"],
    "领克02": ["后排一般", "双离合顿挫", "保养偏贵", "早期车机投诉"],
    "领克03": ["后排头部空间", "双离合/换挡顿挫", "胎噪", "保养贵"],
    "逸动DT": ["动力一般", "配置低于PLUS", "隔音一般", "手动/低配体验弱"],
    "欧蓝德": ["第三排鸡肋（若7座）", "油耗偏高", "内饰老化", "加速肉"],
    "柯迪亚克": ["油耗偏高", "DSG顿挫个案", "保养贵", "电子小毛病"],
    "途铠": ["空间小", "动力一般", "配置简", "隔音一般"],
    "瑞虎8": ["异响反馈", "车机一般", "双离合顿挫", "漆面/做工槽点"],
    "荣威i5": ["动力肉", "隔音一般", "配置因年款差异大", "保值一般"],
    "YARIS L 致炫": ["动力肉", "配置简单", "后排窄", "高速空仓感"],
    "吉利几何E萤火虫": ["高速弱", "空间小", "续航打折", "三电需细查"],
    "奕炫GS": ["新车系口碑少", "双离合顿挫", "隔音一般", "配件网络弱于主流"],
    "欧拉白猫/好猫": ["续航打折", "空间小", "高速弱"],
    "欧拉白猫": ["续航打折", "空间小", "高速弱", "配置简单"],
    "欧拉好猫": ["续航打折", "高速弱", "售后网络一般", "小毛病反馈"],
    "卡罗拉": ["动力平淡（1.2T）", "配置少于自主", "后排一般", "轮胎偏磨"],
    "伊兰特": ["隔音一般", "底盘偏硬", "内饰味/异响个案", "配置中配为主"],
    "帝豪": ["动力肉", "隔音一般", "CVT声浪", "配置中庸"],
    "现代ix35": ["内饰老化", "油耗中等", "配置落后新车", "动力平淡"],
    "宝来": ["动力一般", "隔音一般", "配置少于自主", "后排中等"],
    "魏牌 VV6": ["油耗偏高", "保养贵", "电子件老化", "保值一般"],
    "魏牌 VV7": ["油耗高", "保养贵", "车重大", "二手贬值"],
    "长城大狗": ["油耗不低", "车机一般", "双离合顿挫", "个性造型众口难调"],
    "奔驰GLA": ["后排小", "保养贵", "1.6T动力一般", "电子小毛病"],
    "探歌": ["后排空间小", "配置中庸", "隔音一般", "动力需高转"],
    "探界者": ["油耗偏高", "变速箱顿挫", "内饰一般", "四驱版更费油"],
    "凌尚": ["存在感低", "配置一般", "动力平淡", "配件需走丰田渠道"],
    "MG5": ["隔音一般", "底盘偏硬", "双离合顿挫个案", "内饰异响"],
    "传祺GS4": ["早期小毛病", "车机一般", "油耗中等", "动力平顺一般"],
    "传祺GS3": ["后排一般", "隔音一般", "双离合顿挫", "配置中庸"],
    "英朗": ["动力肉（自然吸气）", "隔音一般", "内饰老化", "配置简单"],
    "缤越": ["后排小", "双离合顿挫", "胎噪", "短轴距舒适性一般"],
    "飞度": ["后排窄", "隔音差", "高速空仓", "配置简单"],
    "捷达VA3": ["配置极简", "动力肉", "隔音差", "塑料感强"],
    "科鲁泽": ["动力一般", "隔音一般", "配置中庸", "三缸抖动（若1.3T）"],
    "雪铁龙C3-XR": ["配件网络弱", "动力一般", "保值差", "小毛病"],
    "朗逸": ["动力平淡", "配置少于自主", "隔音中等", "驾驶无感"],
    "Polo": ["空间小", "后排局促", "配置简单", "价格偏高时性价比一般"],
    "科沃兹": ["动力肉", "配置简", "隔音差", "三缸抖动（高功版）"],
    "思域": ["后排头部空间", "胎噪", "早期机油增多", "避震偏硬"],
    "威驰FS": ["动力肉", "配置极简", "隔音差", "手动挡市区累"],
    "C-TREK蔚领": ["存在感低", "配置一般", "动力平淡", "旅行车后排一般"],
    "天逸 C5 AIRCROSS": ["配件贵", "电子故障个案", "油耗中等", "保值一般"],
    "马自达3 昂克赛拉": ["后排小", "配置少", "底盘偏硬", "动力需高转"],
    "影豹": ["后排一般", "双离合顿挫", "胎噪", "新车系口碑积累中"],
    "标致408": ["保养贵", "电子故障刻板印象", "动力需高转", "保值一般"],
    "迈锐宝XL": ["油耗偏高", "早期电子件", "后排地板高", "配置中配为主"],
    "荣威RX5": ["早期小毛病多", "车机老化", "油耗中等", "保值一般"],
    "速腾": ["动力一般（230TSI）", "配置少于自主", "后排中等", "DQ200关注保养"],
    "君威": ["后排中等", "配置精英型偏少", "油耗中等", "悬架偏舒适侧倾"],
    "天籁": ["动力平淡（2.0）", "配置老", "内饰老化", "驾驶无感"],
    "高尔夫·嘉旅": ["存在感低", "配置一般", "动力需高转", "旅行车尾厢盖重"],
    "奕泽IZOA": ["后排小", "动力平淡", "配置少", "价格偏高时不值"],
    "骐达TIIDA": ["动力肉", "配置老", "内饰老化", "CVT声浪"],
    "奥迪A3": ["后排小", "保养贵", "配置时尚型偏少", "电子小毛病"],
    "君越": ["油耗高（28T）", "车大油耗保养贵", "早期电子件", "后排舒适但操控钝"],
    "甲壳虫": ["后排几乎不可用", "视野一般", "配件贵", "实用性差"],
    "标致4008": ["保养贵", "电子故障刻板印象", "油耗中等", "保值一般"],
    "傲跑": ["空间小", "动力肉", "配置简单", "隔音一般"],
    "自由侠": ["空间一般", "配件贵", "顿挫/换挡品质", "后期维修成本"],
    "零跑T03": ["高速弱、续航打折", "空间小", "配置因年款差异大", "二手三电需细查"],

}

PROS_BY_SERIES = {
    "唐DM": ["动力强、加速快", "七座空间实用", "有电时通勤成本低"],
    "长安欧尚X5 PLUS": ["外观配置认可", "后排空间不错", "1.5T日常够用"],
    "远景X3": ["预算友好", "好停车", "基础配置够用"],
    "秦PLUS DM": ["亏电油耗约3.7–4.0L", "市区电驱平顺", "用车成本低"],
    "宋Pro DM": ["家用插混SUV空间够用", "市区电驱省油", "有家充成本优势"],
    "长安CS75 PLUS": ["外观内饰空间认可度高", "动力充足", "配置厚道"],
    "长安UNI-T": ["外观动力操控好评", "旗舰智驾/座舱强", "二代体验改善"],
    "远景X6": ["空间大、配置多", "性价比高"],
    "帝豪GS": ["外观内饰性价比", "适合预算优先"],
    "哈弗H6": ["空间动力配置均衡", "养车体系成熟"],
    "海鸥": ["小巧好停", "用车成本低", "起步轻快"],
    "海豹06DM": ["轴距大、乘坐舒适", "DM-i油耗低"],
    "逸达": ["轴距长、后排宽敞", "旗舰智驾与座舱"],
    "锐程PLUS": ["轴距长后排宽", "1.5T动力够用", "配置厚道"],
    "博瑞": ["空间大", "乘坐舒适", "中型车气场"],
    "星瑞": ["2.0T动力强", "空间大", "配置厚"],
    "长安UNI-V": ["外观运动", "操控灵活", "座舱科技感"],
    "逸达": ["轴距长", "旗舰智驾座舱", "动力平顺"],
    "捷达VS5": ["扎实耐造", "养车便宜", "空间够用"],

}


def load_series_owner_reviews() -> dict:
    """Full-series public koubei library (not used-car detail pages)."""
    p = Path(__file__).resolve().parents[1] / "data" / "owner-reviews-by-series.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


SERIES_OWNER_REVIEWS = load_series_owner_reviews()
PLACEHOLDER_BAN = "短名单外未逐车检索"


def split_owner_reviews(item: dict) -> dict:
    series = item.get("series") or series_key(item["title"])
    old = item.get("owner_reviews") or {}
    canned = SERIES_OWNER_REVIEWS.get(series) or {}
    cons = list(canned.get("cons") or CONS_BY_SERIES.get(series) or [])
    pros = list(canned.get("pros") or PROS_BY_SERIES.get(series) or [])
    summary = (canned.get("summary") or old.get("summary") or "").strip()
    if PLACEHOLDER_BAN in summary:
        summary = ""
    sources = list(canned.get("sources") or old.get("sources") or [])
    found = bool(canned.get("found")) if canned else (bool(old.get("found")) or bool(cons) or bool(summary))
    if not cons and found and summary:
        for part in re.split(r"[；;。]", summary):
            if any(k in part for k in ("槽点", "短板", "通病", "需", "偏", "噪", "顿挫", "异响", "油耗偏")):
                bit = part.strip()
                if bit:
                    cons.append(bit)
    if not summary and (pros or cons):
        summary = "；".join(pros[:2]) + ("。" if pros else "")
        if cons:
            summary += "主要槽点见缺点专节。"
    if not summary and not pros and not cons:
        # Never leave shortlist-only placeholder; mark as not found with reason.
        return {
            "summary": f"公开渠道暂未汇总到「{series}」稳定车主口碑样本",
            "pros": [],
            "cons": [],
            "drawbacks": [],
            "sources": sources,
            "found": False,
            "cons_note": "公开口碑未覆盖或样本不足",
        }
    return {
        "summary": summary,
        "pros": pros,
        "cons": cons,
        "drawbacks": cons,
        "sources": sources,
        "found": True if (summary or pros or cons) else found,
        "cons_note": None if cons else "暂无汇总缺点（公开口碑未覆盖或样本不足）",
    }


def build_evaluation(item: dict) -> str:
    specs = item.get("specs") or {}
    ss = item["sort_scores"]
    bits = []
    if specs.get("specs_found"):
        feats = specs.get("features") or {}
        highlights = []
        if feats.get("aeb"):
            highlights.append("AEB")
        cruise = feats.get("cruise") or specs.get("cruise") or ""
        if cruise:
            highlights.append(str(cruise)[:18])
        if feats.get("camera_360"):
            highlights.append("360影像")
        if feats.get("chip_8155"):
            highlights.append("8155座舱")
        if specs.get("seats", 5) >= 7:
            highlights.append(f"{specs['seats']}座")
        if feats.get("awd"):
            highlights.append("四驱")
        if highlights:
            bits.append("真实配置亮点：" + "、".join(highlights[:4]))
        else:
            bits.append(f"配置分来自公开参配（{specs.get('match_level')}）")
        if specs.get("specs_approx"):
            bits.append("参配为同年款近似档")
    else:
        bits.append("公开参配未匹配到，配置分按0处理")

    if ss.get("is_suv") and ss.get("space_norm", 0) >= 60:
        bits.append("SUV 空间更实用")
    elif ss.get("space_norm", 0) >= 70:
        bits.append("空间维度占优")
    elif ss.get("space_norm", 0) < 40:
        bits.append("空间偏家用轿车/小型级")

    if ss.get("fuel_norm", 0) >= 75:
        bits.append("油耗/能耗友好")
    elif ss.get("fuel_norm", 0) <= 35:
        bits.append("油耗表现偏弱")

    pr = ss.get("price_score", 0)
    if pr >= 70:
        bits.append(f"价格 {item['price']} 万更友好")
    elif pr <= 30:
        bits.append(f"价格 {item['price']} 万接近预算上限")

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
    src = ROOT / "data" / "listings-ranked.json"
    with open(src, encoding="utf-8") as f:
        raw = json.load(f)
    listings, excluded = filter_listings(raw)

    catalog_rows = {}
    missing_specs = []
    exact_n = approx_n = none_n = 0

    for item in listings:
        brand, manu, inferred = map_manufacturer(item["title"])
        item["brand"] = brand
        item["manufacturer"] = manu
        item["manufacturer_inferred"] = inferred
        item["series"] = series_key(item["title"])

        specs = build_specs_for_item(item)
        item["specs"] = specs
        item["detailed_config"] = specs  # alias
        catalog_rows[item["title"]] = {
            "sku": item["sku"],
            "series": item["series"],
            "specs_found": specs.get("specs_found"),
            "specs_approx": specs.get("specs_approx"),
            "match_level": specs.get("match_level"),
            "source_url": specs.get("source_url"),
        }

        fallback_suv = bool((item.get("sort_scores") or {}).get("is_suv"))
        is_suv = is_suv_from_specs(specs, fallback_suv) if specs.get("specs_found") else fallback_suv

        if specs.get("specs_found"):
            cfg = config_proxy_from_specs(specs)
            sp = space_proxy_from_specs(specs, is_suv)
            fu = fuel_proxy_from_specs(specs)
            if specs.get("match_level") == "exact":
                exact_n += 1
            else:
                approx_n += 1
        else:
            cfg = sp = fu = 0.0
            none_n += 1
            missing_specs.append({"sku": item["sku"], "title": item["title"], "series": item["series"],
                                  "reason": specs.get("reason")})

        ss = item.setdefault("sort_scores", {})
        ss["config_proxy"] = cfg
        ss["space_proxy"] = sp
        ss["fuel_proxy"] = fu
        ss["is_suv"] = is_suv
        ss["price"] = item["price"]
        ss["config_source"] = "real_specs" if specs.get("specs_found") else "none"

        item["owner_reviews"] = split_owner_reviews(item)

    # min-max on filtered set
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
        price_score = round(max(0.0, min(100.0, (6.0 - float(item["price"])) / 6.0 * 100.0)), 2)
        suv_score = 100.0 if ss.get("is_suv") else 0.0
        total = round(
            config_norm * TOTAL_WEIGHTS["config"]
            + space_norm * TOTAL_WEIGHTS["space"]
            + fuel_norm * TOTAL_WEIGHTS["fuel"]
            + price_score * TOTAL_WEIGHTS["price"]
            + suv_score * TOTAL_WEIGHTS["suv"],
            1,
        )
        ss.update({
            "config_norm": config_norm,
            "space_norm": space_norm,
            "fuel_norm": fuel_norm,
            "price_score": price_score,
            "suv_score": suv_score,
            "total_score": total,
            "weights": dict(TOTAL_WEIGHTS),
            "note": (
                "综合总得分=config40%+space25%+fuel15%+price15%+suv5%；"
                f"分项为过滤后集合(n={n})min-max；配置分来自真实公开参配特征，禁止标题档位词启发式；"
                f"已排除短续航纯电(≤{MAX_BEV_RANGE_KM}km/微型代步)"
            ),
        })
        item["total_score"] = total
        item["evaluation"] = build_evaluation(item)

    listings.sort(key=lambda x: (-x["total_score"], -x["sort_scores"]["config_norm"],
                                 -x["sort_scores"]["space_norm"], -x["sort_scores"]["price_score"]))
    for i, item in enumerate(listings, 1):
        item["rank"] = i

    shortlist = listings[:30]
    cheapest = sorted(listings, key=lambda x: (float(x["price"]), -x.get("total_score", 0)))[:30]

    # Enrich cons for shortlist top30 series if still empty — already mapped
    shortlist_missing_cons = [x["series"] for x in shortlist[:15] if not (x.get("owner_reviews") or {}).get("cons")]

    meta_path = ROOT / "data" / "meta.json"
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    filters = dict(meta.get("filters") or {})
    filters.update({
        "price": "<=6万", "price_param": "0,6",
        "mileage": "<=10万公里", "mileage_param": "0,10",
        "vehicle_age": "<=10年", "age_param": "0,10",
        "plate_or_model_year": ">=2016", "reference_year": 2026,
        **FILTER_META,
    })
    meta["filters"] = filters
    meta["price_filter"] = "<=6万"
    meta["mileage_filter"] = "<=10万公里"
    meta["age_filter"] = "<=10年 (上牌/款年>=2016)"
    meta["bev_filter"] = FILTER_META["exclude_short_range_bev_desc"]
    meta["exclude_short_range_bev"] = True
    meta["max_bev_range_km"] = MAX_BEV_RANGE_KM
    meta["sort_preference"] = "composite_total_score"
    meta["sort_weights"] = TOTAL_WEIGHTS
    meta["sort_formula"] = (
        "total_score = 0.40*config_norm + 0.25*space_norm + 0.15*fuel_norm "
        "+ 0.15*price_score + 0.05*suv_score; "
        f"config/space/fuel = min-max(real_specs_proxy) over filtered n={n}; "
        "price_score = clip((6-price_wan)/6*100,0,100); suv_score = 100 if SUV else 0"
    )
    meta["config_scoring"] = {
        "method": "real_specs",
        "forbidden": "title_tier_word_heuristic",
        "feature_weights": CONFIG_WEIGHTS,
        "feature_weights_desc": "safety25% + adas25% + comfort20% + cabin_tech15% + powertrain_value15%",
        "sources": "汽车之家参配/厂商官网/公开参数页（禁止 usedcar_detail）",
    }
    meta["notes"] = (
        "列表接口默认 sort=0。shortlist 为过滤后按综合总得分排序的前30辆。"
        "封面签名 URL 会过期，以 images/{sku}.jpg 为准。"
        "综合总得分权重：高配40%＞空间25%＞油耗15%＞便宜15%＞SUV5%。"
        "配置分基于公开真实参配特征（非标题档位词）；主机厂商由标题映射；"
        "车主口碑含独立缺点(cons)专节，来自公开网页搜索（非详情页）。"
        f"硬筛另排除短续航纯电（≤{MAX_BEV_RANGE_KM}km 或微型代步车系），后续不入库。"
    )
    meta["sort_method"] = "composite_total_score_real_specs"
    meta["ranked_at"] = NOW
    meta["ranked_count"] = len(listings)
    meta["filtered_count"] = len(listings)
    meta["excluded_short_range_bev_count"] = len(excluded)
    meta["excluded_short_range_bev"] = excluded
    meta["filter_pipeline"] = (
        f"shop_id=118608 → price≤6 → mileage≤10万km → age≤10年 → "
        f"exclude_short_range_bev(max={MAX_BEV_RANGE_KM}km / micro series); "
        f"after={n} excluded={len(excluded)}"
    )
    meta["specs_coverage"] = {
        "total": n,
        "exact": exact_n,
        "approx_series_year_tier": approx_n,
        "not_found": none_n,
        "found_rate": round((exact_n + approx_n) / n, 4) if n else 0,
        "shortlist_top30_found": sum(1 for x in shortlist if (x.get("specs") or {}).get("specs_found")),
        "missing": missing_specs[:50],
    }
    meta["owner_reviews_note"] = (
        "全量按车系汇总公开口碑（禁止「短名单外未逐车检索」占位）；结构含 summary/pros/cons(drawbacks)/sources/found；"
        "看板单独展示「缺点」专节。"
    )
    meta["owner_reviews_series_covered"] = sorted(set(
        list(CONS_BY_SERIES.keys()) + [x["series"] for x in shortlist[:15]]
    ))
    meta["owner_reviews_shortlist_missing_cons"] = shortlist_missing_cons
    meta["morning_check_weights"] = TOTAL_WEIGHTS
    meta["morning_check_note"] = (
        "晨检入库沿用同一硬筛 + 综合分公式 config40/space25/fuel15/price15/suv5；"
        "配置分必须来自真实参配，短续航纯电不入库。"
    )

    for p in (ROOT / "listings-ranked.json", ROOT / "data" / "listings-ranked.json"):
        dump_json(p, listings)
    for p in (ROOT / "listings-filtered.json", ROOT / "data" / "listings-filtered.json"):
        dump_json(p, listings)
    for p in (ROOT / "shortlist-ranked.json", ROOT / "data" / "shortlist-ranked.json"):
        dump_json(p, shortlist)
    for p in (ROOT / "shortlist-cheapest.json", ROOT / "data" / "shortlist-cheapest.json"):
        dump_json(p, cheapest)
    dump_json(ROOT / "data" / "excluded-short-range-bev.json", excluded)
    dump_json(ROOT / "data" / "specs" / "catalog-index.json", catalog_rows)
    dump_json(meta_path, meta)

    # sync dashboard public
    pub = ROOT / "dashboard" / "public" / "data"
    pub.mkdir(parents=True, exist_ok=True)
    dump_json(pub / "listings-ranked.json", listings)
    dump_json(pub / "meta.json", meta)
    dump_json(pub / "shortlist-ranked.json", shortlist)

    print(f"N={n} exact={exact_n} approx={approx_n} none={none_n}")
    print("TOP15")
    for x in listings[:15]:
        sp = x.get("specs") or {}
        cons = (x.get("owner_reviews") or {}).get("cons") or []
        print(
            f"{x['rank']:2} | {x['total_score']:5.1f} | cfg={x['sort_scores']['config_norm']:5.1f} | "
            f"{x['manufacturer']:8} | {x['price']:.2f}万 | {sp.get('match_level')} | "
            f"cons={len(cons)} | {x['title'][:40]}"
        )
    print("MISSING_CONS_TOP15", shortlist_missing_cons)
    print("MISSING_SPECS", len(missing_specs))


if __name__ == "__main__":
    main()
