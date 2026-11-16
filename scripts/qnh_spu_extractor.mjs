#!/usr/bin/env node
/**
 * 牵牛花 SPU 主图与多规格详情自动化抽取引擎 (QNH SPU Extractor)
 * 
 * 核心功能：
 * 1. 自动连接/启动调试 Chrome (端口 9222/9223/9224)；
 * 2. 自动开启牵牛花后台商品页与 1688 首页；
 * 3. 校验登录态；若未登录，给出明确的人工登录引导；
 * 4. 登录就绪后，自动读取目标 Excel 中的 SPU 列表；
 * 5. 在牵牛花页面上下文并发批量调用内部商品接口，秒级抓取全部 SPU 的高清主图、全套副图、规格与零售价；
 * 6. 落盘为结构化 JSON 缓存供后续以图搜款引擎使用。
 */

import fs from "node:fs/promises";
import fsSync from "node:fs";
import { execSync, spawn } from "node:child_process";
import path from "node:path";
import openpyxl from "node:child_process";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let CDP_HTTP = process.env.CDP_HTTP || (process.env.CDP_PORT ? `http://127.0.0.1:${process.env.CDP_PORT}` : "");

export async function detectOrLaunchChrome() {
  if (CDP_HTTP) return CDP_HTTP;

  // 1. 尝试探测已有的活跃端口
  for (const port of [9222, 9223, 9224, 9225]) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(600) });
      if (res.ok) {
        CDP_HTTP = `http://127.0.0.1:${port}`;
        console.log(`[Chrome] 已连入活跃调试端口: ${port}`);
        return CDP_HTTP;
      }
    } catch {}
  }

  // 2. 若均未启动，自动以后台模式启动常规 Google Chrome
  const port = 9222;
  console.log(`[Chrome] 未检测到运行中的调试 Chrome，正在自动启动常规 Google Chrome (端口: ${port})...`);
  const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  if (!fsSync.existsSync(chromePath)) {
    throw new Error(`系统未找到 Google Chrome: ${chromePath}`);
  }

  const userDataDir = `/tmp/chrome_dev_session_${port}`;
  spawn(chromePath, [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${userDataDir}`,
    "https://qnh.meituan.com/home.html#/unifiedGoods/store/spu-list",
    "https://www.1688.com/"
  ], {
    detached: true,
    stdio: "ignore"
  }).unref();

  // 等待 Chrome 启动就绪
  for (let i = 0; i < 20; i++) {
    await sleep(600);
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(600) });
      if (res.ok) {
        CDP_HTTP = `http://127.0.0.1:${port}`;
        console.log(`[Chrome] 成功启动并接入端口: ${port}`);
        return CDP_HTTP;
      }
    } catch {}
  }

  throw new Error(`启动 Chrome 超时，请检查端口 ${port} 是否可用`);
}

export async function ensureRequiredTabs() {
  const cdpUrl = await detectOrLaunchChrome();
  const tabs = await (await fetch(`${cdpUrl}/json/list`)).json();

  let qnhTab = tabs.find(t => t.type === "page" && t.url.includes("qnh.meituan.com"));
  let aliTab = tabs.find(t => t.type === "page" && t.url.includes("1688.com"));

  if (!qnhTab) {
    console.log("[Chrome] 正在打开美团牵牛花商品页...");
    await fetch(`${cdpUrl}/json/new?https://qnh.meituan.com/home.html#/unifiedGoods/store/spu-list`);
    await sleep(1500);
  }

  if (!aliTab) {
    console.log("[Chrome] 正在打开 1688 首页...");
    await fetch(`${cdpUrl}/json/new?https://www.1688.com/`);
    await sleep(1500);
  }

  const updatedTabs = await (await fetch(`${cdpUrl}/json/list`)).json();
  qnhTab = updatedTabs.find(t => t.type === "page" && t.url.includes("qnh.meituan.com"));
  aliTab = updatedTabs.find(t => t.type === "page" && t.url.includes("1688.com"));

  return { qnhTab, aliTab };
}

