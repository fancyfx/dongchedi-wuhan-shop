#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import autohome_exact_rules as rules  # noqa: E402
import sync_exact_trim_specs as base  # noqa: E402
from ranking_v2.apply_verified import apply_verified_record  # noqa: E402
from ranking_v2.config_score import config_score  # noqa: E402
from ranking_v2.energy import resolve_ranking_energy  # noqa: E402


def test_critical_identity_rejects_wrong_powertrain():
    assert not rules.critical_identity_compatible(
        "英朗 2018款 18T 自动精英型",
        "英朗 2018款 15T 手动精英型",
    )
    assert rules.critical_identity_compatible(
        "传祺GS4 2017款 235T 手动两驱舒适版",
        "传祺GS4 2017款 235T 手动两驱舒适版",
    )
    assert not rules.critical_identity_compatible(
        "海鸥 2025款 405KM 飞翔版",
        "海鸥 2025款 305KM 活力版",
    )
    assert rules.critical_identity_compatible(
        "星瑞 2023款 2.0T 尊贵型",
        "星瑞 2023款 2.0TD 尊贵型",
    )


def test_legacy_aliases_raise_real_coverage_and_energy():
    rows = {
        "车型名称": "测试SUV 2019款 1.5T 自动尊贵版",
        "厂商指导价(元)": "12.88万",
        "能源类型": "汽油",
        "级别": "紧凑型SUV",
        "座位数(个)": "5",
        "发动机": "1.5T 169马力 L4",
        "变速箱": "7挡双离合",
        "长*宽*高(mm)": "4600*1860*1700",
        "轴距(mm)": "2720",
        "燃油标号": "92号",
        "工信部综合油耗(L/100km)": "7.2",
        "主/副驾驶座安全气囊": "主● / 副●",
        "前/后排侧气囊": "前● / 后-",
        "前/后排头部气囊(气帘)": "前● / 后●",
        "车身稳定控制(ESC/ESP/DSC等)": "●",
        "主动刹车/主动安全系统": "●",
        "并线辅助": "-",
        "自适应巡航": "●",
        "定速巡航": "●",
        "全景摄像头": "●",
        "前/后驻车雷达": "前● / 后●",
        "自动泊车入位": "-",
        "主/副驾驶座电动调节": "主● / 副●",
        "前/后排座椅加热": "前● / 后-",
        "前/后排座椅通风": "前- / 后-",
        "全景天窗": "●",
        "电动天窗": "●",
        "电动后备厢": "●",
        "无钥匙进入系统": "●",
        "远程启动": "-",
        "后座出风口": "●",
        "温度分区控制": "●",
        "空调控制方式": "自动空调",
        "座椅材质": "仿皮",
        "全液晶仪表盘": "●",
        "中控台彩色大屏尺寸": "12.3英寸",
        "手机互联/映射": "●",
        "手机无线充电": "-",
        "HUD抬头数字显示": "-",
        "自动头灯": "●",
        "自适应远近光": "-",
    }
    canonical = rules.canonicalize_rows(rows)
    trim = base.build_trim(canonical["车型名称"], 999001, 999, canonical, 1.0)
    trim = rules.enrich_trim(trim, canonical)
    trim["trim_id"] = "trim_test_autohome"
    item = apply_verified_record({"sku": "test", "price": 5.0}, {"trim": trim})
    cfg = config_score(item["specs"])
    energy = resolve_ranking_energy(item["specs"])
    assert cfg["coverage"] >= 0.60, cfg
    assert energy["raw_ranking_energy"]["value"] == 7.2, energy
    assert energy["value"] == 8.64, energy
    assert energy["type"] == "official_nedc_with_uncertainty", energy
    assert item["specs"]["features"]["camera_360"] is True
    assert item["specs"]["features"]["front_radar"] is True
    assert item["specs"]["features"]["rear_radar"] is True


def _cand(title: str, spec_id: int, rows: dict | None = None):
    return SimpleNamespace(title=title, spec_id=spec_id, rows=rows or {})


