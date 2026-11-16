#!/usr/bin/env python3
"""
生成本地单文件可视化比对与核验看板 (Visual Sourcing Audit HTML Dashboard)
彻底解决人工逐个点击链接导致平台风控与核对低效问题。
双列直观对照：左边门店原图与售价，右边供货商大厂主图、规格、采购价与毛利率。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="导出本地可视化比对核验看板")
    parser.add_argument("--progress", default="/tmp/pdd_sourcing_progress.json", help="比对进度 JSON 路径")
    parser.add_argument("--qnh", default="/tmp/qnh_all_details_fixed.json", help="牵牛花商品元数据 JSON 路径")
    parser.add_argument("--output", default="/Users/cenbusi/Desktop/sourcing_audit_dashboard.html", help="输出 HTML 文件路径")
    args = parser.parse_args()

    if not os.path.isfile(args.progress):
        print(f"进度文件不存在: {args.progress}", file=sys.stderr)
        return 1

    progress = json.load(open(args.progress, "r", encoding="utf-8"))
    qnh_map = {}
    if os.path.isfile(args.qnh):
        qnh_list = json.load(open(args.qnh, "r", encoding="utf-8"))
        for it in qnh_list:
            qnh_map[str(it.get("row"))] = it

    matched_items = []
    for k, v in progress.items():
        if v.get("status") == "MATCHED":
            q = qnh_map.get(str(k), {})
            matched_items.append({
                "row": int(k),
                "storeName": q.get("excelName") or q.get("qnhName") or v.get("name", "未命名商品"),
                "storeSpec": q.get("excelSpec") or q.get("specName") or "",
                "storePic": q.get("picUrl") or "",
                "retailPrice": float(q.get("basicPrice") or q.get("suggestPrice") or v.get("retail_price") or 0.0),
                "platform": v.get("platform") or ("1688" if "1688" in (v.get("goods_url") or "") else "拼多多"),
                "supplierPic": v.get("main_pic") or "",
                "supplierTitle": v.get("sku_specs") or v.get("name") or "",
                "supplierUrl": v.get("goods_url") or "",
                "checkoutUrl": v.get("checkout_url") or v.get("goods_url") or "",
                "ratio": int(v.get("ratio") or 1),
                "groupPrice": float(v.get("group_price") or 0.0),
                "unitPrice": float(v.get("unit_price") or v.get("landed_unit_price") or 0.0),
                "sales": v.get("sales_volume") or 0,
                "moq": v.get("moq") or 1,
            })

    matched_items.sort(key=lambda x: x["row"])

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>供应链比价可视化直检看板 ({len(matched_items)} 个已匹配商品)</title>
<style>
  :root {{
    --bg: #f4f6f9;
    --card-bg: #ffffff;
    --border: #e2e8f0;
    --primary: #2563eb;
    --success: #16a34a;
    --danger: #dc2626;
    --text: #1e293b;
    --text-muted: #64748b;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 24px;
    line-height: 1.5;
  }}
  header {{
    background: var(--card-bg);
    padding: 20px 24px;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    margin-bottom: 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
  }}
  h1 {{ font-size: 20px; font-weight: 700; color: #0f172a; }}
  .stats-badge {{
    background: #eff6ff;
    color: var(--primary);
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 14px;
    font-weight: 600;
  }}
  .search-box {{
    padding: 8px 16px;
    border: 1px solid var(--border);
    border-radius: 8px;
    width: 280px;
    font-size: 14px;
    outline: none;
  }}
  .search-box:focus {{ border-color: var(--primary); }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
    gap: 18px;
  }}
  .card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    display: flex;
    flex-direction: column;
    gap: 14px;
    transition: transform 0.15s, box-shadow 0.15s;
  }}
  .card:hover {{
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #f1f5f9;
    padding-bottom: 8px;
  }}
  .row-num {{
    font-size: 13px;
    font-weight: 700;
    color: #475569;
    background: #f8fafc;
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
  }}
  .platform-tag {{
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
  }}
  .platform-1688 {{ background: #fff7ed; color: #ea580c; border: 1px solid #ffedd5; }}
  .platform-pdd {{ background: #fef2f2; color: #e11d48; border: 1px solid #ffe4e6; }}
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
    width: 130px;
    height: 130px;
    object-fit: cover;
    border-radius: 8px;
    background: #e2e8f0;
    border: 1px solid #e2e8f0;
    margin-bottom: 8px;
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
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 12px;
  }}
  .margin-badge {{
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
  }}
  .margin-good {{ background: #dcfce7; color: var(--success); }}
  .margin-low {{ background: #fef3c7; color: #b45309; }}
  .link-btn {{
    color: var(--primary);
    text-decoration: none;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 4px;
    border: 1px solid #bfdbfe;
    background: #eff6ff;
  }}
  .link-btn:hover {{ background: #dbeafe; }}
</style>
</head>
<body>

<header>
  <div>
    <h1>🛒 1688 & 拼多多供应链直检看板</h1>
    <p style="font-size: 13px; color: var(--text-muted); margin-top: 4px;">
      双列图片直观对照，避免逐个点开详情页引发平台风控。已加载 <strong>{len(matched_items)}</strong> 个匹配商品。
    </p>
  </div>
  <div style="display: flex; align-items: center; gap: 12px;">
    <input type="text" id="searchInput" class="search-box" placeholder="搜索商品名、规格或行号...">
    <div class="stats-badge">总计 {len(matched_items)} 项</div>
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

        html_content += f"""
  <div class="card" data-title="{it['storeName']} {it['supplierTitle']} {it['row']}">
    <div class="card-header">
      <span class="row-num">Row #{it['row']}</span>
      <span class="platform-tag {platform_class}">{it['platform']} (销量: {sales_str})</span>
    </div>

    <div class="compare-row">
      <!-- 门店原始商品 -->
      <div class="side">
        <span class="side-title">门店在售商品</span>
        <img class="product-img" src="{it['storePic']}" loading="lazy" alt="门店主图" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'100\\'><rect fill=\\'%23eee\\' width=\\'100\\' height=\\'100\\'/><text fill=\\'%23999\\' x=\\'50%\\' y=\\'50%\\' text-anchor=\\'middle\\' dominant-baseline=\\'middle\\'>暂无图片</text></svg>'">
        <div class="item-name" title="{it['storeName']}">{it['storeName']}</div>
        <div class="item-spec">{it['storeSpec']}</div>
        <div class="item-price price-store">零售价: ¥{it['retailPrice']:.2f}</div>
      </div>

      <!-- 匹配供货商商品 -->
      <div class="side">
        <span class="side-title">匹配供货商货源</span>
        <img class="product-img" src="{it['supplierPic']}" loading="lazy" alt="供货商主图" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'100\\'><rect fill=\\'%23eee\\' width=\\'100\\' height=\\'100\\'/><text fill=\\'%23999\\' x=\\'50%\\' y=\\'50%\\' text-anchor=\\'middle\\' dominant-baseline=\\'middle\\'>暂无图片</text></svg>'">
        <div class="item-name" title="{it['supplierTitle']}">{it['supplierTitle']}</div>
        <div class="item-spec">{it['ratio']}倍包装 | 采购¥{it['groupPrice']:.2f}</div>
        <div class="item-price price-sup">到手价: ¥{it['unitPrice']:.2f}</div>
      </div>
    </div>

    <div class="card-footer">
      <div>
        毛利率: <span class="margin-badge {margin_class}">{margin:.1f}%</span>
      </div>
      <div>
        <a href="{it['checkoutUrl']}" target="_blank" class="link-btn">直达链接 ↗</a>
      </div>
    </div>
  </div>
"""

    html_content += """
</div>

<script>
  const searchInput = document.getElementById('searchInput');
  const cards = document.querySelectorAll('.card');

  searchInput.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase().trim();
    cards.forEach(card => {
      const txt = (card.getAttribute('data-title') || '').toLowerCase();
      if (!q || txt.includes(q)) {
        card.style.display = 'flex';
      } else {
        card.style.display = 'none';
      }
    });
  });
</script>

</body>
</html>
"""

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"★ 成功导出离线可视化直检看板至: {args.output} (共包含 {len(matched_items)} 个已匹配商品)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
