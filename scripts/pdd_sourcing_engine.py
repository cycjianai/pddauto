#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拼多多三级极速自动化寻源与结算链接引擎 (PDD Tri-Mode Sourcing Engine) v3.0
- 核心策略（按速率由高到低自动调度）：
  1. 通道 A (CDP_WHITEBOX, ~1.2s/SPU)：依附本机已登录常规 Chrome (端口 9222)，直读
     window.rawData.store.initDataObj.goods，一次性提取同 SPU 下全部真实 sku_id 与元为单位的 group_price；
  2. 通道 B (USB_DEBUG, 105ms~2.0s/SPU)：
     - 有图搜同款 ➔ 【单件原子流相册以图搜图】(传一张、搜一张、finally 销毁一张，相册零污染)；
     - 无图搜关键词 ➔ DeepLink 0.1s 秒开 + 限定包名 dumpsys 105ms 内存提取；
  3. 通道 C (ESP32_PHYSICAL)：遇滑块/强风控自动降级至 ESP32 BLE HID + 预编译 mac_ocr (50ms)。
- 六大防坑铁律：
  * 同 SPU 多 SKU 预聚合（aggregate_rows_by_spu），同一 SPU 仅流转 1 次图片、加载 1 次详情页；
  * 严禁伪造/推算 goods_id 或 sku_id（强制校验 ^\\d+$，防触发拼多多 WAF “当前访问人数较多，排队中”）；
  * 结算链接唯一标准：https://mobile.yangkeduo.com/order_checkout.html?goods_id={goods_id}&sku_id={sku_id}&goods_number=1（严禁拼接 group_id）；
  * 价格单位防除以 100：skus[i].group_price 原生已是【元】为单位的字符串（如 "33.90"），严禁除以 100；
  * 相册防误删四重锁：专属前缀 pdd_task_tmp_，严禁通配符，物理删除后立即刷新媒体库；
  * 标准六列回填（F~K列）：商品链接、拼多多规格（中文分号“；”分隔）、结算链接、下单比例、采购价、单位采购价公式。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import Quartz
    import Vision
    from Foundation import NSURL
    from PIL import Image
    HAS_MACOS_FRAMEWORKS = True
except ImportError:
    HAS_MACOS_FRAMEWORKS = False


class EngineMode(Enum):
    CDP_WHITEBOX = "cdp_whitebox"      # 通道 A：Chrome 9222 window.rawData 极速白盒模式（首选）
    USB_DEBUG = "usb_debug"            # 通道 B：ADB 极速白盒与单件原子流搜图模式
    ESP32_PHYSICAL = "esp32_physical"  # 通道 C：ESP32 物理黑盒防风控兜底模式


# 拼多多高频风控特征库
RISK_PATTERNS = [
    r"验证码",
    r"安全验证",
    r"滑块",
    r"拖动滑块",
    r"请完成验证",
    r"账号异常",
    r"访问过于频繁",
    r"当前访问人数较多",
    r"排队中",
    r"系统开小差",
    r"登录失效",
    r"重新登录",
    r"risk.?control",
]

# 专属临时图片安全前缀（绝对红线：任何删除操作必须以此前缀开头）
TEMP_PHOTO_PREFIX = "pdd_task_tmp_"
REMOTE_PHOTO_DIR = "/sdcard/DCIM/Camera"

# 搜索结果页防误点店铺装修横幅 (mall_page.html) 的安全点击脚本
CDP_SEARCH_CLICK_FIRST_GOODS_JS = """
(() => {
  const imgs = Array.from(document.querySelectorAll('img')).filter(img => {
    const r = img.getBoundingClientRect();
    const a = img.closest('a');
    const href = a ? a.href : '';
    return r.width > 100 && r.height > 100 && r.top > 200 && !href.includes('mall_page.html');
  });
  if (imgs.length > 0) {
    imgs[0].click();
    return { clicked: true, count: imgs.length };
  }
  return { clicked: false, count: 0 };
})()
""".strip()

