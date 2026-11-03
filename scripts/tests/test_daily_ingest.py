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
    fetch_shop_batch,
    normalize_card,
    parse_cash_price,
)
from display_gate import ranked_threshold  # noqa: E402
from filters import admission_reason, is_zhiying, keep_listing  # noqa: E402

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
