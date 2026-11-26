#!/usr/bin/env python3
"""
生成本地单文件可视化比对与核验看板 (Visual Sourcing Audit HTML Dashboard)
彻底解决人工逐个点击链接导致平台风控与核对低效问题。
双列直观对照：左边门店官方高清原图与真实在售售价，右边供货商大厂主图、规格、采购价、到手价与毛利率。
支持：
  1. 任意符合标准 15 列字段的 Excel 导入后自动动态解析渲染，且 Excel -> HTML 单向权威同步全部已标记状态（含结尾顺序标记的「不匹配」）。
  2. 团队接力续审：导入后自动定位最后一条「不匹配」位置，一键跳转无缝继续审核。
  3. 原地自动保存 (File System Access API) + 一键下载已核对 Excel（严格规范单 .xlsx 后缀，绝不重复追加 .xlsx）。
  4. 本机 8899 后台直连模式兼容。
"""

from __future__ import annotations

import argparse
import base64
import glob
import io
import json
import os
import re
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    from PIL import Image
except ImportError:
    Image = None

PROGRESS_PATH = "/tmp/pdd_sourcing_progress.json"
QNH_PATH = "/tmp/qnh_all_details_fixed.json"
MAX_TARGET_ROW = 1791  # 默认预置数据最大行号；导入外部 Excel 时不受此限制，全表完整解析


def get_default_html_output() -> str:
    if os.path.isdir("/Users/cenbusi/Desktop/当前工作"):
        return "/Users/cenbusi/Desktop/当前工作/sourcing_audit_dashboard.html"
    return "/Users/cenbusi/Desktop/sourcing_audit_dashboard.html"


OUTPUT_HTML = get_default_html_output()


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


