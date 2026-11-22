#!/usr/bin/env python3
"""
Yuandian Shanggou (原点闪购) Admin SaaS Silent Background CDP Client (pddauto v3.3)
- Auto-discovers Chrome CDP port (9222..9229 or explicit --port / CDP_PORT) with a logged-in
  `saas.fuliops.cn/procurement-sourcing` (or `saas.fuliops.cn` admin) tab.
- 100% background silent: NEVER calls Page.bringToFront or Input.dispatchMouseEvent.
- Uses the logged-in admin session's `localStorage.getItem("admin_token")` strictly inside page context.
- HARD SAFETY LOCK: Intentionally provides NO `/deliver` or `/cancel` methods; final customer delivery &
  billing settlement MUST always be confirmed manually by the operator.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .cdp_1688 import CDPSession, _http_json

API_BASE = "/api/v1/admin/procurement-sourcing"


def discover_yuandian_tab(port: Optional[int] = None) -> Tuple[str, Dict[str, Any]]:
    """Find a live Chrome CDP endpoint & tab hosting `saas.fuliops.cn/procurement-sourcing`."""
    env_port = os.environ.get("CDP_PORT")
    candidates: List[int] = []
    if port:
        candidates.append(int(port))
    elif env_port and env_port.isdigit():
        candidates.append(int(env_port))
    candidates.extend([p for p in (9222, 9223, 9224, 9225, 9226, 9227, 9228, 9229) if p not in candidates])

    fallback: Optional[Tuple[str, Dict[str, Any]]] = None
    for p in candidates:
        base = f"http://127.0.0.1:{p}"
        try:
            pages = _http_json(base, "/json/list", timeout=1.2)
        except Exception:
            continue
        if not isinstance(pages, list):
            continue
        for pg in pages:
            if pg.get("type") != "page":
                continue
            url = (pg.get("url") or "").lower()
            if "saas.fuliops.cn/procurement-sourcing" in url:
                return base, pg
            if fallback is None and "saas.fuliops.cn" in url and "/operator/" not in url:
                fallback = (base, pg)
        if port and p == int(port) and fallback is not None:
            return fallback

    if fallback is not None:
        return fallback
    raise RuntimeError(
        "No logged-in Yuandian admin tab (`saas.fuliops.cn/procurement-sourcing`) found on Chrome CDP ports 9222..9229. "
        "Open `https://saas.fuliops.cn/procurement-sourcing` in regular Chrome with --remote-debugging-port=9222."
    )


class YuandianAdminClient:
    """Silent CDP API bridge for `https://saas.fuliops.cn/procurement-sourcing`."""

    def __init__(self, port: Optional[int] = None):
        self.base, self.tab = discover_yuandian_tab(port)
        ver = _http_json(self.base, "/json/version")
        bs = CDPSession(ver["webSocketDebuggerUrl"])
        try:
            bs.call("Browser.setDownloadBehavior", {"behavior": "default"})
        finally:
            bs.close()
        self.sess = CDPSession(self.tab["webSocketDebuggerUrl"])

    def close(self) -> None:
        self.sess.close()

    def __enter__(self) -> "YuandianAdminClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _api(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        timeout: float = 20.0,
    ) -> Any:
        body_js = "undefined" if body is None else json.dumps(json.dumps(body, ensure_ascii=False))
        expr = f"""(async () => {{
          const token = localStorage.getItem('admin_token');
          if (!token) return {{ __ok: false, status: 401, error: 'admin_token missing in localStorage (please log in to saas.fuliops.cn admin)' }};
          const opts = {{
            method: {json.dumps(method)},
            headers: {{ 'Authorization': 'Bearer ' + token }}
          }};
          const rawBody = {body_js};
          if (rawBody !== undefined) {{
            opts.headers['Content-Type'] = 'application/json';
            opts.body = rawBody;
          }}
          const resp = await fetch({json.dumps(path)}, opts);
          const text = await resp.text();
          let data = null;
          try {{ data = JSON.parse(text); }} catch {{ data = text; }}
          return {{ __ok: resp.ok, status: resp.status, data }};
        }})()"""
        res = self.sess.js(expr, timeout=timeout)
        if not isinstance(res, dict) or not res.get("__ok"):
            status = res.get("status") if isinstance(res, dict) else "unknown"
            detail = res.get("error") or res.get("data") if isinstance(res, dict) else res
            raise RuntimeError(f"Yuandian API {method} {path} failed (HTTP {status}): {detail}")
        return res["data"]

    def get_page_payload(self) -> Optional[Dict[str, Any]]:
        """Read embedded `<script id='agent-task-payload'>` JSON currently active on the page (if present)."""
        raw = self.sess.js("document.getElementById('agent-task-payload')?.textContent || ''")
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) and data.get("task") else None
        except Exception:
            return None

    def get_rules(self) -> Dict[str, Any]:
        """Fetch live sourcing rules (`version` + `rules_text`) from backend."""
        return self._api("GET", f"{API_BASE}/rules")

    def list_tasks(
        self,
        status: str = "all",
        q: str = "",
        page: int = 1,
        page_size: int = 80,
    ) -> Dict[str, Any]:
        qs = urllib.parse.urlencode({"status": status, "q": q, "page": page, "page_size": page_size})
        return self._api("GET", f"{API_BASE}/tasks?{qs}")

    def get_task_detail(self, task_no: str) -> Dict[str, Any]:
        enc = urllib.parse.quote(task_no, safe="")
        return self._api("GET", f"{API_BASE}/tasks/{enc}")

    def patch_item(self, task_no: str, item_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        enc = urllib.parse.quote(task_no, safe="")
        return self._api("PATCH", f"{API_BASE}/tasks/{enc}/items/{int(item_id)}", body=fields)

    def reload_tab_silently(self) -> None:
        """Silently refresh the admin tab in background so updated rows are immediately visible."""
        self.sess.call("Page.reload", {})
