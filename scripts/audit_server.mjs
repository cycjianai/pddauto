#!/usr/bin/env node
/**
 * 供应链直检看板实时同步交互服务 (Sourcing Audit Server)
 * 端口: 8899 (支持 CORS 跨域)
 * 功能:
 *   1. 接收前端卡片【❌ 匹配错误 / ✅ 恢复匹配】点击请求。
 *   2. 原子修改 /tmp/pdd_sourcing_progress.json 中的 match_status。
 *   3. 毫秒级增量回写 /Users/cenbusi/Desktop/2743.xlsx 的第 14 列 (N 列【是否匹配】)。
 *   4. 支持直接提供 Web 看板服务与静态 HTML 刷新。
 */

import http from "node:http";
import url from "node:url";
import fs from "node:fs";
import path from "node:path";
import { execFileSync, execSync } from "node:child_process";

const PORT = process.env.AUDIT_PORT ? parseInt(process.env.AUDIT_PORT, 10) : 8899;
const PROGRESS_PATH = "/tmp/pdd_sourcing_progress.json";

function getExcelPath() {
  if (fs.existsSync("/Users/cenbusi/Desktop/当前工作/2743.xlsx")) {
    return "/Users/cenbusi/Desktop/当前工作/2743.xlsx";
  }
  return "/Users/cenbusi/Desktop/2743.xlsx";
}

function getHtmlPath() {
  if (fs.existsSync("/Users/cenbusi/Desktop/当前工作/sourcing_audit_dashboard.html")) {
    return "/Users/cenbusi/Desktop/当前工作/sourcing_audit_dashboard.html";
  }
  return "/Users/cenbusi/Desktop/sourcing_audit_dashboard.html";
}

const SCRIPT_DIR = path.dirname(new URL(import.meta.url).pathname);
const EXPORT_SCRIPT = path.join(SCRIPT_DIR, "export_visual_audit_html.py");

// 单行原子更新 Excel 第 14 列 (N列)
function updateExcelCell(rowNum, matchStatus) {
  const excelPath = getExcelPath();
  const text = matchStatus === "MISMATCH" ? "不匹配" : "匹配";
  const pyCode = `
import openpyxl, sys
try:
    wb = openpyxl.load_workbook("${excelPath}")
    ws = wb.active
    ws.cell(row=${rowNum}, column=14, value="${text}")
    wb.save("${excelPath}")
    print("OK")
except Exception as e:
    print(f"ERR: {e}", file=sys.stderr)
    sys.exit(1)
`;
  try {
    const out = execFileSync("python3", ["-c", pyCode], { encoding: "utf8", timeout: 15000 });
    return out.trim() === "OK";
  } catch (e) {
    console.error(`[AuditServer] 更新 Excel Row ${rowNum} 失败:`, e.message);
    return false;
  }
}

// 刷新 HTML 看板
function regenerateHtml() {
  try {
    if (fs.existsSync(EXPORT_SCRIPT)) {
      execSync(`python3 "${EXPORT_SCRIPT}"`, { timeout: 30000 });
      return true;
    }
  } catch (e) {
    console.error("[AuditServer] 生成 HTML 失败:", e.message);
  }
  return false;
}

const server = http.createServer((req, res) => {
  // CORS 头支持跨域（兼容 file:/// 与 http://127.0.0.1）
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  const parsedUrl = url.parse(req.url, true);
  const pathname = parsedUrl.pathname;

  // 1. 切换匹配状态 API: /api/toggle-match?row=123&status=MISMATCH
  if (pathname === "/api/toggle-match") {
    const row = parseInt(parsedUrl.query.row, 10);
    const status = (parsedUrl.query.status || "").toUpperCase(); // MATCH 或 MISMATCH

    if (!row || (status !== "MATCH" && status !== "MISMATCH")) {
      res.writeHead(400, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ ok: false, error: "Invalid row or status (use MATCH or MISMATCH)" }));
      return;
    }

    try {
      if (fs.existsSync(PROGRESS_PATH)) {
        const raw = fs.readFileSync(PROGRESS_PATH, "utf8");
        const progress = JSON.parse(raw);
        const rowKey = String(row);
        if (progress[rowKey]) {
          progress[rowKey].match_status = status;
          fs.writeFileSync(PROGRESS_PATH, JSON.stringify(progress, null, 2), "utf8");
        }
      }

      // 同步更新 Excel
      const excelOk = updateExcelCell(row, status);

      console.log(`[AuditServer] Row #${row} 状态已更新为: ${status === "MISMATCH" ? "❌ 不匹配" : "✅ 匹配"} (Excel写入: ${excelOk ? "成功" : "失败"})`);

      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({
        ok: true,
        row,
        status,
        text: status === "MISMATCH" ? "不匹配" : "匹配",
        excel_updated: excelOk,
      }));
    } catch (e) {
      res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }

  // 2. 状态统计 API: /api/status
  if (pathname === "/api/status") {
    try {
      let total = 0;
      let mismatch = 0;
      let matched = 0;
      if (fs.existsSync(PROGRESS_PATH)) {
        const progress = JSON.parse(fs.readFileSync(PROGRESS_PATH, "utf8"));
        for (const v of Object.values(progress)) {
          if (v.status === "MATCHED") {
            total++;
            if (v.match_status === "MISMATCH") {
              mismatch++;
            } else {
              matched++;
            }
          }
        }
      }
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ ok: true, total, matched, mismatch }));
    } catch (e) {
      res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }

  // 3. 手动触发刷新看板 API: /api/refresh
  if (pathname === "/api/refresh") {
    const ok = regenerateHtml();
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok, message: ok ? "看板刷新完成" : "刷新失败" }));
    return;
  }

  // 4. 默认主页：直接提供看板页面
  if (pathname === "/" || pathname === "/dashboard") {
    const htmlPath = getHtmlPath();
    if (fs.existsSync(htmlPath)) {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      fs.createReadStream(htmlPath).pipe(res);
      return;
    }
  }

  res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
  res.end("Not Found");
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`====================================================`);
  console.log(`★ 供应链比价核验实时交互服务已启动!`);
  console.log(`  - 本地直达地址: http://127.0.0.1:${PORT}`);
  console.log(`  - API 端点: http://127.0.0.1:${PORT}/api/toggle-match?row={row}&status={MATCH|MISMATCH}`);
  console.log(`  - 同步目标文件: ${getExcelPath()} (第 14 列 N列: 是否匹配)`);
  console.log(`====================================================`);
});
