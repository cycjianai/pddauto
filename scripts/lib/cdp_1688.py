#!/usr/bin/env python3
"""
1688 100% Silent Background Chrome CDP Client (pddauto v3.0)
- Auto-discovers an existing Chrome remote-debugging port (9222..9229) or uses --cdp-port / CDP_PORT.
- ALWAYS executes Browser.setDownloadBehavior({"behavior": "default"}) on attach.
- STRICT NO-FOCUS-STEAL / NO-MOUSE-STEAL:
  * Uses ONLY Page.navigate, DOM.setFileInputFiles, window.open same-tab hook, and DOM el.click().
  * NEVER calls Input.dispatchMouseEvent, NEVER calls Page.bringToFront, NEVER pops new tabs.
- STRICT ANTI-CAPTCHA / NO-BYPASS:
  * Immediately halts and returns {"challenge": True} if any slider/login/punish page appears.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from websockets.sync.client import connect

RISK_JS = r"""(() => {
  const t = (document.title || '') + ' ' + ((document.body && document.body.innerText) || '').slice(0, 1200);
  return /验证码拦截|安全验证|请按住滑块|请完成验证|滑动验证|访问受限|访问被拒绝|点击按钮进行验证|验证后继续|亲，访问受限/.test(t)
    || /punish|captcha|deny_pc|login\.1688|login\.taobao/.test(location.href);
})()"""

IMAGE_CARDS_JS = r"""(() => {
  const out = [];
  for (const e of document.querySelectorAll('.major-offer,[class*="searchOfferWrapper"]')) {
    if (!e.offsetWidth || !e.offsetHeight) continue;
    let id = (e.getAttribute('data-renderkey') || '').match(/_(\d{8,16})$/)?.[1];
    const link = e.querySelector('a[href*="/offer/"]')?.href;
    if (!id && link) id = link.match(/offer\/(\d+)/)?.[1];
    if (!id || out.some(v => v.id === id)) continue;
    const lines = e.innerText.split(/\n/).map(x => x.trim()).filter(Boolean);
    const im = e.querySelector('[class*="offerImgInner"] img') || e.querySelector('img');
    out.push({
      id,
      title: lines[0] || '',
      price: (e.querySelector('[class*="offerPriceRow"]')?.innerText || '').replace(/\s+/g, ''),
      text: lines.slice(0, 25),
      img: im?.currentSrc || im?.src || '',
      url: 'https://detail.1688.com/offer/' + id + '.html',
    });
  }
  return {
    items: out,
    regions: [...document.querySelectorAll('[class^="cropRegion--"]')].map(e => e.classList.toString()),
    empty: /暂无相关货源|未找到相关|没有搜索到|没有找到符合|这里空空如也/.test(document.body?.innerText || ''),
    title: document.title,
  };
})()"""

OFFER_RENDER_JS = r"""(() => {
  const e = q => document.querySelector(q);
  const text = q => e(q)?.innerText?.trim() || '';
  const arr = q => Array.from(document.querySelectorAll(q)).filter(x => x.offsetWidth && x.offsetHeight);
  const body = document.body?.innerText || '';
  const opts = arr('#skuSelection .sku-filter-button').map(b => ({
    v: (b.innerText || '').trim(),
    raw: (b.textContent || ''),
    selected: b.classList.contains('active'),
    thumb: b.querySelector('img')?.currentSrc || b.querySelector('img')?.src || '',
  }));
  const rows = arr('#skuSelection .expand-view-item').map(b => ({
    v: (b.querySelector('.item-label')?.innerText || '').trim(),
    raw: (b.querySelector('.item-label')?.textContent || ''),
    info: [...b.querySelectorAll('.item-price-stock')].map(x => x.innerText.trim()),
    qty: b.querySelector('input')?.value || '',
    img: b.querySelector('img')?.currentSrc || b.querySelector('img')?.src || '',
  }));
  const hero = arr('#gallery img').sort((a, b) => (b.offsetWidth * b.offsetHeight) - (a.offsetWidth * a.offsetHeight))[0];
  const ship = text('#shippingServices').split(/\n/).filter(x => /运费|包邮|免邮|免运|发货|送达/.test(x)).join(' / ');
  const ready = !!e('#skuSelection');
  const challenge = (!ready && /访问验证|安全验证|滑动验证|请完成验证|请先登录|请登录后|亲，访问受限|点击按钮进行验证|请按住滑块/.test(body.slice(0, 2300)))
    || /punish|captcha|login\.1688|login\.taobao/.test(location.href);
  const unavailable = !ready && /已下架|已过期|商品不存在|该商品不存在|无法找到|无法查看|宝贝不存在|暂不支持/.test(body.slice(0, 3000));

  // Extract raw 1688 skuModel (exact skuProps + skuInfoMap preserving multi-spaces, 3-tier keys, industrial keys)
  let skuModel = null;
  let tempModel = null;
  try {
    const dj = window.context?.result?.data?.Root?.fields?.dataJson;
    if (dj) {
      if (dj.skuModel) skuModel = dj.skuModel;
      if (dj.tempModel) tempModel = dj.tempModel;
    }
  } catch (err) {}
  if (!skuModel) {
    const seen = new Set();
    const walk = (obj, depth) => {
      if (!obj || typeof obj !== 'object' || depth > 12 || seen.has(obj) || skuModel) return;
      seen.add(obj);
      if (obj.skuInfoMap && typeof obj.skuInfoMap === 'object') { skuModel = obj; return; }
      for (const k of Object.keys(obj)) {
        if (k === 'window' || k === 'self' || k === 'parent' || k === 'top' || k === 'document') continue;
        try { walk(obj[k], depth + 1); } catch (err) {}
      }
    };
    walk(window.context, 0);
    if (!skuModel) walk(window.__INIT_DATA, 0);
    if (!skuModel) walk(window.__DETAIL_DATA, 0);
  }

  let offerTitle = (tempModel && tempModel.offerTitle) || '';
  if (!offerTitle) {
    const h1 = document.querySelector('#productTitle h1, .title-first-column h1, h1');
    offerTitle = (h1 && h1.textContent && h1.textContent.trim()) || (document.title || '').replace(/\s*-\s*阿里巴巴\s*$/, '').trim();
  }

  const unesc = s => {
    const ta = document.createElement('textarea');
    ta.innerHTML = String(s || '');
    return ta.value;
  };
  const skuProps = [];
  if (skuModel && Array.isArray(skuModel.skuProps)) {
    for (const p of skuModel.skuProps) {
      skuProps.push({
        prop: p.prop || '',
        values: (p.value || []).map(v => ({name: v.name || '', imageUrl: v.imageUrl || ''})),
      });
    }
  }
  const skuMap = {};
  const qnhSpecs = [];
  if (skuModel && skuModel.skuInfoMap && typeof skuModel.skuInfoMap === 'object') {
    for (const [k, v] of Object.entries(skuModel.skuInfoMap)) {
      if (!v || typeof v !== 'object') continue;
      skuMap[k] = {
        skuId: v.skuId ?? null,
        specId: v.specId ?? null,
        specAttrs: v.specAttrs ?? k,
        canBookCount: v.canBookCount ?? null,
        price: v.price ?? null,
        discountPrice: v.discountPrice ?? null,
      };
      const parts = k.includes('&gt;') ? k.split('&gt;').map(unesc) : [unesc(k)];
      const deduped = (parts.length === 2 && parts[0] === parts[1]) ? [parts[0]] : parts;
      const qnhSpec = deduped.join('; ');
      qnhSpecs.push({
        spec: qnhSpec,
        price: v.discountPrice ?? v.price ?? null,
        stock: v.canBookCount ?? null,
        skuId: v.skuId ?? null,
        specId: v.specId ?? null,
      });
    }
  } else if (ready && !unavailable && offerTitle) {
    // 0-SKU single item: Qianniuhua matches exact 1688 offerTitle
    qnhSpecs.push({spec: offerTitle, price: null, stock: null, skuId: null, specId: null, zeroSkuTitle: true});
  }

  return {
    url: location.href.split('?')[0],
    title: document.title,
    offerTitle,
    goods: text('#productTitle').slice(0, 650),
    ready,
    challenge,
    unavailable,
    main: text('#mainPrice'),
    ship,
    shop: text('#shopNavigation').slice(0, 500),
    attrs: text('#productAttributes').slice(0, 4000),
    options: opts,
    rows,
    skuProps,
    skuMap,
    qnh_specs: qnhSpecs,
    sku: text('#skuSelection').slice(0, 6500),
    image: (hero?.currentSrc || hero?.src || '').split('.jpg_')[0] + ((hero?.currentSrc || hero?.src || '').includes('.jpg_') ? '.jpg' : ''),
    unavailableText: !ready ? ((body.match(/.{0,14}(已下架|已过期|商品不存在|该商品不存在|无法找到|无法查看|宝贝不存在|暂不支持).{0,22}/) || [])[0] || null) : null,
  };
})()"""


def _http_json(base: str, path: str, timeout: float = 3.0) -> Any:
    with urllib.request.urlopen(base + path, timeout=timeout) as resp:
        return json.load(resp)


PROTECTED_TAB_HOSTS = (
    "saas.fuliops.cn",
    "qnh.meituan.com",
    "shangoue.meituan.com",
    "nr.ele.me",
    "saas-retail.ele.me",
    "mini.guodongcheng.cn",
    "yangkeduo.com",
    "pinduoduo.com",
)


def discover_cdp_base(port: Optional[int] = None) -> str:
    env_port = os.environ.get("CDP_PORT")
    candidates: List[int] = []
    if port:
        candidates.append(int(port))
    elif env_port and env_port.isdigit():
        candidates.append(int(env_port))
    candidates.extend([p for p in (9222, 9224, 9223, 9225, 9226, 9227, 9228, 9229) if p not in candidates])

    best_base = None
    for p in candidates:
        base = f"http://127.0.0.1:{p}"
        try:
            pages = _http_json(base, "/json/list", timeout=1.2)
            if not isinstance(pages, list):
                continue
            if port and p == int(port):
                return base
            if any("1688.com" in (pg.get("url") or "") for pg in pages if pg.get("type") == "page"):
                return base
            if best_base is None and any(pg.get("type") == "page" for pg in pages):
                best_base = base
        except Exception:
            continue
    if best_base:
        return best_base
    raise RuntimeError(
        "No live Chrome CDP endpoint found on ports 9222..9229. "
        "Launch regular Chrome with --remote-debugging-port=<PORT> --user-data-dir=/tmp/chrome_dev_session_<PORT>."
    )


class CDPSession:
    def __init__(self, ws_url: str):
        self.ws = connect(ws_url, open_timeout=8, close_timeout=2, max_size=24_000_000)
        self._id = 0

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Any:
        self._id += 1
        req_id = self._id
        self.ws.send(json.dumps({"id": req_id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv(timeout=timeout))
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result", {})

    def js(self, expression: str, timeout: float = 15.0) -> Any:
        r = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        }, timeout=timeout)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("text", "JS evaluation error"))
        return r.get("result", {}).get("value")


def _is_protected_tab(url: str) -> bool:
    u = (url or "").lower()
    if u.startswith("file://") or u.startswith("chrome://") or u.startswith("devtools://"):
        return True
    return any(host in u for host in PROTECTED_TAB_HOSTS)


def open_silent_1688_session(port: Optional[int] = None) -> Tuple[CDPSession, str, str]:
    """Attach silently to an existing 1688 tab or spawn a dedicated background 1688 tab (never hijacks business tabs)."""
    base = discover_cdp_base(port)
    ver = _http_json(base, "/json/version")
    browser_sess = CDPSession(ver["webSocketDebuggerUrl"])
    try:
        browser_sess.call("Browser.setDownloadBehavior", {"behavior": "default"})
        pages = [
            pg for pg in _http_json(base, "/json/list")
            if pg.get("type") == "page" and not (pg.get("url") or "").startswith("devtools://")
        ]
        target = next((pg for pg in pages if "1688.com" in (pg.get("url") or "")), None)
        if target is None:
            # Prefer an empty/new-tab page if available; NEVER hijack Yuandian/QNH/merchant business tabs
            target = next(
                (pg for pg in pages if (pg.get("url") or "") in ("about:blank", "chrome://newtab/") or not _is_protected_tab(pg.get("url") or "")),
                None,
            )
        if target is None:
            # Create a 100% background tab via CDP Target.createTarget (zero window/focus steal)
            created = browser_sess.call("Target.createTarget", {"url": "https://www.1688.com/", "background": True})
            new_tid = created.get("targetId")
            for _ in range(20):
                time.sleep(0.25)
                refreshed = _http_json(base, "/json/list")
                target = next((pg for pg in refreshed if pg.get("id") == new_tid and pg.get("webSocketDebuggerUrl")), None)
                if target is not None:
                    break
            time.sleep(1.6)
    finally:
        browser_sess.close()

    if target is None:
        raise RuntimeError(f"Failed to attach or open a background 1688 tab on {base}")
    return CDPSession(target["webSocketDebuggerUrl"]), target["id"], base


def ensure_1688_home(sess: CDPSession) -> bool:
    url = sess.js("location.href") or ""
    if "www.1688.com" not in url or "offer/" in url or "pc-image-search" in url or "s.1688.com" in url:
        sess.call("Page.navigate", {"url": "https://www.1688.com/"})
        time.sleep(2.4)
    return not bool(sess.js(RISK_JS))


def silent_image_search(sess: CDPSession, img_path: Path) -> Dict[str, Any]:
    """Upload a local store image to 1688 image search in the SAME background tab (zero focus/mouse steal)."""
    if not img_path.is_file():
        return {"error": f"missing_store_img:{img_path}"}
    if not ensure_1688_home(sess):
        return {"challenge": True}

    root = sess.call("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
    node = sess.call("DOM.querySelector", {"nodeId": root, "selector": "input[type=file]"})["nodeId"]
    if not node:
        sess.call("Page.navigate", {"url": "https://www.1688.com/"})
        time.sleep(2.5)
        if sess.js(RISK_JS):
            return {"challenge": True}
        root = sess.call("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        node = sess.call("DOM.querySelector", {"nodeId": root, "selector": "input[type=file]"})["nodeId"]
    if not node:
        return {"error": "no_file_input"}

    sess.call("DOM.setFileInputFiles", {"nodeId": node, "files": [str(img_path.resolve())]})
    ready = False
    for _ in range(24):
        ready = bool(sess.js(r"""(() => {
          const p = document.querySelector('[class*=imageSearchPopover]');
          const e = p?.querySelector('[class*=actionPrimary]');
          return !!(e && !e.disabled && p.innerText.includes('已上传1张图') && p.querySelector('img'));
        })()"""))
        if ready:
            break
        if sess.js(RISK_JS):
            return {"challenge": True}
        time.sleep(0.28)
    if not ready:
        return {"error": "nopreview"}

    # Hook window.open so 1688 navigates in the SAME background tab without opening a foreground tab!
    sess.js(r"""(() => {
      if (!window.__pddautoHookedOpen) {
        window.__pddautoHookedOpen = true;
        window.open = function(url) {
          if (url) location.href = url;
          return window;
        };
      }
      const p = document.querySelector('[class*=imageSearchPopover]');
      const e = p?.querySelector('[class*=actionPrimary]');
      if (e) e.click();
    })()""")

    for _ in range(26):
        time.sleep(0.75)
        try:
            cur_url = sess.js("location.href") or ""
        except Exception:
            continue
        if any(k in cur_url for k in ("punish", "captcha", "login.1688", "login.taobao")):
            return {"challenge": True}
        if sess.js(RISK_JS):
            return {"challenge": True}
        if "pc-image-search" in cur_url:
            data = sess.js(IMAGE_CARDS_JS)
            if data and (data.get("items") or data.get("empty")):
                return data
    return {"error": "noresults"}


def silent_keyword_search(sess: CDPSession, keyword: str, limit: int = 15) -> Dict[str, Any]:
    """Run silent 1688 keyword search via Page.navigate (zero mouse/focus steal)."""
    q = urllib.parse.quote(keyword.encode("gbk", errors="ignore"))
    sess.call("Page.navigate", {"url": f"https://s.1688.com/selloffer/offer_search.htm?keywords={q}"})
    time.sleep(3.4)
    cur_url = sess.js("location.href") or ""
    if any(k in cur_url for k in ("punish", "captcha", "login.1688", "login.taobao")) or sess.js(RISK_JS):
        return {"challenge": True, "keyword": keyword, "items": []}

    items = sess.js(f"""(() => {{
      const cards = [...document.querySelectorAll('a[href*="detail.1688.com/offer/"]')];
      const seen = new Set(), out = [];
      for (const a of cards) {{
        const m = (a.href || '').match(/offer\\/(\\d+)\\.html/);
        if (!m || seen.has(m[1])) continue;
        seen.add(m[1]);
        const box = a.closest('[class*="offer"], [class*="card"], li, div') || a;
        const txt = (box.innerText || a.innerText || '').replace(/\\s+/g, ' ').trim();
        if (txt.length < 4) continue;
        const imgEl = box.querySelector('img');
        out.push({{
          id: m[1],
          title: txt.slice(0, 140),
          img: imgEl?.currentSrc || imgEl?.src || '',
          url: 'https://detail.1688.com/offer/' + m[1] + '.html',
        }});
        if (out.length >= {int(limit)}) break;
      }}
      return out;
    }})()""") or []
    return {"challenge": False, "keyword": keyword, "count": len(items), "items": items}


def load_offer_card(sess: CDPSession, oid: str, click_option: Optional[str] = None) -> Dict[str, Any]:
    """Silently load a 1688 offer page, expand all SKU rows, and optionally DOM-click a tier-1 option."""
    link = f"https://detail.1688.com/offer/{oid}.html"
    cur = sess.js("location.href.split('?')[0]") or ""
    if cur != link:
        sess.call("Page.navigate", {"url": link})

    rec: Dict[str, Any] = {}
    for delay in (0.5, 0.7, 0.9, 1.1, 1.4, 1.8, 2.2):
        time.sleep(delay)
        try:
            rec = sess.js(OFFER_RENDER_JS) or {}
        except Exception:
            continue
        if rec.get("challenge") or rec.get("unavailable"):
            return rec
        if rec.get("url") == link and rec.get("ready") and (rec.get("rows") or len(rec.get("sku", "")) > 20):
            break

    if not rec.get("ready"):
        return rec

    # Click any "展开全部 / 查看更多" button silently
    sess.js(r"""(() => {
      for (const el of document.querySelectorAll('#skuSelection button, #skuSelection span, #skuSelection div')) {
        const t = (el.innerText || '').trim();
        if (t === '展开全部' || t === '查看更多' || t === '展开') { try { el.click(); } catch {} }
      }
    })()""")
    time.sleep(0.5)

    # Optionally click a specific tier-1 option (essential for 2-tier 1688 SKUs!)
    clicked_ok = False
    if click_option:
        arg = json.dumps(click_option, ensure_ascii=False)
        clicked_ok = bool(sess.js(f"""(() => {{
          const target = {arg};
          const buttons = [...document.querySelectorAll('#skuSelection .sku-filter-button, #skuSelection button, #skuSelection [class*="prop-item"], #skuSelection div, #skuSelection span')];
          let el = buttons.find(b => b.innerText && b.innerText.trim() === target && b.children.length <= 3);
          if (!el) el = buttons.find(b => b.innerText && b.innerText.trim().includes(target) && b.children.length <= 2);
          if (!el || el.disabled) return false;
          el.click();
          return true;
        }})()"""))
        if clicked_ok:
            time.sleep(0.8)

    rec2 = sess.js(OFFER_RENDER_JS) or {}
    rec.update({k: v for k, v in rec2.items() if k not in ("url", "title")})
    rec["clicked_option"] = click_option if clicked_ok else None
    rec["meta"] = sess.js(r"""(() => ({
      ship: [...document.querySelectorAll('[class*=logistic], [class*=freight]')].map(e => e.innerText.trim()).filter(Boolean).slice(0, 3),
      sku_txt: (document.querySelector('#skuSelection')?.innerText || '').slice(0, 1400),
      price_bar: (document.querySelector('[class*=price-content], [class*=priceBox], .price-text')?.innerText || '').slice(0, 220),
    }))()""") or {}
    return rec
