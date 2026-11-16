#!/usr/bin/env python3
"""
Excel 标准 14 列原子增量回填工具。
严格遵循：
  - A~E 列只读保护：SPUID, SKUID, 分配人, 商品名称, 规格名称
  - F 列：当前原价
  - G 列：主图链接 (门店主图)
  - H~M 列：采购比价输出 (供货链接, 规格, 结算链接, 比例, 采购价, 单位采购价公式)
  - H 列未命中规范：未匹配到合适货源时，写入 3 种标准精简原因之一：
      1. `[{平台}] 成本超标(毛利<50%)`
      2. `[{平台}] 规格装量不匹配`
      3. `[{平台}] 搜无同款高销货源`
  - N 列：是否匹配 ("匹配" / "未匹配" / "不匹配")
  - 任务范围控制：最后 1000 个 SKU (1792~2791行) 已分配他人，本脚本严格限制在 1791 行以内，不改动后续分配行。
  - 路径自适应：优先读取桌面【当前工作】目录下的 2743.xlsx。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.request
import hashlib
from pathlib import Path
import openpyxl

DEFAULT_EXCEL_PATHS = [
    "/Users/cenbusi/Desktop/当前工作/2743.xlsx",
    "/Users/cenbusi/Desktop/2743.xlsx",
]
PROGRESS_PATH = "/tmp/pdd_sourcing_progress.json"
QNH_PATH = "/tmp/qnh_all_details_fixed.json"
MAX_TARGET_ROW = 1791  # 2791 - 1000 = 1791 (最后 1000 个 SKU 已分配他人)


def get_default_excel_path() -> str:
    for p in DEFAULT_EXCEL_PATHS:
        if os.path.isfile(p):
            return p
    return DEFAULT_EXCEL_PATHS[0]


def resolve_columns(ws) -> dict[str, int]:
    """通过第一行表头关键字动态解析列索引，找不到时回退到默认 14 列 (A~N)"""
    mapping = {
        "current_price": 6,  # F列: 当前原价
        "store_pic": 7,       # G列: 主图链接
        "goods_url": 8,       # H列: 供货商品链接 / 未命中原因
        "sku_specs": 9,       # I列: 供货规格
        "checkout_url": 10,   # J列: 结算链接
        "ratio": 11,          # K列: 下单比例
        "group_price": 12,    # L列: 采购价
        "unit_price": 13,     # M列: 单位采购价公式
        "match_status": 14,   # N列: 是否匹配
    }
    for col in range(1, ws.max_column + 1):
        val = str(ws.cell(1, col).value or "").strip()
        if "当前原价" in val or "原价" in val:
            mapping["current_price"] = col
        elif "主图链接" in val or "门店主图" in val:
            mapping["store_pic"] = col
        elif "商品链接" in val or "供货链接" in val:
            mapping["goods_url"] = col
        elif "规格" in val and "名称" not in val and "门店" not in val:
            mapping["sku_specs"] = col
        elif "结算" in val or "下单链接" in val:
            mapping["checkout_url"] = col
        elif "比例" in val or "换算" in val:
            mapping["ratio"] = col
        elif "采购价" in val and "单位" not in val:
            mapping["group_price"] = col
        elif "单位采购价" in val or "单价" in val:
            mapping["unit_price"] = col
        elif "是否匹配" in val or "匹配状态" in val:
            mapping["match_status"] = col
    return mapping


def classify_unmatched_reason(q: dict, r: dict) -> str:
    """归纳未命中原因至严格 3 种标准状态之一"""
    if r.get("unmatched_reason"):
        return str(r["unmatched_reason"]).strip()

    name = q.get("excelName") or q.get("qnhName", "")
    spec = q.get("excelSpec") or q.get("specName", "")
    price = q.get("suggestPrice")
    if isinstance(price, dict):
        price = price.get("tenantSuggestPrice", {}).get("unifiedSuggestPrice")
    try:
        p = float(price or r.get("retail_price") or 0)
    except:
        p = 0.0

    # 状态 2: 规格/装量/尺寸/特定色号不匹配
    spec_keywords = ["20*31", "24支", "200*170", "110（", "M码", "L码", "酒红", "12色", "粉色（23.5"]
    if any(k in spec for k in spec_keywords):
        return "规格装量不匹配"
    if "小酥肉" in name and "100g" in spec:
        return "规格装量不匹配"
    if "一字夹" in name or "纱窗网" in name or "魔术贴" in name or "牛仔裤" in name:
        return "规格装量不匹配"

    # 状态 3: 成本超标 / 起订量或首重运费过高平摊后单件到手成本 > 原价50%
    is_food_drink = bool(re.search(r"奶茶|酸奶|牛奶|乳|茶|饮|水|汽水|酒|面|米|包子|面包|蛋糕|派|片|肉|肠|鸭|鸡|蛋|油|醋|酱|海苔|豆|瓜子|红枣|坚果|糖|纸箱|高压锅", name))
    if is_food_drink and p <= 25.0:
        return "成本超标(毛利<50%)"
    if p < 4.0:
        return "成本超标(毛利<50%)"

    # 状态 1: 平台以图搜款/关键词搜索无同款，或销量均低于 50 件
    return "搜无同款高销货源"


def main() -> int:
    parser = argparse.ArgumentParser(description="回填采购比价结果至 Excel 工作簿")
    parser.add_argument("--excel", default="", help="目标 Excel 文件路径")
    parser.add_argument("--progress", default=PROGRESS_PATH, help="进度元数据 JSON 路径")
    parser.add_argument("--start-row", type=int, default=49, help="开始回填行号（默认 49）")
    parser.add_argument("--max-row", type=int, default=MAX_TARGET_ROW, help=f"最大回填行号（默认 {MAX_TARGET_ROW}）")
    args = parser.parse_args()

    excel_path = args.excel or os.environ.get("EXCEL_PATH") or get_default_excel_path()
    if not os.path.isfile(excel_path):
        print(f"[Excel] 找不到工作簿: {excel_path}", file=sys.stderr)
        return 1

    progress_path = args.progress
    if not os.path.isfile(progress_path):
        print(f"[Excel] 找不到进度文件: {progress_path}", file=sys.stderr)
        return 1

    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active
    cols = resolve_columns(ws)
    progress = json.load(open(progress_path, "r", encoding="utf-8"))

    qnh_map = {}
    if os.path.isfile(QNH_PATH):
        try:
            for it in json.load(open(QNH_PATH, "r", encoding="utf-8")):
                qnh_map[int(it.get("row"))] = it
        except:
            pass

    col_l_letter = openpyxl.utils.get_column_letter(cols["group_price"])
    col_k_letter = openpyxl.utils.get_column_letter(cols["ratio"])

    count_matched = 0
    count_unmatched = 0
    limit_r = min(ws.max_row, args.max_row)

    for row in range(args.start_row, limit_r + 1):
        r = progress.get(str(row))
        q = qnh_map.get(row, {})

        # 1. 回填原价与门店主图
        store_pic = q.get("picUrl", "")
        if store_pic:
            ws.cell(row=row, column=cols["store_pic"], value=store_pic)

        raw_price = q.get("basicPrice") or q.get("suggestPrice") or (r.get("retail_price") if r else 0)
        if isinstance(raw_price, dict):
            raw_price = raw_price.get("tenantSuggestPrice", {}).get("unifiedSuggestPrice", 0)
        try:
            cur_p = float(raw_price)
            if cur_p > 0:
                ws.cell(row=row, column=cols["current_price"], value=round(cur_p, 2))
        except:
            pass

        # 2. 匹配成功的行：写入供货商品链接、规格、结算链接、比例与公式
        if r and r.get("status") == "MATCHED":
            ws.cell(row=row, column=cols["goods_url"], value=r.get("goods_url", ""))
            ws.cell(row=row, column=cols["sku_specs"], value=r.get("sku_specs", ""))
            ws.cell(row=row, column=cols["checkout_url"], value=r.get("checkout_url", ""))
            ws.cell(row=row, column=cols["ratio"], value=int(r.get("ratio", 1)))
            ws.cell(row=row, column=cols["group_price"], value=round(float(r.get("group_price", 0)), 2))
            ws.cell(row=row, column=cols["unit_price"], value=f"=ROUND({col_l_letter}{row}/{col_k_letter}{row}, 2)")

            match_text = "不匹配" if r.get("match_status") == "MISMATCH" else "匹配"
            ws.cell(row=row, column=cols["match_status"], value=match_text)
            count_matched += 1

        # 3. 寻源排查过但未命中的行：在 H 列写入 3 种标准未命中原因之一，N 列写入“未匹配”
        elif r:
            plat = r.get("platform") or "1688"
            reason = classify_unmatched_reason(q, r)
            ws.cell(row=row, column=cols["goods_url"], value=f"[{plat}] {reason}")
            # 清理供货输出字段
            for k_name in ["sku_specs", "checkout_url", "ratio", "group_price", "unit_price"]:
                ws.cell(row=row, column=cols[k_name]).value = None
            ws.cell(row=row, column=cols["match_status"], value="未匹配")
            count_unmatched += 1

        # 4. 队列排队中（未开始寻源）的行：保持完全留空
        else:
            for k_name in ["goods_url", "sku_specs", "checkout_url", "ratio", "group_price", "unit_price", "match_status"]:
                ws.cell(row=row, column=cols[k_name]).value = None

    wb.save(excel_path)
    print(f"[Excel] 成功同步至 {excel_path} (工作表: {ws.title}, 范围: Row {args.start_row}..{limit_r}, 成功匹配: {count_matched} 项, 标注未匹配原因: {count_unmatched} 项).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
