"""V3 score weights, anchors, energy prices, finance reserve."""
from __future__ import annotations

SCORE_VERSION = "v3.2.0"

WEIGHTS = {
    "config": 0.28,
    "space": 0.20,
    "powertrain": 0.20,
    "condition": 0.18,
    "value_price": 0.14,
}

# V3.2 SUV-first modern cabin + realistic depreciation anchors
# Cap discount bonus around ~3.2 fold so inflated-MSRP old models cannot game rankings.
VALUE_DISCOUNT_POINTS = [
    (0.32, 90),
    (0.38, 82),
    (0.45, 70),
    (0.55, 55),
    (0.68, 38),
]

VALUE_PRICE_POINTS = [
    (2.5, 100),
    (3.5, 92),
    (4.2, 84),
    (4.8, 74),
    (5.3, 62),
    (5.7, 50),
    (6.0, 38),
]

V3_MILEAGE_POINTS = [
    (0, 100),
    (1.5, 99),
    (3.0, 92),
    (4.5, 82),
    (5.5, 70),
    (6.5, 55),
    (8.0, 34),
    (10.0, 12),
]

V3_AGE_POINTS_YEARS = [
    (0, 100),
    (2, 97),
    (4, 88),
    (5, 79),
    (6, 66),
    (7, 50),
    (8, 34),
    (9, 20),
    (10, 10),
]

V3_WHEELBASE_POINTS = [
    (2500, 35),
    (2600, 55),
    (2680, 75),
    (2730, 86),
    (2800, 95),
    (2900, 100),
]

V3_WIDTH_POINTS = [
    (1720, 25),
    (1800, 58),
    (1840, 74),
    (1880, 90),
    (1920, 100),
]

V3_HEIGHT_POINTS = [
    (1430, 35),
    (1480, 48),
    (1560, 68),
    (1650, 86),
    (1720, 96),
    (1800, 100),
]

V3_CONFIG_CURVE_POINTS = [
    (0, 10),
    (20, 30),
    (40, 52),
    (55, 68),
    (70, 82),
    (85, 94),
    (100, 100),
]

BUDGET = {
    "hard_max_wan": 6.0,
    "full_price_score_wan": 3.0,
}

FINANCE = {
    "unknown_all_in_reserve_wan": 0.5,
}

ENERGY = {
    "default_scenario": "no_home_charging",
    "gas_92_yuan_l": 8.0,
    "gas_95_yuan_l": 8.5,
    "home_electricity_yuan_kwh": 0.8,
    "public_electricity_yuan_kwh": 1.5,
    "wltc_fallback_multiplier": 1.15,
    "nedc_fallback_multiplier": 1.20,
    "real_world_min_n": 20,
}

CONFIG_POINTS = {
    "airbags_6plus": 8,
    "esp": 3,
    "aeb": 10,
    "fcw": 4,
    "lka": 5,
    "lane_centering": 4,
    "bsd": 5,
    "dow": 3,
    "acc": 6,
    "camera_360": 6,
    "radar_front_rear": 3,
    "auto_park": 3,
    "power_driver_seat": 2,
    "power_passenger_seat": 2,
    "seat_heating": 3,
    "seat_ventilation": 5,
    "panoramic_sunroof": 2,
    "power_tailgate": 3,
    "keyless_entry": 1,
    "remote_start": 1,
    "rear_ac_vents": 2,
    "dual_zone_climate": 2,
    "leather_seats": 1,
    "full_lcd_cluster": 3,
    "screen_12plus": 3,
    "phone_link": 2,
    "wireless_charge": 2,
    "voice_control": 2,
    "ota": 2,
    "hud": 3,
    "chip_8155": 3,
}
CONFIG_POINTS_MAX = sum(CONFIG_POINTS.values())

MILEAGE_POINTS = [
    (0, 100),
    (1, 100),
    (2, 95),
    (3, 90),
    (4, 82),
    (5, 72),
    (6, 62),
    (8, 42),
    (10, 20),
]

AGE_POINTS_YEARS = [
    (0, 100),
    (2, 100),
    (3, 90),
    (4, 80),
    (5, 68),
    (6, 55),
    (8, 30),
    (10, 10),
]

ENERGY_COST_POINTS = [
    (0, 100),
    (15, 100),
    (20, 95),
    (30, 85),
    (40, 70),
    (50, 55),
    (60, 40),
    (70, 25),
    (80, 10),
    (90, 0),
]

WHEELBASE_POINTS = [
    (2500, 20),
    (2600, 40),
    (2700, 65),
    (2800, 90),
    (2900, 100),
]

WIDTH_POINTS = [
    (1700, 20),
    (1800, 55),
    (1850, 75),
    (1900, 90),
    (1950, 100),
]

LENGTH_POINTS = [
    (3800, 10),
    (4300, 35),
    (4600, 65),
    (4800, 85),
    (5000, 100),
]

TRUNK_POINTS = [
    (300, 30),
    (400, 55),
    (500, 80),
    (600, 100),
]

SPACE_WEIGHTS = {
    "wheelbase": 0.45,
    "width": 0.25,
    "length": 0.15,
    "trunk": 0.15,
}

# Legacy list retained for scraper sanitization only. Ranking V3 does not
# inherit approximate configuration; exact-trim V3 data is authoritative.
ADVANCED_FEATURE_KEYS = (
    "aeb",
    "fcw",
    "ldw",
    "lka",
    "lane_centering",
    "bsd",
    "dow",
    "acc",
    "auto_park",
    "remote_park",
    "camera_360",
    "transparent_chassis",
    "seat_heating",
    "seat_ventilation",
    "power_driver_seat",
    "power_passenger_seat",
    "hud",
    "wireless_charge",
    "power_tailgate",
    "chip_8155",
    "l2",
    "highway_assist",
    "fatigue_monitor",
)