export async function checkLoginState(qnhTab, aliTab) {
  let qnhLoggedIn = false;
  let aliLoggedIn = false;

  // 1. 检查牵牛花登录态
  if (qnhTab?.webSocketDebuggerUrl) {
    try {
      const ws = new WebSocket(qnhTab.webSocketDebuggerUrl);
      await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
      const testJs = `(() => {
        const u = location.href;
        if (u.includes("login") || u.includes("passport")) return { loggedIn: false };
        const hasUser = Boolean(document.querySelector('.ant-dropdown-link, .header-user, [class*="userInfo"], [class*="header"]'));
        return { loggedIn: hasUser || !u.includes("login") };
      })()`;
      ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: testJs, returnByValue: true } }));
      const res = await new Promise(r => ws.onmessage = ev => r(JSON.parse(ev.data)));
      ws.close();
      qnhLoggedIn = Boolean(res?.result?.result?.value?.loggedIn);
    } catch {}
  }

  // 2. 检查 1688 登录态
  if (aliTab?.webSocketDebuggerUrl) {
    try {
      const ws = new WebSocket(aliTab.webSocketDebuggerUrl);
      await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
      const testJs = `(() => {
        const u = location.href;
        if (u.includes("login.taobao.com") || u.includes("login.1688.com")) return { loggedIn: false };
        const hasAccount = Boolean(document.querySelector('.profile-name, .member-info, .user-name, [class*="userName"]'));
        return { loggedIn: hasAccount || !u.includes("login") };
      })()`;
      ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: testJs, returnByValue: true } }));
      const res = await new Promise(r => ws.onmessage = ev => r(JSON.parse(ev.data)));
      ws.close();
      aliLoggedIn = Boolean(res?.result?.result?.value?.loggedIn);
    } catch {}
  }

  return { qnhLoggedIn, aliLoggedIn };
}

