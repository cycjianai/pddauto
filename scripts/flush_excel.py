#!/usr/bin/env python3
"""
Excel 标准 6 列（F~K 列）原子增量回填工具。
支持动态参数指定工作簿路径、自适应 Sheet 与动态行数识别。
严格保护 A~E 前五列输入信息，仅写入 F~K 六列采购与比价结果。
支持 --embed-images: 在表格中直接内嵌商品高清缩略图，避免逐个点开链接引发风控。
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import sys
import urllib.request
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import openpyxl
from openpyxl.drawing.image import Image
from PIL import Image as PILImage

CACHE_DIR = "/tmp/sourcing_thumbs"
os.makedirs(CACHE_DIR, exist_ok=True)


def get_cached_thumbnail(url: str, size: int = 100) -> str | None:
    if not url or not url.startswith("http"):
        return None
    h = hashlib.md5(url.encode()).hexdigest()
    p = os.path.join(CACHE_DIR, f"{h}_{size}.jpg")
    if os.path.isfile(p):
        return p
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=6).read()
        im = PILImage.open(io.BytesIO(data))
        im.thumbnail((size, size))
        im.convert("RGB").save(p, format="JPEG", quality=85)
        return p
    except Exception:
        return None


def find_default_excel() -> str:
    env_path = os.environ.get("EXCEL_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    desktop = Path.home() / "Desktop"
    candidates = sorted(desktop.glob("*.xlsx"))
    if candidates:
        return str(candidates[0])
    cwd_candidates = sorted(Path(".").glob("*.xlsx"))
    if cwd_candidates:
        return str(cwd_candidates[0])
    return "/Users/cenbusi/Desktop/2743.xlsx"


def resolve_columns(ws) -> dict[str, int]:
    """通过第一行表头关键字动态解析列索引，找不到时回退到默认标准 6 列 (F~K: 6..11)"""
    mapping = {
        "goods_url": 6,     # F列: 商品链接
        "sku_specs": 7,     # G列: 供货规格
        "checkout_url": 8,  # H列: 结算链接
        "ratio": 9,         # I列: 下单比例
        "group_price": 10,  # J列: 采购总价
        "unit_price": 11,   # K列: 单位采购价公式
        "image_col": 12,    # L列: 供货主图 (可选嵌入)
    }
    for col in range(1, ws.max_column + 1):
        val = str(ws.cell(1, col).value or "").strip()
        if "商品链接" in val or "供货链接" in val:
            mapping["goods_url"] = col
        elif "规格" in val and "名称" not in val:
            mapping["sku_specs"] = col
        elif "结算" in val or "下单链接" in val:
            mapping["checkout_url"] = col
        elif "比例" in val or "换算" in val:
            mapping["ratio"] = col
        elif "采购价" in val and "单位" not in val:
            mapping["group_price"] = col
        elif "单位采购价" in val or "单价" in val:
            mapping["unit_price"] = col
        elif "主图" in val or "供货图" in val or "图片" in val:
            mapping["image_col"] = col
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="回填采购比价结果至 Excel 工作簿")
    parser.add_argument("--excel", default="", help="目标 Excel 文件路径")
    parser.add_argument("--progress", default="/tmp/pdd_sourcing_progress.json", help="进度元数据 JSON 路径")
    parser.add_argument("--start-row", type=int, default=49, help="开始回填行号（默认 49，保护前 48 行模板）")
    parser.add_argument("--embed-images", action="store_true", help="在表格中直接内嵌供货商高清商品主图缩略图")
    args = parser.parse_args()

    excel_path = args.excel or find_default_excel()
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

    col_j_letter = openpyxl.utils.get_column_letter(cols["group_price"])
    col_i_letter = openpyxl.utils.get_column_letter(cols["ratio"])

    # 如果开启图片嵌入且表头还没有主图列，在最后追加表头
    img_col = cols.get("image_col", 12)
    if args.embed_images:
        img_col_letter = openpyxl.utils.get_column_letter(img_col)
        ws.cell(row=1, column=img_col, value="供货商主图")
        ws.column_dimensions[img_col_letter].width = 14

    # 并发预下载缩略图
    if args.embed_images:
        matched_urls = [v.get("main_pic") for v in progress.values() if v.get("main_pic")]
        with ThreadPoolExecutor(max_workers=16) as ex:
            list(ex.map(get_cached_thumbnail, matched_urls))

    count = 0
    max_r = ws.max_row
    for row in range(args.start_row, max_r + 1):
        r = progress.get(str(row))
        if r and r.get("status") == "MATCHED":
            ws.cell(row=row, column=cols["goods_url"], value=r.get("goods_url", ""))
            ws.cell(row=row, column=cols["sku_specs"], value=r.get("sku_specs", ""))
            ws.cell(row=row, column=cols["checkout_url"], value=r.get("checkout_url", ""))
            ws.cell(row=row, column=cols["ratio"], value=int(r.get("ratio", 1)))
            ws.cell(row=row, column=cols["group_price"], value=round(float(r.get("group_price", 0)), 2))
            ws.cell(row=row, column=cols["unit_price"], value=f"=ROUND({col_j_letter}{row}/{col_i_letter}{row}, 2)")

            if args.embed_images:
                ws.row_dimensions[row].height = 60
                pic_url = r.get("main_pic", "")
                thumb_path = get_cached_thumbnail(pic_url)
                if thumb_path and os.path.isfile(thumb_path):
                    try:
                        img = Image(thumb_path)
                        img.width = 56
                        img.height = 56
                        img_col_letter = openpyxl.utils.get_column_letter(img_col)
                        ws.add_image(img, f"{img_col_letter}{row}")
                        # 兼容写入 WPS 的 DISPIMG 公式
                        ws.cell(row=row, column=img_col, value=f'=DISPIMG("{pic_url}", 1)')
                    except Exception:
                        pass
            count += 1
        else:
            # 清理未匹配行的输出列（严格保护前 5 列 A~E 原样不动）
            for k_name in ["goods_url", "sku_specs", "checkout_url", "ratio", "group_price", "unit_price"]:
                ws.cell(row=row, column=cols[k_name]).value = None
            if args.embed_images:
                ws.cell(row=row, column=img_col).value = None

    wb.save(excel_path)
    print(f"[Excel] 成功同步 {count} 个匹配结果至 {excel_path} (工作表: {ws.title}, 总行数: {max_r}, 嵌入图片: {args.embed_images}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
