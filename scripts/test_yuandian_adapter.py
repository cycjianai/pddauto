#!/usr/bin/env python3
"""Deterministic unit tests for pddauto v3.3 Yuandian SaaS Adapter & Dual-Mode Gates."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from step1_prepare import build_platform_policy, classify_route
from step1_yuandian_pull import build_manifest_from_task
from step2_1688_search import enforce_pdd_first_before_1688
from step4_apply_and_export import apply_decisions, run_redteam_audit
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

    # 10. v3.4 classify_route with category & expanded food/FMCG keywords (including R209 diaper & food snacks)
    assert classify_route("蓓秀 山茶油婴儿纸尿裤 XL码", "XL", category="母婴用品/尿裤/尿不湿") == "pdd"
    assert classify_route("叻滋滋 韩式牛肉味大豆素肉 16g/包", "16g/包") == "pdd"
    assert classify_route("金龙鱼 优质东北大米 5kg/袋", "5kg") == "pdd"
    assert classify_route("立顿 绿茶袋泡茶50g/盒", "25包") == "pdd"
    assert classify_route("新款原创毛巾绣刺绣布贴 1个", "1个") == "1688"
    # Anti-false-positive checks on decorative words (糖果色浴巾 / 奶茶玻璃杯 / 面膜收纳盒 / 防晒口罩 / 化妆刷)
    assert classify_route("【颜色可选】糖果条绒浴巾加厚大浴巾70*140cm", "1条") == "1688"
    assert classify_route("ins网红餐厅宽口果茶杯玻璃杯子奶茶饮品杯", "385ml") == "1688"
    assert classify_route("透明桌面收纳盒分类整理收纳篮面膜收纳盒", "1个") == "1688"
    assert classify_route("立体白色口罩一次性三层防护防晒显脸小", "1个") == "1688"
    assert classify_route("镰刀鼻影刷化妆刷修容刷", "1支", category="彩妆香水 美妆工具 化妆刷") == "1688"
    assert build_platform_policy("pdd")["platform_policy"] == "pdd_first_lock"

    # 11. v3.4 Step 2A hard gate: block 1688 search on PDD-first row without PDD disk artifact
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        m = build_manifest_from_task(SAMPLE_TASK, wd, only_pending=True, download_images=False)
        (wd / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        # Row 2 is 1688_first -> allowed immediately
        enforce_pdd_first_before_1688(wd, [2])
        # Row 3 (火锅蘸料) is pdd_first_lock -> BLOCKED without pdd_*/R3.json!
        expect_raises(lambda: enforce_pdd_first_before_1688(wd, [3]), "PDD_FIRST_GATE_BLOCKED")
        # Blocked PDD artifact (blocked=True) does NOT unlock 1688!
        (wd / "pdd_kw").mkdir()
        (wd / "pdd_kw" / "R3.json").write_text(json.dumps({"row": 3, "blocked": True, "cands": []}), encoding="utf-8")
        expect_raises(lambda: enforce_pdd_first_before_1688(wd, [3]), "PDD_FIRST_GATE_BLOCKED")
        # Real non-blocked PDD search artifact unlocks Round-2 1688 search!
        (wd / "pdd_kw" / "R3.json").write_text(json.dumps({"row": 3, "blocked": False, "cands": []}), encoding="utf-8")
        enforce_pdd_first_before_1688(wd, [2, 3])

        # 12. v3.4 Step 4B (Yuandian) PDD-first gate: block 1688 without PDD evidence, without reason, or if PDD margin >= 50%
        card_index_fb = {"892914632446": {"小熊头"}, "777000111222": {"香辣蘸料120g*10袋"}}
        fb_1688_base = {
            "row": 3,
            "skuid": "1992965625605226587",
            "visual_verified": True,
            "source": "https://detail.1688.com/offer/777000111222.html",
            "spec": "香辣蘸料120g*10袋",
            "checkout": "https://detail.1688.com/offer/777000111222.html",
            "units": 10,
            "paid": 20.0,
        }
        # 12a: No PDD evidence dir -> REJECTED
        expect_raises(
            lambda: prepare_patch_operations(SAMPLE_TASK, [fb_1688_base], card_index_fb, pdd_dirs=[]),
            "PDD-First Round-1 Gate",
        )
        # 12b: Has PDD evidence, but missing pdd_fallback_reason -> REJECTED
        expect_raises(
            lambda: prepare_patch_operations(SAMPLE_TASK, [fb_1688_base], card_index_fb, pdd_dirs=[wd / "pdd_kw"]),
            "pdd_fallback_reason",
        )
        # 12c: pdd_low_margin claimed, but pdd_best_unit_price=2.5 vs retail=5.5 (54.5% >= 50%) -> REJECTED!
        fb_cheat = dict(fb_1688_base, pdd_fallback_reason="pdd_low_margin", pdd_best_unit_price=2.5)
        expect_raises(
            lambda: prepare_patch_operations(SAMPLE_TASK, [fb_cheat], card_index_fb, pdd_dirs=[wd / "pdd_kw"]),
            "PDD-First Margin Gate",
        )
        # 12d: Valid PDD evidence + pdd_low_margin (pdd_best_unit_price=3.5 vs retail=5.5 -> 36.4% < 50%) -> PASS!
        fb_ok = dict(fb_1688_base, pdd_fallback_reason="pdd_low_margin", pdd_best_unit_price=3.5)
        ops_fb = prepare_patch_operations(SAMPLE_TASK, [fb_ok], card_index_fb, pdd_dirs=[wd / "pdd_kw"])
        assert len(ops_fb) == 1 and ops_fb[0][3]["channel"] == "1688"

        # 13. v3.4 Step 4A (Excel) PDD-first gate + Red-Team Audit
        import openpyxl

        xlsx_p = wd / "test.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "门店商品"
        ws.append(["SPUID", "SKUID", "分配人", "商品名称", "规格名称", "当前原价", "主图链接", "供货商品链接", "供货规格", "结算链接", "下单比例", "采购价", "单位采购价", "是否匹配", "供货商主图"])
        ws.append(["SPU1", "SKU_FOOD_1", "", "海天 味极鲜酱油 380ml/瓶", "380ml/瓶", 10.0, "", "", "", "", "", "", "", "未匹配", ""])
        wb.save(xlsx_p)

        dec_no_ev = wd / "dec_bad.json"
        dec_no_ev.write_text(json.dumps([{
            "row": 2,
            "skuid": "SKU_FOOD_1",
            "visual_verified": True,
            "source": "https://detail.1688.com/offer/777000111222.html",
            "spec": "香辣蘸料120g*10袋",
            "units": 10,
            "paid": 40.0,
            "img_url": "https://cbu01.alicdn.com/img/ibank/test.jpg",
            "pdd_fallback_reason": "pdd_no_match",
        }], ensure_ascii=False), encoding="utf-8")
        # Row 2 has NO pdd_kw/R2.json -> BLOCKED even without manifest.json!
        expect_raises(
            lambda: apply_decisions(xlsx_p, "门店商品", dec_no_ev, pdd_dirs=[wd / "pdd_kw"]),
            "PDD-First Round-1 Gate",
        )
        # Create genuine PDD search evidence R2.json -> PASS!
        (wd / "pdd_kw" / "R2.json").write_text(json.dumps({"row": 2, "blocked": False, "cands": []}), encoding="utf-8")
        n_upd = apply_decisions(xlsx_p, "门店商品", dec_no_ev, pdd_dirs=[wd / "pdd_kw"])
        assert n_upd == 1
        rep_ok = run_redteam_audit(xlsx_p, "门店商品", pdd_dirs=[wd / "pdd_kw"])
        assert rep_ok["pdd_first_1688_total"] == 1 and len(rep_ok["pdd_first_unverified_1688"]) == 0
        # Remove R2.json -> Red-Team Audit immediately flags unverified 1688 on food row!
        (wd / "pdd_kw" / "R2.json").unlink()
        rep_bad = run_redteam_audit(xlsx_p, "门店商品", pdd_dirs=[wd / "pdd_kw"])
        assert len(rep_bad["pdd_first_unverified_1688"]) == 1

    print(json.dumps({"passed": True, "tests": 13}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
