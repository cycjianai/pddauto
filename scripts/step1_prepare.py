#!/usr/bin/env python3
"""
Step 1: Prepare Manifest, Download Store Hero Photos & Classify Platform Routes (pddauto v3.0)
Usage:
  python3 step1_prepare.py --excel /path/to/sheet.xlsx --workdir /path/to/work [--sheet 门店商品] [--only-unmatched] [--rows 2-421]
Output:
  <workdir>/store/{row}.jpg
  <workdir>/manifest.json
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import openpyxl
from PIL import Image, ImageOps

FRESH_RE = re.compile(
    r"新鲜蔬菜|新鲜水果|鲜水果|鲜甜水果玉米|红富士.*水果|生菜|娃娃菜|香菜|小葱|鲜肉|猪肋排|五花肉|鲜鸡蛋|活虾|生鲜"
)
FRESH_EXCLUDE_RE = re.compile(
    r"干|零食|真空|即食|味|香精|洗发|沐浴|护手|香水|玩具|摆件|玩偶|公仔|"
    r"苹果\d|iPhone|iPad|iWatch|耳机|数据线|充电|手机壳|钢化膜|散热|电容笔|读卡器|扩展坞|"
    r"刀|汤圆|饺|包子|粥|贴|暖宝宝|指甲油|拖鞋|胸贴|起泡胶|刨丝器|菜板|盘子|牙签|竹签|土豆条|蛋花汤|果汁|奶茶|蒜瓣"
)
COMBO_RE = re.compile(r"调酒组合|礼盒组合|套装组合|整箱组合|多品组合|\+.*组合")
PDD_PRIORITY_RE = re.compile(
    r"零食|饮料|牛奶|纯牛奶|酸奶|鲜奶|矿泉水|饮用水|气泡水|汽水|可乐|雪碧|啤酒|鸡尾酒|咖啡|奶茶|茶饮料|"
    r"方便面|泡面|拌面|酸辣粉|螺蛳粉|米线|火鸡面|薯片|饼干|面包|吐司|蛋糕|辣条|凤爪|鸡爪|鸭脖|卤味|牛肉干|鸡胸肉|"
    r"花生|瓜子|坚果|葡萄干|山楂|红枣|蜜饯|糖果|巧克力|口香糖|槟榔|调料|调味料|调味酱|蘸料|底料|酱油|陈醋|香醋|蚝油|花生酱|芝麻酱|麻酱|辣椒酱|香米|食用油|猪油|"
    r"洗发水|护发素|沐浴露|洗面奶|洁面|卸妆|面霜|乳液|防晒|定妆喷雾|修容|粉底|口红|牙膏|卫生巾|护垫|纸尿裤|湿巾|洗脸巾|抽纸|卷纸|洗衣液|消毒液|洗液|"
    r"电饭煲|养生壶|电煮锅|电磁炉|吹风机|煎药壶|路由器|随身wifi|体脂秤"
)
DONE_STATUSES = {"已核可采购", "已核同款(毛利<50%)", "已核同款(售价为0)", "匹配", "已翻新1", "组合商品", "生鲜蔬果本地采购"}


def parse_rows_spec(spec: Optional[str], max_row: int) -> Optional[Set[int]]:
    if not spec:
        return None
    out: Set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), min(int(b), max_row) + 1))
        else:
            out.add(int(part))
    return out


def classify_route(name: str, spec: str) -> str:
    txt = f"{name} {spec}"
    if COMBO_RE.search(txt):
        return "combo"
    if FRESH_RE.search(txt) and not FRESH_EXCLUDE_RE.search(txt):
        return "fresh"
    if PDD_PRIORITY_RE.search(txt):
        return "pdd"
    return "1688"


def download_store_img(row: int, url: str, store_dir: Path) -> str:
    dest = store_dir / f"{row}.jpg"
    if dest.is_file() and dest.stat().st_size > 1024:
        return str(dest)
    if not url or not url.startswith("http"):
        return ""
    try:
        req = urllib.request.Request(url.replace("http://", "https://"), headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=15).read()
        with Image.open(BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((800, 800))
            im.save(dest, quality=90)
        return str(dest)
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=15).read()
            with Image.open(BytesIO(data)) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((800, 800))
                im.save(dest, quality=90)
            return str(dest)
        except Exception:
            return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 1: Prepare manifest & store images for pddauto v3.0")
    ap.add_argument("--excel", required=True, help="Input 15-column Excel path")
    ap.add_argument("--workdir", required=True, help="Working directory for cache/manifest/images")
    ap.add_argument("--sheet", default="门店商品", help="Worksheet name (falls back to active sheet)")
    ap.add_argument("--only-unmatched", action="store_true", help="Include only rows not yet finalized")
    ap.add_argument("--rows", default=None, help="Row range filter, e.g. '2-421' or '12,15,20-30'")
    ap.add_argument("--workers", type=int, default=6, help="Concurrent image download threads")
    args = ap.parse_args()

    excel_p = Path(args.excel).resolve()
    workdir = Path(args.workdir).resolve()
    store_dir = workdir / "store"
    store_dir.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.load_workbook(excel_p, data_only=True)
    ws = wb[args.sheet] if args.sheet in wb.sheetnames else wb.active
    row_filter = parse_rows_spec(args.rows, ws.max_row)

    rows_data: List[Dict[str, Any]] = []
    for r in range(2, ws.max_row + 1):
        if row_filter is not None and r not in row_filter:
            continue
        spuid = str(ws.cell(r, 1).value or "").strip()
        skuid = str(ws.cell(r, 2).value or "").strip()
        name = str(ws.cell(r, 4).value or "").strip()
        spec = str(ws.cell(r, 5).value or "").strip()
        if not name and not spuid and not skuid:
            continue
        raw_retail = ws.cell(r, 6).value
        try:
            retail = round(float(raw_retail), 2) if raw_retail not in (None, "") else 0.0
        except Exception:
            retail = 0.0
        img_url = str(ws.cell(r, 7).value or "").strip()
        status = str(ws.cell(r, 14).value or "").strip()
        if args.only_unmatched and status in DONE_STATUSES:
            continue
        rows_data.append({
            "row": r,
            "spuid": spuid,
            "skuid": skuid,
            "name": name,
            "spec": spec,
            "retail": retail,
            "store_img_url": img_url,
            "store_img_local": "",
            "status": status,
            "route": classify_route(name, spec),
        })

    def _dl(item: Dict[str, Any]) -> None:
        item["store_img_local"] = download_store_img(item["row"], item["store_img_url"], store_dir)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(_dl, rows_data))

    manifest = {
        "excel": str(excel_p),
        "sheet": ws.title,
        "workdir": str(workdir),
        "total": len(rows_data),
        "routes": {
            k: sum(1 for x in rows_data if x["route"] == k)
            for k in ("1688", "pdd", "combo", "fresh")
        },
        "rows": rows_data,
    }
    out_p = workdir / "manifest.json"
    out_p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    missing_img = sum(1 for x in rows_data if not x["store_img_local"])
    print(f"OK: Prepared {len(rows_data)} rows -> {out_p}")
    print(f"    Routes: {manifest['routes']} | Missing store imgs: {missing_img}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
