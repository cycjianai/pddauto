#!/usr/bin/env python3
"""
Pinduoduo Native Android App ADB + macOS Vision OCR Engine (pddauto v3.0)
- Auto-discovers ADB binary, online Android device serial, and bundled mac_ocr binary.
- Supports:
  1. Smart Keyword Search with brand-flagship banner bypass coordinates + optional sort_sales=False for mini packs.
  2. Atomic Single-Photo Album Image Search with pixel-vector thumbnail verification & guaranteed finally rm -f cleanup.
  3. Direct SKU Drawer Inspector (deep-link goods_id + tap target SKUs to capture live coupon-applied prices).
- STRICT ANTI-CAPTCHA / NO-BYPASS:
  Immediately aborts and returns {"blocked": True} on any risk/captcha/login/real-name gate.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from PIL import Image, ImageChops, ImageOps, ImageStat

SKILL_ROOT = Path(__file__).resolve().parents[2]
BUNDLED_OCR = SKILL_ROOT / "scripts" / "bin" / "mac_ocr"
SWIFT_OCR_SRC = SKILL_ROOT / "scripts" / "tools" / "mac_ocr.swift"

RISK_RE = re.compile(
    r"请完成验证|安全验证|请先登录|操作频繁|访问频繁|访问过于频繁|实名认证|账号存在风险|已限制部分操作|完成验证后"
)
ADDR_MASK_RE = re.compile(r"街道|幢|\d室|收货地址|手机尾号|收货人|更换支付方式|路.{0,10}号")


def resolve_adb() -> str:
    for cand in (os.environ.get("ADB_BIN"), "/opt/homebrew/bin/adb", "/usr/local/bin/adb", shutil.which("adb")):
        if cand and os.path.isfile(cand):
            return cand
    raise RuntimeError("adb binary not found. Install via `brew install android-platform-tools`.")


def resolve_ocr() -> str:
    if BUNDLED_OCR.is_file() and os.access(BUNDLED_OCR, os.X_OK):
        return str(BUNDLED_OCR)
    if os.path.isfile("/tmp/mac_ocr") and os.access("/tmp/mac_ocr", os.X_OK):
        return "/tmp/mac_ocr"
    if SWIFT_OCR_SRC.is_file() and shutil.which("swiftc"):
        BUNDLED_OCR.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", str(SWIFT_OCR_SRC), "-o", str(BUNDLED_OCR)], check=True)
        os.chmod(BUNDLED_OCR, 0o755)
        return str(BUNDLED_OCR)
    raise RuntimeError(f"mac_ocr binary missing at {BUNDLED_OCR} and swiftc compilation unavailable.")


def resolve_device(adb: str, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    env_dev = os.environ.get("ADB_DEVICE")
    if env_dev:
        return env_dev
    out = subprocess.check_output([adb, "devices"], text=True)
    for line in out.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    raise RuntimeError("No online Android device found via `adb devices`. Connect USB & enable debugging.")


class PddPhone:
    def __init__(self, device: Optional[str] = None, work_tmp: Optional[Path] = None):
        self.adb = resolve_adb()
        self.ocr_bin = resolve_ocr()
        self.device = resolve_device(self.adb, device)
        self.tmp_dir = (work_tmp or Path("/tmp/pddauto_observe"))
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.frame_png = self.tmp_dir / "frame.png"
        self.screen_w, self.screen_h = self._detect_resolution()

    def _detect_resolution(self) -> Tuple[int, int]:
        try:
            out = self.shell("wm", "size")
            m = re.search(r"(\d+)x(\d+)", out)
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
        return 1216, 2640

    def run(self, args: List[str], timeout: float = 15.0) -> bytes:
        return subprocess.run(args, timeout=timeout, check=True, capture_output=True).stdout

    def shell(self, *args: Any, timeout: float = 15.0) -> str:
        return self.run([self.adb, "-s", self.device, "shell", shlex.join(map(str, args))], timeout=timeout).decode(errors="ignore")

    def go(self, url: str) -> str:
        return self.shell("am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", url)

    def tap(self, x: float, y: float) -> None:
        self.shell("input", "tap", int(round(x)), int(round(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 280) -> None:
        self.shell("input", "swipe", x1, y1, x2, y2, ms)

    def back(self) -> None:
        self.shell("input", "keyevent", "4")

    def wakeup(self) -> None:
        self.shell("input", "keyevent", "KEYCODE_WAKEUP")

    def screenshot(self, dest: Optional[Path] = None) -> Path:
        out_p = dest or self.frame_png
        raw = self.run([self.adb, "-s", self.device, "exec-out", "screencap", "-p"])
        out_p.write_bytes(raw)
        return out_p

    def ocr_frame(self, save_jpg: Optional[Path] = None) -> List[Tuple[int, int, str]]:
        self.screenshot(self.frame_png)
        data = json.loads(self.run([self.ocr_bin, str(self.frame_png)]))
        obs: List[Tuple[int, int, str]] = []
        for o in data.get("observations", []):
            cx = round(self.screen_w * (o["x"] + o["width"] / 2.0))
            cy = round(self.screen_h * (1.0 - o["y"] - o["height"] / 2.0))
            obs.append((cx, cy, str(o["text"]).strip()))
        if save_jpg:
            Image.open(self.frame_png).convert("RGB").save(save_jpg, quality=88)
        return obs

    def is_blocked(self, obs: List[Tuple[int, int, str]]) -> bool:
        return any(RISK_RE.search(t) for _, y, t in obs if y > 130)

    def is_spec_drawer(self, obs: List[Tuple[int, int, str]]) -> bool:
        return any("已选" in t and y < 1550 for _, y, t in obs) or any(
            ("提交订单" in t or "确认下单" in t) for _, y, t in obs if y > 2250
        )

    def is_pdd_foreground(self) -> bool:
        txt = self.shell("dumpsys", "activity", "activities")
        return bool(re.search(r"topResumedActivity=ActivityRecord\{[^}]+com\.xunmeng\.pinduoduo/", txt))

    def current_goods_id(self) -> Optional[str]:
        dump = self.shell("dumpsys", "activity", "com.xunmeng.pinduoduo")
        blocks = dump.split("  ACTIVITY ")
        if not blocks:
            return None
        recent = blocks[-1]
        bundles = re.findall(r"mArguments=Bundle\[\{(.*?)\}\]", recent, re.S)
        for b in reversed(bundles):
            m = re.search(r'goods_id[=:" ]+(\d{6,20})', b)
            if m and "goods.html" in b:
                return m.group(1)
        return None

    def _capture_detail_and_sku(self, out_dir: Path, hero_name: str) -> Tuple[List[str], List[str]]:
        det = self.ocr_frame()
        if self.frame_png.exists():
            im = Image.open(self.frame_png).convert("RGB")
            w, h = im.size
            im.crop((0, int(h * 0.045), w, int(h * 0.51))).resize((360, 360)).save(out_dir / hero_name, quality=86)
        det_lines = [t for _, y, t in det if 1150 < y < 2280]
        btn = [
            (x, y) for x, y, t in det
            if x >= 580 and y > 2310 and re.search(r"免拼|拼单|购买|抢购|发起|[￥¥]\s*\d", t)
            and not re.search("提交|支付|下单", t)
        ]
        sku_lines: List[str] = []
        if btn:
            self.tap(*btn[-1])
            time.sleep(0.95)
            dr = self.ocr_frame()
            if self.is_spec_drawer(dr):
                sku_lines = [t for _, y, t in dr if 650 < y < 2450 and not ADDR_MASK_RE.search(t)]
                self.swipe(600, 2100, 600, 1350, 280)
                time.sleep(0.45)
                dr2 = self.ocr_frame()
                if self.is_spec_drawer(dr2):
                    for _, y, t in dr2:
                        if 1050 < y < 2320 and t not in sku_lines and not ADDR_MASK_RE.search(t):
                            sku_lines.append(t)
                self.back()
                time.sleep(0.35)
        return det_lines[:18], sku_lines[:35]

    def smart_kw_search(
        self,
        keyword: str,
        out_dir: Path,
        tag: str,
        max_cards: int = 2,
        sort_sales: bool = True,
    ) -> Dict[str, Any]:
        """Brand-banner-bypassing keyword search (probes y=1080 and y=1800 until max_cards unique gids captured)."""
        out_dir.mkdir(parents=True, exist_ok=True)
        self.wakeup()
        self.go("pinduoduo://com.xunmeng.pinduoduo/search_result.html?search_key=" + quote(keyword))
        view: List[Tuple[int, int, str]] = []
        for d in (1.2, 1.0, 1.2):
            time.sleep(d)
            view = self.ocr_frame()
            if self.is_blocked(view):
                return {"mode": "smart_kw", "keyword": keyword, "blocked": True, "cands": []}
            if any("销量" in t for _, y, t in view if y < 650):
                break
        if sort_sales:
            sbtn = next(((x, y) for x, y, t in view if t.strip() == "销量" and y < 650), None)
            if sbtn:
                self.tap(*sbtn)
                time.sleep(1.1)

        cands: List[Dict[str, Any]] = []
        seen_gids = set()
        # Banner-bypass coordinates: top cards sit below y=1000 when brand flagship banner renders
        tap_pts = [(300, 1080), (900, 1080), (300, 1800), (900, 1800)]
        for cx, cy in tap_pts:
            if len(cands) >= max_cards:
                break
            cur = self.ocr_frame()
            if self.is_blocked(cur):
                return {"mode": "smart_kw", "keyword": keyword, "blocked": True, "cands": cands}
            if not any("销量" in t for _, y, t in cur if y < 650):
                self.go("pinduoduo://com.xunmeng.pinduoduo/search_result.html?search_key=" + quote(keyword))
                time.sleep(1.3)
                cur = self.ocr_frame()
                if sort_sales:
                    sbtn = next(((x, y) for x, y, t in cur if t.strip() == "销量" and y < 650), None)
                    if sbtn:
                        self.tap(*sbtn)
                        time.sleep(1.0)
            self.tap(cx, cy)
            time.sleep(1.4)
            det = self.ocr_frame()
            if self.is_blocked(det):
                return {"mode": "smart_kw", "keyword": keyword, "blocked": True, "cands": cands}
            gid = self.current_goods_id()
            if not gid or gid in seen_gids or any("商品已售罄" in t for _, y, t in det if y < 600):
                self.back()
                time.sleep(0.55)
                continue
            seen_gids.add(gid)
            cidx = len(cands)
            hero_name = f"{tag}_k{cidx}_{gid}_hero.jpg"
            det_lines, sku_lines = self._capture_detail_and_sku(out_dir, hero_name)
            self.back()
            time.sleep(0.55)
            cands.append({
                "idx": cidx,
                "gid": gid,
                "hero": str(out_dir / hero_name),
                "detail": det_lines,
                "sku": sku_lines,
            })
        return {"mode": "smart_kw", "keyword": keyword, "sort_sales": sort_sales, "blocked": False, "cands": cands}

    @staticmethod
    def _vec(im: Image.Image) -> Image.Image:
        return ImageOps.fit(im.convert("RGB"), (18, 18), method=Image.Resampling.BILINEAR)

    def _find_verified_album_tile(self, store_img: Path) -> Tuple[Optional[Tuple[int, int, List[float]]], str]:
        expected = self._vec(Image.open(store_img))
        started = time.monotonic()
        for _ in range(13):
            obs = self.ocr_frame()
            if self.is_blocked(obs):
                return None, "blocked"
            if not self.is_pdd_foreground():
                return None, "not_in_pdd_foreground"
            if any("请对准商品或码" in t for _, _, t in obs):
                self.tap(1115, 1164)
                time.sleep(0.25)
                obs = self.ocr_frame()
            if any("我的相册" in t for _, _, t in obs) and any(("拍照" in t or "最近搜索" in t) for _, _, t in obs):
                im = Image.open(self.frame_png).convert("RGB").resize((442, 960))
                scores: List[float] = []
                for k in range(4):
                    x = 110.5 * k
                    opts = [
                        round(sum(ImageStat.Stat(ImageChops.difference(
                            expected, self._vec(im.crop((round(x + 1), top, round(x + 109.5), top + 109)))
                        )).mean) / 3.0, 2)
                        for top in (775, 777, 779, 781)
                    ]
                    scores.append(min(opts))
                if min(scores) <= 24.0:
                    slot = scores.index(min(scores))
                    px = round((55 + 110.5 * slot) * self.screen_w / 442)
                    py = round(2300 * self.screen_h / 2640)
                    return (px, py, scores), ""
                self.back()
                time.sleep(0.42)
                continue
            if any(t == "首页" for _, y, t in obs if y > 2300) and any("个人中心" in t for _, y, t in obs if y > 2300):
                self.tap(1090, 222)
                time.sleep(0.55)
                continue
            self.back()
            time.sleep(0.38)
            if time.monotonic() - started > 32:
                break
        return None, "album_tile_not_found"

    def atomic_image_search(
        self,
        store_img: Path,
        out_dir: Path,
        tag: str,
        max_cards: int = 2,
        sort_sales: bool = False,
    ) -> Dict[str, Any]:
        """Atomic single-photo PDD album image search with guaranteed zero album pollution."""
        if not store_img.is_file():
            return {"mode": "image", "err": f"missing_store_img:{store_img}", "blocked": False, "cands": []}
        out_dir.mkdir(parents=True, exist_ok=True)
        self.wakeup()
        remote = f"/sdcard/DCIM/Camera/pddauto_atomic_{tag}_{int(time.time())}.jpg"
        self.run([self.adb, "-s", self.device, "push", str(store_img), remote])
        self.shell("am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", "file://" + remote)
        cands: List[Dict[str, Any]] = []
        try:
            self.go("pinduoduo://com.xunmeng.pinduoduo/search_image_capture.html")
            time.sleep(0.85)
            located, reason = self._find_verified_album_tile(store_img)
            if not located:
                return {"mode": "image", "err": reason, "blocked": reason == "blocked", "cands": []}
            px, py, _ = located
            self.tap(px, py)
            start = time.monotonic()
            view: List[Tuple[int, int, str]] = []
            ok = False
            while time.monotonic() - start < 26:
                time.sleep(1.0)
                view = self.ocr_frame()
                t = " ".join(v[2] for v in view)
                if self.is_blocked(view):
                    return {"mode": "image", "blocked": True, "cands": []}
                if "销量" in t and "价格" in t:
                    ok = True
                    break
                if ("再试一次" in t or "取消" in t) and "请对准商品或码" in t:
                    self.tap(1115, 1164)
                    time.sleep(0.35)
                    self.tap(px, py)
            if not ok:
                return {"mode": "image", "err": "search_timeout", "blocked": False, "cands": []}
            if sort_sales:
                sbtn = next(((x, y) for x, y, t in view if t.strip() == "销量" and 350 < y < 700), None)
                if sbtn:
                    self.tap(*sbtn)
                    time.sleep(1.1)

            seen_gids = set()
            for cx, cy in [(300, 980), (900, 980), (300, 1850), (900, 1850)]:
                if len(cands) >= max_cards:
                    break
                cur = self.ocr_frame()
                if self.is_blocked(cur):
                    return {"mode": "image", "blocked": True, "cands": cands}
                if not any("销量" in t for _, y, t in cur if y < 750):
                    break
                self.tap(cx, cy)
                time.sleep(1.45)
                det = self.ocr_frame()
                if self.is_blocked(det):
                    return {"mode": "image", "blocked": True, "cands": cands}
                gid = self.current_goods_id()
                if not gid or gid in seen_gids or any("商品已售罄" in t for _, y, t in det if y < 600):
                    self.back()
                    time.sleep(0.5)
                    continue
                seen_gids.add(gid)
                cidx = len(cands)
                hero_name = f"{tag}_c{cidx}_{gid}_hero.jpg"
                det_lines, sku_lines = self._capture_detail_and_sku(out_dir, hero_name)
                self.back()
                time.sleep(0.55)
                cands.append({
                    "idx": cidx,
                    "gid": gid,
                    "hero": str(out_dir / hero_name),
                    "detail": det_lines,
                    "sku": sku_lines,
                })
            return {"mode": "image", "blocked": False, "cands": cands}
        finally:
            # GUARANTEED ZERO ALBUM POLLUTION
            try:
                self.shell("rm", "-f", remote)
                self.shell("am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", "file://" + remote)
            except Exception:
                pass

    def inspect_goods_skus(self, gid: str, tap_keywords: List[str], out_dir: Path, tag: str) -> Dict[str, Any]:
        """Direct deep-link to a specific goods_id and tap specific SKU keywords to verify live coupon prices."""
        out_dir.mkdir(parents=True, exist_ok=True)
        self.wakeup()
        self.go(f"pinduoduo://com.xunmeng.pinduoduo/goods.html?goods_id={gid}")
        time.sleep(2.0)
        det = self.ocr_frame(out_dir / f"{tag}_{gid}_det.jpg")
        if self.is_blocked(det):
            return {"gid": gid, "blocked": True}
        det_lines = [t for _, y, t in det if 100 < y < 2350]
        btn = [
            (x, y) for x, y, t in det
            if x >= 580 and y > 2310 and re.search(r"免拼|拼单|购买|抢购|发起|[￥¥]\s*\d", t)
            and not re.search("提交|支付|下单", t)
        ]
        snaps: List[Dict[str, Any]] = []
        if btn:
            self.tap(*btn[-1])
            time.sleep(1.0)
            dr = self.ocr_frame(out_dir / f"{tag}_{gid}_sku0.jpg")
            snaps.append({"label": "initial", "lines": [t for _, y, t in dr if 500 < y < 2450 and not ADDR_MASK_RE.search(t)]})
            for ti, kw in enumerate(tap_keywords):
                hit = next(((x, y, t) for x, y, t in dr if kw in t and 900 < y < 2300), None)
                if hit:
                    self.tap(hit[0], hit[1])
                    time.sleep(0.85)
                    dr2 = self.ocr_frame(out_dir / f"{tag}_{gid}_tap{ti}.jpg")
                    snaps.append({
                        "label": f"tap:{kw}",
                        "tapped": hit[2],
                        "lines": [t for _, y, t in dr2 if 500 < y < 2450 and not ADDR_MASK_RE.search(t)],
                    })
            self.back()
            time.sleep(0.4)
        self.back()
        return {"gid": gid, "blocked": False, "detail": det_lines[:25], "snaps": snaps}