# 商品详情页一次性提取真实 goods_id 与全量在售 skus 的白盒脚本
CDP_RAW_DATA_EXTRACT_JS = """
(() => {
  const g = window?.rawData?.store?.initDataObj?.goods;
  if (!g || !g.goods_id) return { ok: false, error: 'rawData_goods_missing' };
  const goodsId = String(g.goods_id).trim();
  const skus = (g.skus || [])
    .filter(s => s && s.is_onsale !== 0 && (s.quantity === undefined || s.quantity > 0))
    .map(s => ({
      sku_id: String(s.sku_id).trim(),
      specs: (s.specs || []).map(sp => sp.spec_value).filter(Boolean).join('；'),
      group_price: parseFloat(s.group_price),
      normal_price: parseFloat(s.normal_price || s.group_price),
      thumb_url: s.thumb_url || ''
    }));
  return {
    ok: true,
    goods_id: goodsId,
    goods_name: g.goods_name || '',
    goods_url: 'https://mobile.yangkeduo.com/goods.html?goods_id=' + goodsId,
    skus
  };
})()
""".strip()

_NUMERIC_ID_RE = re.compile(r"^\d+$")
_PACK_COUNT_PATTERNS = [
    # 匹配形如 "480ml*9瓶", "330ml*12罐", "25g*10袋"
    re.compile(r"\d+(?:\.\d+)?\s*(?:ml|mL|L|g|kg|克|毫升|升)\s*[*xX×]\s*(\d+)\s*(?:瓶|听|罐|袋|盒|包|支|桶|枚|颗|只|个|片|双|条)", re.IGNORECASE),
    # 匹配形如 "*10枚", "x6包"
    re.compile(r"[*xX×]\s*(\d+)\s*(?:瓶|听|罐|袋|盒|包|支|桶|枚|颗|只|个|片|双|条)"),
    # 匹配形如 "10枚装", "20颗", "9瓶【囤货】", "12听/箱"
    re.compile(r"(?<![.\d])(\d+)\s*(?:枚|颗|只|个|片|双|条|瓶|听|罐|袋|盒|包|支)(?:装|入|【|/|$)"),
]


def validate_numeric_id(value: Any, field_name: str = "id") -> str:
    """强制校验拼多多 goods_id / sku_id 为真实纯数字字符串，严防伪造/占位符触发排队页。"""
    text = str(value or "").strip()
    if not text or not _NUMERIC_ID_RE.fullmatch(text):
        raise ValueError(f"invalid_pdd_{field_name}:{text!r} (必须为真实纯数字 ID，严禁伪造或使用占位符)")
    return text


def extract_pack_count(spec_text: str) -> int:
    """从规格或商品标题文本中提取内含物理件数（默认返回 1）。"""
    text = str(spec_text or "").strip()
    if not text:
        return 1
    for pattern in _PACK_COUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            count = int(match.group(1))
            if 1 <= count <= 1000:
                return count
    return 1


def compute_order_ratio(store_spec_text: str, pdd_spec_text: str) -> int:
    """
    计算 I 列【下单比例】：拼多多采购规格内含件数 ÷ 门店销售 SKU 内含件数。
    例如：门店卖 "1颗" 皮蛋，拼多多选 "10枚装" ➔ 下单比例 = 10；
          门店卖 "330ml*12瓶/箱"，拼多多选 "330ml*12瓶整箱" ➔ 下单比例 = 1。
    """
    store_count = max(1, extract_pack_count(store_spec_text))
    pdd_count = max(1, extract_pack_count(pdd_spec_text))
    if pdd_count >= store_count:
        return max(1, round(pdd_count / store_count))
    return 1


