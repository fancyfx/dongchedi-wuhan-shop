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


if __name__ == "__main__":
    test_merge_prefer_live_keeps_vault_fallback()
    test_apply_live_rows_marks_snapshot()
    test_live_fixture_h6_coverage_above_threshold()
    print("autohome live tests passed")
