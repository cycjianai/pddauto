#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic unit tests for PDD Tri-Mode Sourcing Engine v3.0."""

from __future__ import annotations

import json
import unittest

from pdd_sourcing_engine import (
    CDP_RAW_DATA_EXTRACT_JS,
    CDP_SEARCH_CLICK_FIRST_GOODS_JS,
    EngineMode,
    PDDSourcingEngine,
    aggregate_rows_by_spu,
    compute_order_ratio,
    extract_pack_count,
    parse_raw_goods_data,
    validate_numeric_id,
)


class TestPDDSourcingEngine(unittest.TestCase):
    def test_url_builders_and_numeric_validation(self):
        self.assertEqual(
            PDDSourcingEngine.build_goods_url("1020822012874"),
            "https://mobile.yangkeduo.com/goods.html?goods_id=1020822012874",
        )
        checkout = PDDSourcingEngine.build_checkout_url("1020822012874", "1989975858303", 1)
        self.assertEqual(
            checkout,
            "https://mobile.yangkeduo.com/order_checkout.html?goods_id=1020822012874&sku_id=1989975858303&goods_number=1",
        )
        self.assertNotIn("group_id", checkout)

        for bad_id in ("", "abc", "123_fake", "null", "undefined", "1020822012874;drop"):
            with self.assertRaises(ValueError):
                validate_numeric_id(bad_id, "goods_id")
            with self.assertRaises(ValueError):
                PDDSourcingEngine.build_checkout_url(bad_id, "1989975858303")
            with self.assertRaises(ValueError):
                PDDSourcingEngine.build_checkout_url("1020822012874", bad_id)

    def test_parse_raw_goods_data_preserves_yuan_price_and_semicolon_specs(self):
        raw_goods = {
            "goods_id": 940322316708,
            "goods_name": "元气森林气泡水480ml整箱",
            "min_on_sale_group_price": 4400,
            "skus": [
                {
                    "sku_id": 1892532124926,
                    "is_onsale": 1,
                    "quantity": 200,
                    "group_price": "44.00",
                    "normal_price": "48.00",
                    "specs": [
                        {"spec_key": "规格", "spec_value": "480ML*9瓶【囤货】"},
                        {"spec_key": "口味", "spec_value": "混合口味 【新老包装随机】"},
                    ],
                },
                {
                    "sku_id": 1892532124999,
                    "is_onsale": 0,
                    "quantity": 0,
                    "group_price": "19.90",
                    "specs": [{"spec_key": "规格", "spec_value": "已下架规格"}],
                },
            ],
        }
        parsed = parse_raw_goods_data(raw_goods)
        self.assertEqual(parsed["goods_id"], "940322316708")
        self.assertEqual(len(parsed["skus"]), 1)
        sku = parsed["skus"][0]
        self.assertEqual(sku["sku_id"], "1892532124926")
        self.assertEqual(sku["specs"], "480ML*9瓶【囤货】；混合口味 【新老包装随机】")
        # Crucial check: 44.00 Yuan is NOT divided by 100
        self.assertAlmostEqual(sku["group_price"], 44.00, places=2)
        self.assertEqual(
            sku["checkout_url"],
            "https://mobile.yangkeduo.com/order_checkout.html?goods_id=940322316708&sku_id=1892532124926&goods_number=1",
        )

    def test_compute_order_ratio_and_six_column_backfill(self):
        self.assertEqual(extract_pack_count("480ML*9瓶【囤货】"), 9)
        self.assertEqual(extract_pack_count("精选松花皮蛋 10枚装"), 10)
        self.assertEqual(extract_pack_count("1颗"), 1)
        self.assertEqual(compute_order_ratio("1颗", "10枚装"), 10)
        self.assertEqual(compute_order_ratio("480ml/瓶", "480ML*9瓶【囤货】"), 9)
        self.assertEqual(compute_order_ratio("330ml*12瓶/箱", "330ml*12瓶整箱"), 1)

        cols = PDDSourcingEngine.build_six_column_backfill(
            goods_id="940322316708",
            sku_id="1892532124926",
            specs_text="480ML*9瓶【囤货】；白桃味",
            group_price_yuan=44.00,
            order_ratio=9,
            excel_row=2,
        )
        self.assertEqual(cols["F"], "https://mobile.yangkeduo.com/goods.html?goods_id=940322316708")
        self.assertEqual(cols["G"], "480ML*9瓶【囤货】；白桃味")
        self.assertEqual(
            cols["H"],
            "https://mobile.yangkeduo.com/order_checkout.html?goods_id=940322316708&sku_id=1892532124926&goods_number=1",
        )
        self.assertEqual(cols["I"], 9)
        self.assertEqual(cols["J"], 44.00)
        self.assertEqual(cols["K"], "=ROUND(J2/I2, 2)")
        self.assertEqual(cols["unit_price_value"], 4.89)

    def test_spu_pre_aggregation(self):
        rows = [
            {"row_index": 2, "spu_id": "SPU_100", "product_name": "踩屎感拖鞋", "sku_id": "SKU_1", "spec": "白色 36-37"},
            {"row_index": 3, "spu_id": "SPU_100", "product_name": "踩屎感拖鞋", "sku_id": "SKU_2", "spec": "黑色 40-41"},
            {"row_index": 4, "spu_id": "SPU_200", "product_name": "松花皮蛋", "sku_id": "SKU_3", "spec": "1个"},
        ]
        groups = aggregate_rows_by_spu(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["spu_id"], "SPU_100")
        self.assertEqual(len(groups[0]["sku_rows"]), 2)
        self.assertEqual(groups[1]["spu_id"], "SPU_200")
        self.assertEqual(len(groups[1]["sku_rows"]), 1)

    def test_adb_extractor_works_without_group_id_and_photo_guard_blocks_unsafe_paths(self):
        engine = PDDSourcingEngine(mode=EngineMode.USB_DEBUG)
        res = engine.extract_checkout_url_from_adb(
            dumpsys_output='Intent { dat=pinduoduo://... goods_id=1020822012874&sku_id=1989975858303 "spec":"10枚装" }'
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["goods_id"], "1020822012874")
        self.assertEqual(res["sku_id"], "1989975858303")
        self.assertEqual(res["group_id"], "")

        for unsafe_path in (
            "/Users/local/photo.jpg",
            "/sdcard/DCIM/Camera/*.jpg",
            "/sdcard/DCIM/Camera/../secret.jpg",
            "/sdcard/DCIM/Camera/IMG_20261107.jpg",
            "/sdcard/DCIM/Camera/mmexport12345.jpg",
        ):
            with self.assertRaises(ValueError):
                engine._safe_cleanup_remote_temp_photo(unsafe_path)

        self.assertIn("mall_page.html", CDP_SEARCH_CLICK_FIRST_GOODS_JS)
        self.assertIn("window?.rawData?.store?.initDataObj?.goods", CDP_RAW_DATA_EXTRACT_JS)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPDDSourcingEngine)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print(json.dumps({"passed": True, "tests": result.testsRun}, ensure_ascii=False))
