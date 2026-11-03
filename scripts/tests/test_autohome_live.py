#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import autohome_exact_rules as rules
import autohome_live_config as live
import sync_exact_trim_specs as base
import sync_exact_trim_specs_autohome as ah
from ranking_v2.apply_verified import _verified_specs_from_trim
from ranking_v2.config_score import config_score
from ranking_v2.data_quality import assess_score_eligibility


FIXTURE = ROOT / "scripts" / "fixtures" / "autohome_live_49472_rows.json"


def test_live_fixture_h6_coverage_above_threshold():
    rows = rules.canonicalize_rows(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert rows.get("前方碰撞预警") == "●"
    assert "全景" in str(rows.get("天窗类型") or "")
    assert rows.get("巡航系统") and "巡航" in rows["巡航系统"]
    cand = ah.Candidate(
        spec_id=49472,
        title="哈弗H6 2021款 第三代 2.0T 自动两驱Max",
        rows=rows,
        source_path="live:config/spec/49472.html",
        snapshot="live",
        series_id=2123,
    )
    trim_id, trim = ah.build_autohome_trim(cand, 1.0)
    trim = rules.enrich_trim(trim, rows)
    assert trim_id.startswith("trim_ah_")
    assert trim["features"]["active_safety"]["fcw"] is True
    assert trim["features"]["active_safety"]["aeb"] is True
    assert trim["features"]["active_safety"]["esp"] is True
    assert trim["features"]["parking_adas"]["surround_360"] is True
    specs = _verified_specs_from_trim(trim)
    coverage = float(config_score(specs)["coverage"])
    assert coverage >= 0.60, coverage
    item = {
        "sku": "357301752",
        "title": "哈弗H6 2021款 第三代 2.0T 自动两驱Max版",
        "price": 5.19,
        "effective_price_wan": 5.19,
        "mileage_wan": 2.49,
        "plate_year": 2021,
        "model_year": 2021,
        "specs": specs,
        "detailed_config": specs,
    }
    gate = assess_score_eligibility(item)
    assert gate["eligible"] is True, gate


def test_merge_prefer_live_keeps_vault_fallback():
    vault = {"稀有字段": "●", "前方碰撞预警": ""}
    live_rows = {"前方碰撞预警": "●", "天窗类型": "可开启全景天窗"}
    merged = live.merge_prefer_live(vault, live_rows)
    assert merged["稀有字段"] == "●"
    assert merged["前方碰撞预警"] == "●"
    assert merged["天窗类型"] == "可开启全景天窗"


def test_apply_live_rows_marks_snapshot():
    cand = ah.Candidate(49472, "t", {"A": "1"}, "vault.csv", "202202", 1)
    out = live.apply_live_rows(cand, {"A": "1", "B": "●"})
    assert out.snapshot == "live"
    assert out.rows["B"] == "●"
    assert str(out.source_path).startswith("live:")


def test_normalize_config_tree_drops_empty_and_plain_lines():
    raw = {
        "spec_id": 1,
        "title": "",
        "rows": {"车型名称": "测试车型"},
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "sections": [
            {"name": "", "group": "param", "items": [{"name": "忽略空分组", "value": "x"}]},
            {
                "name": "基本参数",
                "group": "param",
                "items": [
                    {"name": "", "value": "无名"},
                    {"name": "厂商", "value": "长城"},
                    {"name": "空值", "value": ""},
                    {"name": "纯文本", "value": "2.0T", "lines": [{"name": "", "value": "2.0T"}]},
                    {
                        "name": "驾驶模式切换",
                        "value": "● 运动 / ○ 雪地",
                        "lines": [
                            {"name": "运动", "value": "●", "mark": "standard"},
                            {"name": "雪地", "value": "○", "mark": "optional"},
                            {"name": "备注", "value": "备注", "mark": "other"},
                        ],
                    },
                ],
            },
            {"name": "空分组", "group": "config", "items": []},
            {"name": "主动安全", "group": "config", "items": [{"name": "主动刹车/主动安全系统", "value": "●"}]},
        ],
    }
    tree = live.normalize_config_tree(raw)
    assert tree["schema_version"] == "autohome-live-config-tree-1"
    assert tree["spec_id"] == 1
    assert tree["title"] == "测试车型"
    assert tree["url"] == "https://car.autohome.com.cn/config/spec/1.html"
    assert tree["fetched_at"] == "2026-01-01T00:00:00+00:00"
    assert tree["legend"] == {"standard": "●", "optional": "○", "absent": "-"}
    assert [s["name"] for s in tree["sections"]] == ["基本参数", "主动安全"]
    assert [s["group"] for s in tree["sections"]] == ["param", "config"]
    items = {it["name"]: it for it in tree["sections"][0]["items"]}
    assert list(items) == ["厂商", "空值", "纯文本", "驾驶模式切换"]
    assert "lines" not in items["厂商"]
    assert items["空值"]["value"] == "-"
    assert "lines" not in items["纯文本"]
    lines = items["驾驶模式切换"]["lines"]
    assert lines[0] == {"name": "运动", "value": "●", "mark": "standard"}
    assert lines[1] == {"name": "雪地", "value": "○", "mark": "optional"}
    assert lines[2] == {"name": "备注", "value": "备注"}
    assert "mark" not in lines[2]
    assert tree["sections"][1]["items"][0]["value"] == "●"
    assert "lines" not in tree["sections"][1]["items"][0]


def test_live_config_tree_49472():
    path = ROOT / "data" / "specs" / "live-config" / "49472.json"
    tree = json.loads(path.read_text(encoding="utf-8"))
    assert tree["schema_version"] == "autohome-live-config-tree-1"
    assert tree["spec_id"] == 49472
    assert tree["url"] == "https://car.autohome.com.cn/config/spec/49472.html"
    assert tree["legend"]["standard"] == "●"
    names = [s["name"] for s in tree["sections"]]
    for required in ("基本参数", "车身", "发动机", "变速箱", "主动安全", "天窗/玻璃"):
        assert required in names, names
    items = [it for sec in tree["sections"] for it in sec["items"]]
    brake = [it for it in items if it["name"] == "主动刹车/主动安全系统"]
    assert brake and brake[0]["value"] == "●"
    sunroof = [it for it in items if it["name"] == "天窗类型"]
    assert sunroof and "全景" in str(sunroof[0]["value"])
    cruise = [it for it in items if it["name"] == "巡航系统"]
    assert cruise and "巡航" in str(cruise[0]["value"])
    assert any("360" in it["name"] or "360" in str(it["value"]) for it in items)
    assert any("中控" in it["name"] for it in items)
    assert len(tree["sections"]) >= 15
    assert len(items) >= 120
    dash = ROOT / "dashboard" / "public" / "data" / "live-config" / "49472.json"
    assert json.loads(dash.read_text(encoding="utf-8"))["spec_id"] == 49472
    index = json.loads((ROOT / "data" / "specs" / "live-config" / "index.json").read_text(encoding="utf-8"))
    assert index["sku_to_spec"]["357301752"] == 49472
    assert str(49472) in index["specs"]
    assert index["spec_count"] == len(index["specs"])
    assert "sections" not in json.loads((ROOT / "data" / "specs" / "autohome-live-cache.json").read_text(encoding="utf-8"))["results"]["49472"]


if __name__ == "__main__":
    test_merge_prefer_live_keeps_vault_fallback()
    test_apply_live_rows_marks_snapshot()
    test_live_fixture_h6_coverage_above_threshold()
    test_normalize_config_tree_drops_empty_and_plain_lines()
    test_live_config_tree_49472()
    print("autohome live tests passed")
