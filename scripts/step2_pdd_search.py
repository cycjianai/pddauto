#!/usr/bin/env python3
"""
Step 2B: Pinduoduo Native App ADB Search & SKU Inspector (pddauto v3.0)
Modes:
  --mode smart-kw    : Brand-banner-bypass keyword search -> <workdir>/pdd_kw/R{row}.json + hero JPGs
  --mode img         : Atomic single-photo album search (0 album pollution) -> <workdir>/pdd_img/R{row}.json + hero JPGs
  --mode inspect-sku : Direct deep-link goods_id + tap specific SKUs -> <workdir>/pdd_inspect/{tag}_{gid}.json
Immediately aborts with exit code 9 on any risk/captcha/login prompt (strict no-bypass).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.adb_pdd import PddPhone


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 2B: Pinduoduo native App ADB search & SKU inspector")
    ap.add_argument("--workdir", required=True, help="Working directory containing store/ and output subdirs")
    ap.add_argument("--mode", required=True, choices=["smart-kw", "img", "inspect-sku"])
    ap.add_argument("--jobs-file", default=None, help="[smart-kw|img] Path to jobs JSON file")
    ap.add_argument("--subdir", default=None, help="Override output subdirectory under workdir")
    ap.add_argument("--gid", default=None, help="[inspect-sku] PDD goods_id")
    ap.add_argument("--taps", default="", help="[inspect-sku] Comma-separated SKU keywords to tap")
    ap.add_argument("--tag", default="inspect", help="[inspect-sku] Output file prefix tag")
    ap.add_argument("--device", default=None, help="Explicit ADB device serial (auto-detected if omitted)")
    ap.add_argument("--overwrite", action="store_true", help="Re-run even if cached JSON exists")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    phone = PddPhone(device=args.device, work_tmp=workdir / "observe")
    print(f"[PDD ADB] Device={phone.device} res={phone.screen_w}x{phone.screen_h}", flush=True)

    if args.mode == "inspect-sku":
        if not args.gid:
            raise SystemExit("--mode inspect-sku requires --gid")
        out_dir = workdir / (args.subdir or "pdd_inspect")
        taps = [x.strip() for x in args.taps.split(",") if x.strip()]
        res = phone.inspect_goods_skus(str(args.gid), taps, out_dir, args.tag)
        (out_dir / f"{args.tag}_{args.gid}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 9 if res.get("blocked") else 0

    if not args.jobs_file:
        raise SystemExit(f"--mode {args.mode} requires --jobs-file")
    jobs = json.loads(Path(args.jobs_file).read_text(encoding="utf-8"))
    out_dir = workdir / (args.subdir or ("pdd_kw" if args.mode == "smart-kw" else "pdd_img"))
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, item in enumerate(jobs, 1):
        # Accept either dict {"row":..., "kw":..., "max_cards":..., "sort_sales":...} or list [row, kw, max_cards, sort_sales]
        if isinstance(item, dict):
            r = int(item["row"])
            kw = str(item.get("kw", ""))
            mc = int(item.get("max_cards", 2))
            sort_sales = bool(item.get("sort_sales", args.mode == "smart-kw"))
        else:
            r = int(item[0])
            if args.mode == "smart-kw":
                kw = str(item[1])
                mc = int(item[2]) if len(item) > 2 else 2
                sort_sales = bool(item[3]) if len(item) > 3 else True
            else:
                kw = ""
                mc = int(item[1]) if len(item) > 1 else 2
                sort_sales = bool(item[2]) if len(item) > 2 else False

        out_f = out_dir / f"R{r}.json"
        if not args.overwrite and out_f.is_file():
            old = json.loads(out_f.read_text(encoding="utf-8"))
            if old.get("cands"):
                print(f"[{i}/{len(jobs)}] R{r} CACHED ({len(old['cands'])} cands)", flush=True)
                continue

        if args.mode == "smart-kw":
            print(f"[{i}/{len(jobs)}] [SMART KW] R{r}: {kw} (sort_sales={sort_sales})", flush=True)
            res = phone.smart_kw_search(kw, out_dir, f"R{r}", max_cards=mc, sort_sales=sort_sales)
        else:
            print(f"[{i}/{len(jobs)}] [ATOMIC IMG] R{r} (sort_sales={sort_sales})", flush=True)
            res = phone.atomic_image_search(workdir / "store" / f"{r}.jpg", out_dir, f"R{r}", max_cards=mc, sort_sales=sort_sales)

        res["row"] = r
        out_f.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    -> cands={len(res.get('cands', []))} err={res.get('err', '')} blocked={res.get('blocked', False)}", flush=True)
        if res.get("blocked"):
            print(f"[BLOCKED_HALT] R{r}: PDD risk/captcha prompt detected. Stopping immediately (no bypass).", flush=True)
            return 9
        time.sleep(random.uniform(2.3, 3.3))

    print("PDD_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
