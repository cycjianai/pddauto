#!/usr/bin/env python3
"""
Step 4B (Yuandian SaaS Mode): Push Visually-Verified Decisions to `saas.fuliops.cn/procurement-sourcing`
+ Mandatory Zero-Annotation Spec Gate + Channel Sync + Server & Local Red-Team Verification (pddauto v3.3).

HARD SAFETY LOCK:
  - NEVER calls `/deliver` ("回传客户并结算") or `/cancel`.
  - Safely transitions processed orders to `ready_to_deliver` ("待回传") for final human review & settlement.

Usage:
  python3 step4_yuandian_push.py \
    --workdir /abs/path/to/workdir \
    --decisions <workdir>/decisions.json \
    [--task-no YD-20261122-CG-000001] \
    [--acard-dirs "<workdir>/sku_live,<workdir>/acard"] \
    [--port 9222] \
    [--dry-run] \
    [--no-reload]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.cdp_yuandian import YuandianAdminClient
from step4_apply_and_export import (
    ALLOWED_STATUS_ONLY,
    FORBIDDEN_SPEC_PATTERNS,
    _load_1688_card_index,
    collect_pdd_evidence_dirs,
    has_pdd_search_evidence,
    load_manifest_index,
    validate_platform_policy_gate,
    validate_verbatim_spec,
)
from step1_prepare import classify_route


def infer_channel(source_url: str, explicit_channel: Optional[str] = None) -> str:
    if explicit_channel:
        c = explicit_channel.strip().lower()
        if c in ("1688", "pdd", "taobao", "jd", "other"):
            return c
    u = (source_url or "").lower()
    if "1688.com" in u:
        return "1688"
    if "yangkeduo.com" in u or "pinduoduo.com" in u:
        return "pdd"
    if "taobao.com" in u or "tmall.com" in u:
        return "taobao"
    if "jd.com" in u:
        return "jd"
    return "other"


def validate_pdd_checkout_url(row: int, checkout: str) -> None:
    """Enforce PDD checkout URL contract: never carry group_id, numeric goods_id/sku_id only."""
    low = checkout.lower()
    if "yangkeduo.com" not in low and "pinduoduo.com" not in low:
        return
    if "group_id=" in low:
        raise RuntimeError(
            f"Row {row} REJECTED (PDD Checkout Gate): checkout URL must NOT contain group_id: {checkout}"
        )
    if "order_checkout.html" in low:
        mg = re.search(r"[?&]goods_id=(\d{6,22})(?:&|$)", checkout)
        ms = re.search(r"[?&]sku_id=(\d{6,22})(?:&|$)", checkout)
        if not mg or not ms:
            raise RuntimeError(
                f"Row {row} REJECTED (PDD Checkout Gate): order_checkout.html requires numeric goods_id & sku_id: {checkout}"
            )


def prepare_patch_operations(
    task: Dict[str, Any],
    decisions: List[Dict[str, Any]],
    card_index: Dict[str, set],
    allow_unverified_spec: bool = False,
    manifest_by_skuid: Optional[Dict[str, Dict[str, Any]]] = None,
    manifest_by_row: Optional[Dict[int, Dict[str, Any]]] = None,
    pdd_dirs: Optional[List[Path]] = None,
) -> List[Tuple[int, int, str, Dict[str, Any]]]:
    """Validate every decision against live task state and build `(row, item_id, skuid, patch_payload)` list."""
    m_by_sk = manifest_by_skuid or {}
    m_by_r = manifest_by_row or {}
    ev_pdd_dirs = pdd_dirs or []
    task_status = str(task.get("status") or "")
    if task_status in ("completed", "cancelled"):
        raise RuntimeError(f"Task {task.get('task_no')} is already finalized (status={task_status}); refusing to edit.")

    current_staff_id = (task.get("current_staff") or {}).get("id")
    by_skuid: Dict[str, Dict[str, Any]] = {}
    by_row: Dict[int, Dict[str, Any]] = {}
    for idx, it in enumerate(task.get("items") or [], start=2):
        r = int(it.get("row_index") or idx)
        by_row[r] = it
        sk = str(it.get("skuid") or "").strip()
        if sk:
            by_skuid[sk] = it

    ops: List[Tuple[int, int, str, Dict[str, Any]]] = []
    for it in decisions:
        sk_exp = str(it.get("skuid") or "").strip()
        if not sk_exp:
            raise RuntimeError(f"Decision entry missing required 'skuid' lock field: {it}")
        live_item = by_skuid.get(sk_exp)
        if live_item is None:
            raise RuntimeError(f"SKUID {sk_exp} not found in live task {task.get('task_no')}")

        row_num = int(it.get("row") or live_item.get("row_index") or 0)
        live_row = int(live_item.get("row_index") or 0)
        if it.get("row") is not None and live_row and int(it["row"]) != live_row:
            raise RuntimeError(
                f"Row/SKUID mismatch for {sk_exp}: decisions has row={it['row']}, live task has row_index={live_row}"
            )

        assignee_id = live_item.get("assignee_staff_id")
        if assignee_id and current_staff_id and assignee_id != current_staff_id:
            raise RuntimeError(
                f"Row {row_num} ({sk_exp}) is claimed by another staff_id={assignee_id} (current={current_staff_id})"
            )

        item_id = int(live_item["id"])

        # Unmatched / combo / fresh status-only decision
        if it.get("status_only") or it.get("match_status") == "unmatched":
            st = str(it.get("status_only") or "未匹配").strip()
            if it.get("status_only") and st not in ALLOWED_STATUS_ONLY:
                raise RuntimeError(f"Row {row_num} invalid status_only '{st}', allowed: {sorted(ALLOWED_STATUS_ONLY)}")
            reason = str(it.get("unmatched_reason") or ("" if st in ("未匹配", "不匹配") else st)).strip()
            payload = {
                "supply_url": "",
                "supply_spec": "",
                "checkout_url": "",
                "order_ratio": None,
                "purchase_price": None,
                "match_status": "unmatched",
                "unmatched_reason": reason,
            }
            ops.append((row_num, item_id, sk_exp, payload))
            continue

        # Matched decision: MUST pass visual_verified + verbatim spec + valid URLs + positive numbers
        if it.get("visual_verified") is not True:
            raise RuntimeError(f"Row {row_num} ({sk_exp}) rejected: missing 'visual_verified': true (blind writes prohibited!)")

        source = str(it.get("source") or "").strip()
        spec = str(it.get("spec") or "").strip("\r\n")
        checkout = str(it.get("checkout") or source).strip()
        if not re.match(r"^https?://\S+$", source, re.I):
            raise RuntimeError(f"Row {row_num} invalid supply_url: {source!r}")
        if not re.match(r"^https?://\S+$", checkout, re.I):
            raise RuntimeError(f"Row {row_num} invalid checkout_url: {checkout!r}")
        if not spec.strip():
            raise RuntimeError(f"Row {row_num} empty supply_spec")

        validate_verbatim_spec(
            row=row_num,
            source=source,
            spec=spec,
            card_index=card_index,
            allow_unverified_spec=allow_unverified_spec,
        )
        validate_pdd_checkout_url(row_num, checkout)

        # HARD GATE (v3.4): Round-1 PDD Lock for food/FMCG — block 1688 without real PDD disk evidence + fallback reason
        live_cat = " ".join(
            str(live_item.get(k) or "").strip()
            for k in ("category", "category_name", "cat1", "cat2", "cat3", "first_category", "second_category")
            if live_item.get(k)
        )
        validate_platform_policy_gate(
            row=row_num,
            skuid=sk_exp,
            name=str(live_item.get("product_name") or "").strip(),
            spec=str(live_item.get("spec_name") or "").strip(),
            source=source,
            retail=Decimal(str(live_item.get("retail_price") or 0)),
            decision_item=it,
            manifest_by_skuid=m_by_sk,
            manifest_by_row=m_by_r,
            pdd_dirs=ev_pdd_dirs,
            category=live_cat,
        )

        units = Decimal(str(it["units"]))
        paid = Decimal(str(it["paid"]))
        if units <= 0 or paid <= 0:
            raise RuntimeError(f"Row {row_num} invalid units={units} or paid={paid}")

        channel = infer_channel(source, it.get("channel"))
        ratio_val: Any = int(units) if units == int(units) else float(units)
        price_val = float(paid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        payload = {
            "supply_url": source,
            "supply_spec": spec,
            "checkout_url": checkout,
            "order_ratio": ratio_val,
            "purchase_price": price_val,
            "channel": channel,
            "match_status": "matched",
            "unmatched_reason": "",
        }
        ops.append((row_num, item_id, sk_exp, payload))

    return ops


def run_yuandian_redteam_audit(
    task: Dict[str, Any],
    manifest_by_skuid: Optional[Dict[str, Dict[str, Any]]] = None,
    manifest_by_row: Optional[Dict[int, Dict[str, Any]]] = None,
    pdd_dirs: Optional[List[Path]] = None,
) -> Dict[str, Any]:
    """Run local + server red-team integrity checks on the live Yuandian task snapshot."""
    server_checks = dict(task.get("red_team_checks") or {})
    bad_spec_annotations = []
    tiny_cost = []
    single_pack_low = []
    inversions = []
    channel_mismatches = []
    pdd_first_unverified_1688 = []
    counts = {"matched": 0, "unmatched": 0, "pending": 0}
    m_by_sk = manifest_by_skuid or {}
    m_by_r = manifest_by_row or {}
    ev_pdd_dirs = pdd_dirs or []

    for it in (task.get("items") or []):
        st = str(it.get("match_status") or "pending")
        counts[st] = counts.get(st, 0) + 1
        if st != "matched":
            continue
        r = int(it.get("row_index") or it.get("id") or 0)
        spec_val = str(it.get("supply_spec") or "")
        src = str(it.get("supply_url") or "")
        ch = str(it.get("channel") or "")
        expected_ch = infer_channel(src)
        if expected_ch in ("1688", "pdd") and ch != expected_ch:
            channel_mismatches.append((r, ch, expected_ch))
        if expected_ch == "1688" and ev_pdd_dirs:
            sk = str(it.get("skuid") or "").strip()
            pname = str(it.get("product_name") or "").strip()
            pspec = str(it.get("spec_name") or "").strip()
            m_it = m_by_sk.get(sk) or m_by_r.get(r)
            is_pdd_first = (
                (m_it is not None and (m_it.get("platform_policy") == "pdd_first_lock" or m_it.get("route") == "pdd"))
                or classify_route(pname, pspec) == "pdd"
            )
            if is_pdd_first and not has_pdd_search_evidence(r, ev_pdd_dirs):
                pdd_first_unverified_1688.append((r, sk, pname[:28]))
        for pat, desc in FORBIDDEN_SPEC_PATTERNS:
            if pat.search(spec_val):
                bad_spec_annotations.append((r, desc, spec_val[:50]))
                break
        try:
            retail = float(it.get("retail_price") or 0)
            u = float(it.get("order_ratio") or 1)
            p = float(it.get("purchase_price") or 0)
            uc = p / u
        except Exception:
            continue
        name = str(it.get("product_name") or "")
        if retail > 0:
            margin = (1.0 - uc / retail) * 100.0
            if uc > retail:
                inversions.append((r, retail, round(uc, 3), name[:24]))
            if retail >= 3.0 and u >= 10 and uc < retail * 0.07:
                tiny_cost.append((r, retail, u, p, round(uc, 3), name[:24]))
            if u == 1 and margin < 25.0:
                single_pack_low.append((r, round(margin, 1), retail, p, name[:24], spec_val[:24]))

    report = {
        "task_no": task.get("task_no"),
        "status": task.get("status"),
        "counts": counts,
        "server_red_team_checks": server_checks,
        "server_all_passed": bool(server_checks) and all(bool(v) for v in server_checks.values()),
        "settlement_preview": task.get("settlement_preview"),
        "channel_mismatches": channel_mismatches,
        "pdd_first_unverified_1688": pdd_first_unverified_1688,
        "bad_spec_annotations": bad_spec_annotations,
        "tiny_cost_suspects": tiny_cost,
        "single_pack_low_margin": single_pack_low,
        "price_inversions": inversions,
    }
    print("=== YUANDIAN RED-TEAM AUDIT ===")
    print(f"  Task: {report['task_no']} | Status: {report['status']} | Counts: {counts}")
    print(f"  Server Checks: {server_checks} (all_passed={report['server_all_passed']})")
    print(f"  Settlement Preview (NOT auto-settled): {report['settlement_preview']}")
    print(
        f"  channel_mismatches={len(channel_mismatches)} | pdd_first_unverified_1688={len(pdd_first_unverified_1688)} | "
        f"bad_spec_annotations={len(bad_spec_annotations)} | "
        f"tiny_cost_suspects={len(tiny_cost)} | single_pack_low_margin={len(single_pack_low)} | "
        f"price_inversions={len(inversions)}"
    )
    for tag, items_list in (
        ("CHANNEL_MISMATCH", channel_mismatches),
        ("PDD_FIRST_UNVERIFIED_1688", pdd_first_unverified_1688),
        ("BAD_SPEC", bad_spec_annotations),
        ("TINY_COST", tiny_cost),
        ("SINGLE_PACK_LOW", single_pack_low),
        ("INVERSION", inversions),
    ):
        for x in items_list[:10]:
            print(f"   [{tag}] {x}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 4B: Push verified decisions to Yuandian SaaS admin (never auto-delivers)")
    ap.add_argument("--workdir", default=None, help="Working directory containing manifest.json / acard / sku_live")
    ap.add_argument("--task-no", default=None, help="Explicit Yuandian task_no (reads from manifest.json or open tab if omitted)")
    ap.add_argument("--decisions", default=None, help="Path to visually-verified decisions.json (required unless --audit-only)")
    ap.add_argument("--acard-dirs", default="", help="Comma-separated dirs with 1688 acard/sku_live JSONs for strict verbatim spec check")
    ap.add_argument("--allow-unverified-spec", action="store_true", help="Emergency bypass for verbatim spec check (NOT recommended)")
    ap.add_argument("--audit-only", action="store_true", help="Skip PATCH writes; audit live Yuandian task state only")
    ap.add_argument("--dry-run", action="store_true", help="Validate everything & print PATCH payloads without writing to server")
    ap.add_argument("--no-reload", action="store_true", help="Do not silently reload the Yuandian admin tab after push")
    ap.add_argument("--port", type=int, default=None, help="Explicit Chrome remote debugging port (auto-discovers 9222..9229)")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve() if args.workdir else None
    task_no = args.task_no
    if not task_no and workdir and (workdir / "manifest.json").is_file():
        m = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
        task_no = m.get("task_no")

    with YuandianAdminClient(port=args.port) as client:
        if not task_no:
            embedded = client.get_page_payload()
            if embedded and embedded.get("task", {}).get("task_no"):
                task_no = str(embedded["task"]["task_no"])
        if not task_no:
            raise SystemExit("Could not infer --task-no from manifest.json or active admin page; pass --task-no explicitly.")

        live_task = client.get_task_detail(task_no)

        if not args.audit_only:
            if not args.decisions:
                raise SystemExit("Provide --decisions <file.json> or pass --audit-only")
            decisions_p = Path(args.decisions).resolve()
            decisions = json.loads(decisions_p.read_text(encoding="utf-8"))
            if not isinstance(decisions, list):
                raise ValueError("decisions.json must be a JSON array")

            dirs_to_load: List[Path] = [Path(s.strip()).resolve() for s in args.acard_dirs.split(",") if s.strip()]
            for base_dir in filter(None, (workdir, decisions_p.parent)):
                for sub in ("sku_live", "acard"):
                    cand = base_dir / sub
                    if cand.is_dir() and cand not in dirs_to_load:
                        dirs_to_load.append(cand)
            card_index = _load_1688_card_index(dirs_to_load)

            manifest_p = (workdir / "manifest.json") if (workdir and (workdir / "manifest.json").is_file()) else (decisions_p.parent / "manifest.json")
            m_by_sk, m_by_r = load_manifest_index(manifest_p if manifest_p.is_file() else None)
            ev_pdd_dirs = collect_pdd_evidence_dirs(base_dirs=[d for d in (workdir, decisions_p.parent) if d])

            ops = prepare_patch_operations(
                task=live_task,
                decisions=decisions,
                card_index=card_index,
                allow_unverified_spec=args.allow_unverified_spec,
                manifest_by_skuid=m_by_sk,
                manifest_by_row=m_by_r,
                pdd_dirs=ev_pdd_dirs,
            )

            if args.dry_run:
                print(f"DRY_RUN_OK: Validated {len(ops)} items for Yuandian task {task_no} (0 writes performed).")
                for row_num, item_id, skuid, payload in ops:
                    print(f"  [DRY-RUN] Row {row_num} item_id={item_id} skuid={skuid} -> {json.dumps(payload, ensure_ascii=False)}")
                return 0

            latest_task = live_task
            for row_num, item_id, skuid, payload in ops:
                latest_task = client.patch_item(task_no, item_id, payload)
                print(
                    f"  [PATCHED] Row {row_num} item_id={item_id} skuid={skuid} "
                    f"status={payload['match_status']} channel={payload.get('channel', '-')} "
                    f"price={payload.get('purchase_price')} ratio={payload.get('order_ratio')}",
                    flush=True,
                )
                time.sleep(0.15)

            live_task = client.get_task_detail(task_no)
            if not args.no_reload:
                client.reload_tab_silently()

        audit_m_p = (workdir / "manifest.json") if (workdir and (workdir / "manifest.json").is_file()) else None
        am_sk, am_r = load_manifest_index(audit_m_p)
        am_pdd = collect_pdd_evidence_dirs(base_dirs=[workdir] if workdir else [])
        report = run_yuandian_redteam_audit(live_task, manifest_by_skuid=am_sk, manifest_by_row=am_r, pdd_dirs=am_pdd)
        if workdir:
            (workdir / "yuandian_push_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if not report["server_all_passed"]:
            print("ERROR: One or more Yuandian server red_team_checks FAILED! Review and fix before delivery.", file=sys.stderr)
            return 2

    print("YUANDIAN_PUSH_DONE (Safe stop before delivery/settlement — operator should review & click '回传客户并结算' manually).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