def test_identity_fallback_uses_trim_power_gearbox_wheelbase():
    """Fallback identity only. First-pass title score and thresholds stay unchanged."""
    chosen, reason, basis = rules.identity_choose(
        "逸达 2023款 1.5T GDI 自动旗舰型",
        "逸达",
        [
            _cand("逸达 2023款 蓝鲸NE 1.5T GDI DCT旗舰型", 60082),
            _cand("逸达 2023款 蓝鲸NE 1.5T GDI DCT豪华型", 60080),
        ],
    )
    assert chosen is not None and chosen.spec_id == 60082, (reason, basis)
    assert "档位" in basis and "动力" in basis and "变速箱" in basis

    chosen, reason, basis = rules.identity_choose(
        "轩逸 2019款 1.6XV CVT智联尊享版 国VI",
        "轩逸",
        [
            _cand("轩逸 2019款 1.6XV CVT智联尊享版 国V", 1),
            _cand("轩逸 2019款 1.6XV CVT智联尊享版 国VI", 36081),
        ],
    )
    assert chosen is not None and chosen.spec_id == 36081 and "排放" in basis, reason

    chosen, reason, _basis = rules.identity_choose(
        "瑞虎8 2020款 改款 290TGDI 自动精英版",
        "瑞虎8",
        [
            _cand("瑞虎8 2020款 改款 1.5TCI 自动精英版", 1),
            _cand("瑞虎8 2020款 1.5TCI 自动豪华版", 2),
        ],
    )
    assert chosen is None and reason == "critical_identity_mismatch"

    chosen, reason, _basis = rules.identity_choose(
        "瑞虎8 2020款 改款 290TGDI 自动精英版",
        "瑞虎8",
        [
            _cand("瑞虎8 2020款 改款 290TGDI 自动精英版", 51178),
            _cand("瑞虎8 2020款 改款 1.5TCI 自动精英版", 1),
        ],
    )
    assert chosen is not None and chosen.spec_id == 51178, reason

    chosen, reason, _basis = rules.identity_choose(
        "轩逸 2024款 改款三 经典 1.6L XE CVT舒适版",
        "轩逸",
        [
            _cand("轩逸 2024款 改款 经典 1.6XE CVT舒适版", 70177),
            _cand("轩逸 2024款 改款二 经典 1.6XE CVT舒适版", 71105),
            _cand("轩逸 2024款 改款三 经典 1.6XE CVT舒适版", 73729),
        ],
    )
    assert chosen is not None and chosen.spec_id == 73729, reason

    chosen, reason, _basis = rules.identity_choose(
        "英朗 2018款 18T 自动精英型",
        "英朗",
        [_cand("英朗 2018款 15T 自动精英型", 9)],
    )
    assert chosen is None and reason == "critical_identity_mismatch"

    chosen, reason, _basis = rules.identity_choose(
        "博越 2020款 1.5TD 自动智联PRO",
        "博越",
        [
            _cand("博越 2020款 1.5TD 自动智慧PRO", 1),
            _cand("博越 2020款 1.5TD 自动智联PRO", 41024),
        ],
    )
    assert chosen is not None and chosen.spec_id == 41024, reason

    chosen, reason, _basis = rules.identity_choose(
        "哈弗H6 2021款 1.5GDIT 自动都市版",
        "哈弗H6",
        [_cand("哈弗H6 2021款 1.5T 自动都市版", 47054, {"发动机": "1.5T 169马力 L4"})],
    )
    assert chosen is None and reason == "critical_identity_mismatch", reason

    chosen, reason, _basis = rules.identity_choose(
        "捷达VS5 2019款 280TSI 自动悦享版",
        "捷达VS5",
        [
            _cand("捷达VS5 2019款 280TSI 自动悦享型", 41219),
            _cand("捷达VS5 2019款 280TSI 自动悦享型Pro", 50001),
        ],
    )
    assert chosen is not None and chosen.spec_id == 41219, reason

    chosen, reason, _basis = rules.identity_choose(
        "捷达VS5 2022款 280TSI 自动悦享版Pro",
        "捷达VS5",
        [
            _cand("捷达VS5 2022款 280TSI 自动悦享型", 1),
            _cand("捷达VS5 2022款 280TSI 自动悦享型Pro", 54454),
        ],
    )
    assert chosen is not None and chosen.spec_id == 54454, reason

    chosen, reason, _basis = rules.identity_choose(
        "探界者 2017款 535T 自动四驱拓界版",
        "探界者",
        [
            _cand("探界者 2017款 RS 535T 自动四驱拓界版", 31489),
            _cand("探界者 2017款 535T 自动四驱拓界版", 30053),
        ],
    )
    assert chosen is not None and chosen.spec_id == 30053, reason

    chosen, reason, basis = rules.identity_choose(
        "哈弗H6 2021款 第二代 1.5T 自动都市版",
        "哈弗H6",
        [
            _cand("哈弗H6 2021款 1.5T 自动都市版", 47052, {"轴距(mm)": "2680"}),
            _cand("哈弗H6 2021款 国潮版 1.5T 自动都市版", 50164, {"轴距(mm)": "2680"}),
            _cand("哈弗H6 2021款 1.5GDIT 自动都市版", 47054, {"发动机": "1.5T 169马力 L4"}),
        ],
        listing_wheelbase=2680,
    )
    assert chosen is not None and chosen.spec_id == 50164, (reason, basis)
    assert "第二代=国潮版" in basis and "轴距" in basis

    # The 国潮 alias is H6-only. Elsewhere an exact residual beats a prefixed one.
    chosen, reason, _basis = rules.identity_choose(
        "其他 2021款 第二代 1.5T 自动都市版",
        "其他",
        [
            _cand("其他 2021款 1.5T 自动都市版", 1),
            _cand("其他 2021款 国潮版 1.5T 自动都市版", 2),
        ],
    )
    assert chosen is not None and chosen.spec_id == 1, reason

    chosen, reason, _basis = rules.identity_choose(
        "博瑞 2021款 1.8T 领航版",
        "博瑞",
        [
            _cand("博瑞 2021款 1.8T 领航版+", 1),
            _cand("博瑞 2021款 1.8T 领航版", 46863),
        ],
    )
    assert chosen is not None and chosen.spec_id == 46863, reason

    chosen, reason, _basis = rules.identity_choose(
        "星瑞 2023款 2.0T 尊贵型",
        "星瑞",
        [_cand("星瑞 2023款 2.0TD 尊贵型", 7)],
    )
    assert chosen is not None and chosen.spec_id == 7, reason

    chosen, reason, basis = rules.identity_choose(
        "示例 2020款 1.5T 自动舒适版",
        "示例",
        [
            _cand("示例 2020款 1.5T 自动舒适版", 11, {"轴距(mm)": "2600"}),
            _cand("示例 2020款 1.5T 自动舒适版", 12, {"轴距(mm)": "2700"}),
        ],
        listing_wheelbase=2605,
    )
    assert chosen is not None and chosen.spec_id == 11 and "轴距" in basis, reason

    # A unique exact title is kept when the backfilled wheelbase disagrees.
    chosen, reason, basis = rules.identity_choose(
        "示例 2020款 1.5T 自动舒适版",
        "示例",
        [_cand("示例 2020款 1.5T 自动舒适版", 11, {"轴距(mm)": "2700"})],
        listing_wheelbase=2600,
    )
    assert chosen is not None and chosen.spec_id == 11 and "轴距" not in basis, (reason, basis)

    chosen, reason, basis = rules.identity_choose(
        "秦PLUS DM 2023款 DM-i 冠军版 120KM 领先型",
        "秦PLUS DM",
        [
            _cand("秦PLUS 2023款 冠军版 DM-i 55KM领先型", 61527),
            _cand("秦PLUS 2023款 冠军版 DM-i 120KM领先型", 61235),
            _cand("秦PLUS 2023款 冠军版 EV 420KM领先型", 62385),
        ],
    )
    assert chosen is not None and chosen.spec_id == 61235, reason
    assert "续航" in basis

    chosen, reason, _basis = rules.identity_choose(
        "秦PLUS DM 2025款 智驾版 DM-i 55KM 领先型",
        "秦PLUS DM",
        [_cand("秦PLUS 2025款 DM-i 智驾版 55KM领先型", 71504)],
    )
    assert chosen is not None and chosen.spec_id == 71504, reason

    chosen, reason, _basis = rules.identity_choose(
        "唐DM 2018款 DM 2.0T 全时四驱智联创享型 7座 国V",
        "唐DM",
        [
            _cand("唐新能源 2018款 DM 2.0T 全时四驱智联创享型 5座 国V", 36857),
            _cand("唐新能源 2018款 DM 2.0T 全时四驱智联创享型 7座 国V", 35062),
            _cand("唐 2018款 2.0T 自动智联创享型", 99999),
        ],
    )
    assert chosen is not None and chosen.spec_id == 35062, reason

    # 改款 is a different facelift from 马赫版, so it must not be attached.
    chosen, reason, _basis = rules.identity_choose(
        "奕炫 2023款 改款 1.5L 自动追风版",
        "奕炫",
        [_cand("奕炫 2023款 马赫版 1.5L 自动追风版", 59144)],
    )
    assert chosen is None, reason
    assert reason in {"generation_conflict", "exact_trim_similarity_below_threshold"}


if __name__ == "__main__":
    test_critical_identity_rejects_wrong_powertrain()
    test_legacy_aliases_raise_real_coverage_and_energy()
    test_identity_fallback_uses_trim_power_gearbox_wheelbase()
    print("autohome exact field/identity rules tests passed")
