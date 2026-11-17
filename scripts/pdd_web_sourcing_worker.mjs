import fs from "node:fs/promises";
import fsSync from "node:fs";
import { execSync } from "node:child_process";
import {
  cleanSkuSpecText,
  computeRatio,
  isSpecCompatible,
  detectKnownBrand,
} from "./pdd_phone_worker_v3.mjs";

const QNH_FIXED_PATH = "/Users/cenbusi/.gemini/antigravity/brain/da210e82-b25c-40ef-abb7-464dde2672c8/scratch/qnh_all_details_fixed.json";
const PROGRESS_PATH = "/tmp/pdd_sourcing_progress.json";
const PROGRESS_BACKUP_PATH = "/Users/cenbusi/.gemini/antigravity/brain/da210e82-b25c-40ef-abb7-464dde2672c8/scratch/pdd_sourcing_progress_live.json";
const FLUSH_SCRIPT_PATH = "/Users/cenbusi/.gemini/antigravity/brain/da210e82-b25c-40ef-abb7-464dde2672c8/scratch/flush_excel.py";
const DASHBOARD_SCRIPT_PATH = "/Users/cenbusi/Desktop/原点项目-S1/.agents/skills/procurement-sourcing/scripts/export_visual_audit_html.py";
const CDP_HTTP = "http://127.0.0.1:9224";

const LIMIT_SPUS = process.env.LIMIT_SPUS ? parseInt(process.env.LIMIT_SPUS, 10) : Infinity;
const TARGET_ROW = process.env.TARGET_ROW ? parseInt(process.env.TARGET_ROW, 10) : null;
const MAX_ROW = 1791; // Strict boundary: Rows 1792~2791 are assigned to others

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (baseMs, spreadMs = 600) => baseMs + Math.floor(Math.random() * spreadMs);

const CORE_NOUNS = [
  "口腔抑菌液", "口腔喷雾", "剃须泡沫", "刮胡泡", "素颜霜", "遮瑕膏", "洗面奶", "沐浴露", "洗发水", "护发素",
  "身体乳", "护手霜", "润唇膏", "口红", "粉底液", "气垫", "散粉", "眉笔", "修眉刀", "眼线笔", "睫毛膏", "卸妆水",
  "穿戴甲", "指甲油", "留香珠", "柔顺剂", "洗衣液", "洗衣凝珠", "洗衣粉", "洗洁精", "油污净", "洁厕灵", "管道疏通剂",
  "消毒液", "漱口水", "牙膏", "牙刷", "牙线棒", "牙线", "棉签", "化妆棉", "湿巾", "抽纸", "卷纸", "手帕纸", "厨房纸",
  "卫生巾", "护垫", "安心裤", "安全套", "避孕套", "润滑液", "退热贴", "创可贴", "创口贴", "碘伏棉签", "酒精棉片",
  "蒸汽眼罩", "眼罩", "耳塞", "口罩", "胎监带", "暖宫贴", "暖宝宝", "足贴", "温湿度计", "温度计", "一次性内裤",
  "内裤", "文胸", "胸贴", "鲨鱼裤", "安全裤", "打底裤", "丝袜", "船袜", "袜子", "一次性拖鞋", "拖鞋", "凉鞋", "鞋垫",
  "一次性雨衣", "雨衣", "雨伞", "发圈", "发夹", "发箍", "数据线", "充电器", "充电头", "有线耳机", "耳机", "转接头",
  "拓展坞", "鼠标垫", "鼠标", "键盘", "U盘", "内存卡", "读卡器", "手机壳", "钢化膜", "手机支架", "自拍杆", "充电宝",
  "纽扣电池", "电池", "插线板", "排插", "灯泡", "台灯", "小夜灯", "手电筒", "小风扇", "电蚊拍", "蚊香液", "蚊香片",
  "杀虫气雾剂", "蟑螂药", "粘鼠板", "除湿袋", "计算器", "剪刀", "美工刀", "指甲刀", "水果刀", "菜刀", "削皮刀",
  "开瓶器", "打火机", "速燃炭", "修正带", "圆珠笔", "中性笔", "铅笔", "马克笔", "荧光笔", "水彩笔", "油画棒",
  "尺子", "橡皮擦", "卷笔刀", "笔袋", "印泥", "文件袋", "文件夹", "长尾夹", "订书机", "双面胶", "透明胶带", "胶带",
  "502胶水", "扎带", "行李箱绑带", "工牌套", "卡套", "粘钩", "挂钩", "自粘窗帘", "窗帘", "松紧带", "地垫", "桌布",
  "垃圾袋", "保鲜膜", "保鲜袋", "密封袋", "一次性纸杯", "一次性杯", "吸管", "一次性筷", "空气炸锅纸", "烘焙纸", "锡纸",
  "洗碗布", "抹布", "百洁布", "钢丝球", "海绵擦", "扫把", "拖把", "垃圾桶", "马桶刷", "衣架", "收纳盒", "收纳袋",
  "压缩袋", "保温杯", "水杯", "脸盆", "水桶", "皂盒", "浴球", "搓澡巾", "浴帽", "梳子", "化妆镜", "剃须刀", "挖耳勺",
  "扑克牌", "麻将", "骰子", "奶茶", "酸奶", "牛奶", "红茶", "绿茶", "冰红茶", "苏打水", "薯片", "瓜子", "海带",
  "鸡爪", "大米", "食用油", "小酥肉粉", "面粉", "切菜板", "纸碗", "餐盘", "黑头铲", "镊子"
];

