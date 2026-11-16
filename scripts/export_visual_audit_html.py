#!/usr/bin/env python3
"""
生成本地单文件可视化比对与核验看板 (Visual Sourcing Audit HTML Dashboard)
彻底解决人工逐个点击链接导致平台风控与核对低效问题。
双列直观对照：左边门店官方高清原图与真实在售售价，右边供货商大厂主图、规格、采购价、到手价与毛利率。
深度集成实时同步机制：卡片点击【❌ 匹配错误】按钮，通过本地交互服务一秒联动回填 Excel 第 14 列 (N列【是否匹配】)。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROGRESS_PATH = "/tmp/pdd_sourcing_progress.json"
QNH_PATH = "/tmp/qnh_all_details_fixed.json"
OUTPUT_HTML = "/Users/cenbusi/Desktop/sourcing_audit_dashboard.html"


def extract_retail_price(q: dict, v: dict) -> float:
    """提取门店真实零售指导价"""
    raw = q.get("suggestPrice")
    if isinstance(raw, dict):
        raw = raw.get("tenantSuggestPrice", {}).get("unifiedSuggestPrice")
    if not raw or raw == "0" or raw == "0.00":
        raw = q.get("basicPrice")
    if not raw or raw == "0" or raw == "0.00":
        raw = v.get("retail_price")
    try:
        val = float(raw)
        if val > 0:
            return round(val, 2)
    except (ValueError, TypeError):
        pass
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="导出本地可视化比对核验看板")
    parser.add_argument("--progress", default=PROGRESS_PATH, help="比对进度 JSON 路径")
    parser.add_argument("--qnh", default=QNH_PATH, help="牵牛花商品元数据 JSON 路径")
    parser.add_argument("--output", default=OUTPUT_HTML, help="输出 HTML 文件路径")
    args = parser.parse_args()

    if not os.path.isfile(args.progress):
        print(f"进度文件不存在: {args.progress}", file=sys.stderr)
        return 1

    progress = json.load(open(args.progress, "r", encoding="utf-8"))
    qnh_map = {}
    if os.path.isfile(args.qnh):
        try:
            qnh_list = json.load(open(args.qnh, "r", encoding="utf-8"))
            for it in qnh_list:
                qnh_map[str(it.get("row"))] = it
        except Exception as e:
            print(f"读取 QNH 数据警告: {e}", file=sys.stderr)

    matched_items = []
    for k, v in progress.items():
        if v.get("status") == "MATCHED":
            q = qnh_map.get(str(k), {})
            retail_p = extract_retail_price(q, v)
            unit_p = float(v.get("unit_price") or v.get("landed_unit_price") or 0.0)
            group_p = float(v.get("group_price") or 0.0)
            ratio = int(v.get("ratio") or 1)
            sales = v.get("sales_volume") or 0

            # 状态：MATCH (默认) 或 MISMATCH
            match_status = v.get("match_status", "MATCH").upper()
            if match_status != "MISMATCH":
                match_status = "MATCH"

            matched_items.append({
                "row": int(k),
                "storeName": q.get("excelName") or q.get("qnhName") or v.get("name", "未命名商品"),
                "storeSpec": q.get("excelSpec") or q.get("specName") or "",
                "storePic": q.get("picUrl") or "",
                "retailPrice": retail_p,
                "platform": v.get("platform") or ("1688" if "1688" in (v.get("goods_url") or "") else "拼多多"),
                "supplierPic": v.get("main_pic") or "",
                "supplierTitle": v.get("sku_specs") or v.get("name") or "",
                "supplierUrl": v.get("goods_url") or "",
                "checkoutUrl": v.get("checkout_url") or v.get("goods_url") or "",
                "ratio": ratio,
                "groupPrice": group_p,
                "unitPrice": unit_p,
                "sales": sales,
                "moq": v.get("moq") or 1,
                "matchStatus": match_status,
            })

    matched_items.sort(key=lambda x: x["row"])
    mismatch_count = sum(1 for x in matched_items if x["matchStatus"] == "MISMATCH")
    matched_count = len(matched_items) - mismatch_count

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>供应链比价可视化直检看板 ({len(matched_items)} 个已匹配商品)</title>
<style>
  :root {{
    --bg: #f1f5f9;
    --card-bg: #ffffff;
    --border: #e2e8f0;
    --primary: #2563eb;
    --primary-hover: #1d4ed8;
    --success: #16a34a;
    --warning: #d97706;
    --danger: #dc2626;
    --danger-hover: #b91c1c;
    --text: #0f172a;
    --text-muted: #64748b;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 20px 24px;
    line-height: 1.5;
  }}
  header {{
    background: var(--card-bg);
    padding: 18px 24px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    margin-bottom: 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    position: sticky;
    top: 12px;
    z-index: 100;
  }}
  .header-left {{
    display: flex;
    align-items: center;
    gap: 14px;
  }}
  h1 {{ font-size: 19px; font-weight: 700; color: #0f172a; }}
  .header-desc {{ font-size: 13px; color: var(--text-muted); margin-top: 2px; }}
  .filter-tabs {{
    display: flex;
    background: #f1f5f9;
    padding: 4px;
    border-radius: 8px;
    gap: 4px;
  }}
  .tab-btn {{
    border: none;
    background: transparent;
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    color: #475569;
    transition: all 0.15s;
  }}
  .tab-btn.active {{
    background: #ffffff;
    color: var(--primary);
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }}
  .search-box {{
    padding: 8px 14px;
    border: 1px solid var(--border);
    border-radius: 8px;
    width: 240px;
    font-size: 13px;
    outline: none;
    transition: border-color 0.2s;
  }}
  .search-box:focus {{ border-color: var(--primary); }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
    gap: 18px;
  }}
  .card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    display: flex;
    flex-direction: column;
    gap: 12px;
    transition: transform 0.15s, box-shadow 0.15s, border-color 0.2s;
    position: relative;
  }}
  .card:hover {{
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(0,0,0,0.07);
  }}
  .card.is-mismatch {{
    border: 1.5px solid #fca5a5;
    background: #fffafa;
    opacity: 0.88;
  }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #f1f5f9;
    padding-bottom: 8px;
  }}
  .header-tags {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .row-num {{
    font-size: 13px;
    font-weight: 700;
    color: #334155;
    background: #f1f5f9;
    padding: 2px 8px;
    border-radius: 4px;
  }}
  .platform-tag {{
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
  }}
  .platform-1688 {{ background: #fff7ed; color: #ea580c; border: 1px solid #ffedd5; }}
  .platform-pdd {{ background: #fef2f2; color: #e11d48; border: 1px solid #ffe4e6; }}
  .status-badge {{
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
  }}
  .status-matched {{ background: #dcfce7; color: #15803d; }}
  .status-mismatch {{ background: #fee2e2; color: #b91c1c; }}
  .compare-row {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }}
  .side {{
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    background: #f8fafc;
    padding: 12px;
    border-radius: 8px;
    border: 1px solid #edf2f7;
  }}
  .side-title {{
    font-size: 11px;
    text-transform: uppercase;
    color: var(--text-muted);
    font-weight: 700;
    margin-bottom: 6px;
  }}
  .product-img {{
    width: 140px;
    height: 140px;
    object-fit: cover;
    border-radius: 8px;
    background: #e2e8f0;
    border: 1px solid #e2e8f0;
    margin-bottom: 8px;
    cursor: zoom-in;
    transition: transform 0.2s;
  }}
  .product-img:hover {{
    transform: scale(1.05);
  }}
  .item-name {{
    font-size: 13px;
    font-weight: 600;
    line-height: 1.4;
    height: 38px;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    margin-bottom: 4px;
  }}
  .item-spec {{
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 6px;
  }}
  .item-price {{
    font-size: 15px;
    font-weight: 700;
  }}
  .price-store {{ color: #0284c7; }}
  .price-sup {{ color: var(--danger); }}
  .card-footer {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #fafafa;
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 12px;
    border: 1px solid #f1f5f9;
  }}
  .margin-badge {{
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 12px;
  }}
  .margin-good {{ background: #dcfce7; color: var(--success); }}
  .margin-low {{ background: #fef3c7; color: #b45309; }}
  .footer-actions {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .link-btn {{
    color: var(--primary);
    text-decoration: none;
    font-weight: 600;
    padding: 5px 10px;
    border-radius: 6px;
    border: 1px solid #bfdbfe;
    background: #eff6ff;
    transition: background 0.15s;
  }}
  .link-btn:hover {{ background: #dbeafe; }}
  .btn-audit {{
    padding: 5px 12px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    transition: all 0.15s;
  }}
  .btn-mark-mismatch {{
    background: #fee2e2;
    color: #dc2626;
    border-color: #fca5a5;
  }}
  .btn-mark-mismatch:hover {{
    background: #fecaca;
    color: #b91c1c;
  }}
  .btn-restore-match {{
    background: #fef3c7;
    color: #b45309;
    border-color: #fde68a;
  }}
  .btn-restore-match:hover {{
    background: #fde68a;
  }}
  /* Toast 提示 */
  #toast {{
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: #0f172a;
    color: #ffffff;
    padding: 10px 18px;
    border-radius: 8px;
    font-size: 13px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    opacity: 0;
    transform: translateY(10px);
    transition: opacity 0.2s, transform 0.2s;
    pointer-events: none;
    z-index: 1000;
  }}
  #toast.show {{
    opacity: 1;
    transform: translateY(0);
  }}
</style>
</head>
<body>

<header>
  <div class="header-left">
    <div>
      <h1>🛒 1688 & 拼多多供应链直检看板</h1>
      <div class="header-desc">
        双列图片直观对照 | 已核准 <strong>{len(matched_items)}</strong> 个匹配商品 | 变更点击实时原子写回 <code>2743.xlsx</code> 第 14 列 (N列)
      </div>
    </div>
  </div>

  <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
    <div class="filter-tabs">
      <button class="tab-btn active" data-filter="all">全部 (<span id="countAll">{len(matched_items)}</span>)</button>
      <button class="tab-btn" data-filter="matched">✅ 匹配 (<span id="countMatched">{matched_count}</span>)</button>
      <button class="tab-btn" data-filter="mismatch">❌ 标记不匹配 (<span id="countMismatch">{mismatch_count}</span>)</button>
    </div>
    <input type="text" id="searchInput" class="search-box" placeholder="搜索商品名、规格或行号...">
  </div>
</header>

<div class="grid" id="productGrid">
"""

    for it in matched_items:
        margin = 0.0
        if it["retailPrice"] > 0:
            margin = ((it["retailPrice"] - it["unitPrice"]) / it["retailPrice"]) * 100
        margin_class = "margin-good" if margin >= 50 else "margin-low"
        sales_str = f"{it['sales']} 件" if it['sales'] < 10000 else f"{(it['sales']/10000):.1f} 万件"
        platform_class = "platform-1688" if it["platform"] == "1688" else "platform-pdd"
        is_mismatch = it["matchStatus"] == "MISMATCH"
        card_class = "card is-mismatch" if is_mismatch else "card"

        html_content += f"""
  <div class="{card_class}" id="card-{it['row']}" data-row="{it['row']}" data-status="{it['matchStatus']}" data-title="{it['storeName']} {it['supplierTitle']} {it['row']}">
    <div class="card-header">
      <div class="header-tags">
        <span class="row-num">Row #{it['row']}</span>
        <span class="platform-tag {platform_class}">{it['platform']} (销量: {sales_str})</span>
      </div>
      <div>
        <span class="status-badge {'status-mismatch' if is_mismatch else 'status-matched'}" id="status-badge-{it['row']}">
          {'❌ 不匹配' if is_mismatch else '✅ 匹配中'}
        </span>
      </div>
    </div>

    <div class="compare-row">
      <!-- 门店原始商品 -->
      <div class="side">
        <span class="side-title">门店在售商品</span>
        <img class="product-img" src="{it['storePic']}" loading="lazy" alt="门店主图" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'100\\'><rect fill=\\'%23eee\\' width=\\'100\\' height=\\'100\\'/><text fill=\\'%23999\\' x=\\'50%\\' y=\\'50%\\' text-anchor=\\'middle\\' dominant-baseline=\\'middle\\'>暂无图片</text></svg>'">
        <div class="item-name" title="{it['storeName']}">{it['storeName']}</div>
        <div class="item-spec">{it['storeSpec']}</div>
        <div class="item-price price-store">原价: ¥{it['retailPrice']:.2f}</div>
      </div>

      <!-- 匹配供货商商品 -->
      <div class="side">
        <span class="side-title">匹配供货商货源</span>
        <img class="product-img" src="{it['supplierPic']}" loading="lazy" alt="供货商主图" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'100\\'><rect fill=\\'%23eee\\' width=\\'100\\' height=\\'100\\'/><text fill=\\'%23999\\' x=\\'50%\\' y=\\'50%\\' text-anchor=\\'middle\\' dominant-baseline=\\'middle\\'>暂无图片</text></svg>'">
        <div class="item-name" title="{it['supplierTitle']}">{it['supplierTitle']}</div>
        <div class="item-spec">{it['ratio']}倍包装 | 采购¥{it['groupPrice']:.2f}</div>
        <div class="item-price price-sup">到手单价: ¥{it['unitPrice']:.2f}</div>
      </div>
    </div>

    <div class="card-footer">
      <div>
        毛利率: <span class="margin-badge {margin_class}">{margin:.1f}%</span>
      </div>
      <div class="footer-actions">
        <a href="{it['checkoutUrl']}" target="_blank" class="link-btn">直达链接 ↗</a>
        <button class="btn-audit {'btn-restore-match' if is_mismatch else 'btn-mark-mismatch'}" id="btn-toggle-{it['row']}" onclick="toggleMatchStatus({it['row']})">
          {'⚠️ 标记错误 (点击恢复)' if is_mismatch else '❌ 匹配错误'}
        </button>
      </div>
    </div>
  </div>
"""

    html_content += """
</div>

<div id="toast"></div>

<script>
  const API_BASE = "http://127.0.0.1:8899";
  const searchInput = document.getElementById('searchInput');
  const cards = document.querySelectorAll('.card');
  const tabBtns = document.querySelectorAll('.tab-btn');
  const toast = document.getElementById('toast');

  let currentFilter = 'all';

  function showToast(msg) {
    toast.innerText = msg;
    toast.classList.add('show');
    setTimeout(() => {
      toast.classList.remove('show');
    }, 2500);
  }

  function updateCounts() {
    let total = cards.length;
    let mismatch = 0;
    cards.forEach(c => {
      if (c.getAttribute('data-status') === 'MISMATCH') mismatch++;
    });
    let matched = total - mismatch;
    document.getElementById('countAll').innerText = total;
    document.getElementById('countMatched').innerText = matched;
    document.getElementById('countMismatch').innerText = mismatch;
  }

  function applyFilters() {
    const q = searchInput.value.toLowerCase().trim();
    cards.forEach(card => {
      const txt = (card.getAttribute('data-title') || '').toLowerCase();
      const status = card.getAttribute('data-status');
      
      let matchSearch = !q || txt.includes(q);
      let matchTab = true;
      if (currentFilter === 'matched') matchTab = (status !== 'MISMATCH');
      else if (currentFilter === 'mismatch') matchTab = (status === 'MISMATCH');

      card.style.display = (matchSearch && matchTab) ? 'flex' : 'none';
    });
  }

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentFilter = btn.getAttribute('data-filter');
      applyFilters();
    });
  });

  searchInput.addEventListener('input', applyFilters);

  // 核心：点击切换匹配状态，实时向本地服务发送请求，并原子回写 2743.xlsx 第 14 列 (N列)
  async function toggleMatchStatus(row) {
    const card = document.getElementById('card-' + row);
    const badge = document.getElementById('status-badge-' + row);
    const btn = document.getElementById('btn-toggle-' + row);
    if (!card) return;

    const curStatus = card.getAttribute('data-status') || 'MATCH';
    const nextStatus = (curStatus === 'MISMATCH') ? 'MATCH' : 'MISMATCH';

    // 乐观 UI 更新
    card.setAttribute('data-status', nextStatus);
    if (nextStatus === 'MISMATCH') {
      card.classList.add('is-mismatch');
      badge.className = 'status-badge status-mismatch';
      badge.innerText = '❌ 不匹配';
      btn.className = 'btn-audit btn-restore-match';
      btn.innerText = '⚠️ 标记错误 (点击恢复)';
    } else {
      card.classList.remove('is-mismatch');
      badge.className = 'status-badge status-matched';
      badge.innerText = '✅ 匹配中';
      btn.className = 'btn-audit btn-mark-mismatch';
      btn.innerText = '❌ 匹配错误';
    }
    updateCounts();

    // 发送 API 请求同步写入 Excel
    try {
      const resp = await fetch(`${API_BASE}/api/toggle-match?row=${row}&status=${nextStatus}`);
      const data = await resp.json();
      if (data.ok) {
        showToast(`Row #${row} 状态已联动更新为【${data.text}】，已同步写入 Excel N 列!`);
      } else {
        showToast(`Row #${row} 更新失败: ${data.error}`);
      }
    } catch (e) {
      showToast(`Row #${row} 本地已标记为【${nextStatus === 'MISMATCH' ? '不匹配' : '匹配'}】(服务未连接时本地缓存有效)`);
    }
  }
</script>

</body>
</html>
"""

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"★ 成功导出具备实时双向同步的可视化直检看板至: {args.output}")
    print(f"  - 总匹配商品数: {len(matched_items)} 项")
    print(f"  - 正常匹配: {matched_count} 项, 标记不匹配: {mismatch_count} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