export async function extractSpusFromQnh(excelPath, outputPath = "/tmp/qnh_all_details_fixed.json") {
  const { qnhTab, aliTab } = await ensureRequiredTabs();
  const loginState = await checkLoginState(qnhTab, aliTab);

  if (!loginState.qnhLoggedIn) {
    console.log("\n========================================================");
    console.log("【账号登录引导提示】");
    console.log("检测到美团牵牛花后台尚未完成登录！");
    console.log("👉 请在刚刚打开的 Chrome 窗口中：");
    console.log("   1. 扫码/账号登录牵牛花后台，并进入本次比价的门店；");
    console.log("   2. 确认可正常访问商品列表页面；");
    console.log("   3. 同样在 1688 页面确认已登录采购账号；");
    console.log("登录完成后，请重新运行本命令，系统将自动开始抓取主图与比价！");
    console.log("========================================================\n");
    return { success: false, reason: "WAITING_FOR_LOGIN" };
  }

  console.log(`[QNH] 牵牛花登录状态就绪，开始读取目标表格: ${excelPath}`);

  // 从 Excel 中提取待处理行 SPUID 与 SKUID
  const extractPython = `
import openpyxl, json, sys
wb = openpyxl.load_workbook("${excelPath}", data_only=True)
ws = wb.active
items = []
for r in range(2, ws.max_row + 1):
    spu_val = ws.cell(r, 1).value
    sku_val = ws.cell(r, 2).value
    name_val = ws.cell(r, 4).value
    spec_val = ws.cell(r, 5).value
    if spu_val:
        items.append({
            "row": r,
            "spuId": str(spu_val).strip(),
            "skuId": str(sku_val).strip() if sku_val else "",
            "excelName": str(name_val).strip() if name_val else "",
            "excelSpec": str(spec_val).strip() if spec_val else ""
        })
print(json.dumps(items, ensure_ascii=False))
`;
  const rawItemsJson = execSync(`python3 -c '${extractPython}'`, { encoding: "utf8" });
  const rawItems = JSON.parse(rawItemsJson);
  console.log(`[QNH] 成功从表格读取 ${rawItems.length} 个 SPU 待匹配项`);

  // 提取唯一 SPU 列表
  const uniqueSpuIds = [...new Set(rawItems.map(it => it.spuId).filter(Boolean))];
  console.log(`[QNH] 独立 SPU 数量: ${uniqueSpuIds.length}，准备分批并发调用页面接口抓取主图与副图...`);

  const ws = new WebSocket(qnhTab.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });

  const spuDataMap = new Map();
  const batchSize = 100;

  for (let idx = 0; idx < uniqueSpuIds.length; idx += batchSize) {
    const chunk = uniqueSpuIds.slice(idx, idx + batchSize);
    const chunkJson = JSON.stringify(chunk);

    const evaluateJs = `(async () => {
      try {
        const res = await fetch("/qnh-gw3/api/product/tenant/page-query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            pageNum: 1,
            pageSize: ${chunk.length},
            spuIdList: ${chunkJson}
          })
        });
        return await res.json();
      } catch(e) {
        return { code: -1, msg: String(e) };
      }
    })()`;

    ws.send(JSON.stringify({
      id: idx + 10,
      method: "Runtime.evaluate",
      params: { expression: evaluateJs, awaitPromise: true, returnByValue: true }
    }));

    const response = await new Promise(r => ws.onmessage = ev => r(JSON.parse(ev.data)));
    const apiResult = response?.result?.result?.value;

    if (apiResult?.code === 0 && Array.isArray(apiResult?.data?.list)) {
      for (const spu of apiResult.data.list) {
        const sid = String(spu.spuId);
        const pics = spu.picUrlList || [];
        spuDataMap.set(sid, {
          spuId: sid,
          qnhName: spu.spuName || spu.goodsName || "",
          picUrl: pics[0] || "",
          allPics: pics,
          skus: spu.skus || []
        });
      }
      process.stdout.write(`\r[QNH] 抓取进度: ${Math.min(idx + batchSize, uniqueSpuIds.length)} / ${uniqueSpuIds.length} SPU 已同步`);
    } else {
      console.warn(`\n[QNH] 批次 ${idx} 查询异常: ${apiResult?.msg || '未知错误'}`);
    }
    await sleep(250);
  }
  console.log("");
  ws.close();

  // 合并拼装输出为完整的抓取元数据文件
  const mergedDetails = rawItems.map(it => {
    const qnh = spuDataMap.get(it.spuId) || {};
    const skuObj = (qnh.skus || []).find(s => String(s.skuId) === it.skuId) || (qnh.skus || [])[0] || {};
    return {
      row: it.row,
      spuId: it.spuId,
      skuId: it.skuId,
      excelName: it.excelName,
      excelSpec: it.excelSpec,
      qnhName: qnh.qnhName || it.excelName,
      picUrl: qnh.picUrl || "",
      allPics: qnh.allPics || (qnh.picUrl ? [qnh.picUrl] : []),
      suggestPrice: skuObj.suggestPrice || it.retailPrice || 0,
      basicPrice: skuObj.basicPrice || it.retailPrice || 0,
      upc: (skuObj.upcList && skuObj.upcList[0]) || "",
      specName: skuObj.spec || it.excelSpec || ""
    };
  });

  await fs.writeFile(outputPath, JSON.stringify(mergedDetails, null, 2), "utf8");
  console.log(`[QNH] ★ 全部 SPU 主图与多规格提取完成！共 ${mergedDetails.length} 条记录已存盘至: ${outputPath}`);
  return { success: true, count: mergedDetails.length, outputPath };
}

// CLI 直接执行入口
if (process.argv[1] && process.argv[1].endsWith("qnh_spu_extractor.mjs")) {
  const excelArg = process.argv[2] || "/Users/cenbusi/Desktop/2743.xlsx";
  extractSpusFromQnh(excelArg)
    .then(res => {
      if (!res.success) process.exit(2);
      process.exit(0);
    })
    .catch(err => {
      console.error("[QNH Extractor Fatal]", err.message);
      process.exit(1);
    });
}