export function generatePddSearchKeywords(name, spec, brand) {
  const full = `${name} ${spec || ""}`;
  const matchedNoun = CORE_NOUNS.find((n) => full.includes(n));
  const isDigitalStorage = /U盘|优盘|内存卡|TF卡|SD卡|固态硬盘|移动硬盘/i.test(full);
  const measureMatch =
    full.match(/(?<!\d)(\d+)\s*(GB|TB)\b/i) ||
    (isDigitalStorage ? full.match(/(?<!\d)(\d+)\s*G(?![a-zA-Z])/i) : null) ||
    full.match(/(?<!\d)(\d+)\s*(W|瓦)(?![a-zA-Z])/i) ||
    full.match(/(?<![a-zA-Z\d])(\d+(?:\.\d+)?)\s*(ml|mL|g|kg|L)(?![a-zA-Z])/);

  const measureToken = measureMatch
    ? `${measureMatch[1]}${measureMatch[2].toUpperCase() === "G" && isDigitalStorage ? "GB" : measureMatch[2]}`
    : "";

  if (brand && matchedNoun) {
    return [`${brand} ${matchedNoun} ${measureToken}`.replace(/\s+/g, " ").trim()];
  }

  let raw = name
    .replace(/【[^】]*】/g, " ")
    .replace(/（[^）]*）/g, " ")
    .replace(/\([^)]*\)/g, " ")
    .replace(/家有点点|龙猫购|优选好物|优选|无品牌|zxc|nis/gi, " ")
    .replace(/^\s*\d+\s*[个盒袋瓶双件套份条罐听杯卷台对把本盆只张支装]+\s*/g, " ")
    .replace(/[/／+*#_，,、|]+/g, " ")
    .replace(/\d+(?:\.\d+)?\s*(?:ml|mL|g|kg|L|cm|mm)\s*(?:\/[瓶支盒袋套个片条])?/gi, " ");

  const noise = [
    "大容量", "便携小巧", "防震防尘防水", "颜色随机", "颜色可选", "休闲怀旧", "送绳子",
    "多色可选", "厚度可选", "耐磨耐用", "全家可用", "有效控油", "持久防水不脱妆",
    "男女通用", "夏季新款", "高级感", "纯色透明", "天然橡胶胶乳", "外用液体剂型",
    "拍几份发几片", "生日礼物", "学习用品", "开学推荐", "新老包装随机", "持久留香", "清新口气",
  ];
  for (const n of noise) raw = raw.replace(new RegExp(n, "g"), " ");
  raw = raw.replace(/\s+\d*\s*[个盒袋瓶双件套份条罐听杯卷台对把本盆只张支]\s*$/g, " ");
  raw = raw.replace(/\s+/g, " ").trim();

  if (matchedNoun) {
    const rawFirst = raw.split(" ")[0]?.slice(0, 4) || "";
    const prefix = brand || (rawFirst && !rawFirst.includes(matchedNoun) && !matchedNoun.includes(rawFirst) ? rawFirst : "");
    const quals = [];
    for (const q of [
      "男士", "女士", "儿童", "一次性", "不锈钢", "陶瓷", "自粘", "魔术贴", "免打孔",
    ]) {
      if (full.toUpperCase().includes(q.toUpperCase()) && !matchedNoun.includes(q) && !prefix.includes(q)) {
        quals.push(q);
        if (quals.length >= 2) break;
      }
    }
    const dimMatch = full.match(/(?<!\d)(\d{2,3}\s*[*xX×]\s*\d{2,3}\s*cm)/i);
    const dimTok = dimMatch ? dimMatch[1].replace(/\s+/g, "") : "";
    const parts = [prefix, ...quals, matchedNoun, dimTok || measureToken].filter(Boolean);
    return [parts.join(" ").replace(/\s+/g, " ").trim()];
  }

  const tokens = raw.split(" ").filter(Boolean);
  let baseKw = tokens.length >= 2 ? `${tokens[0].slice(0, 6)} ${tokens[1].slice(0, 8)}` : (tokens[0] || name).slice(0, 10);
  if (measureToken && !baseKw.includes(measureToken)) baseKw = `${baseKw} ${measureToken}`;
  return [baseKw.replace(/\s+/g, " ").trim()];
}

export function parsePddSalesCount(salesTip) {
  if (!salesTip) return 0;
  const s = String(salesTip);
  const mWan = s.match(/([0-9.]+)\s*万\s*\+?/);
  if (mWan) return Math.round(parseFloat(mWan[1]) * 10000);
  const mNum = s.match(/(\d+)\s*\+?/);
  if (mNum) return parseInt(mNum[1], 10);
  return 0;
}

export class PersistentCdpSession {
  constructor(wsUrlOrTabId) {
    if (typeof wsUrlOrTabId === "string" && wsUrlOrTabId.startsWith("ws://")) {
      this.wsUrl = wsUrlOrTabId;
      this.tabId = null;
    } else {
      this.tabId = wsUrlOrTabId;
      this.wsUrl = null;
    }
    this.ws = null;
    this.seq = 1;
    this.pending = new Map();
  }

  async connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    if (this.ws) {
      try { this.ws.close(); } catch {}
      this.ws = null;
    }

    const tabs = await (await fetch(`${CDP_HTTP}/json/list`)).json();
    let tab = this.tabId ? tabs.find((t) => t.id === this.tabId) : null;
    if (!tab) {
      tab = tabs.find((t) => t.type === "page" && t.url.includes("yangkeduo.com"));
    }
    if (!tab) {
      tab = tabs.find((t) => t.type === "page" && !t.url.includes("qnh.meituan.com"));
    }
    if (!tab) throw new Error("未找到可用的拼多多 Chrome 标签页");
    this.tabId = tab.id;
    this.wsUrl = tab.webSocketDebuggerUrl;

    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      const onOpen = () => { cleanup(); resolve(); };
      const onErr = (e) => { cleanup(); reject(e); };
      const cleanup = () => {
        this.ws?.removeEventListener("open", onOpen);
        this.ws?.removeEventListener("error", onErr);
      };
      this.ws.addEventListener("open", onOpen);
      this.ws.addEventListener("error", onErr);
    });

    this.ws.addEventListener("message", (ev) => {
      try {
        const msg = JSON.parse(String(ev.data));
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) reject(new Error(JSON.stringify(msg.error)));
          else resolve(msg.result);
        }
      } catch {}
    });

    this.ws.addEventListener("close", () => {
      for (const [id, { reject }] of this.pending.entries()) {
        reject(new Error("WebSocket closed"));
      }
      this.pending.clear();
      this.ws = null;
    });

    this.ws.addEventListener("error", () => {
      for (const [id, { reject }] of this.pending.entries()) {
        reject(new Error("WebSocket error"));
      }
      this.pending.clear();
      this.ws = null;
    });

    try {
      await this.rawSend("Page.enable", {}, 5000);
      await this.rawSend("DOM.enable", {}, 5000);
      await this.rawSend("Runtime.enable", {}, 5000);
    } catch {}
  }

  rawSend(method, params = {}, timeoutMs = 25000) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        return reject(new Error("WebSocket not open"));
      }
      const id = this.seq++;
      const timer = setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          try { this.ws?.close(); } catch {}
          this.ws = null;
          reject(new Error(`CDP timeout: ${method}`));
        }
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (val) => {
          clearTimeout(timer);
          resolve(val);
        },
        reject: (err) => {
          clearTimeout(timer);
          reject(err);
        },
      });
      try {
        this.ws.send(JSON.stringify({ id, method, params }));
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(err);
      }
    });
  }

  async send(method, params = {}, timeoutMs = 25000) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      await this.connect();
    }
    try {
      return await this.rawSend(method, params, timeoutMs);
    } catch (e) {
      if (e.message.includes("CDP timeout") || e.message.includes("closed") || e.message.includes("not open")) {
        console.warn(`[CDP Auto-Recover] ${method} interrupted (${e.message}), reconnecting CDP...`);
        await this.connect();
        return await this.rawSend(method, params, timeoutMs);
      }
      throw e;
    }
  }

  async evalJs(expression, userGesture = false) {
    const res = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
      userGesture,
    }, 20000);
    if (res?.exceptionDetails) {
      console.error("[evalJs Exception]", res.exceptionDetails.text, res.exceptionDetails.exception?.description);
    }
    return res?.result?.value;
  }

  close() {
    try {
      this.ws?.close();
    } catch {}
    this.ws = null;
  }
}

