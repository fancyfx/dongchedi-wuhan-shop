#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

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


if __name__ == "__main__":
    test_critical_identity_rejects_wrong_powertrain()
    test_legacy_aliases_raise_real_coverage_and_energy()
    print("autohome exact field/identity rules tests passed")
