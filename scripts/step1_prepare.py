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
PDD_CATEGORY_RE = re.compile(
    r"食品|零食|饮品|饮料|速食|罐头|粮油|调味|干货|冲调|乳饮|酒水|茶叶|咖啡|"
    r"个人洗护|个护|洗护|护肤|纸品|家清|母婴用品.*尿裤|尿不湿|宠物食品|猫粮|狗粮|猫罐头"
)
GENERAL_MERCH_CATEGORY_RE = re.compile(
    r"家居日用|家纺布艺|厨具餐具|水具|五金|服饰|鞋靴|箱包|美妆工具|化妆刷|玩具|文具|办公|运动户外|汽车用品|智能穿戴配件|数码配件|手机配件"
)
NON_FMCG_OBJECT_RE = re.compile(
    r"收纳盒|收纳篮|整理箱|玻璃杯|水杯|保温杯|果茶杯|奶茶杯|果汁杯|咖啡杯|条绒浴巾|大浴巾|化妆刷|鼻影刷|眼影刷|开瓶器|启瓶器|开酒器|修眉刀|刮眉刀|防晒口罩|立体.*口罩|一次性.*口罩|医用口罩|防晒衣|冰袖|遮阳帽|遮阳伞|充电器|数据线|保护壳|手机壳"
)
PDD_PRIORITY_RE = re.compile(
    r"零食|饮料|牛奶|纯牛奶|酸奶|鲜奶|矿泉水|饮用水|气泡水|汽水|可乐|雪碧|啤酒|鸡尾酒|清酒|红酒|白酒|咖啡|奶茶|茶饮料|茶叶|茶包|绿茶|红茶|乌龙茶|花茶|袋泡茶|凉茶|果茶|厚椰乳|椰浆|八宝粥|麦片|燕麦|豆浆|藕粉|芝麻糊|"
    r"方便面|泡面|拌面|板面|干脆面|酸辣粉|螺蛳粉|米线|火鸡面|薯片|薯条|锅巴|曲奇|饼干|面包|吐司|蛋糕|蛋挞皮|辣条|素肉|素食|豆干|魔芋|鱼豆腐|海苔|紫菜|榨菜|凤爪|鸡爪|鸭脖|鸭舌|鸭肝|鸭掌|鸭翅|卤味|牛肉干|鸡胸肉|鸡肉肠|火腿肠|猪油渣|活珠子|皮蛋|肉松|"
    r"花生|瓜子|坚果|葡萄干|山楂|红枣|蜜饯|话梅|西梅|糖果|巧克力|果冻|口香糖|槟榔|雪花酥|猫耳朵|"
    r"调料|调味料|调味酱|蘸料|底料|酱油|生抽|老抽|陈醋|香醋|蚝油|番茄酱|番茄沙司|花生酱|芝麻酱|麻酱|辣椒酱|腐乳|大米|香米|挂面|白砂糖|麦芽糖|黄油|奶酪|芝士|食用油|猪油|熟白芝麻|"
    r"洗发水|洗发露|护发素|沐浴露|沐浴|洗面奶|洁面|卸妆|面霜|乳液|防晒霜|防晒露|防晒乳|防晒喷雾|定妆喷雾|粉底|口红|唇膏|精华|面膜|护手霜|身体乳|搓泥宝|发蜡|"
    r"牙膏|牙刷|漱口水|卫生巾|护垫|纸尿裤|拉拉裤|尿不湿|湿巾|洗脸巾|抽纸|卷纸|洗衣液|洗衣粉|洗衣凝珠|柔顺剂|肥皂|香皂|洗洁精|洁厕|消毒液|洗液|"
    r"猫粮|狗粮|猫罐头|猫条|宠物零食|"
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


def classify_route(name: str, spec: str, category: str = "") -> str:
    txt = f"{name} {spec}"
    if COMBO_RE.search(txt):
        return "combo"
    if FRESH_RE.search(txt) and not FRESH_EXCLUDE_RE.search(txt):
        return "fresh"
    # True consumable paper/diaper/hygiene items always stay PDD-first
    if re.search(r"洗脸巾|湿巾|抽纸|卷纸|卫生巾|纸尿裤|拉拉裤|尿不湿", txt):
        return "pdd"
    if category:
        if PDD_CATEGORY_RE.search(category) and not GENERAL_MERCH_CATEGORY_RE.search(category):
            return "pdd"
        if GENERAL_MERCH_CATEGORY_RE.search(category):
            return "1688"
    if NON_FMCG_OBJECT_RE.search(txt):
        return "1688"
    if PDD_PRIORITY_RE.search(txt):
        return "pdd"
    return "1688"


def build_platform_policy(route: str) -> Dict[str, Any]:
    """Return enforceable Round-1 platform lock contract for manifest.json (pddauto v3.4)."""
    if route == "pdd":
        return {
            "platform_policy": "pdd_first_lock",
            "round1_platform": "pdd",
            "fallback_platforms": ["1688"],
            "fallback_conditions": ["pdd_no_match", "pdd_low_margin"],
        }
    if route == "1688":
        return {
            "platform_policy": "1688_first",
            "round1_platform": "1688",
            "fallback_platforms": ["pdd"],
            "fallback_conditions": [],
        }
    return {
        "platform_policy": "no_sourcing",
        "round1_platform": "",
        "fallback_platforms": [],
        "fallback_conditions": [],
    }


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
        route = classify_route(name, spec)
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
            "route": route,
            **build_platform_policy(route),
        })

    def _dl(item: Dict[str, Any]) -> None:
        item["store_img_local"] = download_store_img(item["row"], item["store_img_url"], store_dir)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(_dl, rows_data))

    manifest = {
        "policy_version": "v3.4",
        "excel": str(excel_p),
        "sheet": ws.title,
        "workdir": str(workdir),
        "total": len(rows_data),
        "routes": {
            k: sum(1 for x in rows_data if x["route"] == k)
            for k in ("1688", "pdd", "combo", "fresh")
        },
        "pdd_first_locked_count": sum(1 for x in rows_data if x.get("platform_policy") == "pdd_first_lock"),
        "rows": rows_data,
    }
    out_p = workdir / "manifest.json"
    out_p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    missing_img = sum(1 for x in rows_data if not x["store_img_local"])
    print(f"OK: Prepared {len(rows_data)} rows -> {out_p}")
    print(f"    Routes: {manifest['routes']} | PDD-First Locked: {manifest['pdd_first_locked_count']} | Missing store imgs: {missing_img}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
