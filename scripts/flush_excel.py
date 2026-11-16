#!/usr/bin/env python3
"""
Excel 标准 14 列原子增量回填工具。
严格遵循：
  - A~E 列只读保护：SPUID, SKUID, 门店名称, 分配人, 规格名称
  - F 列：当前原价
  - G 列：主图链接 (门店主图)
  - H~M 列：采购比价输出 (供货链接, 规格, 结算链接, 比例, 采购价, 单位采购价公式)
  - N 列：是否匹配 ("匹配" / "不匹配")
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import openpyxl

EXCEL_PATH = "/Users/cenbusi/Desktop/2743.xlsx"
PROGRESS_PATH = "/tmp/pdd_sourcing_progress.json"
QNH_PATH = "/tmp/qnh_all_details_fixed.json"


def resolve_columns(ws) -> dict[str, int]:
    """通过第一行表头关键字动态解析列索引，找不到时回退到默认 14 列 (A~N)"""
    mapping = {
        "current_price": 6,  # F列: 当前原价
        "store_pic": 7,       # G列: 主图链接
        "goods_url": 8,       # H列: 供货商品链接
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


def main() -> int:
    parser = argparse.ArgumentParser(description="回填采购比价结果至 Excel 工作簿")
    parser.add_argument("--excel", default="", help="目标 Excel 文件路径")
    parser.add_argument("--progress", default=PROGRESS_PATH, help="进度元数据 JSON 路径")
    parser.add_argument("--start-row", type=int, default=49, help="开始回填行号（默认 49）")
    args = parser.parse_args()

    excel_path = args.excel or os.environ.get("EXCEL_PATH") or EXCEL_PATH
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

    count = 0
    max_r = ws.max_row
    for row in range(args.start_row, max_r + 1):
        r = progress.get(str(row))
        q = qnh_map.get(row, {})

        # 回填原价与门店主图
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

        if r and r.get("status") == "MATCHED":
            ws.cell(row=row, column=cols["goods_url"], value=r.get("goods_url", ""))
            ws.cell(row=row, column=cols["sku_specs"], value=r.get("sku_specs", ""))
            ws.cell(row=row, column=cols["checkout_url"], value=r.get("checkout_url", ""))
            ws.cell(row=row, column=cols["ratio"], value=int(r.get("ratio", 1)))
            ws.cell(row=row, column=cols["group_price"], value=round(float(r.get("group_price", 0)), 2))
            ws.cell(row=row, column=cols["unit_price"], value=f"=ROUND({col_l_letter}{row}/{col_k_letter}{row}, 2)")

            match_text = "不匹配" if r.get("match_status") == "MISMATCH" else "匹配"
            ws.cell(row=row, column=cols["match_status"], value=match_text)
            count += 1
        else:
            # 清理未匹配行的输出列（严格保护前 5 列 A~E 原样不动）
            for k_name in ["goods_url", "sku_specs", "checkout_url", "ratio", "group_price", "unit_price", "match_status"]:
                ws.cell(row=row, column=cols[k_name]).value = None

    wb.save(excel_path)
    print(f"[Excel] 成功同步 {count} 个匹配结果至 {excel_path} (工作表: {ws.title}, 总行数: {max_r}, 列数: {ws.max_column}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