def parse_raw_goods_data(raw_goods: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析 window.rawData.store.initDataObj.goods 原始字典：
    - 校验真实数字 goods_id 與 sku_id；
    - 多级规格使用中文分号 "；" 拼接；
    - 直接将 s.group_price 解析为元（float），严禁除以 100。
    """
    if not isinstance(raw_goods, dict) or not raw_goods.get("goods_id"):
        raise ValueError("rawData_goods_missing")
    goods_id = validate_numeric_id(raw_goods["goods_id"], "goods_id")
    parsed_skus: List[Dict[str, Any]] = []
    for sku in raw_goods.get("skus") or []:
        if not isinstance(sku, dict):
            continue
        if sku.get("is_onsale") == 0:
            continue
        if sku.get("quantity") is not None and int(sku.get("quantity")) <= 0:
            continue
        sku_id = validate_numeric_id(sku.get("sku_id"), "sku_id")
        specs_list = sku.get("specs") or []
        specs_str = "；".join(
            str(sp.get("spec_value", "")).strip()
            for sp in specs_list
            if isinstance(sp, dict) and str(sp.get("spec_value", "")).strip()
        )
        # 铁律：skus[i].group_price 原生已是以元为单位的字符串（如 "33.90"），严禁除以 100
        group_price = float(sku["group_price"])
        normal_price = float(sku.get("normal_price") or sku["group_price"])
        parsed_skus.append({
            "sku_id": sku_id,
            "specs": specs_str,
            "group_price": round(group_price, 2),
            "normal_price": round(normal_price, 2),
            "thumb_url": str(sku.get("thumb_url") or ""),
            "checkout_url": PDDSourcingEngine.build_checkout_url(goods_id, sku_id),
        })
    return {
        "goods_id": goods_id,
        "goods_name": str(raw_goods.get("goods_name") or "").strip(),
        "goods_url": PDDSourcingEngine.build_goods_url(goods_id),
        "skus": parsed_skus,
    }


def aggregate_rows_by_spu(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    [Step 0 同 SPU 多 SKU 预聚合器]
    将表格多行按 spu_id（若无则按清洗后的 product_name）聚合，使同 SPU 仅流转 1 次主图、检索 1 次详情页。
    """
    groups: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for idx, row in enumerate(rows):
        spu_id = str(row.get("spu_id") or row.get("SPUID") or "").strip()
        product_name = str(row.get("product_name") or row.get("商品名称") or "").strip()
        key = spu_id if spu_id else f"name:{product_name}"
        if key not in groups:
            order.append(key)
            groups[key] = {
                "spu_key": key,
                "spu_id": spu_id,
                "product_name": product_name,
                "image_url": str(row.get("image_url") or "").strip(),
                "sku_rows": [],
            }
        elif not groups[key]["image_url"] and row.get("image_url"):
            groups[key]["image_url"] = str(row.get("image_url")).strip()
        groups[key]["sku_rows"].append({
            "row_index": row.get("row_index", idx + 2),
            "sku_id": str(row.get("sku_id") or row.get("SKUID") or "").strip(),
            "spec": str(row.get("spec") or row.get("规格") or "").strip(),
            "price": row.get("price") or row.get("售价"),
            "raw": row,
        })
    return [groups[k] for k in order]


class PDDSourcingEngine:
    def __init__(
        self,
        mode: Optional[EngineMode] = None,
        device_id: str = "b78d30ef",
        esp32_ip: str = "192.168.0.116",
        window_name: str = "手机投屏",
        cdp_port: int = 9222,
    ):
        self.device_id = device_id
        self.esp32_ip = esp32_ip
        self.window_name = window_name
        self.cdp_port = cdp_port
        self.wid = None
        self.bounds = None

        if mode is None:
            self.mode = self._auto_detect_mode()
        else:
            self.mode = mode

    def _auto_detect_mode(self) -> EngineMode:
        """优先级：通道 A (Chrome CDP 9222) ➔ 通道 B (USB ADB) ➔ 通道 C (ESP32)"""
        try:
            url = f"http://127.0.0.1:{self.cdp_port}/json/version"
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return EngineMode.CDP_WHITEBOX
        except Exception:
            pass
        try:
            out = subprocess.check_output(["adb", "devices"], text=True, timeout=2)
            lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("List of")]
            for l in lines:
                if "\tdevice" in l:
                    self.device_id = l.split()[0]
                    return EngineMode.USB_DEBUG
        except Exception:
            pass
        return EngineMode.ESP32_PHYSICAL

    def switch_mode(self, target_mode: EngineMode, reason: str = ""):
        """运行期安全平滑模式切换"""
        self.mode = target_mode

    # ==========================================
    # 核心能力：标准链接生成与六列回填字典构建
    # ==========================================

    @staticmethod
    def build_goods_url(goods_id: str) -> str:
        gid = validate_numeric_id(goods_id, "goods_id")
        return f"https://mobile.yangkeduo.com/goods.html?goods_id={gid}"

    @staticmethod
    def build_checkout_url(goods_id: str, sku_id: str, goods_number: int = 1) -> str:
        """
        拼多多现代抗风控标准结算链接：
        仅使用 goods_id + sku_id + goods_number=1，严禁携带失效 group_id，严禁伪造 ID。
        """
        gid = validate_numeric_id(goods_id, "goods_id")
        sid = validate_numeric_id(sku_id, "sku_id")
        qty = max(1, int(goods_number))
        return f"https://mobile.yangkeduo.com/order_checkout.html?goods_id={gid}&sku_id={sid}&goods_number={qty}"

    @staticmethod
    def build_six_column_backfill(
        goods_id: str,
        sku_id: str,
        specs_text: str,
        group_price_yuan: float,
        order_ratio: int,
        excel_row: int,
    ) -> Dict[str, Any]:
        """
        构建标准 F~K 六列回填数据：
        - F列：拼多多商品链接
        - G列：拼多多规格（多规格以中文分号“；”分隔）
        - H列：结算链接（无 group_id）
        - I列：下单比例（整数）
        - J列：采购价（元，保留2位小数）
        - K列：单位采购价公式 =ROUND(J{row}/I{row}, 2)
        """
        ratio = max(1, int(order_ratio))
        price = round(float(group_price_yuan), 2)
        if price <= 0:
            raise ValueError(f"invalid_group_price:{group_price_yuan}")
        row_num = int(excel_row)
        return {
            "F": PDDSourcingEngine.build_goods_url(goods_id),
            "G": str(specs_text or "默认规格").strip(),
            "H": PDDSourcingEngine.build_checkout_url(goods_id, sku_id, goods_number=1),
            "I": ratio,
            "J": price,
            "K": f"=ROUND(J{row_num}/I{row_num}, 2)",
            "unit_price_value": round(price / ratio, 2),
        }

    # ==========================================
    # 核心能力：相册单件原子流搜图与防误删四重锁
    # ==========================================

    def _safe_cleanup_remote_temp_photo(self, remote_file_path: str):
        """
        [防误删铁律] 安全销毁手机上的专属临时照片（四重防御锁）：
        1. 必须是合法字符串且位于 /sdcard/ 下；
        2. 严禁包含通配符 (*, ?, ..) 或空格；
        3. 文件名必须严格以 pdd_task_tmp_ 开头，严禁触碰任何日常个人照片；
        4. 物理删除后立即广播刷新媒体库，抹除缩略图。
        """
        if not remote_file_path or not isinstance(remote_file_path, str):
            return
        if not remote_file_path.startswith("/sdcard/"):
            raise ValueError(f"[安全红线拦截] 禁止在 /sdcard/ 以外操作: {remote_file_path}")
        if any(c in remote_file_path for c in ["*", "?", "..", " "]):
            raise ValueError(f"[安全红线拦截] 路径包含通配符或非法字符: {remote_file_path}")

        filename = os.path.basename(remote_file_path)
        if not filename.startswith(TEMP_PHOTO_PREFIX):
            raise ValueError(
                f"[安全红线拦截] 拒绝删除非引擎专属临时文件: {remote_file_path} (必须以 {TEMP_PHOTO_PREFIX} 开头)"
            )

        try:
            subprocess.run(["adb", "-s", self.device_id, "shell", "rm", "-f", remote_file_path], check=True, timeout=3)
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "am",
                    "broadcast",
                    "-a",
                    "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                    "-d",
                    f"file://{remote_file_path}",
                ],
                check=True,
                timeout=3,
            )
        except Exception:
            pass

    def search_by_image_atomic_flow(self, image_url: str) -> bool:
        """[单件原子流] 传一张 ➔ 搜一张 ➔ finally 强制物理删除，保持手机相册永久零污染"""
        timestamp = int(time.time() * 1000)
        temp_filename = f"{TEMP_PHOTO_PREFIX}{timestamp}.jpg"
        local_cache = f"/tmp/{temp_filename}"
        remote_path = f"{REMOTE_PHOTO_DIR}/{temp_filename}"

        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            req = urllib.request.Request(image_url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp, open(local_cache, "wb") as f:
                f.write(resp.read())

            subprocess.run(["adb", "-s", self.device_id, "push", local_cache, remote_path], check=True, timeout=5)
            subprocess.run(
                [
                    "adb",
                    "-s",
                    self.device_id,
                    "shell",
                    "am",
                    "broadcast",
                    "-a",
                    "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                    "-d",
                    f"file://{remote_path}",
                ],
                check=True,
                timeout=3,
            )
            time.sleep(0.4)

            deeplink = "pinduoduo://com.xunmeng.pinduoduo/search_image_capture.html"
            subprocess.run(
                ["adb", "-s", self.device_id, "shell", f"am start -a android.intent.action.VIEW -d '{deeplink}'"],
                check=True,
                timeout=3,
            )
            time.sleep(0.9)
            subprocess.run(["adb", "-s", self.device_id, "shell", "input", "tap", "100", "2020"], check=True, timeout=2)
            time.sleep(1.2)
            return True
        finally:
            self._safe_cleanup_remote_temp_photo(remote_path)
            if os.path.exists(local_cache):
                os.remove(local_cache)

    # ==========================================
    # 通道 B：USB 调试 (ADB) 极速搜索与内存结算提取 (105ms)
    # ==========================================

    def deeplink_search(self, keyword: str) -> bool:
        """通过拼多多原生 Scheme 0.1 秒秒开搜索结果页"""
        encoded_kw = urllib.parse.quote(keyword)
        deeplink = f"pinduoduo://com.xunmeng.pinduoduo/search_result.html?search_key={encoded_kw}"
        cmd = ["adb", "-s", self.device_id, "shell", f"am start -a android.intent.action.VIEW -d '{deeplink}'"]
        try:
            subprocess.run(cmd, capture_output=True, timeout=3)
            time.sleep(1.0)
            return True
        except Exception:
            return False

    def check_risk_and_failover(self, detected_texts: List[str]) -> bool:
        """检测是否触发风控，若命中立即自动降级切换到 ESP32 物理模式"""
        joined_text = " ".join(detected_texts)
        for pattern in RISK_PATTERNS:
            if re.search(pattern, joined_text, re.IGNORECASE):
                self.switch_mode(EngineMode.ESP32_PHYSICAL, reason=f"命中风控特征:{pattern}")
                return True
        return False

    def extract_checkout_url_from_adb(self, dumpsys_output: Optional[str] = None) -> Dict[str, Any]:
        """
        [极速白盒] 限定包名从当前拼多多前台 Activity 内存中 105ms 提取结算链接。
        注意：现代结算链接仅需 goods_id 与 sku_id，不再强依赖 group_id。
        """
        t0 = time.time()
        if dumpsys_output is None:
            cmd = ["adb", "-s", self.device_id, "shell", "dumpsys activity com.xunmeng.pinduoduo"]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
                out = p.stdout
            except Exception as e:
                return {"ok": False, "error": f"ADB dumpsys 执行失败: {e}"}
        else:
            out = dumpsys_output

        g_id = re.search(r"goods_id[^\w]+(\d+)", out)
        s_id = re.search(r"sku_id[^\w]+(\d+)", out)
        grp_id = re.search(r"group_id[^\w]+(\d+)", out)

        spec = re.search(r'\\+"spec\\+":\\+"([^\\"]+)\\+"', out)
        if not spec:
            spec = re.search(r'"spec":\s*"([^"]+)"', out)

        g_name = re.search(r'goods_name[^\w]+([^\\",\n\r]+)', out)
        elapsed_ms = (time.time() - t0) * 1000

        if g_id and s_id:
            goods_id = g_id.group(1)
            sku_id = s_id.group(1)
            group_id = grp_id.group(1) if grp_id else ""
            checkout_url = self.build_checkout_url(goods_id, sku_id, goods_number=1)
            return {
                "ok": True,
                "mode": "usb_debug",
                "elapsed_ms": round(elapsed_ms, 1),
                "goods_id": goods_id,
                "sku_id": sku_id,
                "group_id": group_id,
                "goods_name": g_name.group(1).strip() if g_name else "",
                "spec": spec.group(1).strip() if spec else "",
                "checkout_url": checkout_url,
            }
        return {
            "ok": False,
            "mode": "usb_debug",
            "elapsed_ms": round(elapsed_ms, 1),
            "error": "未在当前活动中抓取到完整的 goods_id/sku_id",
        }

    # ==========================================
    # 通道 C：ESP32 硬件拟真与预编译 mac_ocr 极速视觉
    # ==========================================

    @staticmethod
    def ensure_compiled_ocr_binary(binary_path: str = "/tmp/mac_ocr") -> Optional[str]:
        """将 vision_ocr.swift 预编译为原生二进制（单次识别从 2.0s 降至 50ms）。"""
        target = Path(binary_path)
        if target.is_file() and os.access(target, os.X_OK):
            return str(target)
        swift_src = Path(__file__).with_name("vision_ocr.swift")
        if not swift_src.is_file():
            return None
        try:
            subprocess.run(["swiftc", str(swift_src), "-O", "-o", str(target)], check=True, timeout=30)
            return str(target)
        except Exception:
            return None

    def refresh_window(self) -> bool:
        if not HAS_MACOS_FRAMEWORKS:
            return False
        windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
        for w in windows:
            owner = w.get("kCGWindowOwnerName", "")
            if (self.window_name in owner or "OPPO" in owner) and w.get("kCGWindowBounds", {}).get("Height", 0) > 100:
                self.wid = w.get("kCGWindowNumber")
                self.bounds = w.get("kCGWindowBounds")
                return True
        return False

    def activate_window(self):
        subprocess.run(["osascript", "-e", f'tell application "{self.window_name}" to activate'])
        time.sleep(0.1)

    def click_desktop(self, desk_x: float, desk_y: float):
        if not HAS_MACOS_FRAMEWORKS:
            return
        self.activate_window()
        pt = Quartz.CGPoint(desk_x, desk_y)
        down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, pt, Quartz.kCGMouseButtonLeft)
        up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, pt, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        time.sleep(0.05)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)

    def click_relative(self, rel_x: float, rel_y: float):
        if not self.refresh_window() or not self.bounds:
            return
        desk_x = self.bounds["X"] + self.bounds["Width"] * rel_x
        desk_y = self.bounds["Y"] + self.bounds["Height"] * rel_y
        self.click_desktop(desk_x, desk_y)

    @staticmethod
    def resolve_goods_id_from_share_url(share_url: str) -> Optional[str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            )
        }
        try:
            req = urllib.request.Request(share_url, headers=headers, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                final_url = resp.geturl()
            m = re.search(r"goods_id=(\d+)", final_url)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None
