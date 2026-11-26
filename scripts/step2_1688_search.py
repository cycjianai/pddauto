#!/usr/bin/env python3
"""
Step 2A: 1688 100% Silent Background Search & Detail Fetcher (pddauto v3.0)
Modes:
  --mode img    : Silent background image search -> <workdir>/aliimg/{row}.json
  --mode kw     : Silent background keyword search -> <workdir>/alikw/{row}.json
  --mode detail : Silent background offer detail + optional tier-1 SKU click -> <workdir>/acard/{row}-{oid}.json
                  Enforces anti-CAPTCHA cadence (cooldown after every --burst offers, exit 9 immediately on challenge).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.cdp_1688 import (
    load_offer_card,
    open_silent_1688_session,
    silent_image_search,
    silent_keyword_search,
)


def _has_valid_pdd_artifact(workdir: Path, row: int) -> bool:
    """Verify at least one non-blocked PDD search JSON (pdd_*/R{row}.json) exists on disk."""
    for sub in sorted(workdir.glob("pdd*")):
        if not sub.is_dir():
            continue
        fp = sub / f"R{row}.json"
        if not fp.is_file():
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("blocked") is True:
            continue
        if "cands" not in data and "candidates" not in data:
            continue
        if data.get("row") is not None and int(data["row"]) != row:
            continue
        return True
    return False


def enforce_pdd_first_before_1688(workdir: Path, rows: list[int]) -> None:
    """HARD GATE (pddauto v3.4): Refuse to run 1688 search/detail on Round-1 PDD-locked rows
    until real PDD search artifacts exist on disk (pdd_*/R{row}.json)."""
    manifest_p = workdir / "manifest.json"
    if not manifest_p.is_file():
        return
    try:
        manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    except Exception:
        return
    locked_rows = {
        int(it["row"])
        for it in (manifest.get("rows") or [])
        if it.get("row") is not None
        and (it.get("platform_policy") == "pdd_first_lock" or it.get("route") == "pdd")
    }
    if not locked_rows:
        return
    violations = sorted({int(r) for r in rows if int(r) in locked_rows and not _has_valid_pdd_artifact(workdir, int(r))})
    if violations:
        sample = violations[:15]
        raise RuntimeError(
            f"[PDD_FIRST_GATE_BLOCKED] {len(violations)} row(s) are locked to Round-1 PDD "
            f"(food/FMCG platform_policy='pdd_first_lock') and have ZERO PDD search artifacts on disk: {sample}. "
            f"You MUST run step2_pdd_search.py FIRST (Round 1) before falling back to 1688!"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 2A: 1688 silent background search/detail engine")
    ap.add_argument("--workdir", required=True, help="Working directory containing store/ and output subdirs")
    ap.add_argument("--mode", required=True, choices=["img", "kw", "detail"])
    ap.add_argument("--rows", default=None, help="[img] JSON list of row numbers, e.g. '[2,3,4]'")
    ap.add_argument("--rows-file", default=None, help="[img] Path to JSON list of row numbers")
    ap.add_argument("--jobs-file", default=None, help="[kw] Path to JSON list of {'row': int, 'kw': str}")
    ap.add_argument("--plan-file", default=None, help="[detail] Path to JSON list of {'row': int, 'oid': str, 'option'?: str}")
    ap.add_argument("--cdp-port", type=int, default=None, help="Explicit Chrome remote debugging port (auto-discovered if omitted)")
    ap.add_argument("--burst", type=int, default=18, help="[detail] Pause cooldown after this many offers (default 18)")
    ap.add_argument("--cooldown", type=int, default=65, help="[detail] Cooldown seconds between bursts (default 65)")
    ap.add_argument("--kw-burst", type=int, default=4, help="[kw] Pause cooldown after this many keyword searches (default 4)")
    ap.add_argument("--kw-cooldown", type=int, default=55, help="[kw] Cooldown seconds between kw bursts (default 55)")
    ap.add_argument("--img-burst", type=int, default=12, help="[img] Pause cooldown after this many image searches (default 12)")
    ap.add_argument("--img-cooldown", type=int, default=45, help="[img] Cooldown seconds between img bursts (default 45)")
    ap.add_argument("--img-delay-min", type=float, default=5.2, help="[img] Minimum seconds between img searches (default 5.2)")
    ap.add_argument("--img-delay-max", type=float, default=6.8, help="[img] Maximum seconds between img searches (default 6.8)")
    ap.add_argument("--overwrite", action="store_true", help="Re-fetch even if cached JSON exists")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()

    # Pre-validate Round-1 PDD lock BEFORE even opening Chrome CDP so unsearched food/FMCG rows fail fast!
    if args.mode == "img":
        if args.rows_file:
            _pre_rows = json.loads(Path(args.rows_file).read_text(encoding="utf-8"))
        elif args.rows:
            _pre_rows = json.loads(args.rows)
        else:
            raise SystemExit("--mode img requires --rows or --rows-file")
        enforce_pdd_first_before_1688(workdir, [int(r) for r in _pre_rows])
    elif args.mode == "kw":
        if not args.jobs_file:
            raise SystemExit("--mode kw requires --jobs-file")
        _pre_jobs = json.loads(Path(args.jobs_file).read_text(encoding="utf-8"))
        enforce_pdd_first_before_1688(workdir, [int(j["row"]) for j in _pre_jobs])
    elif args.mode == "detail":
        if not args.plan_file:
            raise SystemExit("--mode detail requires --plan-file")
        _pre_plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
        enforce_pdd_first_before_1688(workdir, [int(p["row"]) for p in _pre_plan if p.get("row") is not None])

    sess, tab_id, cdp_base = open_silent_1688_session(args.cdp_port)
    print(f"[1688 SILENT] Attached to {cdp_base} tab={tab_id} (zero focus/mouse steal)", flush=True)

    try:
        if args.mode == "img":
            if args.rows_file:
                rows = json.loads(Path(args.rows_file).read_text(encoding="utf-8"))
            elif args.rows:
                rows = json.loads(args.rows)
            else:
                raise SystemExit("--mode img requires --rows or --rows-file")
            out_dir = workdir / "aliimg"
            out_dir.mkdir(parents=True, exist_ok=True)
            fetched_since_cool = 0
            for i, r in enumerate(rows, 1):
                out_f = out_dir / f"{r}.json"
                if not args.overwrite and out_f.is_file():
                    old = json.loads(out_f.read_text(encoding="utf-8"))
                    if old.get("items"):
                        print(f"[{i}/{len(rows)}] R{r} CACHED ({len(old['items'])} items)", flush=True)
                        continue
                if args.img_burst > 0 and fetched_since_cool >= args.img_burst:
                    print(f"[COOLDOWN] Reached {args.img_burst} img searches, cooling {args.img_cooldown}s to avoid 1688 rate limit...", flush=True)
                    time.sleep(args.img_cooldown)
                    fetched_since_cool = 0
                res = silent_image_search(sess, workdir / "store" / f"{r}.jpg")
                if res.get("challenge"):
                    print(f"[CHALLENGE_HALT] R{r}: 1688 risk gate triggered. Stopping immediately (no bypass).", flush=True)
                    return 9
                res["row"] = r
                if res.get("items") or res.get("empty"):
                    out_f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
                fetched_since_cool += 1
                print(f"[{i}/{len(rows)}] R{r} items={len(res.get('items', []))} err={res.get('error', '')}", flush=True)
                time.sleep(random.uniform(args.img_delay_min, args.img_delay_max))

        elif args.mode == "kw":
            if not args.jobs_file:
                raise SystemExit("--mode kw requires --jobs-file")
            jobs = json.loads(Path(args.jobs_file).read_text(encoding="utf-8"))
            out_dir = workdir / "alikw"
            out_dir.mkdir(parents=True, exist_ok=True)
            fetched_since_cool = 0
            empty_streak = 0
            for i, job in enumerate(jobs, 1):
                r = int(job["row"])
                kw = str(job["kw"])
                out_f = out_dir / f"{r}.json"
                if not args.overwrite and out_f.is_file():
                    old = json.loads(out_f.read_text(encoding="utf-8"))
                    if old.get("items"):
                        print(f"[{i}/{len(jobs)}] R{r} CACHED ({len(old['items'])} items)", flush=True)
                        continue
                if fetched_since_cool >= args.kw_burst:
                    print(f"[COOLDOWN] Reached {args.kw_burst} kw searches, cooling {args.kw_cooldown}s to avoid s.1688 rate limit...", flush=True)
                    time.sleep(args.kw_cooldown)
                    fetched_since_cool = 0
                res = silent_keyword_search(sess, kw)
                if res.get("challenge"):
                    print(f"[CHALLENGE_HALT] R{r}: 1688 risk gate triggered. Stopping immediately.", flush=True)
                    return 9
                res["row"] = r
                n_items = len(res.get("items", []))
                if n_items > 0:
                    out_f.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
                    empty_streak = 0
                else:
                    empty_streak += 1
                fetched_since_cool += 1
                print(f"[{i}/{len(jobs)}] R{r} kw='{kw}' items={n_items}", flush=True)
                if empty_streak >= 2:
                    print(f"[CHALLENGE_HALT] R{r}: 2 consecutive empty kw results (likely soft rate-limit). Stopping safely before slider.", flush=True)
                    return 9
                time.sleep(random.uniform(4.8, 6.2))

        elif args.mode == "detail":
            if not args.plan_file:
                raise SystemExit("--mode detail requires --plan-file")
            plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
            out_dir = workdir / "acard"
            out_dir.mkdir(parents=True, exist_ok=True)
            fetched_since_cool = 0
            for i, item in enumerate(plan, 1):
                r = int(item["row"])
                oid = str(item["oid"])
                opt = item.get("option")
                suffix = "-clicked" if opt else ""
                out_f = out_dir / f"{r}-{oid}{suffix}.json"
                if not args.overwrite and out_f.is_file():
                    old = json.loads(out_f.read_text(encoding="utf-8"))
                    if old.get("ready"):
                        print(f"[{i}/{len(plan)}] R{r}-{oid}{suffix} CACHED", flush=True)
                        continue
                if fetched_since_cool >= args.burst:
                    print(f"[COOLDOWN] Reached {args.burst} detail fetches, cooling {args.cooldown}s to avoid CAPTCHA...", flush=True)
                    time.sleep(args.cooldown)
                    fetched_since_cool = 0
                obj = load_offer_card(sess, oid, click_option=opt)
                if obj.get("challenge"):
                    print(f"[CHALLENGE_HALT] R{r}-{oid}: 1688 risk gate triggered. Stopping immediately.", flush=True)
                    return 9
                obj["row"] = r
                obj["oid"] = oid
                obj["sales_lbl"] = item.get("sales", "")
                obj["img_url"] = item.get("img", "") or obj.get("image", "")
                out_f.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                fetched_since_cool += 1
                print(
                    f"[{i}/{len(plan)}] R{r}-{oid}{suffix} ready={obj.get('ready')} "
                    f"opts={len(obj.get('options', []))} rows={len(obj.get('rows', []))} "
                    f"clicked={obj.get('clicked_option')} | {(obj.get('title') or '')[:26]}",
                    flush=True,
                )
                time.sleep(random.uniform(3.8, 4.7))
    finally:
        sess.close()

    print("1688_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