function flushToExcel() {
  try {
    const out = execSync(`python3 "${FLUSH_SCRIPT_PATH}"`, { encoding: "utf8", timeout: 40000 });
    console.log(out.trim());
    try {
      const dbOut = execSync(`python3 "${DASHBOARD_SCRIPT_PATH}"`, { encoding: "utf8", timeout: 30000 });
      console.log(dbOut.trim().split("\n")[0]);
    } catch {}
  } catch (e) {
    console.error("[Excel] Flush error:", e.message);
  }
}

async function searchPdd(pageSession, query) {
  const url = `https://mobile.yangkeduo.com/search_result.html?search_key=${encodeURIComponent(query)}&sort_type=_sales`;
  await pageSession.send("Page.navigate", { url });
  await sleep(jitter(2000, 500));

  const res = await pageSession.evalJs(`(() => {
    const list = window.rawData?.stores?.store?.data?.ssrListData?.list || [];
    return list.slice(0, 15).map(it => ({
      goodsID: String(it.goodsID || it.goods_id || ''),
      goodsName: String(it.goodsName || it.goods_name || ''),
      priceInfo: it.priceInfo,
      salesTip: it.salesTip,
      imgUrl: it.imgUrl || it.hd_thumb_url || ''
    }));
  })()`);

  return Array.isArray(res) ? res : [];
}

