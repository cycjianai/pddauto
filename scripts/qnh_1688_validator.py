#!/usr/bin/env python3
"""
Qianniuhua Enterprise 1688 API Bridge & Pre-Import Verifier (pddauto v3.5)

Uses the user's already-logged-in Qianniuhua Chrome tab (CDP port 9222..9229) to call:
  - POST /qnh-gw2/scm/online-procure/batch-query-channel-goods (25~50 1688 offers/call, ~65ms/offer, ZERO 1688 CAPTCHA!)
  - POST /qnh-gw4/scm/online-procure/relation/query-out-goods  (single offer fallback)

Capabilities:
  1. --mode fetch-offers : Batch-fetch exact Qianniuhua-canonical 1688 SKU lists (channelSpecName, specPrice, stock,
                           minOrderQuantity [Col P 起购数], batchNumber [Col Q 下单倍数], mixNumber, unit, picUrlList, status)
                           for arbitrary 1688 offerIds.
  2. --mode verify-excel : Pre-validate every 1688 row in a 15/17-col sourcing Excel workbook against Qianniuhua's live
                           1688 API BEFORE importing into Qianniuhua (catches spec mismatches, hidden multi-spaces,
                           3-tier keys, delisted offers, zero-stock SKUs, and Col P 起购数 / Col Q 下单倍数 mismatches).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
import websockets

ALIBABA_1688_CHANNEL_ID = 2


def find_qnh_tab(port: Optional[int] = None) -> Tuple[int, Dict[str, Any]]:
    ports = [port] if port else list(range(9222, 9230))
    for p in ports:
        try:
            tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{p}/json/list", timeout=1.5).read())
        except Exception:
            continue
        for t in tabs:
            if t.get("type") == "page" and "qnh.meituan.com" in (t.get("url") or ""):
                return p, t
    raise RuntimeError(
        "No logged-in Qianniuhua (qnh.meituan.com) tab found on Chrome CDP ports 9222..9229. "
        "Open Qianniuhua in regular Chrome with --remote-debugging-port=9222."
    )


async def ensure_default_download_behavior(port: int) -> None:
    ver = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3).read())
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=24_000_000) as bws:
        await bws.send(json.dumps({"id": 1, "method": "Browser.setDownloadBehavior", "params": {"behavior": "default"}}))
        await bws.recv()


async def batch_query_1688_offers(
    oids: List[str],
    port: Optional[int] = None,
    batch_size: int = 25,
    delay_sec: float = 0.25,
) -> Dict[str, List[Dict[str, Any]]]:
    p, tab = find_qnh_tab(port)
    await ensure_default_download_behavior(p)
    unique_oids = list(dict.fromkeys(str(o).strip() for o in oids if str(o).strip()))
    db: Dict[str, List[Dict[str, Any]]] = {}

    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
        mid = 1

        async def eval_js(expr: str) -> Any:
            nonlocal mid
            cid = mid
            mid += 1
            await ws.send(json.dumps({
                "id": cid,
                "method": "Runtime.evaluate",
                "params": {"expression": expr, "returnByValue": True, "awaitPromise": True},
            }))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == cid:
                    if msg.get("result", {}).get("exceptionDetails"):
                        raise RuntimeError(str(msg["result"]["exceptionDetails"]))
                    return msg.get("result", {}).get("result", {}).get("value")

        total_batches = (len(unique_oids) + batch_size - 1) // batch_size
        t0 = time.time()
        for i in range(0, len(unique_oids), batch_size):
            batch = unique_oids[i : i + batch_size]
            res = await eval_js(f"""
            (async () => {{
              const t0 = performance.now();
              const r = await fetch('/qnh-gw2/scm/online-procure/batch-query-channel-goods', {{
                method: 'POST', credentials: 'include',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{channelId: {ALIBABA_1688_CHANNEL_ID}, channelGoodsIds: {json.dumps(batch)}}})
              }}).then(x => x.json()).catch(e => ({{code: -1, msg: String(e)}}));
              return {{ms: Math.round(performance.now()-t0), code: r?.code, msg: r?.msg, list: r?.data?.list || []}};
            }})()
            """)
            if res.get("code") != 0:
                print(f"  [BATCH {i//batch_size+1}/{total_batches}] ERROR code={res.get('code')} msg={res.get('msg')}", flush=True)
                continue
            by_oid: Dict[str, List[Dict[str, Any]]] = {}
            for item in res["list"]:
                oid = str(item.get("channelGoodsId") or "")
                by_oid.setdefault(oid, []).append(item)
            db.update(by_oid)
            print(
                f"  [BATCH {i//batch_size+1:2d}/{total_batches}] offers={len(by_oid)}/{len(batch)} "
                f"skus={len(res['list']):4d} ms={res['ms']}",
                flush=True,
            )
            if i + batch_size < len(unique_oids):
                await asyncio.sleep(delay_sec)

        # Fallback query-out-goods for any offer missed by batch-query
        missing = [o for o in unique_oids if o not in db]
        for oid in missing:
            r = await eval_js(f"""
            (async () => {{
              const x = await fetch('/qnh-gw4/scm/online-procure/relation/query-out-goods', {{
                method: 'POST', credentials: 'include',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                  channelId: {ALIBABA_1688_CHANNEL_ID},
                  channelGoodsId: {json.dumps(oid)},
                  completeGoodsUrl: 'https://detail.1688.com/offer/' + {json.dumps(oid)} + '.html'
                }})
              }}).then(r => r.json()).catch(e => ({{code: -1, msg: String(e)}}));
              return {{code: x?.code, msg: x?.msg, list: x?.data?.list || []}};
            }})()
            """)
            if r.get("code") == 0 and r.get("list"):
                db[oid] = r["list"]

        print(f"QNH_1688_FETCH_OK: {len(db)}/{len(unique_oids)} offers in {time.time()-t0:.1f}s", flush=True)
    return db


def match_qnh_spec(spec: str, items: List[Dict[str, Any]]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Match an Excel Col I spec against Qianniuhua's official channelSpecName list."""
    for it in items:
        if (it.get("channelSpecName") or "") == spec:
            return "EXACT", it
    if "; " in spec:
        parts = spec.split("; ")
        if len(parts) == 2:
            a, b = parts
            for it in items:
                cs = it.get("channelSpecName") or ""
                if cs in (f"{a}_{b}", f"{b}_{a}", f"{a};{b}", f"{b};{a}"):
                    return "2TIER_EQUIV", it
    return "MISMATCH", None