HTML_HEAD = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>供应链比价可视化直检看板</title>
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js" onerror="var s=document.createElement('script');s.src='https://unpkg.com/xlsx@0.18.5/dist/xlsx.full.min.js';document.head.appendChild(s);"></script>
<style>
  :root {
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
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 20px 24px;
    line-height: 1.5;
  }
  header {
    background: var(--card-bg);
    padding: 18px 24px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    margin-bottom: 18px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    position: sticky;
    top: 12px;
    z-index: 100;
  }
  .header-left {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  h1 { font-size: 19px; font-weight: 700; color: #0f172a; }
  .header-desc { font-size: 13px; color: var(--text-muted); margin-top: 2px; }
  .filter-tabs {
    display: flex;
    background: #f1f5f9;
    padding: 4px;
    border-radius: 8px;
    gap: 4px;
    flex-wrap: wrap;
  }
  .tab-btn {
    border: none;
    background: transparent;
    padding: 6px 13px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    color: #475569;
    transition: all 0.15s;
  }
  .tab-btn.active {
    background: #ffffff;
    color: var(--primary);
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }
  .search-box {
    padding: 8px 14px;
    border: 1px solid var(--border);
    border-radius: 8px;
    width: 240px;
    font-size: 13px;
    outline: none;
    transition: border-color 0.2s;
  }
  .search-box:focus { border-color: var(--primary); }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
    gap: 18px;
  }
  .card {
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
    content-visibility: auto;
    contain-intrinsic-size: 0 360px;
  }
  .card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(0,0,0,0.07);
  }
  .card.is-mismatch {
    border: 1.5px solid #fca5a5;
    background: #fffafa;
    opacity: 0.9;
  }
  .card.is-unmatched {
    border: 1.5px dashed #cbd5e1;
    background: #f8fafc;
  }
  .card.flash-highlight {
    box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.35);
    border-color: #2563eb;
  }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #f1f5f9;
    padding-bottom: 8px;
    gap: 8px;
  }
  .header-tags {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .row-num {
    font-size: 13px;
    font-weight: 700;
    color: #334155;
    background: #f1f5f9;
    padding: 2px 8px;
    border-radius: 4px;
  }
  .platform-tag {
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
  }
  .platform-1688 { background: #fff7ed; color: #ea580c; border: 1px solid #ffedd5; }
  .platform-pdd { background: #fef2f2; color: #e11d48; border: 1px solid #ffe4e6; }
  .platform-other { background: #f1f5f9; color: #475569; border: 1px solid #e2e8f0; }
  .status-badge {
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
    white-space: nowrap;
  }
  .status-matched { background: #dcfce7; color: #15803d; }
  .status-mismatch { background: #fee2e2; color: #b91c1c; }
  .status-unmatched { background: #e2e8f0; color: #475569; }
  .compare-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .side {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    background: #f8fafc;
    padding: 12px;
    border-radius: 8px;
    border: 1px solid #edf2f7;
    min-width: 0;
  }
  .side-title {
    font-size: 11px;
    text-transform: uppercase;
    color: var(--text-muted);
    font-weight: 700;
    margin-bottom: 6px;
  }
  .product-img {
    width: 140px;
    height: 140px;
    object-fit: cover;
    border-radius: 8px;
    background: #e2e8f0;
    border: 1px solid #e2e8f0;
    margin-bottom: 8px;
    cursor: zoom-in;
    transition: transform 0.2s;
  }
  .product-img:hover {
    transform: scale(1.05);
  }
  .item-name {
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
    word-break: break-word;
  }
  .item-spec {
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 6px;
    word-break: break-word;
  }
  .item-price {
    font-size: 15px;
    font-weight: 700;
  }
  .price-store { color: #0284c7; }
  .price-sup { color: var(--danger); }
  .card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #fafafa;
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 12px;
    border: 1px solid #f1f5f9;
    gap: 8px;
    flex-wrap: wrap;
  }
  .margin-badge {
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 12px;
  }
  .margin-good { background: #dcfce7; color: var(--success); }
  .margin-low { background: #fef3c7; color: #b45309; }
  .footer-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .link-btn {
    color: var(--primary);
    text-decoration: none;
    font-weight: 600;
    padding: 5px 10px;
    border-radius: 6px;
    border: 1px solid #bfdbfe;
    background: #eff6ff;
    transition: background 0.15s;
  }
  .link-btn:hover { background: #dbeafe; }
  .btn-audit {
    padding: 5px 12px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    transition: all 0.15s;
  }
  .btn-mark-mismatch {
    background: #fee2e2;
    color: #dc2626;
    border-color: #fca5a5;
  }
  .btn-mark-mismatch:hover {
    background: #fecaca;
    color: #b91c1c;
  }
  .btn-restore-match {
    background: #fef3c7;
    color: #b45309;
    border-color: #fde68a;
  }
  .btn-restore-match:hover {
    background: #fde68a;
  }
  #toast {
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
    max-width: 480px;
  }
  #toast.show {
    opacity: 1;
    transform: translateY(0);
  }
  .file-sync-banner {
    background: #ffffff;
    border: 2px dashed #cbd5e1;
    border-radius: 12px;
    padding: 14px 20px;
    margin-bottom: 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    transition: all 0.2s ease;
  }
  .file-sync-banner.dragover {
    border-color: #2563eb;
    background: #eff6ff;
  }
  .file-sync-banner.is-connected {
    border: 1.5px solid #86efac;
    background: #f0fdf4;
  }
  .file-sync-banner.is-direct-server {
    border: 1.5px solid #93c5fd;
    background: #f0f9ff;
  }
  .sync-left {
    display: flex;
    align-items: center;
    gap: 14px;
    flex: 1;
    min-width: 280px;
  }
  .sync-icon {
    font-size: 26px;
    width: 44px;
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #f8fafc;
    border-radius: 10px;
    border: 1px solid #e2e8f0;
    flex-shrink: 0;
  }
  .sync-details {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .sync-title {
    font-size: 14px;
    font-weight: 700;
    color: #1e293b;
  }
  .sync-desc {
    font-size: 12.5px;
    color: #64748b;
    line-height: 1.45;
  }
  .sync-right {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .btn-sync {
    background: #2563eb;
    color: #ffffff;
    border: none;
    padding: 8px 15px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: background 0.15s;
  }
  .btn-sync:hover {
    background: #1d4ed8;
  }
  .btn-sync.btn-export {
    background: #16a34a;
  }
  .btn-sync.btn-export:hover {
    background: #15803d;
  }
  .btn-sync.btn-jump {
    background: #d97706;
  }
  .btn-sync.btn-jump:hover {
    background: #b45309;
  }
  .empty-state {
    grid-column: 1 / -1;
    text-align: center;
    padding: 48px 20px;
    background: #ffffff;
    border-radius: 12px;
    border: 1px solid var(--border);
    color: var(--text-muted);
    font-size: 14px;
  }
</style>
</head>
<body>

<header>
  <div class="header-left">
    <div>
      <h1>🛒 1688 &amp; 拼多多供应链直检看板</h1>
      <div class="header-desc" id="headerDesc">
        双列图片直观对照 | 支持导入任意规定 15/17 列 Excel 自动可视化并同步已标记状态
      </div>
    </div>
  </div>

  <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
    <div class="filter-tabs">
      <button class="tab-btn active" data-filter="all">全部 (<span id="countAll">0</span>)</button>
      <button class="tab-btn" data-filter="matched">✅ 匹配 (<span id="countMatched">0</span>)</button>
      <button class="tab-btn" data-filter="mismatch">❌ 标记不匹配 (<span id="countMismatch">0</span>)</button>
      <button class="tab-btn" data-filter="unmatched" id="tabUnmatched" style="display:none;">⚪ 未匹配 (<span id="countUnmatched">0</span>)</button>
    </div>
    <input type="text" id="searchInput" class="search-box" placeholder="搜索商品名、规格、SPU或行号...">
  </div>
</header>

<div id="fileSyncBanner" class="file-sync-banner">
  <div class="sync-left">
    <div class="sync-icon" id="syncIcon">📂</div>
    <div class="sync-details">
      <div class="sync-title" id="syncTitle">离线团队协作模式 (支持导入任意标准字段 Excel 接力审核)</div>
      <div class="sync-desc" id="syncDesc">
        请点击右侧按钮选择或将收到的 <code>.xlsx</code> 表格拖入此区域。导入后将<b>自动读取并同步表格中已标记的【匹配 / 不匹配】状态</b>，继续标记后原地自动保存或一键下载！
      </div>
    </div>
  </div>
  <div class="sync-right">
    <button class="btn-sync btn-jump" id="btnJumpLast" onclick="jumpToLastMismatch()" style="display:none;">⏭️ 跳到最后不匹配处</button>
    <button class="btn-sync" id="btnSelectFile" onclick="handleSelectExcelFile()">📂 导入/关联本地 Excel</button>
    <button class="btn-sync btn-export" id="btnExportExcel" onclick="handleExportExcel()" style="display:none;">📥 下载已核对 Excel</button>
  </div>
</div>

<div class="grid" id="productGrid"></div>

<div id="toast"></div>

<script id="embeddedData" type="application/json">__EMBEDDED_JSON__</script>
<script>
  const API_BASE = "http://127.0.0.1:8899";
  const PLACEHOLDER_IMG = "data:image/svg+xml;utf8," + encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'><rect fill='#e2e8f0' width='140' height='140'/><text fill='#64748b' font-size='13' x='50%' y='50%' text-anchor='middle' dominant-baseline='middle'>暂无图片</text></svg>"
  );

  const searchInput = document.getElementById('searchInput');
  const productGrid = document.getElementById('productGrid');
  const tabBtns = document.querySelectorAll('.tab-btn');
  const toast = document.getElementById('toast');

  // 预置内置数据（无 Excel 导入时默认展示，并用于补充缺失主图/销量）
  let EMBEDDED_ITEMS = [];
  try {
    EMBEDDED_ITEMS = JSON.parse(document.getElementById('embeddedData').textContent || '[]');
  } catch (e) {
    console.error("解析内置数据失败:", e);
  }

  // 构建多维索引用于为导入表格智能补全供货商主图或销量
  const EMBEDDED_BY_SKU = new Map();
  const EMBEDDED_BY_SPU = new Map();
  const EMBEDDED_BY_URL = new Map();
  const EMBEDDED_BY_NAME = new Map();
  EMBEDDED_ITEMS.forEach(it => {
    if (it.skuId) EMBEDDED_BY_SKU.set(String(it.skuId).trim(), it);
    if (it.spuId) EMBEDDED_BY_SPU.set(String(it.spuId).trim(), it);
    if (it.supplierUrl) EMBEDDED_BY_URL.set(String(it.supplierUrl).trim(), it);
    if (it.storeName) EMBEDDED_BY_NAME.set(String(it.storeName).trim(), it);
  });

  const DEFAULT_FILE_NAME = __DEFAULT_FILE_NAME__;
  let currentItems = [];
  let itemMapByRow = new Map();
  let currentFilter = 'all';
  let isBackendConnected = false;
  let localFileHandle = null;
  let localWorkbook = null;
  let localFileName = "";
  let activeSheetName = "";
  let activeStatusColIdx = 13; // 默认第 14 列 (N 列: 是否匹配)，导入时按表头动态识别
  let isExcelLoaded = false;
  let lastMismatchRow = null;
  let toastTimer = null;

  function escapeHtml(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showToast(msg) {
    toast.innerText = msg;
    toast.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.classList.remove('show');
    }, 3200);
  }

  function isHttpUrl(val) {
    return typeof val === 'string' && /^https?:\/\//i.test(val.trim());
  }

  function parseNumber(val, fallback = 0) {
    if (val === null || val === undefined || val === '') return fallback;
    if (typeof val === 'number') return Number.isFinite(val) ? val : fallback;
    const cleaned = String(val).replace(/[¥￥,\s]/g, '');
    const num = parseFloat(cleaned);
    return Number.isFinite(num) ? num : fallback;
  }

  function getCellRawValue(ws, r, c) {
    if (c < 0) return '';
    const addr = XLSX.utils.encode_cell({ r, c });
    const cell = ws[addr];
    if (!cell) return '';
    if (cell.v !== undefined && cell.v !== null && cell.v !== '') return cell.v;
    if (cell.w !== undefined && cell.w !== null && cell.w !== '') return cell.w;
    return '';
  }

  function getCellText(ws, r, c) {
    const v = getCellRawValue(ws, r, c);
    return v === null || v === undefined ? '' : String(v).trim();
  }

  // 根据表头行自动探测各规定字段所在列索引，兼容标准 15 列及扩展表
  function detectColumns(ws, range) {
    const headerRow = range.s.r;
    const headers = [];
    for (let c = range.s.c; c <= range.e.c; c++) {
      headers[c] = getCellText(ws, headerRow, c).replace(/\s+/g, '');
    }

    const findCol = (patterns, fallback) => {
      for (const pat of patterns) {
        const idx = headers.findIndex(h => h && pat.test(h));
        if (idx >= 0) return idx;
      }
      return fallback;
    };

    const spuCol = findCol([/^SPUID$/i, /SPU/i], 0);
    const skuCol = findCol([/^SKUID$/i, /SKU/i], 1);
    const assigneeCol = findCol([/^分配人$/], 2);
    const nameCol = findCol([/^商品名称$/, /品名|商品名/], 3);
    const specCol = findCol([/^规格名称$/, /门店规格|^规格$/], 4);
    const retailCol = findCol([/^当前原价$/, /原价|售价|零售价/], 5);
    const storePicCol = findCol([/^主图链接$/, /门店主图|主图/], 6);
    const supplierUrlCol = findCol([/^供货商品链接$/, /供货链接|货源链接/], 7);
    const supplierSpecCol = findCol([/^供货规格$/, /采购规格/], 8);
    const checkoutUrlCol = findCol([/^结算链接$/, /下单链接/], 9);
    const ratioCol = findCol([/^下单比例$/, /比例|倍率/], 10);
    const groupPriceCol = findCol([/^采购价$/, /实付价|拿货价/], 11);
    const unitPriceCol = findCol([/^单位采购价$/, /到手单价|单位成本|单价/], 12);
    const statusCol = findCol([/^是否匹配$/, /匹配状态|审核状态/], 13);
    const moqCol = findCol([/^起购数$/, /起订量|起批量/], -1);
    const orderMultipleCol = findCol([/^下单倍数$/, /拍下倍数|倍数/], -1);

    // 供货商主图列：优先精确匹配表头，避免把“sku问题”误识别为图片列
    let supplierPicCol = findCol([/^供货商主图$/, /供货主图|货源主图|供货商.*图/], -1);
    if (supplierPicCol < 0 && range.e.c >= 14) {
      const h14 = headers[14] || '';
      if (!h14 || !/问题|备注|原因/.test(h14)) {
        // 抽样检查前 20 行第 15 列(O列)是否包含 http 链接
        let urlHits = 0;
        const sampleEnd = Math.min(range.e.r, headerRow + 25);
        for (let r = headerRow + 1; r <= sampleEnd; r++) {
          if (isHttpUrl(getCellText(ws, r, 14))) urlHits++;
        }
        if (urlHits > 0) supplierPicCol = 14;
      }
    }

    return {
      headerRow,
      spuCol,
      skuCol,
      assigneeCol,
      nameCol,
      specCol,
      retailCol,
      storePicCol,
      supplierUrlCol,
      supplierSpecCol,
      checkoutUrlCol,
      ratioCol,
      groupPriceCol,
      unitPriceCol,
      statusCol,
      supplierPicCol,
      moqCol,
      orderMultipleCol
    };
  }

  // 解析导入的 Excel 工作簿，将全表所有行（包含最后结尾标记为“不匹配”的行）真实同步为看板数据
  function parseItemsFromWorkbook(wb) {
    const preferredSheet = wb.SheetNames.find(n => n === '门店商品') || wb.SheetNames[0];
    activeSheetName = preferredSheet;
    const ws = wb.Sheets[preferredSheet];
    if (!ws || !ws['!ref']) {
      return { items: [], statusCol: 13 };
    }

    const range = XLSX.utils.decode_range(ws['!ref']);
    const cols = detectColumns(ws, range);
    activeStatusColIdx = cols.statusCol;

    const items = [];
    for (let r = cols.headerRow + 1; r <= range.e.r; r++) {
      const excelRow = r + 1;
      const spuId = getCellText(ws, r, cols.spuCol);
      const skuId = getCellText(ws, r, cols.skuCol);
      const storeName = getCellText(ws, r, cols.nameCol);
      const storeSpec = getCellText(ws, r, cols.specCol);
      const supplierUrl = getCellText(ws, r, cols.supplierUrlCol);
      const rawStatus = getCellText(ws, r, cols.statusCol);

      // 跳过完全空白的行
      if (!storeName && !spuId && !skuId && !supplierUrl && !rawStatus) {
        continue;
      }

      const retailPrice = parseNumber(getCellRawValue(ws, r, cols.retailCol), 0);
      const storePic = getCellText(ws, r, cols.storePicCol);
      const supplierTitle = getCellText(ws, r, cols.supplierSpecCol);
      const checkoutRaw = getCellText(ws, r, cols.checkoutUrlCol);
      const ratioRaw = parseNumber(getCellRawValue(ws, r, cols.ratioCol), 1);
      const ratio = ratioRaw > 0 ? ratioRaw : 1;
      const groupPrice = parseNumber(getCellRawValue(ws, r, cols.groupPriceCol), 0);
      let unitPrice = parseNumber(getCellRawValue(ws, r, cols.unitPriceCol), 0);
      if (unitPrice <= 0 && groupPrice > 0 && ratio > 0) {
        unitPrice = Math.round((groupPrice / ratio) * 100) / 100;
      }

      const hasSupplierUrl = isHttpUrl(supplierUrl);
      const checkoutUrl = isHttpUrl(checkoutRaw) ? checkoutRaw : (hasSupplierUrl ? supplierUrl : '');

      // 从内置元数据缓存中尝试补全缺失的供货商主图 / 销量
      const cached =
        (skuId && EMBEDDED_BY_SKU.get(skuId)) ||
        (spuId && EMBEDDED_BY_SPU.get(spuId)) ||
        (hasSupplierUrl && EMBEDDED_BY_URL.get(supplierUrl)) ||
        (storeName && EMBEDDED_BY_NAME.get(storeName)) ||
        null;

      let supplierPic = '';
      if (cols.supplierPicCol >= 0) {
        const p = getCellText(ws, r, cols.supplierPicCol);
        if (isHttpUrl(p)) supplierPic = p;
      }
      if (!supplierPic && cols.assigneeCol >= 0) {
        const maybePic = getCellText(ws, r, cols.assigneeCol);
        if (isHttpUrl(maybePic) && /\.(jpg|jpeg|png|webp|gif)|alicdn|pddpic|meituan/i.test(maybePic)) {
          supplierPic = maybePic;
        }
      }
      if (!supplierPic && cached && cached.supplierPic) {
        supplierPic = cached.supplierPic;
      }

      let platform = '未识别';
      if (/1688\.com/i.test(supplierUrl) || /\[1688\]/.test(supplierUrl)) platform = '1688';
      else if (/yangkeduo\.com|pinduoduo\.com/i.test(supplierUrl) || /\[拼多多\]/.test(supplierUrl)) platform = '拼多多';
      else if (cached && cached.platform) platform = cached.platform;

      // 核心状态分类：完全尊重导入 Excel 第 N 列（是否匹配）的真实值
      let matchStatus = 'UNMATCHED';
      let originalMatchLabel = '匹配';
      if (rawStatus === '不匹配' || /^❌?\s*不匹配/.test(rawStatus)) {
        matchStatus = 'MISMATCH';
      } else if (
        rawStatus === '未匹配' ||
        rawStatus === '待重新寻源' ||
        rawStatus === '组合商品' ||
        rawStatus === '生鲜蔬果本地采购'
      ) {
        matchStatus = 'UNMATCHED';
        originalMatchLabel = rawStatus;
      } else if (rawStatus) {
        // 如：匹配、已翻新1、已核可采购、已核同款(毛利<50%)、已核同款(售价为0) 等
        matchStatus = 'MATCH';
        originalMatchLabel = rawStatus;
      } else if (hasSupplierUrl) {
        // N 列为空但已有供货链接时，作为待核对匹配项展示
        matchStatus = 'MATCH';
      } else {
        matchStatus = 'UNMATCHED';
        originalMatchLabel = '未匹配';
      }

      const rawMoq = cols.moqCol >= 0 ? parseNumber(getCellRawValue(ws, r, cols.moqCol), 0) : 0;
      const rawMult = cols.orderMultipleCol >= 0 ? parseNumber(getCellRawValue(ws, r, cols.orderMultipleCol), 0) : 0;

      items.push({
        row: excelRow,
        spuId,
        skuId,
        storeName: storeName || `未命名商品 (Row #${excelRow})`,
        storeSpec,
        storePic: isHttpUrl(storePic) ? storePic : (cached ? cached.storePic : ''),
        retailPrice,
        platform,
        supplierPic,
        supplierTitle: supplierTitle || (!hasSupplierUrl ? supplierUrl : ''),
        supplierUrl: hasSupplierUrl ? supplierUrl : '',
        unmatchedReason: !hasSupplierUrl ? supplierUrl : '',
        checkoutUrl,
        ratio,
        groupPrice,
        unitPrice,
        sales: cached ? (cached.sales || 0) : 0,
        moq: rawMoq > 0 ? Math.round(rawMoq) : (cached ? (cached.moq || null) : null),
        orderMultiple: rawMult > 0 ? Math.round(rawMult) : (cached ? (cached.orderMultiple || null) : null),
        matchStatus,
        wasUnmatched: matchStatus === 'UNMATCHED',
        originalMatchLabel,
        rawStatus
      });
    }

    return { items, statusCol: cols.statusCol };
  }

  function buildCardElement(it) {
    const margin = it.retailPrice > 0 && it.unitPrice > 0
      ? ((it.retailPrice - it.unitPrice) / it.retailPrice) * 100
      : null;
    const marginClass = (margin !== null && margin >= 50) ? 'margin-good' : 'margin-low';
    const marginText = margin !== null ? `${margin.toFixed(1)}%` : '--';

    const sales = Number(it.sales || 0);
    const salesStr = sales > 0
      ? (sales < 10000 ? ` (销量: ${sales} 件)` : ` (销量: ${(sales / 10000).toFixed(1)} 万件)`)
      : '';
    const platformClass = it.platform === '1688'
      ? 'platform-1688'
      : (it.platform === '拼多多' ? 'platform-pdd' : 'platform-other');

    const isMismatch = it.matchStatus === 'MISMATCH';
    const isUnmatched = it.matchStatus === 'UNMATCHED';
    const cardClass = isMismatch
      ? 'card is-mismatch'
      : (isUnmatched ? 'card is-unmatched' : 'card');

    const badgeClass = isMismatch
      ? 'status-badge status-mismatch'
      : (isUnmatched ? 'status-badge status-unmatched' : 'status-badge status-matched');
    const badgeText = isMismatch
      ? '❌ 不匹配'
      : (isUnmatched ? `⚪ ${it.rawStatus || '未匹配'}` : `✅ ${it.originalMatchLabel && it.originalMatchLabel !== '匹配' ? it.originalMatchLabel : '匹配中'}`);

    const btnClass = isMismatch ? 'btn-audit btn-restore-match' : 'btn-audit btn-mark-mismatch';
    const btnText = isMismatch ? '⚠️ 标记错误 (点击恢复)' : '❌ 匹配错误';

    const card = document.createElement('div');
    card.className = cardClass;
    card.id = `card-${it.row}`;
    card.setAttribute('data-row', String(it.row));
    card.setAttribute('data-status', it.matchStatus);
    card.setAttribute('data-title', `${it.storeName} ${it.storeSpec} ${it.supplierTitle} ${it.spuId || ''} ${it.skuId || ''} ${it.row}`.toLowerCase());

    const linkHtml = it.checkoutUrl
      ? `<a href="${escapeHtml(it.checkoutUrl)}" target="_blank" rel="noopener noreferrer" class="link-btn">直达链接 ↗</a>`
      : '';
    const actionBtnHtml = !isUnmatched
      ? `<button class="${btnClass}" id="btn-toggle-${it.row}" onclick="toggleMatchStatus(${it.row})">${btnText}</button>`
      : `<button class="btn-audit btn-mark-mismatch" id="btn-toggle-${it.row}" onclick="toggleMatchStatus(${it.row})">❌ 标为不匹配</button>`;

    const moqTag = (it.platform === '1688' && (it.moq || it.orderMultiple))
      ? ` | 起购${escapeHtml(it.moq || 1)}·倍数${escapeHtml(it.orderMultiple || 1)}`
      : '';
    const supSpecLine = isUnmatched && !it.groupPrice
      ? escapeHtml(it.unmatchedReason || '暂无合规货源')
      : `${escapeHtml(it.ratio)}倍包装 | 采购¥${Number(it.groupPrice || 0).toFixed(2)}${moqTag}`;
    const supPriceLine = isUnmatched && !it.unitPrice
      ? '暂无采购价'
      : `到手单价: ¥${Number(it.unitPrice || 0).toFixed(2)}`;

    card.innerHTML = `
      <div class="card-header">
        <div class="header-tags">
          <span class="row-num">Row #${it.row}</span>
          <span class="platform-tag ${platformClass}">${escapeHtml(it.platform)}${escapeHtml(salesStr)}</span>
        </div>
        <div>
          <span class="${badgeClass}" id="status-badge-${it.row}">${escapeHtml(badgeText)}</span>
        </div>
      </div>

      <div class="compare-row">
        <div class="side">
          <span class="side-title">门店在售商品</span>
          <img class="product-img" src="${escapeHtml(it.storePic || PLACEHOLDER_IMG)}" loading="lazy" alt="门店主图" onerror="this.onerror=null;this.src='${PLACEHOLDER_IMG}'">
          <div class="item-name" title="${escapeHtml(it.storeName)}">${escapeHtml(it.storeName)}</div>
          <div class="item-spec">${escapeHtml(it.storeSpec || '--')}</div>
          <div class="item-price price-store">原价: ¥${Number(it.retailPrice || 0).toFixed(2)}</div>
        </div>

        <div class="side">
          <span class="side-title">匹配供货商货源</span>
          <img class="product-img" src="${escapeHtml(it.supplierPic || PLACEHOLDER_IMG)}" loading="lazy" alt="供货商主图" onerror="this.onerror=null;this.src='${PLACEHOLDER_IMG}'">
          <div class="item-name" title="${escapeHtml(it.supplierTitle)}">${escapeHtml(it.supplierTitle || (isUnmatched ? '未找到合规货源' : '--'))}</div>
          <div class="item-spec">${supSpecLine}</div>
          <div class="item-price price-sup">${supPriceLine}</div>
        </div>
      </div>

      <div class="card-footer">
        <div>
          毛利率: <span class="margin-badge ${marginClass}">${marginText}</span>
        </div>
        <div class="footer-actions">
          ${linkHtml}
          ${actionBtnHtml}
        </div>
      </div>
    `;
    return card;
  }

  function renderItems(items) {
    currentItems = items;
    itemMapByRow = new Map();
    productGrid.innerHTML = '';

    if (!items || items.length === 0) {
      productGrid.innerHTML = '<div class="empty-state">当前表格中没有可展示的商品记录，请检查 Excel 表头是否符合规定字段。</div>';
      updateCounts();
      return;
    }

    const frag = document.createDocumentFragment();
    items.forEach(it => {
      itemMapByRow.set(it.row, it);
      frag.appendChild(buildCardElement(it));
    });
    productGrid.appendChild(frag);

    updateCounts();
    applyFilters();
  }

  function refreshLastMismatchJumpButton() {
    let lastRow = null;
    currentItems.forEach(it => {
      if (it.matchStatus === 'MISMATCH') {
        lastRow = it.row;
      }
    });
    lastMismatchRow = lastRow;
    const btnJump = document.getElementById('btnJumpLast');
    if (lastRow !== null) {
      btnJump.style.display = 'inline-flex';
      btnJump.innerText = `⏭️ 跳到最后不匹配 (Row #${lastRow})`;
    } else {
      btnJump.style.display = 'none';
    }
  }

  function jumpToLastMismatch() {
    if (lastMismatchRow === null) {
      showToast('当前表格中暂无已标记为【不匹配】的商品');
      return;
    }
    // 如果当前过滤 Tab 隐藏了不匹配项，自动切回“全部”
    if (currentFilter === 'matched' || currentFilter === 'unmatched') {
      currentFilter = 'all';
      tabBtns.forEach(b => b.classList.toggle('active', b.getAttribute('data-filter') === 'all'));
      applyFilters();
    }
    if (searchInput.value.trim()) {
      searchInput.value = '';
      applyFilters();
    }
    const el = document.getElementById(`card-${lastMismatchRow}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('flash-highlight');
      setTimeout(() => el.classList.remove('flash-highlight'), 1800);
      showToast(`已定位到最后一条标记【不匹配】的商品：Row #${lastMismatchRow}，可接着往下核对！`);
    }
  }

  function updateCounts() {
    let matched = 0;
    let mismatch = 0;
    let unmatched = 0;
    currentItems.forEach(it => {
      if (it.matchStatus === 'MISMATCH') mismatch++;
      else if (it.matchStatus === 'UNMATCHED') unmatched++;
      else matched++;
    });
    const reviewableTotal = matched + mismatch;

    document.getElementById('countAll').innerText = reviewableTotal;
    document.getElementById('countMatched').innerText = matched;
    document.getElementById('countMismatch').innerText = mismatch;
    document.getElementById('countUnmatched').innerText = unmatched;

    const tabUnmatched = document.getElementById('tabUnmatched');
    tabUnmatched.style.display = unmatched > 0 ? 'inline-block' : 'none';

    const targetName = localFileName || DEFAULT_FILE_NAME;
    document.title = `供应链比价可视化直检看板 (${reviewableTotal} 项 | 不匹配 ${mismatch})`;
    document.getElementById('headerDesc').innerHTML =
      `双列图片直观对照 | 可核对 <strong>${reviewableTotal}</strong> 项（匹配 <strong>${matched}</strong> / 不匹配 <strong>${mismatch}</strong>${unmatched > 0 ? ` / 未匹配 ${unmatched}` : ''}） | 变更实时同步至 <code>${escapeHtml(targetName)}</code> 第 ${activeStatusColIdx + 1} 列`;

    refreshLastMismatchJumpButton();
  }

  function applyFilters() {
    const q = searchInput.value.toLowerCase().trim();
    const cardEls = productGrid.querySelectorAll('.card');
    cardEls.forEach(card => {
      const txt = card.getAttribute('data-title') || '';
      const status = card.getAttribute('data-status');

      const matchSearch = !q || txt.includes(q);
      let matchTab = true;
      if (currentFilter === 'all') matchTab = (status !== 'UNMATCHED');
      else if (currentFilter === 'matched') matchTab = (status === 'MATCH');
      else if (currentFilter === 'mismatch') matchTab = (status === 'MISMATCH');
      else if (currentFilter === 'unmatched') matchTab = (status === 'UNMATCHED');

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

  // 1. 检查是否在作者本机开发环境（若已手动导入本地 Excel，则优先使用本地 Excel 模式）
  async function checkBackendStatus() {
    try {
      const resp = await fetch(`${API_BASE}/api/status`, { signal: AbortSignal.timeout(800) });
      if (resp.ok && !isExcelLoaded) {
        isBackendConnected = true;
        const banner = document.getElementById('fileSyncBanner');
        banner.className = 'file-sync-banner is-direct-server';
        document.getElementById('syncIcon').innerText = '⚡';
        document.getElementById('syncTitle').innerText = '已连接本机后台服务 (极速直写模式)';
        document.getElementById('syncDesc').innerHTML = '检测到本机 <code>127.0.0.1:8899</code> 在线，点击标记将直接通过底层脚本极速回写本地 Excel；也可以点击右侧导入任意其他 <code>.xlsx</code> 文件进行离线核对。';
        return true;
      }
    } catch {}
    isBackendConnected = false;
    return false;
  }

  // 2. 选择本地 Excel 文件进行双向关联（支持 Chrome / Edge 原生 File System Access API）
  async function handleSelectExcelFile() {
    if (typeof XLSX === 'undefined') {
      showToast('Excel 解析引擎正在加载，请稍候 1 秒或检查网络连接后重试');
      return;
    }
    if ('showOpenFilePicker' in window) {
      try {
        const [handle] = await window.showOpenFilePicker({
          types: [{
            description: 'Excel 工作簿 (*.xlsx, *.xls)',
            accept: {
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
              'application/vnd.ms-excel': ['.xls']
            }
          }],
          multiple: false
        });
        localFileHandle = handle;
        const file = await handle.getFile();
        await loadWorkbookFromFile(file, true);
        return;
      } catch (err) {
        if (err.name === 'AbortError') return;
        console.warn("showOpenFilePicker 失败，降级为普通文件选择器:", err);
      }
    }

    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.xlsx,.xls';
    input.onchange = async (e) => {
      const file = e.target.files[0];
      if (file) {
        localFileHandle = null;
        await loadWorkbookFromFile(file, false);
      }
    };
    input.click();
  }

  // 核心修复 1：导入 Excel 后以 Excel 为唯一权威真相源，全量解析并把表格中所有已标记状态（包括结尾的不匹配）同步到 HTML！
  async function loadWorkbookFromFile(file, canDirectWrite) {
    if (typeof XLSX === 'undefined') {
      showToast('Excel 解析库尚未加载完成，请稍后重试');
      return;
    }
    localFileName = file.name;
    const arrayBuffer = await file.arrayBuffer();
    localWorkbook = XLSX.read(arrayBuffer, { type: 'array', cellStyles: true });
    isExcelLoaded = true;
    isBackendConnected = false; // 已明确导入本地 Excel 时，完全以该 Excel 为准，避免误写本机默认表

    // 从导入的 Excel 读取真实行数据与 N 列状态，彻底重建看板（绝不再反方向把 HTML 默认值覆盖进 Excel！）
    const { items } = parseItemsFromWorkbook(localWorkbook);

    // 若表里全部都是不匹配（例如 2700个已核对但未匹配商品.xlsx），留在 "全部" Tab 可直接一眼看到全部不匹配卡片
    currentFilter = 'all';
    tabBtns.forEach(b => b.classList.toggle('active', b.getAttribute('data-filter') === 'all'));
    searchInput.value = '';

    renderItems(items);

    const matchedCnt = items.filter(x => x.matchStatus === 'MATCH').length;
    const mismatchCnt = items.filter(x => x.matchStatus === 'MISMATCH').length;
    const unmatchedCnt = items.filter(x => x.matchStatus === 'UNMATCHED').length;

    const banner = document.getElementById('fileSyncBanner');
    banner.className = 'file-sync-banner is-connected';
    document.getElementById('syncIcon').innerText = '🟢';
    document.getElementById('syncTitle').innerText = `已成功导入并同步: ${localFileName}`;

    const syncSummary = `已同步表格状态：<b>匹配 ${matchedCnt} 条</b> / <b>不匹配 ${mismatchCnt} 条</b>${unmatchedCnt > 0 ? ` / 未匹配 ${unmatchedCnt} 条` : ''}${lastMismatchRow ? `（最后不匹配位置：<b>Row #${lastMismatchRow}</b>）` : ''}。`;
    if (canDirectWrite) {
      document.getElementById('syncDesc').innerHTML = `${syncSummary}<br><b>原生无感写盘已开启</b>：后续每一次点击【❌ 匹配错误 / 恢复匹配】，都将精准原地保存至 <code>${escapeHtml(localFileName)}</code>！`;
    } else {
      document.getElementById('syncDesc').innerHTML = `${syncSummary}<br><b>内存已精准关联</b>：继续核对完成后，点击右侧【📥 下载已核对 Excel】即可导出最新表格。`;
    }
    document.getElementById('btnSelectFile').innerText = '🔄 更换文件';
    document.getElementById('btnExportExcel').style.display = 'inline-flex';
    showToast(`已导入 ${localFileName}：同步 ${matchedCnt} 条匹配、${mismatchCnt} 条不匹配！`);
  }

  // 安全更新工作表单元格，并自动扩展 !ref 范围，确保末尾行变更绝不丢失
  function setWorksheetCellString(ws, r, c, text) {
    const cellAddr = XLSX.utils.encode_cell({ r, c });
    const existing = ws[cellAddr];
    if (existing && typeof existing === 'object') {
      ws[cellAddr] = { ...existing, t: 's', v: text, w: text };
      delete ws[cellAddr].f;
    } else {
      ws[cellAddr] = { t: 's', v: text };
    }
    if (ws['!ref']) {
      const range = XLSX.utils.decode_range(ws['!ref']);
      let changed = false;
      if (r < range.s.r) { range.s.r = r; changed = true; }
      if (r > range.e.r) { range.e.r = r; changed = true; }
      if (c < range.s.c) { range.s.c = c; changed = true; }
      if (c > range.e.c) { range.e.c = c; changed = true; }
      if (changed) ws['!ref'] = XLSX.utils.encode_range(range);
    }
  }

  // 原地写回本地 Excel（按当前导入表格的真实行号和状态列索引）
  async function writeMatchStatusToExcel(rowNum, nextStatus, restoreLabel) {
    const text = (nextStatus === 'MISMATCH') ? '不匹配' : (restoreLabel || '匹配');
    if (localWorkbook) {
      const sheetName = activeSheetName || localWorkbook.SheetNames[0];
      const ws = localWorkbook.Sheets[sheetName];
      setWorksheetCellString(ws, rowNum - 1, activeStatusColIdx, text);

      if (localFileHandle) {
        try {
          const newBuf = XLSX.write(localWorkbook, { bookType: 'xlsx', type: 'array' });
          const writable = await localFileHandle.createWritable();
          await writable.write(newBuf);
          await writable.close();
          return { ok: true, directWritten: true, text };
        } catch (err) {
          console.warn("原地写入失败，降级为内存同步:", err);
        }
      }
      return { ok: true, memoryUpdated: true, text };
    }
    return { ok: false, text };
  }

  // 核心修复 2：彻底规范导出文件名，杜绝重复拼接 .xlsx 或重复拼接 _已核对
  function buildExportFileName(rawName) {
    let base = String(rawName || DEFAULT_FILE_NAME || 'procurement').trim();
    // 1. 剥离末尾所有重复/大小写/带空格的 Excel 扩展名（.xlsx / .xls / .xlsm）
    base = base.replace(/(\s*\.(xlsx|xls|xlsm))+$/i, '').trim();
    // 2. 清理夹在序号 "(1)" 或 "_已核对" 之前的残留 ".xlsx"（例如 "2743.xlsx (1)" 或 "2743.xlsx_已核对"）
    base = base.replace(/\.(xlsx|xls|xlsm)(?=(\s*\(\d+\)|\s*_已核对|$))/gi, '').trim();
    // 3. 去重末尾重复的 "_已核对"
    base = base.replace(/(_已核对)+$/g, '').trim();
    if (!base) base = '2743';
    // 4. 如果文件名本身已含"已核对"，不再重复追加 "_已核对"；最终严格且仅带一个 ".xlsx"
    const stem = base.includes('已核对') ? base : `${base}_已核对`;
    return `${stem}.xlsx`;
  }

  // 一键下载已核对 Excel（使用标准 XLSX MIME 类型，避免浏览器/系统误追加第二个 .xlsx）
  function handleExportExcel() {
    if (!localWorkbook) {
      showToast("请先点击上方导入/关联本地 Excel 文件！");
      return;
    }
    const outName = buildExportFileName(localFileName);
    const wbout = XLSX.write(localWorkbook, { bookType: 'xlsx', type: 'array' });
    const blob = new Blob([wbout], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = outName;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 1500);
    showToast(`已成功下载 ${outName}！`);
  }

  // 拖拽文件关联支持
  function setupDragAndDrop() {
    const banner = document.getElementById('fileSyncBanner');
    ['dragenter', 'dragover'].forEach(name => {
      window.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        banner.classList.add('dragover');
      });
    });
    ['dragleave', 'drop'].forEach(name => {
      window.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        banner.classList.remove('dragover');
      });
    });
    window.addEventListener('drop', async (e) => {
      const dt = e.dataTransfer;
      if (!dt || !dt.files || dt.files.length === 0) return;
      const file = dt.files[0];
      if (!/\.(xlsx|xls)$/i.test(file.name)) {
        showToast('请拖入 .xlsx 或 .xls 格式的 Excel 文件！');
        return;
      }
      if (dt.items && dt.items[0] && dt.items[0].getAsFileSystemHandle) {
        try {
          const handle = await dt.items[0].getAsFileSystemHandle();
          if (handle && handle.kind === 'file') {
            localFileHandle = handle;
            await loadWorkbookFromFile(file, true);
            return;
          }
        } catch {}
      }
      localFileHandle = null;
      await loadWorkbookFromFile(file, false);
    });
  }

  // 仅在未导入外部 Excel 时，恢复内置预览数据的 localStorage 离线标记
  function restoreEmbeddedLocalMarks(items) {
    items.forEach(it => {
      try {
        const saved = localStorage.getItem('sourcing_audit_embedded_row_' + it.row);
        if (saved === 'MATCH' || saved === 'MISMATCH') {
          it.matchStatus = saved;
        }
      } catch {}
    });
  }

  function setCardStatusUI(row, status) {
    const it = itemMapByRow.get(row);
    const card = document.getElementById('card-' + row);
    const badge = document.getElementById('status-badge-' + row);
    const btn = document.getElementById('btn-toggle-' + row);
    if (!card || !it) return;

    it.matchStatus = status;
    card.setAttribute('data-status', status);
    card.classList.remove('is-mismatch', 'is-unmatched');

    if (status === 'MISMATCH') {
      card.classList.add('is-mismatch');
      badge.className = 'status-badge status-mismatch';
      badge.innerText = '❌ 不匹配';
      btn.className = 'btn-audit btn-restore-match';
      btn.innerText = '⚠️ 标记错误 (点击恢复)';
    } else if (status === 'UNMATCHED') {
      card.classList.add('is-unmatched');
      badge.className = 'status-badge status-unmatched';
      badge.innerText = `⚪ ${it.originalMatchLabel || '未匹配'}`;
      btn.className = 'btn-audit btn-mark-mismatch';
      btn.innerText = '❌ 标为不匹配';
    } else {
      const label = it.originalMatchLabel && it.originalMatchLabel !== '匹配' ? it.originalMatchLabel : '匹配中';
      badge.className = 'status-badge status-matched';
      badge.innerText = `✅ ${label}`;
      btn.className = 'btn-audit btn-mark-mismatch';
      btn.innerText = '❌ 匹配错误';
    }
  }

  // 核心：点击切换匹配状态（就地更新样式不跳屏，方便误点立即撤回）
  async function toggleMatchStatus(row) {
    const it = itemMapByRow.get(row);
    if (!it) return;

    const curStatus = it.matchStatus || 'MATCH';
    const nextStatus = (curStatus === 'MISMATCH')
      ? (it.wasUnmatched ? 'UNMATCHED' : 'MATCH')
      : 'MISMATCH';
    const restoreLabel = it.originalMatchLabel || (it.wasUnmatched ? '未匹配' : '匹配');

    // 乐观 UI 更新
    setCardStatusUI(row, nextStatus);
    updateCounts();

    // 若当前处于未导入 Excel 的内置预览模式，保存到独立 key
    if (!isExcelLoaded) {
      try {
        localStorage.setItem('sourcing_audit_embedded_row_' + row, nextStatus);
      } catch {}
    }

    // A. 如果未导入外部 Excel 且连接了本机后台服务，直接发送 API
    if (!isExcelLoaded && isBackendConnected) {
      try {
        const resp = await fetch(`${API_BASE}/api/toggle-match?row=${row}&status=${nextStatus}`);
        const data = await resp.json();
        if (data.ok) {
          showToast(`Row #${row} 已同步写入本机后台表格第 14 列 (N列【${data.text}】)!`);
          return;
        }
      } catch {
        isBackendConnected = false;
      }
    }

    // B. 离线/跨电脑协作模式：通过 SheetJS 按真实行号精准写回当前导入的本地 Excel
    const res = await writeMatchStatusToExcel(row, nextStatus, restoreLabel);
    if (res.directWritten) {
      showToast(`Row #${row} 状态已更新为【${res.text}】，已原地自动保存至本地 ${localFileName}！`);
    } else if (res.memoryUpdated) {
      showToast(`Row #${row} 状态已更新为【${res.text}】！完成后点击上方【📥 下载已核对 Excel】。`);
    } else {
      showToast(`Row #${row} 已标记为【${nextStatus === 'MISMATCH' ? '不匹配' : restoreLabel}】！请先点击上方导入本地 Excel 以同步保存。`);
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    const initialItems = EMBEDDED_ITEMS.map(it => ({ ...it }));
    restoreEmbeddedLocalMarks(initialItems);
    renderItems(initialItems);
    checkBackendStatus();
    setupDragAndDrop();
  });
</script>

</body>
</html>
"""


def _index_pdd_hero_images(dirs_spec: str) -> tuple[dict[tuple[int, str], str], dict[str, str]]:
    """Index local PDD hero images (R{row}_*_{gid}_hero.jpg) by (row, gid) and gid."""
    by_rg: dict[tuple[int, str], str] = {}
    by_g: dict[str, str] = {}
    if not dirs_spec:
        return by_rg, by_g
    expanded_dirs: list[str] = []
    for part in dirs_spec.split(","):
        part = part.strip()
        if not part:
            continue
        hits = sorted(glob.glob(part))
        expanded_dirs.extend(hits if hits else [part])
    for d in expanded_dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith("_hero.jpg"):
                continue
            m = re.match(r"R(\d+)_[a-zA-Z0-9]+_(\d{6,20})_hero\.jpg$", fn)
            full = os.path.join(d, fn)
            if m:
                by_rg[(int(m.group(1)), m.group(2))] = full
                by_g[m.group(2)] = full
            else:
                m2 = re.search(r"(\d{8,20})_hero\.jpg$", fn)
                if m2:
                    by_g[m2.group(1)] = full
    return by_rg, by_g


def _img_to_data_uri(img_path: str, max_px: int = 210, quality: int = 72) -> str:
    if not img_path or not os.path.isfile(img_path):
        return ""
    try:
        if Image is not None:
            im = Image.open(img_path).convert("RGB")
            im.thumbnail((max_px, max_px))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        else:
            b64 = base64.b64encode(Path(img_path).read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


def _parse_float(val, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace("¥", "").replace("￥", "").replace(",", "").strip())
    except Exception:
        return default


def load_items_from_excel(excel_path: str, sheet_name: str, pdd_img_dirs: str = "", max_row: int = 0) -> list[dict]:
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for --excel mode (pip install openpyxl)")
    by_rg, by_g = _index_pdd_hero_images(pdd_img_dirs)
    wb = openpyxl.load_workbook(excel_path, data_only=False)
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
    has_moq_cols = (
        str(ws.cell(1, 16).value or "").strip() == "起购数"
        and str(ws.cell(1, 17).value or "").strip() == "下单倍数"
    )
    items: list[dict] = []
    limit = min(ws.max_row, max_row) if max_row and max_row > 0 else ws.max_row

    for r in range(2, limit + 1):
        spu_id = str(ws.cell(r, 1).value or "").strip()
        sku_id = str(ws.cell(r, 2).value or "").strip()
        store_name = str(ws.cell(r, 4).value or "").strip()
        store_spec = str(ws.cell(r, 5).value or "").strip()
        supplier_url = str(ws.cell(r, 8).value or "").strip()
        raw_status = str(ws.cell(r, 14).value or "").strip()
        if not store_name and not spu_id and not sku_id and not supplier_url and not raw_status:
            continue

        retail_p = round(_parse_float(ws.cell(r, 6).value, 0.0), 2)
        store_pic = str(ws.cell(r, 7).value or "").strip()
        supplier_title = str(ws.cell(r, 9).value or "").strip()
        checkout_raw = str(ws.cell(r, 10).value or "").strip()
        ratio_raw = _parse_float(ws.cell(r, 11).value, 1.0)
        ratio = ratio_raw if ratio_raw > 0 else 1.0
        if ratio == int(ratio):
            ratio = int(ratio)
        group_p = round(_parse_float(ws.cell(r, 12).value, 0.0), 2)
        unit_cell = ws.cell(r, 13).value
        if isinstance(unit_cell, (int, float)):
            unit_p = round(float(unit_cell), 2)
        elif group_p > 0 and ratio > 0:
            unit_p = round(group_p / float(ratio), 2)
        else:
            unit_p = 0.0

        has_url = supplier_url.startswith("http")
        checkout_url = checkout_raw if checkout_raw.startswith("http") else (supplier_url if has_url else "")

        if "1688.com" in supplier_url or "[1688]" in supplier_url:
            platform = "1688"
        elif "yangkeduo.com" in supplier_url or "pinduoduo.com" in supplier_url or "[拼多多]" in supplier_url:
            platform = "拼多多"
        else:
            platform = "未识别"

        # Supplier hero photo: Col O CDN URL first, then local PDD hero base64 fallback
        o_pic = str(ws.cell(r, 15).value or "").strip()
        supplier_pic = o_pic if o_pic.startswith("http") else ""
        if not supplier_pic and platform == "拼多多" and has_url:
            m_gid = re.search(r"goods_id=(\d{6,20})", supplier_url)
            if m_gid:
                gid = m_gid.group(1)
                hero_p = by_rg.get((r, gid)) or by_g.get(gid) or ""
                if hero_p:
                    supplier_pic = _img_to_data_uri(hero_p)

        if raw_status == "不匹配" or re.match(r"^❌?\s*不匹配", raw_status):
            match_status = "MISMATCH"
            orig_label = "匹配"
        elif raw_status in ("未匹配", "待重新寻源", "组合商品", "生鲜蔬果本地采购"):
            match_status = "UNMATCHED"
            orig_label = raw_status
        elif raw_status:
            match_status = "MATCH"
            orig_label = raw_status
        elif has_url:
            match_status = "MATCH"
            orig_label = "匹配"
        else:
            match_status = "UNMATCHED"
            orig_label = "未匹配"

        moq_val = None
        order_mult_val = None
        if has_moq_cols and platform == "1688":
            p_raw = ws.cell(r, 16).value
            q_raw = ws.cell(r, 17).value
            try:
                moq_val = int(p_raw) if p_raw not in (None, "") else None
            except (TypeError, ValueError):
                moq_val = None
            try:
                order_mult_val = int(q_raw) if q_raw not in (None, "") else None
            except (TypeError, ValueError):
                order_mult_val = None

        items.append({
            "row": r,
            "spuId": spu_id,
            "skuId": sku_id,
            "storeName": store_name or f"未命名商品 (Row #{r})",
            "storeSpec": store_spec,
            "storePic": store_pic if store_pic.startswith("http") else "",
            "retailPrice": retail_p,
            "platform": platform,
            "supplierPic": supplier_pic,
            "supplierTitle": supplier_title or ("" if has_url else supplier_url),
            "supplierUrl": supplier_url if has_url else "",
            "unmatchedReason": "" if has_url else supplier_url,
            "checkoutUrl": checkout_url,
            "ratio": ratio,
            "groupPrice": group_p,
            "unitPrice": unit_p,
            "sales": 0,
            "moq": moq_val,
            "orderMultiple": order_mult_val,
            "matchStatus": match_status,
            "wasUnmatched": match_status == "UNMATCHED",
            "originalMatchLabel": orig_label,
            "rawStatus": raw_status or ("匹配" if match_status == "MATCH" else "未匹配"),
        })
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="导出本地单文件可视化比对核验看板 (pddauto v3.5)")
    parser.add_argument("--excel", default="", help="权威 15/17 列 Excel 路径（v3.5 首选直读模式，支持 1688 起购数/下单倍数）")
    parser.add_argument("--sheet", default="门店商品", help="Excel 工作表名（默认 门店商品）")
    parser.add_argument("--pdd-img-dirs", default="", help="逗号分隔的拼多多本地实拍头图目录/通配符（自动压缩内嵌）")
    parser.add_argument("--progress", default=PROGRESS_PATH, help="[兼容模式] 旧版比对进度 JSON 路径")
    parser.add_argument("--qnh", default=QNH_PATH, help="[兼容模式] 旧版牵牛花元数据 JSON 路径")
    parser.add_argument("--output", default="", help="输出 HTML 文件路径")
    parser.add_argument("--max-row", type=int, default=0, help="最大收录行号（0 表示全表）")
    args = parser.parse_args()

    default_file_name = "procurement.xlsx"
    matched_items: list[dict] = []

    if args.excel and os.path.isfile(args.excel):
        excel_abs = os.path.abspath(args.excel)
        default_file_name = os.path.basename(excel_abs)
        matched_items = load_items_from_excel(excel_abs, args.sheet, args.pdd_img_dirs, args.max_row)
        out_html = args.output or str(Path(excel_abs).with_name(f"{Path(excel_abs).stem}_直检看板.html"))
    else:
        out_html = args.output or OUTPUT_HTML
        default_file_name = "2743.xlsx"
        max_r = args.max_row if args.max_row > 0 else MAX_TARGET_ROW
        if os.path.isfile(args.progress):
            progress = json.load(open(args.progress, "r", encoding="utf-8"))
            qnh_map = {}
            if os.path.isfile(args.qnh):
                try:
                    for it in json.load(open(args.qnh, "r", encoding="utf-8")):
                        qnh_map[str(it.get("row"))] = it
                except Exception as e:
                    print(f"读取 QNH 数据警告: {e}", file=sys.stderr)

            for k, v in progress.items():
                try:
                    row_num = int(k)
                except Exception:
                    continue
                if row_num > max_r:
                    continue
                if v.get("status") == "MATCHED":
                    q = qnh_map.get(str(k), {})
                    retail_p = extract_retail_price(q, v)
                    unit_p = float(v.get("unit_price") or v.get("landed_unit_price") or 0.0)
                    group_p = float(v.get("group_price") or 0.0)
                    ratio = int(v.get("ratio") or 1)
                    sales = v.get("sales_volume") or 0
                    match_status = "MISMATCH" if str(v.get("match_status") or "MATCH").upper() == "MISMATCH" else "MATCH"
                    matched_items.append({
                        "row": row_num,
                        "spuId": str(q.get("spuId") or v.get("spuId") or ""),
                        "skuId": str(q.get("skuId") or v.get("skuId") or ""),
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
                        "originalMatchLabel": "匹配",
                        "rawStatus": "不匹配" if match_status == "MISMATCH" else "匹配",
                    })
            matched_items.sort(key=lambda x: x["row"])

    embedded_json = json.dumps(matched_items, ensure_ascii=False).replace("</", "<\\/")
    html_content = (
        HTML_HEAD
        .replace("__EMBEDDED_JSON__", embedded_json)
        .replace("__DEFAULT_FILE_NAME__", json.dumps(default_file_name, ensure_ascii=False))
    )

    os.makedirs(os.path.dirname(os.path.abspath(out_html)), exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html_content)

    mismatch_count = sum(1 for x in matched_items if x["matchStatus"] == "MISMATCH")
    unmatched_count = sum(1 for x in matched_items if x["matchStatus"] == "UNMATCHED")
    matched_count = len(matched_items) - mismatch_count - unmatched_count
    with_pic = sum(1 for x in matched_items if x.get("supplierPic"))
    print(f"★ 成功导出同步可视化直检看板至: {out_html}")
    print(f"  - 总记录: {len(matched_items)} 项 (匹配: {matched_count}, 不匹配: {mismatch_count}, 未匹配/免寻源: {unmatched_count})")
    print(f"  - 供货商实图覆盖: {with_pic}/{len(matched_items)} | 文件大小: {os.path.getsize(out_html) / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
