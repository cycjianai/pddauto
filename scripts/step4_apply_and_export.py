#!/usr/bin/env python3
"""
Step 4: Atomic 15-Column Excel Commit + Mandatory Red-Team Integrity Audit + Automatic Synchronized HTML Dashboard Export (pddauto v3.0)

Usage:
  # Apply verified multimodal judge decisions + audit + auto-generate synchronized HTML dashboard:
  python3 step4_apply_and_export.py \
    --excel /path/to/workbook.xlsx \
    --decisions /path/to/decisions.json \
    --pdd-img-dirs "/path/work/pdd_kw,/path/work/pdd_img" \
    [--html-out /path/to/workbook_直检看板.html]

  # Audit + regenerate synchronized HTML without modifying Excel:
  python3 step4_apply_and_export.py --excel /path/to/workbook.xlsx --audit-only
"""

from __future__ import annotations

import argparse
import glob
import html as html_lib
import json
import os
import re
import subprocess
import sys
import zipfile
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import openpyxl

ALLOWED_STATUS_ONLY = {"组合商品", "生鲜蔬果本地采购", "不匹配", "未匹配"}

# Artificial human annotations strictly forbidden in Col I (供货规格) unless verbatim inside supplier skuMap
FORBIDDEN_SPEC_PATTERNS = [
    (re.compile(r"[\(（][^()（）]*(?:包邮|免邮|起批|起订|券后|百亿补贴|店铺优惠|店铺券|关注券|平台券|官补|多人团|万人团|大促价|大促直降|限量低价|惊喜特价|凑单团|晚8限时|剔除仅1次|不含首单券|不含限1次|颜色随机同价|花色随机|款式随机|单价¥|每[支个片包袋瓶卷]¥|官方旗舰店|顺丰包邮|整箱发货|拍\d+[件份支双包箱]=)[^()（）]*[\)）]"), "人工括号备注/券后/包邮/起批注释"),
    (re.compile(r"\(¥[\d.]+\)\s*[+＋]|=1套|不重样|单只价¥"), "禁止硬拼多SKU合成套装/价格算式"),
    (re.compile(r"\s/\s"), "多维规格禁止用 ' / ' 分隔（必须用 '; '）"),
]


def _extract_valid_1688_specs(card: Dict[str, Any]) -> Set[str]:
    """Extract all valid verbatim Qianniuhua 1688 spec strings from an acard or sku_live JSON."""
    valid: Set[str] = set()
    # 1. Preferred: qnh_specs or raw skuMap from window.context.skuModel
    for qs in (card.get("qnh_specs") or []):
        s = str(qs.get("spec") or "")
        if s:
            valid.add(s)
    smap = card.get("skuMap") or {}
    if isinstance(smap, dict) and smap:
        for k in smap.keys():
            if "&gt;" in k:
                valid.add("; ".join(html_lib.unescape(p) for p in k.split("&gt;")))
            else:
                valid.add(html_lib.unescape(k))
    if valid:
        return valid

    # 2. Zero-SKU single item: exact 1688 offerTitle
    opts = [
        (o.strip() if isinstance(o, str) else str(o.get("v") or "").strip())
        for o in (card.get("options") or [])
    ]
    opts = [o for o in opts if o]
    rows = [
        str(x.get("v") or "").strip()
        for x in (card.get("rows") or [])
        if isinstance(x, dict) and str(x.get("v") or "").strip()
    ]
    sku_txt = str(card.get("sku") or "")
    if not opts and not rows and "匹配到" not in sku_txt and "\n规格:" not in ("\n" + sku_txt):
        t = str(card.get("offerTitle") or "").strip() or re.sub(
            r"\s*-\s*阿里巴巴\s*$", "", str(card.get("title") or "")
        ).strip()
        if t:
            valid.add(t)
        return valid

    # 3. Legacy acard DOM fallback (industrial KV / 1-tier / 2-tier)
    if not opts and not rows and "\n规格:" in ("\n" + sku_txt):
        for m in re.findall(r"(?:^|\n)规格:([^\n]+)", sku_txt):
            valid.add(m.strip())
    elif not opts and rows:
        valid.update(rows)
    elif opts and not rows and opts[0] != "全部":
        valid.update(opts)
    elif opts and rows and opts[0] != "全部":
        for o in opts:
            for rv in rows:
                valid.add(f"{o}; {rv}")
    return valid