def main() -> int:
    ap = argparse.ArgumentParser(description="Qianniuhua Enterprise 1688 API Bridge & Pre-Import Verifier")
    ap.add_argument("--mode", required=True, choices=["fetch-offers", "verify-excel"])
    ap.add_argument("--port", type=int, default=None, help="Chrome CDP port hosting Qianniuhua (default auto 9222..9229)")
    ap.add_argument("--oids-file", default=None, help="Newline-separated 1688 offerIds (for fetch-offers)")
    ap.add_argument("--out-json", default=None, help="Output JSON cache path")
    ap.add_argument("--excel", default=None, help="15/17-column sourcing workbook (for verify-excel)")
    ap.add_argument("--sheet", default="Sheet1", help="Worksheet name")
    ap.add_argument("--batch-size", type=int, default=25, help="Offers per batch-query call (default 25, max tested 50)")
    args = ap.parse_args()

    if args.mode == "fetch-offers":
        if not args.oids_file or not args.out_json:
            raise SystemExit("fetch-offers requires --oids-file and --out-json")
        oids = [x.strip() for x in Path(args.oids_file).read_text().splitlines() if x.strip()]
        db = asyncio.run(batch_query_1688_offers(oids, port=args.port, batch_size=args.batch_size))
        Path(args.out_json).write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {len(db)} offers to {args.out_json}")
        return 0

    # verify-excel mode
    if not args.excel:
        raise SystemExit("verify-excel requires --excel")
    wb = openpyxl.load_workbook(args.excel, data_only=True)
    ws = wb[args.sheet] if args.sheet in wb.sheetnames else wb.active
    has_moq_cols = (
        str(ws.cell(1, 16).value or "").strip() == "起购数"
        and str(ws.cell(1, 17).value or "").strip() == "下单倍数"
    )
    rows_1688 = []
    for r in range(2, ws.max_row + 1):
        st = str(ws.cell(r, 14).value or "").strip()
        url = str(ws.cell(r, 8).value or "").strip()
        if st in ("不匹配", "未匹配", "组合商品", "生鲜蔬果本地采购", "") or "1688.com" not in url:
            continue
        m = re.search(r"/offer/(\d+)\.html", url)
        if not m:
            continue
        rows_1688.append((
            r,
            str(ws.cell(r, 2).value or "").strip(),
            m.group(1),
            str(ws.cell(r, 9).value or ""),
            ws.cell(r, 16).value if has_moq_cols else None,
            ws.cell(r, 17).value if has_moq_cols else None,
        ))

    oids = [x[2] for x in rows_1688]
    db = asyncio.run(batch_query_1688_offers(oids, port=args.port, batch_size=args.batch_size))
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")

    ok = 0
    mismatches = []
    delisted = []
    oos = []
    moq_mismatches = []
    for r, sid, oid, spec, ex_moq, ex_mult in rows_1688:
        items = db.get(oid, [])
        mtype, hit = match_qnh_spec(spec, items)
        if not hit:
            mismatches.append((r, sid, oid, spec, [x.get("channelSpecName") for x in items[:3]]))
        else:
            ok += 1
            if hit.get("status") != 1:
                delisted.append((r, oid, spec, hit.get("status")))
            if int(str(hit.get("stock") or "0").strip() or 0) <= 0:
                oos.append((r, oid, spec, hit.get("stock")))
            if has_moq_cols:
                live_moq = int(hit.get("minOrderQuantity") or 1)
                live_mult = int(hit.get("batchNumber") or 1)
                try:
                    ex_moq_i = int(ex_moq) if ex_moq not in (None, "") else None
                    ex_mult_i = int(ex_mult) if ex_mult not in (None, "") else None
                except (TypeError, ValueError):
                    ex_moq_i, ex_mult_i = ex_moq, ex_mult
                if ex_moq_i != live_moq or ex_mult_i != live_mult:
                    moq_mismatches.append((r, oid, f"excel=({ex_moq},{ex_mult})", f"live=({live_moq},{live_mult})"))

    print(f"\n=== QIANNIUHUA 1688 PRE-IMPORT VERIFICATION ===")
    print(
        f"  Total 1688 rows: {len(rows_1688)} | Verified OK: {ok} | Mismatches: {len(mismatches)} | "
        f"Delisted: {len(delisted)} | OOS(stock=0): {len(oos)} | MOQ/Multiple mismatches: {len(moq_mismatches)}"
    )
    for x in mismatches[:20]:
        print("  [MISMATCH]", x)
    for x in delisted[:10]:
        print("  [DELISTED]", x)
    for x in oos[:10]:
        print("  [OOS]", x)
    for x in moq_mismatches[:20]:
        print("  [MOQ_MULT_DIFF]", x)
    return 1 if (mismatches or moq_mismatches) else 0


if __name__ == "__main__":
    raise SystemExit(main())
