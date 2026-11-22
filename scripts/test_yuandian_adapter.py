#!/usr/bin/env python3
"""Deterministic unit tests for pddauto v3.3 Yuandian SaaS Adapter & Dual-Mode Gates."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from step1_yuandian_pull import build_manifest_from_task
from step4_yuandian_push import (
    infer_channel,
    prepare_patch_operations,
    run_yuandian_redteam_audit,
)

SAMPLE_TASK = {
    "task_no": "YD-20261122-CG-TEST01",
    "platform": "qnh",
    "store_id": "1003911",
    "store_name": "龙猫购",
    "status": "sourcing",
    "current_staff": {"id": 1, "name": "admin"},
    "red_team_checks": {
        "zero_manual_notes": True,
        "unit_price_formula": True,
        "supply_url_valid": True,
        "checkout_url_valid": True,
    },
    "settlement_preview": {
        "matched_count": 2,
        "unit_price": 0.3,
        "prehold_amount": 0.9,
        "settled_amount": 0.6,
        "refunded_amount": 0.3,
    },
    "items": [
        {
            "id": 101,
            "row_index": 2,
            "skuid": "2112428689211617326",
            "spuid": "2112428689207058467",
            "product_name": "新款原创毛巾绣刺绣布贴 1个",
            "spec_name": "1个",
            "retail_price": 3.8,
            "main_image_url": "http://example.com/1.jpg",
            "channel": "1688",
            "match_status": "pending",
            "assignee_staff_id": None,
        },
        {
            "id": 102,
            "row_index": 3,
            "skuid": "1992965625605226587",
            "spuid": "1992965625597145128",
            "product_name": "草原红太阳 火锅蘸料香辣味 120g/袋",
            "spec_name": "120g*1袋",
            "retail_price": 5.5,
            "main_image_url": "http://example.com/2.png",
            "channel": "1688",
            "match_status": "pending",
            "assignee_staff_id": None,
        },
        {
            "id": 103,
            "row_index": 4,
            "skuid": "9999999999999999999",
            "spuid": "8888888888888888888",
            "product_name": "礼盒组合套装组合",
            "spec_name": "1套",
            "retail_price": 99.0,
            "main_image_url": "http://example.com/3.jpg",
            "channel": "1688",
            "match_status": "pending",
            "assignee_staff_id": None,
        },
    ],
}


def expect_raises(fn, substr: str) -> None:
    try:
        fn()
    except Exception as exc:
        assert substr in str(exc), f"Expected {substr!r} in error, got: {exc}"
        return
    raise AssertionError(f"Expected exception containing {substr!r}, but succeeded")


def main() -> int:
    # 1. Channel inference
    assert infer_channel("https://detail.1688.com/offer/892914632446.html") == "1688"
    assert infer_channel("https://mobile.yangkeduo.com/goods.html?goods_id=841581690828") == "pdd"
    assert infer_channel("https://mobile.pinduoduo.com/goods.html?goods_id=123456") == "pdd"

    # 2. Manifest generation compatibility with step2 / step3
    with tempfile.TemporaryDirectory() as td:
        m = build_manifest_from_task(
            SAMPLE_TASK,
            Path(td),
            only_pending=True,
            rules={"version": 1, "rules_text": "v3.2"},
            download_images=False,
        )
        assert m["source_mode"] == "yuandian_saas"
        assert m["task_no"] == "YD-20261122-CG-TEST01"
        assert m["total"] == 3
        assert m["routes"]["1688"] == 1
        assert m["routes"]["pdd"] == 1
        assert m["routes"]["combo"] == 1
        assert [r["row"] for r in m["rows"]] == [2, 3, 4]
        assert [r["yuandian_item_id"] for r in m["rows"]] == [101, 102, 103]

    # 3. Valid matched + unmatched decisions with strict 1688 card index
    card_index = {"892914632446": {"小熊头", "小兔头"}}
    valid_decisions = [
        {
            "row": 2,
            "skuid": "2112428689211617326",
            "visual_verified": True,
            "source": "https://detail.1688.com/offer/892914632446.html",
            "spec": "小熊头",
            "checkout": "https://detail.1688.com/offer/892914632446.html",
            "units": 1,
            "paid": 0.47,
        },
        {
            "row": 3,
            "skuid": "1992965625605226587",
            "visual_verified": True,
            "source": "https://mobile.yangkeduo.com/goods.html?goods_id=841581690828",
            "spec": "香辣蘸料120克*60袋",
            "checkout": "https://mobile.yangkeduo.com/order_checkout.html?goods_id=841581690828&sku_id=1992324105964&goods_number=1",
            "units": 60,
            "paid": 168.0,
        },
        {
            "row": 4,
            "skuid": "9999999999999999999",
            "status_only": "组合商品",
        },
    ]
    ops = prepare_patch_operations(SAMPLE_TASK, valid_decisions, card_index)
    assert len(ops) == 3
    assert ops[0][1] == 101 and ops[0][3]["channel"] == "1688" and ops[0][3]["match_status"] == "matched"
    assert ops[1][1] == 102 and ops[1][3]["channel"] == "pdd" and ops[1][3]["order_ratio"] == 60
    assert ops[2][1] == 103 and ops[2][3]["match_status"] == "unmatched" and ops[2][3]["unmatched_reason"] == "组合商品"

    # 4. Reject manual notes in spec (zero_manual_notes hard gate)
    bad_note = [dict(valid_decisions[1], spec="香辣蘸料120克*60袋（包邮）")]
    expect_raises(lambda: prepare_patch_operations(SAMPLE_TASK, bad_note, card_index), "Zero-Annotation Spec Gate")

    # 5. Reject non-verbatim 1688 spec against card_index
    bad_1688 = [dict(valid_decisions[0], spec="小熊头1个")]
    expect_raises(lambda: prepare_patch_operations(SAMPLE_TASK, bad_1688, card_index), "Verbatim 1688 Spec Gate")

    # 6. Reject PDD checkout link containing group_id
    bad_pdd_checkout = [
        dict(
            valid_decisions[1],
            checkout="https://mobile.yangkeduo.com/order_checkout.html?goods_id=841581690828&sku_id=1992324105964&group_id=12345",
        )
    ]
    expect_raises(lambda: prepare_patch_operations(SAMPLE_TASK, bad_pdd_checkout, card_index), "group_id")

    # 7. Reject missing visual_verified
    blind = [dict(valid_decisions[0], visual_verified=False)]
    expect_raises(lambda: prepare_patch_operations(SAMPLE_TASK, blind, card_index), "visual_verified")

    # 8. Reject completed/cancelled task
    done_task = dict(SAMPLE_TASK, status="completed")
    expect_raises(lambda: prepare_patch_operations(done_task, valid_decisions, card_index), "already finalized")

    # 9. Audit summary check
    report = run_yuandian_redteam_audit(SAMPLE_TASK)
    assert report["server_all_passed"] is True

    print(json.dumps({"passed": True, "tests": 9}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