def _load_1688_card_index(acard_dirs: List[Path]) -> Dict[str, Set[str]]:
    """Build oid -> set of valid verbatim Qianniuhua spec strings."""
    idx: Dict[str, Set[str]] = {}
    for d in acard_dirs:
        if not d.is_dir():
            continue
        for fp in glob.glob(str(d / "*.json")):
            try:
                card = json.loads(Path(fp).read_text(encoding="utf-8"))
            except Exception:
                continue
            oid = str(card.get("oid") or "").strip()
            if not oid:
                m = re.match(r"^(?:\d+-)?(\d+)", Path(fp).name)
                oid = m.group(1) if m else ""
            if not oid:
                continue
            specs = _extract_valid_1688_specs(card)
            if specs:
                idx.setdefault(oid, set()).update(specs)
    return idx


def validate_verbatim_spec(
    row: int,
    source: str,
    spec: str,
    card_index: Dict[str, Set[str]],
    allow_unverified_spec: bool = False,
) -> None:
    """HARD GATE: Enforce zero artificial notes & byte-for-byte supplier SKU match (1688 & PDD)."""
    is_1688 = "1688.com" in source
    matched_in_card = False

    if is_1688:
        m = re.search(r"/offer/(\d+)\.html", source)
        oid = m.group(1) if m else ""
        if oid and oid in card_index:
            valid_specs = card_index[oid]
            if spec in valid_specs:
                matched_in_card = True
            elif not allow_unverified_spec:
                samples = sorted(valid_specs)[:6]
                raise RuntimeError(
                    f"Row {row} REJECTED (Verbatim 1688 Spec Gate): spec {spec!r} does NOT match any "
                    f"real SKU on 1688 offer {oid} byte-for-byte! Valid samples: {samples}"
                )

    # Even for PDD (or 1688 without cached card), block artificial annotations unless literally present in supplier skuMap
    if not matched_in_card and not allow_unverified_spec:
        for pat, desc in FORBIDDEN_SPEC_PATTERNS:
            if pat.search(spec):
                raise RuntimeError(
                    f"Row {row} REJECTED (Zero-Annotation Spec Gate): spec {spec!r} contains forbidden "
                    f"{desc}! Col I MUST be the exact selectable supplier SKU text with ZERO human notes."
                )


