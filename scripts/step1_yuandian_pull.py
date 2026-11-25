#!/usr/bin/env python3
"""
Step 1B (Yuandian SaaS Mode): Pull Active Sourcing Order from `saas.fuliops.cn/procurement-sourcing`
into a 100% pipeline-compatible `<workdir>/manifest.json` + `<workdir>/store/{row}.jpg` (pddauto v3.3).

Usage:
  # List orders currently in the Yuandian admin queue:
  python3 step1_yuandian_pull.py --list-tasks [--port 9222]

  # Pull currently open order (or explicit --task-no) into workdir:
  python3 step1_yuandian_pull.py \
    --workdir /abs/path/to/workdir \
    [--task-no YD-20261122-CG-000001] \
    [--only-pending] \
    [--port 9222]

Output:
  <workdir>/yuandian_rules.json   (live backend sourcing rules version & rules_text)
  <workdir>/yuandian_task.json    (raw task snapshot from Yuandian backend)
  <workdir>/store/{row}.jpg       (store hero photos, indexed by row_index)
  <workdir>/manifest.json         (100% compatible with step2_1688_search / step2_pdd_search / step3_render_judge_sheet)
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.cdp_yuandian import YuandianAdminClient
from step1_prepare import build_platform_policy, classify_route, download_store_img


def resolve_target_task_no(client: YuandianAdminClient, explicit_task_no: Optional[str]) -> str:
    if explicit_task_no:
        return explicit_task_no.strip()
    embedded = client.get_page_payload()
    if embedded and embedded.get("task", {}).get("task_no"):
        return str(embedded["task"]["task_no"])
    queue = client.list_tasks(status="all", page=1, page_size=80)
    items = queue.get("items") or []
    for preferred_status in ("sourcing", "pending", "ready_to_deliver"):
        hit = next((x for x in items if x.get("status") == preferred_status), None)
        if hit and hit.get("task_no"):
            return str(hit["task_no"])
    if items and items[0].get("task_no"):
        return str(items[0]["task_no"])
    raise RuntimeError("No sourcing task found in Yuandian admin queue.")


def build_manifest_from_task(
    task: Dict[str, Any],
    workdir: Path,
    only_pending: bool = False,
    rules: Optional[Dict[str, Any]] = None,
    workers: int = 6,
    download_images: bool = True,
) -> Dict[str, Any]:
    store_dir = workdir / "store"
    store_dir.mkdir(parents=True, exist_ok=True)

    rows_data: List[Dict[str, Any]] = []
    for idx, it in enumerate(task.get("items") or [], start=2):
        match_status = str(it.get("match_status") or "pending").strip()
        if only_pending and match_status != "pending":
            continue
        row_num = int(it.get("row_index") or idx)
        spuid = str(it.get("spuid") or "").strip()
        skuid = str(it.get("skuid") or "").strip()
        name = str(it.get("product_name") or "").strip()
        spec = str(it.get("spec_name") or "").strip()
        raw_retail = it.get("retail_price")
        try:
            retail = round(float(raw_retail), 2) if raw_retail not in (None, "") else 0.0
        except Exception:
            retail = 0.0
        img_url = str(it.get("main_image_url") or "").strip()

        category_txt = " ".join(
            str(it.get(k) or "").strip()
            for k in ("category", "category_name", "cat1", "cat2", "cat3", "first_category", "second_category")
            if it.get(k)
        )
        route = classify_route(name, spec, category=category_txt)
        rows_data.append({
            "row": row_num,
            "yuandian_item_id": int(it["id"]),
            "spuid": spuid,
            "skuid": skuid,
            "name": name,
            "spec": spec,
            "category": category_txt,
            "retail": retail,
            "store_img_url": img_url,
            "store_img_local": "",
            "status": match_status,
            "route": route,
            **build_platform_policy(route),
            "existing_channel": str(it.get("channel") or ""),
        })

    if download_images and rows_data:
        def _dl(item: Dict[str, Any]) -> None:
            item["store_img_local"] = download_store_img(item["row"], item["store_img_url"], store_dir)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_dl, rows_data))

    return {
        "policy_version": "v3.4",
        "source_mode": "yuandian_saas",
        "task_no": str(task.get("task_no") or ""),
        "platform": str(task.get("platform") or ""),
        "store_id": str(task.get("store_id") or ""),
        "store_name": str(task.get("store_name") or ""),
        "task_status": str(task.get("status") or ""),
        "rules_version": (rules or {}).get("version"),
        "workdir": str(workdir),
        "total": len(rows_data),
        "routes": {
            k: sum(1 for x in rows_data if x["route"] == k)
            for k in ("1688", "pdd", "combo", "fresh")
        },
        "pdd_first_locked_count": sum(1 for x in rows_data if x.get("platform_policy") == "pdd_first_lock"),
        "rows": rows_data,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 1B: Pull Yuandian SaaS sourcing order -> manifest.json & store images")
    ap.add_argument("--workdir", default=None, help="Working directory for manifest/cache/images (required unless --list-tasks)")
    ap.add_argument("--task-no", default=None, help="Explicit Yuandian task_no (auto-detects active page order if omitted)")
    ap.add_argument("--only-pending", action="store_true", help="Include only items with match_status == 'pending'")
    ap.add_argument("--list-tasks", action="store_true", help="List tasks in Yuandian admin queue and exit")
    ap.add_argument("--status", default="all", choices=["all", "pending", "sourcing", "ready_to_deliver", "completed"], help="[--list-tasks] Filter queue status")
    ap.add_argument("--port", type=int, default=None, help="Explicit Chrome remote debugging port (auto-discovers 9222..9229)")
    ap.add_argument("--workers", type=int, default=6, help="Concurrent store image download threads")
    args = ap.parse_args()

    with YuandianAdminClient(port=args.port) as client:
        if args.list_tasks:
            q = client.list_tasks(status=args.status)
            summary = [
                {
                    "task_no": x.get("task_no"),
                    "platform": x.get("platform"),
                    "store_name": x.get("store_name"),
                    "status": x.get("status"),
                    "valid_count": x.get("valid_count"),
                    "progress_pct": x.get("progress_pct"),
                    "prehold_amount": x.get("prehold_amount"),
                    "settled_amount": x.get("settled_amount"),
                }
                for x in (q.get("items") or [])
            ]
            print(json.dumps({"total": q.get("total", len(summary)), "items": summary}, ensure_ascii=False, indent=2))
            return 0

        if not args.workdir:
            raise SystemExit("--workdir is required unless --list-tasks is set")

        workdir = Path(args.workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)

        task_no = resolve_target_task_no(client, args.task_no)
        rules = client.get_rules()
        task = client.get_task_detail(task_no)

    (workdir / "yuandian_rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    (workdir / "yuandian_task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = build_manifest_from_task(
        task=task,
        workdir=workdir,
        only_pending=args.only_pending,
        rules=rules,
        workers=args.workers,
    )
    out_p = workdir / "manifest.json"
    out_p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    missing_img = sum(1 for x in manifest["rows"] if not x["store_img_local"])
    print(f"OK: Pulled Yuandian task {task_no} ({manifest['platform']} · {manifest['store_name']}, status={manifest['task_status']}) -> {out_p}")
    print(f"    Rows: {manifest['total']} | Routes: {manifest['routes']} | Missing store imgs: {missing_img}")
    print(f"    Live Rules v{rules.get('version')}: saved -> {workdir / 'yuandian_rules.json'}")
    rules_text = str(rules.get("rules_text") or "").strip()
    if rules_text:
        print("--- LIVE YUANDIAN RULES ---")
        print(rules_text)
        print("---------------------------")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
