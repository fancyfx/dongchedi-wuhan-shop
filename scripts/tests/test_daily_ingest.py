#!/usr/bin/env python3
"""Daily ingest rules: self-trade filter, diff, top-100 gate, snapshots."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from daily_ingest import apply_catalog_update, price_of, run  # noqa: E402
from dcd_fetch import (  # noqa: E402
    FixtureClient,
    build_detail_url,
    build_list_url,
    card_sku,
    fetch_multi_shop_batch,
    fetch_shop_batch,
    normalize_card,
    parse_cash_price,
    parse_fulfillment_fees,
    parse_sale_status,
)
from display_gate import ranked_threshold  # noqa: E402
from filters import admission_reason, is_zhiying, keep_listing  # noqa: E402
from shops import compute_landed_costs  # noqa: E402

TODAY = date(2026, 11, 3)


def _base(**overrides):
    item = {
        "sku": "100",
        "title": "速腾 2020款 280TSI 自动舒适型",
        "shop_id": "118608",
        "price": 4.5,
        "cash_price_wan": 4.5,
        "mileage_wan": 3.2,
        "plate_year": 2020,
        "model_year": 2020,
        "badges": ["直营"],
        "is_self_trade_car": True,
        "source_type_name": "自营-个人",
    }
    item.update(overrides)
    return item


def _scored(sku, score, price=4.0, **overrides):
    item = _base(
        sku=sku,
        price=price,
        cash_price_wan=price,
        total_score=score,
        score_eligible=True,
        condition_gate="PASS",
        effective_price_wan=price,
        sort_scores={"price_score": price},
    )
    item.update(overrides)
    return item


def test_zhiying_maps_self_trade_and_rejects_marketing_copy():
    assert is_zhiying({"badges": ["官方保", "直营"], "title": "速腾"})
    assert is_zhiying({"is_self_trade_car": "true", "source_type_name": "自营-个人", "badges": []})
    assert is_zhiying({"is_self_trade_car": False, "source_type_name": "自营-企业", "badges": []})
    assert not is_zhiying({"is_self_trade_car": "false", "source_type_name": "第三方", "badges": []})
    assert not is_zhiying({"is_self_trade_car": False, "source_type_name": "非自营", "title": "直营车可享延保", "badges": []})
    assert not is_zhiying({"badges": ["非直营"], "title": "速腾"})
    assert keep_listing(_base(badges=[], is_self_trade_car="true", source_type_name="自营-个人"), today=TODAY)
    assert admission_reason(_base(badges=[], is_self_trade_car=False, source_type_name="车商"), today=TODAY) == (
        "not_zhiying_or_self_trade"
    )


def test_hard_filters_cash_mileage_age_shop_and_bev():
    assert keep_listing(_base(), today=TODAY)
    assert admission_reason(_base(cash_price_wan=6.2, price=5.5), today=TODAY).startswith("price_")
    assert keep_listing(_base(price=6.5, cash_price_wan=5.9), today=TODAY)
    assert admission_reason(_base(mileage_wan=10.01), today=TODAY).startswith("mileage_")
    assert keep_listing(_base(plate_year=2016), today=TODAY)
    assert "older_than" in admission_reason(_base(plate_year=2015, model_year=2015), today=TODAY)
    assert "shop_id_" in admission_reason(_base(shop_id="227854"), today=TODAY)
    # 7-shop Plan A whitelist allows direct shops and rejects franchise lookalikes (129202/184568)
    assert "shop_id_" in admission_reason(_base(shop_id="129202"), today=TODAY)
    assert "shop_id_" in admission_reason(_base(shop_id="184568"), today=TODAY)
    # Hefei direct shop: bare 5.80w + 840 logi + 500 plate diff = 5.93w <= 6.0w (kept)
    assert keep_listing(_base(shop_id="64909", city="合肥", cash_price_wan=5.80, price=5.80), today=TODAY)
    # Hefei direct shop: bare 5.90w + 840 logi + 500 plate diff = 6.03w > 6.0w (rejected)
    assert admission_reason(
        _base(shop_id="64909", city="合肥", cash_price_wan=5.90, price=5.90),
        today=TODAY,
    ).startswith("price_")
    assert admission_reason(
        _base(title="星愿 2026款 200km 梦想版", fuel_form="4", plate_year=2024),
        today=TODAY,
    ).startswith("pure_bev_range_")
    assert keep_listing(
        _base(title="星愿 2026款 310km 梦想版", fuel_form="4", plate_year=2026),
        today=TODAY,
    )
    assert keep_listing(
        _base(title="秦PLUS DM 2024款 荣耀版 DM-i 55KM 领先型", fuel_form="6", plate_year=2024),
        today=TODAY,
    )
    assert keep_listing(
        _base(
            title="汉DM 2020款 DM 四驱性能版豪华型",
            fuel_form="6",
            plate_year=2020,
            is_self_trade_car=True,
            source_type_name="自营-个人",
            badges=[],
        ),
        today=TODAY,
    )
    assert "micro_city" in admission_reason(
        _base(title="宏光MINIEV 2022款", plate_year=2022, badges=["直营"]),
        today=TODAY,
    )


def test_existing_library_still_passes_hard_filter():
    path = ROOT / "data" / "listings-filtered.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    kept = [row for row in rows if keep_listing(row, today=TODAY)]
    assert len(kept) == len(rows), [admission_reason(row, today=TODAY) for row in rows if not keep_listing(row, today=TODAY)][:5]


def test_added_updated_and_top100_gate():
    inventory = [
        _scored("a", 90, price=5.0, title="在库高分 2021款"),
        _scored("b", 40, price=4.0, title="在库低分 2020款"),
    ]
    ranked = [dict(inventory[0]), dict(inventory[1])]
    incoming = [
        _scored("a", 30, price=3.5, title="在库高分 2021款"),
        _scored("new-low", 10, price=3.0, title="新车不够分 2022款"),
        _scored("new-high", 95, price=4.2, title="新车高分 2022款"),
        _scored("tie", 90, price=5.5, title="同分更贵 2022款"),
    ]
    # Pre-update 2nd of limit 2 is 40. new-low is below. tie equals the old #1
    # but limit 1 is covered separately; here limit 2 threshold is 40.
    result = apply_catalog_update(
        inventory,
        ranked,
        incoming,
        rejected_hard=[],
        admit_below_threshold=False,
        display_limit=2,
        now="2026-11-03T12:00:00+08:00",
    )
    kinds = {(row["sku"], row["change_type"]) for row in result["changelog"]}
    assert ("a", "updated_price") in kinds
    price_row = next(row for row in result["changelog"] if row["sku"] == "a" and row["change_type"] == "updated_price")
    assert price_row["old_price"] == 5.0
    assert price_row["new_price"] == 3.5
    assert price_row["old_score"] == 90
    assert price_row["new_score"] == 30
    assert ("new-low", "rejected_below_top100") in kinds
    assert "new-low" not in {item["sku"] for item in result["inventory"]}
    assert ("new-high", "added") in kinds
    assert any(row["change_type"] == "display_dropped" and row["sku"] == "a" for row in result["changelog"])
    # Scores after the update: new-high 95, tie 90, b 40, a 30. Top 2 are the two new cars.
    assert [item["sku"] for item in result["ranked"]] == ["new-high", "tie"]
    assert all(item.get("display") is True for item in result["ranked"])
    assert {item["sku"] for item in result["below"]} >= {"a", "b"}
    assert all(item.get("display") is False for item in result["below"])
    assert price_of(next(item for item in result["inventory"] if item["sku"] == "a")) == 3.5


def test_new_car_tie_that_misses_the_board_is_not_stored():
    inventory = [_scored("a", 50, price=4.0, sort_scores={"price_score": 50})]
    incoming = [_scored("b", 50, price=5.0, title="同分更贵 2021款", sort_scores={"price_score": 50})]
    result = apply_catalog_update(
        inventory,
        inventory,
        incoming,
        rejected_hard=[],
        admit_below_threshold=False,
        display_limit=1,
        now="2026-11-03T12:00:00+08:00",
    )
    assert result["threshold"] == 50
    assert [item["sku"] for item in result["ranked"]] == ["a"]
    assert "b" not in {item["sku"] for item in result["inventory"]}
    row = next(row for row in result["changelog"] if row["sku"] == "b")
    assert row["change_type"] == "rejected_below_top100"
    assert row["reason"] == "not_in_display_top100"


def test_threshold_is_runtime_not_a_constant():
    rows = [_scored(str(i), 100 - i) for i in range(5)]
    assert ranked_threshold(rows, limit=3) == 98
    assert ranked_threshold(rows, limit=100) is None


def test_removed_when_existing_car_fails_hard_filter():
    inventory = [_scored("a", 80)]
    rejected = [_base(sku="a", shop_id="227854", _reject_reason="shop_id_227854_not_118608")]
    result = apply_catalog_update(
        inventory,
        inventory,
        incoming=[],
        rejected_hard=rejected,
        display_limit=1,
        now="2026-11-03T12:00:00+08:00",
    )
    assert result["inventory"] == []
    assert result["changelog"][0]["change_type"] == "removed_hard_filter"
    assert result["changelog"][0]["old_price"] == 4.0


def test_search_id_paging_shop_filter_and_cash_price():
    def page(skus, search_id, has_more, shops=None):
        cards = []
        for index, sku in enumerate(skus):
            shop = (shops or ["118608"] * len(skus))[index]
            cards.append(
                {
                    "product": {
                        "event_info": {
                            "sku_id": sku,
                            "shop_id": shop,
                            "mileage": "3.20",
                            "year": "2020",
                            "first_registration_time": "1609459200",
                            "is_self_trade_car": "true",
                            "source_type_name": "自营-个人",
                            "series_name": "速腾",
                            "brand_name": "大众",
                        },
                        "product_desc": {"title": f"速腾 2020款 {sku}", "sub_title": "2020年/3.2万公里"},
                        "product_price": {"text": "5.99", "unit": "万"},
                        "product_tag_list": [],
                    }
                }
            )
        return {
            "status": 0,
            "data": {
                "card_list": cards,
                "event_info": {"search_id": search_id},
                "page": {"has_more": has_more, "offset": 2 if has_more else 0},
            },
        }

    def detail(sku, fen):
        return {
            "status": 0,
            "data": {
                "product": {
                    "product_shop": {"shop_id": "118608"},
                    "sku_list": [
                        {"sku_id": sku, "sku_price": {"price": fen, "price_str": f"{fen / 1_000_000:.2f}", "price_unit": "万"}}
                    ],
                }
            },
        }

    pages = [
        page(["1", "2"], "SID-1", True),
        page(["3", "9"], "SID-2", False, shops=["118608", "227854"]),
    ]
    details = {"1": detail("1", 5990000), "2": detail("2", 3990000), "3": detail("3", 4500000)}
    client = FixtureClient(pages, details)
    batch = fetch_shop_batch(client, page_size=2)
    assert [card_sku(card) for card in batch.cards] == ["1", "2", "3"]
    assert client.list_calls[0][2] == ""
    assert client.list_calls[1][2] == "SID-1"
    assert "search_id" in build_list_url(10, 10, "SID-1")
    assert "SID-1" in build_list_url(10, 10, "SID-1")
    assert "product_id=1" in build_detail_url("1")
    assert "sku_id=" not in build_detail_url("1")
    cash = parse_cash_price(details["1"])
    assert cash["cash_price_wan"] == 5.99
    assert parse_cash_price(details["2"])["cash_price_wan"] == 3.99
    normalized = normalize_card(pages[0]["data"]["card_list"][0], details["1"])
    assert normalized["price"] == 5.99
    assert normalized["badges"] == ["直营"]
    assert normalized["is_self_trade_car"] is True
    assert keep_listing(normalized, today=TODAY)


def test_pipeline_snapshots_and_dry_run_do_not_touch_catalog():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        catalog = root / "catalog"
        catalog.mkdir()
        existing = _scored("900001", 88, price=5.0, title="速腾 2020款 900001")
        (catalog / "listings-ranked.json").write_text(json.dumps([existing], ensure_ascii=False), encoding="utf-8")
        (catalog / "listings-filtered.json").write_text(json.dumps([existing], ensure_ascii=False), encoding="utf-8")
        before = hashlib.sha256((catalog / "listings-ranked.json").read_bytes()).hexdigest()
        fixtures = root / "fixtures"
        fixtures.mkdir()

        def card(sku, title, self_trade=True, source="自营-个人"):
            return {
                "product": {
                    "event_info": {
                        "sku_id": sku,
                        "shop_id": "118608",
                        "mileage": "3.20",
                        "year": "2020",
                        "first_registration_time": "1609459200",
                        "is_self_trade_car": "true" if self_trade else "false",
                        "source_type_name": source,
                    },
                    "product_desc": {"title": title, "sub_title": "2020年/3.2万公里"},
                    "product_price": {"text": "4.00", "unit": "万"},
                    "product_tag_list": [],
                }
            }

        def detail(sku, fen, shop="118608"):
            return {
                "status": 0,
                "data": {
                    "product": {
                        "product_shop": {"shop_id": shop},
                        "sku_list": [{"sku_id": sku, "sku_price": {"price": fen, "price_str": f"{fen / 1_000_000:.2f}", "price_unit": "万"}}],
                    }
                },
            }

        page = {
            "status": 0,
            "data": {
                "card_list": [
                    card("900001", "速腾 2020款 900001"),
                    card("900002", "外牌 2020款 900002", self_trade=False, source="第三方"),
                    card("900003", "贵车 2020款 900003"),
                    card("900004", "宏光MINIEV 2021款"),
                ],
                "event_info": {"search_id": "SNAP"},
                "page": {"has_more": False, "offset": 4},
            },
        }
        (fixtures / "list-page1.json").write_text(json.dumps(page), encoding="utf-8")
        (fixtures / "detail-900001.json").write_text(json.dumps(detail("900001", 5000000)), encoding="utf-8")
        (fixtures / "detail-900002.json").write_text(json.dumps(detail("900002", 3000000)), encoding="utf-8")
        (fixtures / "detail-900003.json").write_text(json.dumps(detail("900003", 6500000)), encoding="utf-8")
        (fixtures / "detail-900004.json").write_text(json.dumps(detail("900004", 2000000)), encoding="utf-8")
        snap = root / "snap"
        summary = run(
            [
                "--fixtures",
                str(fixtures),
                "--catalog-dir",
                str(catalog),
                "--snapshot-dir",
                str(snap),
                "--dry-run",
                "--skip-live-fetch",
                "--display-limit",
                "1",
                "--date",
                "20261103",
            ]
        )
        assert summary["dry_run"] is True
        assert summary["catalog_written"] is False
        assert hashlib.sha256((catalog / "listings-ranked.json").read_bytes()).hexdigest() == before
        assert (snap / "changelog.json").exists()
        assert (snap / "summary.json").exists()
        assert (snap / "list-page-00.json").exists()
        assert (snap / "detail-900001.json").exists() or (snap / "detail-900001.json.gz").exists()
        changelog = json.loads((snap / "changelog.json").read_text(encoding="utf-8"))
        reasons = {row["sku"]: row.get("reason") or row["change_type"] for row in changelog}
        assert "not_zhiying" in (reasons["900002"] or "")
        assert reasons["900003"].startswith("price_")
        assert "micro_city" in reasons["900004"]
        assert not any(row["sku"] == "900001" and row["change_type"] == "updated_price" for row in changelog)
        raw = json.loads((snap / "list-page-00.json").read_text(encoding="utf-8"))
        assert raw["data"]["event_info"]["search_id"] == "SNAP"


def test_parse_sale_status_and_missing_reconcile():
    sold_payload = {
        "status": 0,
        "data": {
            "product": {
                "product_status": 0,
                "sku_list": [{"sku_id": "1", "sku_price": {"price": 4490000, "price_str": "4.49"}}],
            },
            "component_list": {"bottom_bar": {"bottom_bar_list": [{"text": "车辆已售出"}]}},
        },
    }
    reserved_payload = {
        "status": 0,
        "data": {
            "product": {
                "product_status": 5,
                "business_info": {"latest_reserved_time": "1794985553"},
                "sku_list": [{"sku_id": "2", "sku_price": {"price": 3990000, "price_str": "3.99"}}],
            },
            "component_list": {"bottom_bar": {"bottom_bar_list": [{"text": "收藏"}, {"text": "电话"}]}},
        },
    }
    onsale_payload = {
        "status": 0,
        "data": {
            "product": {
                "product_status": 1,
                "sku_list": [{"sku_id": "3", "sku_price": {"price": 4990000, "price_str": "4.99"}}],
            },
            "component_list": {"bottom_bar": {"bottom_bar_list": [{"text": "立即订购"}]}},
        },
    }
    assert parse_sale_status(sold_payload)["sale_status"] == "sold"
    assert parse_sale_status(reserved_payload)["sale_status"] == "reserved"
    assert parse_sale_status(onsale_payload)["sale_status"] == "on_sale"

    inv = [
        _scored("sold_sku", 90, price=4.5),
        _scored("res_sku", 85, price=4.0),
        _scored("err_sku", 80, price=4.2),
    ]
    res1 = apply_catalog_update(
        inv,
        inv,
        incoming=[],
        rejected_hard=[],
        reconciled_missing={
            "sold_sku": {"status": "sold", "product_status": 0, "reason": "product_status_0_sold"},
            "res_sku": {"status": "reserved", "product_status": 5, "reason": "product_status_5_reserved"},
            "err_sku": {"status": "detail_failed", "reason": "timeout"},
        },
        display_limit=30,
        now="2026-11-21T00:00:00+08:00",
    )
    inv_skus = {x["sku"] for x in res1["inventory"]}
    ranked_skus = {x["sku"] for x in res1["ranked"]}
    assert "sold_sku" not in inv_skus
    assert "res_sku" in inv_skus and "res_sku" not in ranked_skus
    assert "err_sku" in inv_skus and "err_sku" in ranked_skus
    res_row = next(x for x in res1["inventory"] if x["sku"] == "res_sku")
    assert res_row["sale_status"] == "reserved"
    kinds = {(r["sku"], r["change_type"]) for r in res1["changelog"]}
    assert ("sold_sku", "removed_sold") in kinds
    assert ("res_sku", "reserved_hidden") in kinds
    assert ("err_sku", "detail_failed") in kinds

    # Reserved car returning to list restores on_sale and re-enters ranked
    res2 = apply_catalog_update(
        res1["inventory"],
        res1["ranked"],
        incoming=[_scored("res_sku", 85, price=4.0, sale_status="on_sale")],
        rejected_hard=[],
        display_limit=30,
        now="2026-11-21T01:00:00+08:00",
    )
    assert "res_sku" in {x["sku"] for x in res2["ranked"]}
    assert ("res_sku", "restored_on_sale") in {(r["sku"], r["change_type"]) for r in res2["changelog"]}


def test_plan_a_logistics_fees_and_fallback_chain():
    # 1. Wuhan detail url asks for Wuhan buyer city and parses 0 logistics + 500 plate
    url = build_detail_url("999")
    assert "city_name=%E6%AD%A6%E6%B1%89" in url
    assert "sh_city_name=%E6%AD%A6%E6%B1%89" in url

    remote_det = {
        "status": 0,
        "data": {
            "product": {
                "product_shop": {"shop_id": "64909"},
                "sku_list": [{"sku_id": "10", "sku_price": {"price": 4890000, "price_str": "4.89"}}],
                "product_status": 1,
            },
            "component_list": {
                "fulfillment": {
                    "delivery": {"delivery_location": {"city": {"code": 420100, "name": "武汉"}}, "move_in_location": {"city": {"code": 340100, "name": "合肥"}}},
                    "logistics": {"logistics_amount": {"price": 840}, "process_list": [{"sub_title": "2-4日送达"}]},
                },
                "purchase_plan": {
                    "paytype_detail_list": [
                        {"price_item_list": [{"price_type": 17, "sub_price_items": [{"price_type": 103, "price_str": "1,000"}]}]}
                    ]
                },
            },
        },
    }
    ful = parse_fulfillment_fees(remote_det)
    assert ful["api_logistics_yuan"] == 840
    assert ful["api_plate_fee_yuan"] == 1000
    assert ful["delivery_eta"] == "2-4日送达"

    card = {
        "product": {
            "event_info": {
                "sku_id": "10",
                "shop_id": "64909",
                "shop_city_name": "合肥",
                "mileage": "3.0",
                "year": "2021",
                "is_self_trade_car": "true",
                "source_type_name": "自营-个人",
            },
            "product_desc": {"title": "君威 2021款 552T 精英型"},
            "product_price": {"text": "4.89"},
        }
    }
    normed = normalize_card(card, remote_det)
    assert normed["is_local_wuhan"] is False
    assert normed["shop_short_name"] == "合肥店"
    assert normed["logistics_fee_yuan"] == 840
    assert normed["logistics_fee_source"] == "api"
    assert normed["plate_fee_diff_yuan"] == 500
    assert normed["landed_extra_yuan"] == 1340
    assert normed["landed_price_wan"] == 5.02

    # 2. Fallback chain: city_cache for known city when API missing, then default_1000 for unknown remote city
    c_hefei = compute_landed_costs("64909", city="合肥", api_logistics_yuan=None)
    assert c_hefei["logistics_fee_yuan"] == 840 and c_hefei["logistics_fee_source"] == "city_cache"
    c_unknown = compute_landed_costs("999999", city="外地", api_logistics_yuan=None)
    assert c_unknown["logistics_fee_yuan"] == 1000 and c_unknown["logistics_fee_source"] == "default_1000"
    c_wuhan = compute_landed_costs("118608", city="武汉", api_logistics_yuan=1950, api_plate_fee_yuan=500)
    assert c_wuhan["is_local_wuhan"] is True and c_wuhan["landed_extra_yuan"] == 0


def test_split_wuhan_and_national_boards():
    inventory = [
        _scored("cq1", 92.0, price=4.8, shop_id="225430", city="重庆", is_local_wuhan=False),
        _scored("wh1", 89.0, price=4.5, shop_id="118608", city="武汉", is_local_wuhan=True),
        _scored("hf1", 88.0, price=4.9, shop_id="64909", city="合肥", is_local_wuhan=False),
        _scored("wh2", 85.0, price=4.2, shop_id="118608", city="武汉", is_local_wuhan=True),
        _scored("wh3", 80.0, price=4.1, shop_id="118608", city="武汉", is_local_wuhan=True),
        _scored("wh_res", 95.0, price=4.0, shop_id="118608", city="武汉", is_local_wuhan=True, sale_status="reserved"),
    ]
    res = apply_catalog_update(
        inventory,
        [],
        incoming=[],
        rejected_hard=[],
        display_limit=2,
        now="2026-11-24T22:00:00+08:00",
    )
    # National top-2: cq1 (#1), wh1 (#2)
    assert [x["sku"] for x in res["ranked"]] == ["cq1", "wh1"]
    assert [x["rank"] for x in res["ranked"]] == [1, 2]
    # Wuhan top-2 independent of national cutoff: wh1 (#1, national #2), wh2 (#2, national None)
    assert [x["sku"] for x in res["ranked_wuhan"]] == ["wh1", "wh2"]
    assert [x["rank"] for x in res["ranked_wuhan"]] == [1, 2]
    assert res["ranked_wuhan"][0]["national_rank"] == 2
    assert res["ranked_wuhan"][1]["national_rank"] is None
    assert res["ranked_wuhan"][0]["board_scope"] == "wuhan"
    # National board's rank on inventory/ranked was not overwritten by Wuhan rank
    wh1_national = next(x for x in res["ranked"] if x["sku"] == "wh1")
    assert wh1_national["rank"] == 2
    assert wh1_national["wuhan_rank"] == 1
    # Reserved Wuhan car is excluded from both boards
    assert "wh_res" not in {x["sku"] for x in res["ranked"]}
    assert "wh_res" not in {x["sku"] for x in res["ranked_wuhan"]}


def main() -> None:
    tests = [
        test_zhiying_maps_self_trade_and_rejects_marketing_copy,
        test_hard_filters_cash_mileage_age_shop_and_bev,
        test_existing_library_still_passes_hard_filter,
        test_added_updated_and_top100_gate,
        test_new_car_tie_that_misses_the_board_is_not_stored,
        test_threshold_is_runtime_not_a_constant,
        test_removed_when_existing_car_fails_hard_filter,
        test_search_id_paging_shop_filter_and_cash_price,
        test_pipeline_snapshots_and_dry_run_do_not_touch_catalog,
        test_parse_sale_status_and_missing_reconcile,
        test_plan_a_logistics_fees_and_fallback_chain,
        test_split_wuhan_and_national_boards,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print("ok", fn.__name__)
        except Exception as exc:
            failed += 1
            print("FAIL", fn.__name__, type(exc).__name__, exc)
    if failed:
        raise SystemExit(f"{failed} failed")
    print(f"passed {len(tests)}")


if __name__ == "__main__":
    main()