def apply_decisions(
    excel_path: Path,
    sheet_name: str,
    decisions_path: Path,
    acard_dirs: Optional[List[Path]] = None,
    allow_unverified_spec: bool = False,
) -> int:
    items: List[Dict[str, Any]] = json.loads(decisions_path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("decisions.json must be a JSON array")

    # Auto-discover sibling acard/ and sku_live/ directories for strict 1688 byte-for-byte spec validation
    dirs_to_load: List[Path] = []
    if acard_dirs:
        dirs_to_load.extend(acard_dirs)
    for cand_dir in (decisions_path.parent / "sku_live", decisions_path.parent / "acard"):
        if cand_dir.is_dir() and cand_dir not in dirs_to_load:
            dirs_to_load.append(cand_dir)
    card_index = _load_1688_card_index(dirs_to_load)

    wb = openpyxl.load_workbook(excel_path, data_only=False)
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
    updated = 0

    for it in items:
        r = int(it["row"])
        sku_expected = str(it.get("skuid") or "").strip()
        sku_actual = str(ws.cell(r, 2).value or "").strip()
        if not sku_expected:
            raise RuntimeError(f"Row {r} missing required 'skuid' lock field in decisions.json!")
        if sku_expected != sku_actual:
            raise RuntimeError(f"Row {r} SKUID mismatch: expected {sku_expected}, got {sku_actual}")

        # Status-only classification (e.g. 组合商品 / 生鲜蔬果本地采购 / 不匹配)
        if it.get("status_only"):
            st = str(it["status_only"]).strip()
            if st not in ALLOWED_STATUS_ONLY:
                raise RuntimeError(f"Row {r} invalid status_only '{st}', allowed: {sorted(ALLOWED_STATUS_ONLY)}")
            ws.cell(r, 14).value = st
            if st in ("组合商品", "生鲜蔬果本地采购"):
                ws.cell(r, 8).value = st
                for col in (9, 10, 11, 12, 13, 15):
                    ws.cell(r, col).value = None
            updated += 1
            continue

        # Verified matched item: MUST have visual_verified=True
        if it.get("visual_verified") is not True:
            raise RuntimeError(f"Row {r} rejected: missing 'visual_verified': true (blind writes prohibited!)")

        source = str(it["source"]).strip()
        # Preserve internal consecutive spaces verbatim! Only strip CR/LF newlines.
        spec = str(it["spec"]).strip("\r\n")
        checkout = str(it.get("checkout") or source).strip()
        if not source.startswith("http"):
            raise RuntimeError(f"Row {r} invalid source URL: {source}")
        if not spec.strip():
            raise RuntimeError(f"Row {r} empty spec")

        # HARD GATE: Zero artificial notes & exact verbatim supplier SKU match (1688 + PDD)
        validate_verbatim_spec(
            row=r,
            source=source,
            spec=spec,
            card_index=card_index,
            allow_unverified_spec=allow_unverified_spec,
        )

        units = Decimal(str(it["units"]))
        paid = Decimal(str(it["paid"]))
        if units <= 0 or paid <= 0:
            raise RuntimeError(f"Row {r} invalid units={units} or paid={paid}")

        retail = Decimal(str(ws.cell(r, 6).value or 0))
        if retail > 0:
            margin = Decimal("1") - (paid / units) / retail
            status = "已核可采购" if margin >= Decimal("0.5") else "已核同款(毛利<50%)"
        else:
            status = "已核同款(售价为0)"

        is_1688 = "1688.com" in source
        img_url = str(it.get("img_url") or "").strip()
        if is_1688 and not img_url.startswith("http"):
            raise RuntimeError(f"Row {r} 1688 row MUST include HD CDN 'img_url' for Col O!")
        if not is_1688 and "alicdn.com" in img_url:
            img_url = ""

        # Write strictly to H..O (Cols 8..15); A..G are strictly read-only!
        ws.cell(r, 8).value = source
        ws.cell(r, 9).value = spec
        ws.cell(r, 10).value = checkout
        ws.cell(r, 11).value = float(units) if units != int(units) else int(units)
        ws.cell(r, 12).value = float(paid)
        ws.cell(r, 13).value = f"=ROUND(L{r}/K{r},2)"
        ws.cell(r, 14).value = status
        ws.cell(r, 15).value = img_url or None

        # Clean any legacy 1688 CDN URL accidentally sitting in Col C (分配人)
        c3 = ws.cell(r, 3).value
        if isinstance(c3, str) and c3.strip().startswith("http"):
            ws.cell(r, 3).value = None

        updated += 1

    # Ensure Col O header is properly labeled if blank
    if not ws.cell(1, 15).value:
        ws.cell(1, 15).value = "供货商主图"

    tmp = excel_path.with_suffix(".pddauto_tmp.xlsx")
    wb.save(tmp)
    try:
        with zipfile.ZipFile(tmp) as z:
            bad = z.testzip()
            if bad:
                raise RuntimeError(f"Corrupted xlsx zip member: {bad}")
        os.replace(tmp, excel_path)
    finally:
        if tmp.exists():
            tmp.unlink()

    print(f"COMMIT_OK: Updated {updated} rows in {excel_path} (ZIP integrity OK)")
    return updated


def run_redteam_audit(excel_path: Path, sheet_name: str) -> Dict[str, Any]:
    with zipfile.ZipFile(excel_path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"ZIP CORRUPTION DETECTED: {bad}")

    wb = openpyxl.load_workbook(excel_path, data_only=False)
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active

    cnt = Counter()
    plat = Counter()
    bad_formula = 0
    stale_c_matched = 0
    stale_o_pdd = 0
    miss_o_1688 = 0
    bad_spec_annotations = []
    tiny_cost = []
    single_pack_low = []
    inversions = []

    for r in range(2, ws.max_row + 1):
        name = str(ws.cell(r, 4).value or "").strip()
        if not name and not ws.cell(r, 1).value:
            continue
        st = str(ws.cell(r, 14).value or "").strip()
        cnt[st or "(空)"] += 1
        src = str(ws.cell(r, 8).value or "").strip()
        o_val = str(ws.cell(r, 15).value or "").strip()
        c3 = ws.cell(r, 3).value

        if st in ("已核可采购", "已核同款(毛利<50%)", "已核同款(售价为0)", "匹配", "已翻新1"):
            spec_val = str(ws.cell(r, 9).value or "")
            for pat, desc in FORBIDDEN_SPEC_PATTERNS:
                if pat.search(spec_val):
                    bad_spec_annotations.append((r, desc, spec_val[:50]))
                    break
            if isinstance(c3, str) and c3.strip().startswith("http"):
                stale_c_matched += 1
            if "1688.com" in src:
                plat["1688"] += 1
                if not o_val.startswith("http"):
                    miss_o_1688 += 1
            elif "yangkeduo.com" in src or "pinduoduo.com" in src:
                plat["拼多多"] += 1
                if "alicdn.com" in o_val:
                    stale_o_pdd += 1
            else:
                plat["其他"] += 1

            m_f = str(ws.cell(r, 13).value or "")
            if not m_f.startswith("=ROUND("):
                bad_formula += 1

            try:
                retail = float(ws.cell(r, 6).value or 0)
                u = float(ws.cell(r, 11).value or 1)
                p = float(ws.cell(r, 12).value or 0)
                uc = p / u
            except Exception:
                continue

            if retail > 0:
                margin = (1.0 - uc / retail) * 100.0
                if uc > retail:
                    inversions.append((r, retail, round(uc, 3), name[:24]))
                if retail >= 3.0 and u >= 10 and uc < retail * 0.07:
                    tiny_cost.append((r, retail, u, p, round(uc, 3), name[:24]))
                if u == 1 and margin < 25.0:
                    single_pack_low.append((r, round(margin, 1), retail, p, name[:24], str(ws.cell(r, 9).value or "")[:24]))

    report = {
        "zip_ok": True,
        "status": dict(cnt),
        "platforms": dict(plat),
        "bad_formula": bad_formula,
        "stale_c_matched": stale_c_matched,
        "stale_o_pdd": stale_o_pdd,
        "miss_o_1688": miss_o_1688,
        "bad_spec_annotations": bad_spec_annotations,
        "tiny_cost_suspects": tiny_cost,
        "single_pack_low_margin": single_pack_low,
        "inversions": inversions,
    }
    print("=== RED-TEAM INTEGRITY AUDIT ===")
    print(f"  ZIP: OK | Status: {report['status']} | Platforms: {report['platforms']}")
    print(
        f"  bad_formula={bad_formula} | stale_c_matched={stale_c_matched} | "
        f"stale_o_pdd={stale_o_pdd} | miss_o_1688={miss_o_1688} | "
        f"bad_spec_annotations={len(bad_spec_annotations)}"
    )
    for x in bad_spec_annotations[:10]:
        print("   [BAD_SPEC]", x)
    print(f"  tiny_cost_suspects (possible single-piece miscount): {len(tiny_cost)}")
    for x in tiny_cost[:10]:
        print("   ", x)
    print(f"  single_pack_low_margin (K=1 & margin<25%): {len(single_pack_low)}")
    for x in single_pack_low[:10]:
        print("   ", x)
    print(f"  price_inversions (unit_cost > retail): {len(inversions)}")
    for x in inversions[:10]:
        print("   ", x)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 4: Atomic Excel commit + Red-Team Audit + Synchronized HTML Export")
    ap.add_argument("--excel", required=True, help="Target 15-column Excel workbook path")
    ap.add_argument("--sheet", default="门店商品", help="Worksheet name (default 门店商品)")
    ap.add_argument("--decisions", default=None, help="Path to visually-verified decisions.json")
    ap.add_argument("--acard-dirs", default="", help="Comma-separated dirs containing 1688 acard/sku_live JSONs for strict verbatim spec validation")
    ap.add_argument("--allow-unverified-spec", action="store_true", help="Emergency bypass for verbatim spec check (NOT recommended)")
    ap.add_argument("--audit-only", action="store_true", help="Skip Excel write; run audit + HTML export only")
    ap.add_argument("--html-out", default=None, help="Output HTML path (default: <excel_dir>/<excel_stem>_直检看板.html)")
    ap.add_argument("--pdd-img-dirs", default="", help="Comma-separated dirs/globs containing PDD R*_hero.jpg to embed")
    ap.add_argument("--no-html", action="store_true", help="Skip HTML generation (NOT recommended for final delivery)")
    args = ap.parse_args()

    excel_p = Path(args.excel).resolve()
    if not args.audit_only:
        if not args.decisions:
            raise SystemExit("Provide --decisions <file.json> or pass --audit-only")
        ac_dirs = [Path(s.strip()).resolve() for s in args.acard_dirs.split(",") if s.strip()]
        apply_decisions(
            excel_p,
            args.sheet,
            Path(args.decisions).resolve(),
            acard_dirs=ac_dirs,
            allow_unverified_spec=args.allow_unverified_spec,
        )

    run_redteam_audit(excel_p, args.sheet)

    if not args.no_html:
        html_out = Path(args.html_out).resolve() if args.html_out else excel_p.with_name(f"{excel_p.stem}_直检看板.html")
        exporter = Path(__file__).resolve().parent / "export_visual_audit_html.py"
        cmd = [
            sys.executable,
            str(exporter),
            "--excel", str(excel_p),
            "--sheet", args.sheet,
            "--output", str(html_out),
        ]
        if args.pdd_img_dirs:
            cmd.extend(["--pdd-img-dirs", args.pdd_img_dirs])
        subprocess.run(cmd, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