async function inspectPddGoodsDetail(pageSession, goodsId) {
  const url = `https://mobile.yangkeduo.com/goods.html?goods_id=${goodsId}`;
  await pageSession.send("Page.navigate", { url });
  await sleep(jitter(1800, 500));

  const res = await pageSession.evalJs(`(() => {
    const g = window.rawData?.store?.initDataObj?.goods || {};
    return {
      goods_id: String(g.goodsID || g.goods_id || '${goodsId}'),
      goods_name: String(g.goodsName || g.goods_name || ''),
      min_group_price: g.minGroupPrice,
      side_sales_tip: g.sideSalesTip,
      skus: (g.skus || []).map(s => ({
        sku_id: String(s.skuId || s.sku_id || ''),
        specs: (s.specs || []).map(sp => sp.spec_value).join(';') || s.spec || '默认规格',
        group_price: s.groupPrice || s.group_price,
        quantity: Number(s.quantity ?? 999)
      }))
    };
  })()`);

  return res || null;
}

function classifyPddUnmatchedReason(leadItem, bestSeenPrice, hasCompatibleSpec) {
  const name = leadItem.excelName || "";
  const spec = leadItem.excelSpec || "";
  if (!hasCompatibleSpec) {
    return "规格装量不匹配";
  }
  if (bestSeenPrice !== null) {
    return "成本超标(毛利<50%)";
  }
  return "搜无同款在售货源";
}

