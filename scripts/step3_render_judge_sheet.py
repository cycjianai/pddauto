#!/usr/bin/env python3
"""
Step 3: Mandatory Visual Audit Contact-Sheet & Evidence Renderer (pddauto v3.0)
Renders side-by-side Store vs Supplier visual comparison sheets (max 10 rows/sheet) + structured SKU/OCR/Attr text
so the Multimodal LLM Judge MUST visually inspect photos + SKUs + attributes before ANY row enters decisions.json.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def load_font(size: int) -> ImageFont.ImageFont:
    for fp in FONT_CANDIDATES:
        if os.path.isfile(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def fetch_cached_img(url: str, cache_dir: Path, name: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    dest = cache_dir / f"{name}.jpg"
    if dest.is_file() and dest.stat().st_size > 1000:
        return str(dest)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=12).read()
        dest.write_bytes(data)
        return str(dest)
    except Exception:
        return ""


def collect_1688_candidates(workdir: Path, r: int, thumb_cache: Path) -> List[Dict[str, Any]]:
    cands: List[Dict[str, Any]] = []
    # Prefer fetched detail cards (acard/{r}-{oid}*.json)
    for fp in sorted(glob.glob(str(workdir / "acard" / f"{r}-*.json"))):
        d = json.loads(Path(fp).read_text(encoding="utf-8"))
        oid = str(d.get("oid") or Path(fp).stem.split("-")[1])
        img_u = d.get("img_url") or d.get("image") or ""
        if not img_u:
            for row in (d.get("rows") or []):
                if row.get("img"):
                    img_u = row["img"]
                    break
        local_img = fetch_cached_img(img_u, thumb_cache, f"1688_{r}_{oid}")
        cands.append({
            "id": oid,
            "label": f"{oid} {'[CLICKED]' if d.get('clicked_option') else ''}".strip(),
            "img": local_img,
            "img_url": img_u,
            "title": d.get("goods") or d.get("title") or "",
            "main": str(d.get("main") or "").replace("\n", " "),
            "moq": d.get("moq"),
            "order_multiple": d.get("order_multiple"),
            "ship": d.get("ship") or "",
            "sales": d.get("sales_lbl") or "",
            "attrs": str(d.get("attrs") or "").replace("\n", " | ")[:350],
            "options": [o.get("v") if isinstance(o, dict) else str(o) for o in (d.get("options") or [])[:15]],
            "rows": [(row.get("v", ""), row.get("info", [])) for row in (d.get("rows") or [])[:25]],
            "qnh_specs": d.get("qnh_specs") or [],
            "sku_txt": str((d.get("meta") or {}).get("sku_txt") or "").replace("\n", " | ")[:400],
        })
    return cands


def collect_pdd_candidates(workdir: Path, r: int, subdirs: List[str]) -> List[Dict[str, Any]]:
    cands: List[Dict[str, Any]] = []
    seen = set()
    for sd in subdirs:
        fp = workdir / sd / f"R{r}.json"
        if not fp.is_file():
            continue
        d = json.loads(fp.read_text(encoding="utf-8"))
        for c in d.get("cands", []):
            gid = str(c.get("gid", ""))
            if not gid or gid in seen:
                continue
            seen.add(gid)
            hero = c.get("hero") or ""
            if not hero or not os.path.isfile(hero):
                hits = glob.glob(str(workdir / sd / f"R{r}_*_{gid}_hero.jpg"))
                hero = hits[0] if hits else ""
            cands.append({
                "id": gid,
                "label": f"{sd}:{gid}",
                "img": hero,
                "detail": " | ".join(c.get("detail", [])[:18]),
                "sku": " | ".join(c.get("sku", [])[:35]),
            })
    return cands


def render_sheet(
    rows_meta: List[Dict[str, Any]],
    workdir: Path,
    platform: str,
    pdd_subdirs: List[str],
    out_img: Path,
    out_txt: Path,
) -> None:
    thumb_cache = workdir / "judge_thumbs"
    thumb_cache.mkdir(parents=True, exist_ok=True)
    font = load_font(17)
    font_sm = load_font(14)

    W, H_ROW = 1220, 325
    canvas = Image.new("RGB", (W, H_ROW * max(1, len(rows_meta))), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    lines: List[str] = []

    for idx, meta in enumerate(rows_meta):
        y0 = idx * H_ROW
        r = int(meta["row"])
        name = meta.get("name", "")
        spec = meta.get("spec", "")
        retail = meta.get("retail", 0)
        skuid = meta.get("skuid", "")

        draw.rectangle([0, y0, W, y0 + 48], fill=(234, 242, 253))
        draw.text((10, y0 + 12), f"R{r} | {name[:42]} | 规:{spec[:22]} | 售¥{retail}", fill=(15, 23, 42), font=font)

        sp = meta.get("store_img_local") or str(workdir / "store" / f"{r}.jpg")
        if os.path.isfile(sp):
            im = Image.open(sp).convert("RGB")
            im.thumbnail((235, 235))
            canvas.paste(im, (12, y0 + 58))
        draw.text((12, y0 + 298), f"STORE skuid={skuid}", fill=(30, 64, 175), font=font_sm)

        cands = (
            collect_1688_candidates(workdir, r, thumb_cache)
            if platform == "1688"
            else collect_pdd_candidates(workdir, r, pdd_subdirs)
        )
        lines.append(f"\n================ R{r} | SKUID={skuid} | {name} | 规:{spec} | 售¥{retail} ================")
        if not cands:
            lines.append("  [NO_CANDIDATES]")
        for ci, c in enumerate(cands[:3]):
            x_base = 275 + ci * 315
            if c.get("img") and os.path.isfile(c["img"]):
                im = Image.open(c["img"]).convert("RGB")
                im.thumbnail((235, 235))
                canvas.paste(im, (x_base, y0 + 58))
            draw.text((x_base, y0 + 298), f"c{ci} {c['label'][:30]}", fill=(185, 28, 28), font=font_sm)
            if platform == "1688":
                moq_s = f" | moq={c['moq']} mult={c['order_multiple']}" if c.get("moq") or c.get("order_multiple") else ""
                lines.append(f"  [c{ci}] oid={c['id']} | title={c['title'][:60]} | sales={c['sales']}{moq_s} | main={c['main'][:90]}")
                lines.append(f"       ship={c['ship']} | img_url={c['img_url']}")
                lines.append(f"       attrs={c['attrs']}")
                if c.get("qnh_specs"):
                    lines.append("       [QNH_SPECS 必须逐字原样抄录，严禁增删改任何字/空格/备注]:")
                    for qs in c["qnh_specs"][:25]:
                        sp_raw = qs.get("spec", "")
                        sp_warn = " [含连续空格!原样保留]" if "  " in sp_raw else ""
                        q_moq = qs.get("moq") or c.get("moq")
                        q_mult = qs.get("order_multiple") or c.get("order_multiple")
                        q_extra = f" | 起购={q_moq} | 倍数={q_mult}" if (q_moq or q_mult) else ""
                        lines.append(
                            f"         SPEC={sp_raw!r} | ¥{qs.get('price')} | 库存={qs.get('stock')}{q_extra}{sp_warn}"
                        )
                else:
                    if c["options"]:
                        lines.append(f"       options={c['options']}")
                    for rv, rinfo in c["rows"][:18]:
                        lines.append(f"       ROW: {rv} -> {rinfo}")
                    if not c["rows"] and c["sku_txt"]:
                        lines.append(f"       sku_txt={c['sku_txt']}")
            else:
                lines.append(f"  [c{ci}] gid={c['id']} ({c['label']})")
                lines.append(f"       detail: {c['detail']}")
                lines.append(f"       sku:    {c['sku']}")
        draw.line([(0, y0 + H_ROW - 1), (W, y0 + H_ROW - 1)], fill=(203, 213, 225), width=2)

    out_img.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_img, quality=90)
    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"OK: Rendered {len(rows_meta)} rows -> {out_img} & {out_txt}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 3: Render mandatory visual judge sheets")
    ap.add_argument("--manifest", required=True, help="Path to manifest.json from step1_prepare.py")
    ap.add_argument("--workdir", required=True, help="Working directory")
    ap.add_argument("--platform", required=True, choices=["1688", "pdd"])
    ap.add_argument("--rows", required=True, help="JSON list of row numbers, e.g. '[2,3,4]'")
    ap.add_argument("--pdd-subdirs", default="pdd_kw,pdd_img", help="Comma-separated PDD result subdirs under workdir")
    ap.add_argument("--out-prefix", required=True, help="Output file prefix (e.g. /path/work/judge/batch1)")
    ap.add_argument("--chunk-size", type=int, default=10, help="Max rows per visual contact sheet (default 10)")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    by_row = {int(x["row"]): x for x in manifest.get("rows", [])}
    target_rows = [by_row[int(r)] for r in json.loads(args.rows) if int(r) in by_row]
    pdd_subdirs = [s.strip() for s in args.pdd_subdirs.split(",") if s.strip()]

    prefix = Path(args.out_prefix)
    for part_idx in range(0, len(target_rows), args.chunk_size):
        chunk = target_rows[part_idx : part_idx + args.chunk_size]
        suffix = f"_p{part_idx // args.chunk_size + 1}" if len(target_rows) > args.chunk_size else ""
        render_sheet(
            chunk,
            Path(args.workdir).resolve(),
            args.platform,
            pdd_subdirs,
            Path(f"{prefix}{suffix}.jpg"),
            Path(f"{prefix}{suffix}.txt"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
