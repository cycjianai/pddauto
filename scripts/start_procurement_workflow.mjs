#!/usr/bin/env node
/**
 * 供应链寻源与比价全流程一键主控脚本 (End-to-End Master Workflow)
 * 
 * 自动化闭环流程：
 * 1. 自动启动/连入常规调试 Chrome (9222 / 9223 / 9224)；
 * 2. 自动打开美团牵牛花商品页与 1688 官网；
 * 3. 智能登录态诊断：若未登录，弹出明确的终端指引；
 * 4. 登录完成后，自动并发抓取全店 SPU 的高清主图与多角度副图（秒级完成）；
 * 5. 自动启动 1688 高销以图搜款引擎（带单标签防爆与 55s 自然冷却自愈）；
 * 6. 实时将比价结果原子增量回填至 Excel 目标工作簿 (F~K 列)。
 */

import fs from "node:fs/promises";
import fsSync from "node:fs";
import { fork } from "node:child_process";
import path from "node:path";
import {
  detectOrLaunchChrome,
  ensureRequiredTabs,
  checkLoginState,
  extractSpusFromQnh
} from "./qnh_spu_extractor.mjs";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const excelPath = process.argv[2] || process.env.EXCEL_PATH || "/Users/cenbusi/Desktop/2743.xlsx";
  const qnhCachePath = process.env.QNH_DETAILS_PATH || "/tmp/qnh_all_details_fixed.json";

  console.log("================================================================================");
  console.log("🚀 启动 1688 & 拼多多供应链全流程自动化寻源工作流");
  console.log(`📁 目标工作簿: ${excelPath}`);
  console.log("================================================================================\n");

  // Step 1: 检查/启动原生调试 Chrome
  console.log("[Phase 1/4] 检查环境与浏览器连接...");
  const cdpUrl = await detectOrLaunchChrome();
  const { qnhTab, aliTab } = await ensureRequiredTabs();

  // Step 2: 登录态检测与引导
  console.log("[Phase 2/4] 检查平台账号登录就绪状态...");
  const loginState = await checkLoginState(qnhTab, aliTab);

  if (!loginState.qnhLoggedIn || !loginState.aliLoggedIn) {
    console.log("\n⚠️ =====================【账号登录指引】=====================");
    if (!loginState.qnhLoggedIn) {
      console.log("❌ 美团牵牛花未登录：");
      console.log("   👉 请在已打开的 Chrome 中进入牵牛花后台并切换到需要比价的门店；");
    } else {
      console.log("✅ 美团牵牛花已就绪");
    }

    if (!loginState.aliLoggedIn) {
      console.log("❌ 1688 采购账号未登录：");
      console.log("   👉 请在已打开的 Chrome 1688 标签页中完成登录；");
    } else {
      console.log("✅ 1688 采购账号已就绪");
    }
    console.log("\n💡 完成上述登录后，重新运行此命令即可自动开始作业！");
    console.log("==============================================================\n");
    process.exit(2);
  }

  console.log("✅ 牵牛花与 1688 登录态均已就绪！\n");

  // Step 3: SPU 主图与多规格详情抓取
  console.log("[Phase 3/4] 检查/同步 SPU 主图与规格库...");
  let needExtract = true;
  if (fsSync.existsSync(qnhCachePath)) {
    try {
      const stat = await fs.stat(qnhCachePath);
      if (stat.size > 10000) {
        const cached = JSON.parse(await fs.readFile(qnhCachePath, "utf8"));
        if (Array.isArray(cached) && cached.length > 0) {
          console.log(`[QNH] 检测到现有 SPU 主图缓存: ${cached.length} 条有效记录，直接复用。`);
          needExtract = false;
        }
      }
    } catch {}
  }

  if (needExtract) {
    console.log("[QNH] 正在从牵牛花后台并发批量抓取全部 SPU 高清主图与副图...");
    const res = await extractSpusFromQnh(excelPath, qnhCachePath);
    if (!res.success) {
      console.error("[QNH] SPU 主图提取未完成，终止执行。");
      process.exit(1);
    }
  }

  // Step 4: 启动 1688 以图搜款与自动比价引擎
  console.log("\n[Phase 4/4] 启动 1688 单标签以图搜款主引擎...");
  const workerScript = path.resolve(new URL("./ali1688_sourcing_worker.mjs", import.meta.url).pathname);
  
  const env = {
    ...process.env,
    CDP_HTTP: cdpUrl,
    QNH_DETAILS_PATH: qnhCachePath,
    EXCEL_PATH: excelPath
  };

  const child = fork(workerScript, [], { env, stdio: "inherit" });

  child.on("exit", (code) => {
    console.log(`\n[Workflow] 寻源引擎运行结束，退出码: ${code}`);
    process.exit(code || 0);
  });
}

main().catch(err => {
  console.error("[Workflow Fatal Error]", err);
  process.exit(1);
});