async function main() {
  const rawItems = JSON.parse(await fs.readFile(QNH_FIXED_PATH, "utf8"));
  const byRow = new Map();
  for (const it of rawItems) {
    const r = Number(it.row);
    if (r >= 49 && r <= MAX_ROW && !byRow.has(r)) byRow.set(r, it);
  }

  let progress = {};
  try {
    progress = JSON.parse(await fs.readFile(PROGRESS_PATH, "utf8"));
  } catch {}

  // Filter ONLY unmatched items in Row 49 ~ 1791
  const unmatchedRows = [];
  for (const [r, it] of byRow.entries()) {
    const st = progress[String(r)]?.status;
    if (st !== "MATCHED") {
      unmatchedRows.push(it);
    }
  }

  console.log(`[PDD Sourcing Engine] Total Unmatched Items to recheck on PDD: ${unmatchedRows.length}`);

  // Group by SPU
  const spuGroups = [];
  const spuMap = new Map();
  for (const it of unmatchedRows) {
    const key = it.spuId ? String(it.spuId) : `ROW_${it.row}`;
    if (!spuMap.has(key)) {
      const grp = { spuId: key, rows: [] };
      spuMap.set(key, grp);
      spuGroups.push(grp);
    }
    spuMap.get(key).rows.push(it);
  }
  console.log(`[PDD Sourcing Engine] Total SPUs queued for PDD: ${spuGroups.length}`);

  const tabs = await (await fetch(`${CDP_HTTP}/json/list`)).json();
  const tab = tabs.find((t) => t.type === "page" && t.url.includes("yangkeduo.com"));
  if (!tab) throw new Error("未找到已登录的拼多多 Chrome 标签页");

  const pageSession = new PersistentCdpSession(tab.id);
  await pageSession.connect();

  let processedSpus = 0;
  let newMatches = 0;

  try {
    for (let gIdx = 0; gIdx < spuGroups.length; gIdx++) {
      if (processedSpus >= LIMIT_SPUS) break;

      const grp = spuGroups[gIdx];
      if (TARGET_ROW && !grp.rows.some((r) => r.row === TARGET_ROW)) continue;

      const pendingRows = grp.rows.filter((r) => {
        const st = progress[String(r.row)]?.status;
        return st !== "MATCHED";
      });
      if (pendingRows.length === 0) continue;

      processedSpus++;
      const lead = pendingRows[0];
      const brand = !/适用|兼容/.test(lead.excelName || "") ? detectKnownBrand(lead.excelName) : null;
      const kws = generatePddSearchKeywords(lead.excelName, lead.excelSpec, brand);

      console.log(`\n==================================================`);
      console.log(`[PDD SPU ${gIdx + 1}/${spuGroups.length}] Rows [${pendingRows.map((r) => r.row).join(",")}] | ${lead.excelName}`);
      for (const r of pendingRows) {
        const rt = Number(r.suggestPrice || r.basicPrice || 0);
        console.log(`  - Row ${r.row} (${r.excelSpec}): 原价 ¥${rt} | 半价红线 <= ¥${(rt * 0.5).toFixed(2)}`);
      }

      let matchedAny = false;
      let bestSeenPrice = null;
      let hasCompatibleSpec = false;

      for (const kw of kws) {
        if (pendingRows.every((r) => progress[String(r.row)]?.status === "MATCHED")) break;

        console.log(`  [PDD 搜索] "${kw}" (按销量排序)`);
        const cands = await searchPdd(pageSession, kw);
        console.log(`    搜索到候选商品数: ${cands.length}`);
        if (cands.length === 0) continue;

        // Filter and inspect top candidates (up to 4)
        for (const cand of cands.slice(0, 4)) {
          const remRows = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
          if (remRows.length === 0) break;

          const sales = parsePddSalesCount(cand.salesTip);
          // Filter ghost listings < 50 units sold
          if (sales < 50) continue;

          console.log(`    [候选研判] ${cand.goodsID} | ${cand.goodsName.slice(0, 32)} | ${cand.salesTip} | 标价: ¥${cand.priceInfo}`);
          const detail = await inspectPddGoodsDetail(pageSession, cand.goodsID);
          if (!detail || !Array.isArray(detail.skus) || detail.skus.length === 0) continue;

          for (const rowItem of remRows) {
            const rowKey = String(rowItem.row);
            const retail = Number(rowItem.suggestPrice || rowItem.basicPrice || 0);
            if (retail <= 0) continue;
            const maxUnitPrice = parseFloat((retail * 0.5).toFixed(2));

            const validSkus = [];
            for (const s of detail.skus) {
              if (s.quantity < 10) continue;
              const formattedSpec = cleanSkuSpecText(s.specs);
              const compat = isSpecCompatible(rowItem.excelName, rowItem.excelSpec, detail.goods_name, formattedSpec);
              if (!compat) continue;

              hasCompatibleSpec = true;
              const ratio = computeRatio(rowItem.excelName, rowItem.excelSpec, formattedSpec, detail.goods_name);
              const groupPrice = parseFloat(s.group_price);
              if (isNaN(groupPrice) || groupPrice <= 0) continue;

              const unitPrice = parseFloat((groupPrice / ratio).toFixed(2));
              if (bestSeenPrice === null || unitPrice < bestSeenPrice) {
                bestSeenPrice = unitPrice;
              }

              if (unitPrice <= maxUnitPrice) {
                validSkus.push({
                  skuId: s.sku_id,
                  formattedSpec,
                  groupPrice,
                  unitPrice,
                  ratio,
                  stock: s.quantity,
                });
              }
            }

            if (validSkus.length > 0) {
              validSkus.sort((a, b) => a.unitPrice - b.unitPrice);
              const best = validSkus[0];
              progress[rowKey] = {
                row: rowItem.row,
                spuId: rowItem.spuId,
                skuId: rowItem.skuId,
                platform: "拼多多",
                match_method: "拼多多关键词搜款",
                goods_id: cand.goodsID,
                goods_url: `https://mobile.yangkeduo.com/goods.html?goods_id=${cand.goodsID}`,
                sku_id: best.skuId,
                sku_specs: best.formattedSpec,
                checkout_url: `https://mobile.yangkeduo.com/order_checkout.html?goods_id=${cand.goodsID}&sku_id=${best.skuId}&goods_number=1`,
                ratio: best.ratio,
                group_price: best.groupPrice,
                unit_price: best.unitPrice,
                landed_unit_price: best.unitPrice,
                moq: 1,
                free_ship: true,
                stock: best.stock,
                sales_volume: sales,
                retail_price: retail,
                main_pic: cand.imgUrl,
                coupon_checked: true,
                status: "MATCHED",
              };
              matchedAny = true;
              newMatches++;
              console.log(`    ★ [拼多多] Row ${rowKey} 匹配成功! 销量=${sales} | ${cand.goodsID} | 规格="${best.formattedSpec}" | 比例=${best.ratio} | 单价=¥${best.unitPrice} (<=¥${maxUnitPrice}, 原价¥${retail})`);
            }
          }
        }
      }

      // If still unmatched after PDD, update reason to PDD
      for (const r of pendingRows) {
        const rk = String(r.row);
        if (progress[rk]?.status !== "MATCHED") {
          const reason = classifyPddUnmatchedReason(r, bestSeenPrice, hasCompatibleSpec);
          progress[rk] = {
            row: r.row,
            spuId: r.spuId,
            skuId: r.skuId,
            platform: "拼多多",
            retail_price: Number(r.suggestPrice || r.basicPrice || 0),
            status: "UNMATCHED_PDD",
            unmatched_reason: reason,
          };
          console.log(`    [未命中归因] Row ${r.row}: [拼多多] ${reason}`);
        }
      }

      const serialized = JSON.stringify(progress, null, 2);
      await fs.writeFile(PROGRESS_PATH, serialized, "utf8");
      await fs.writeFile(PROGRESS_BACKUP_PATH, serialized, "utf8");

      if (newMatches > 0 && newMatches % 8 === 0) {
        flushToExcel();
      }

      await sleep(jitter(1200, 400));
    }

    flushToExcel();
    console.log(`\n==================================================`);
    console.log(`★ [PDD Sourcing Engine] 完成全量未命中 SPU 检索！新增匹配项: ${newMatches}`);
    console.log(`==================================================`);
  } finally {
    pageSession.close();
  }
}

import { pathToFileURL } from "node:url";
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    console.error("[PDD Sourcing Engine] Error:", err.message || err);
    flushToExcel();
    process.exit(1);
  });
}
