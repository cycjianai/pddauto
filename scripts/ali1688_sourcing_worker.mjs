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
const TMP_IMG_PATH = "/tmp/ali1688_cur_query.jpg";
const CDP_HTTP = "http://127.0.0.1:9224";

const LIMIT_SPUS = process.env.LIMIT_SPUS ? parseInt(process.env.LIMIT_SPUS, 10) : Infinity;
const TARGET_ROW = process.env.TARGET_ROW ? parseInt(process.env.TARGET_ROW, 10) : null;
const MAX_ROW = process.env.MAX_ROW ? parseInt(process.env.MAX_ROW, 10) : 1791; // 最后 1000 个 SKU (1792~2791行) 已分配他人，本任务严格在 1791 截止

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (baseMs, spreadMs = 800) => baseMs + Math.floor(Math.random() * spreadMs);

// Category classifier: returns true if item is Non-Food 百货/电器/美妆/家居/文具/宠物 (run on 1688)
const FOOD_PAT =
  /奶茶|咖啡|饮料|汽水|可乐|雪碧|芬达|果汁|酸奶|乳酸|发酵乳|纯牛奶|鲜牛奶|调制乳|牛奶|豆奶|椰汁|椰奶|凉茶|冰红茶|绿茶|红茶|乌龙茶|茉莉|花茶|矿泉水|纯净水|饮用水|苏打水|气泡水|山泉|啤酒|白酒|黄酒|红酒|葡萄酒|鸡尾酒|果酒|梅酒|饼干|曲奇|威化|薯片|薯条|锅巴|辣条|魔芋|面筋|方便面|拌面|火鸡面|拉面|汤面|鸡面|牛肉面|粉丝|米线|螺蛳粉|酸辣粉|河粉|凉皮|大米|香米|糯米|小米|食用油|花生油|菜籽油|调和油|橄榄油|香油|芝麻油|食盐|酱油|生抽|老抽|陈醋|白醋|米醋|香醋|料酒|蚝油|耗油|豆瓣酱|辣椒酱|甜面酱|番茄酱|沙拉酱|果酱|花生酱|芝麻酱|白砂糖|冰糖|红糖|黑糖|辣椒面|辣椒粉|干碟|蘸料|调味|调料|佐料|香辛料|口香糖|薄荷糖|棒棒糖|软糖|硬糖|奶糖|喜糖|牛轧糖|棉花糖|巧克力|果冻|布丁|龟苓膏|仙草|肉脯|猪肉脯|牛肉干|牛肉粒|鸭脖|鸭翅|鸭掌|鸭锁骨|鸭腿|鸡爪|凤爪|鸡腿|鸡翅|卤蛋|鹌鹑蛋|皮蛋|松花蛋|变蛋|咸鸭蛋|茶叶蛋|火腿肠|香肠|烤肠|热狗|午餐肉|培根|豆干|豆腐干|香干|臭豆腐|兰花豆|蚕豆|青豆|瓜子|花生|开心果|巴旦木|夏威夷果|腰果|核桃|松子|板栗|甘栗|话梅|西梅|乌梅|红杏干|杏干|芒果干|草莓干|葡萄干|红枣|蜜饯|果脯|山楂|果丹皮|海苔|紫菜|即食汤|速食汤|芙蓉汤|蛋花汤|辣白菜|泡菜|榨菜|萝卜干|酸豆角|雪菜|腐乳|燕麦|麦片|八宝粥|银耳|芝麻糊|藕粉|蜂蜜|蛋糕|面包|吐司|蛋黄派|铜锣烧|沙琪玛|麻花|猫耳朵|泡打粉|酵母|淀粉|生粉|面粉|糯米粉|酥肉粉|面包糠|火锅底料|酸菜鱼|烧烤料|孜然|花椒|八角|桂皮|香叶|干辣椒|胡椒|鸡精|味精|浓汤宝|槟榔|康师傅|统一|农夫山泉|怡宝|百岁山|娃哈哈|旺仔|三只松鼠|百草味|良品铺子|卫龙|洽洽|劲仔|海天|李锦记|老干妈|苏伯/;

const NON_FOOD_OVERRIDE =
  /洗面奶|洁面|沐浴|洗发|护发|发膜|染发|发胶|定型|护肤|爽肤水|化妆水|卸妆|精华|乳液|面霜|眼霜|面膜|唇膏|口红|粉底|气垫|散粉|粉饼|修容|高光|眼影|眉笔|眉刀|眼线|睫毛|美甲|指甲|香水|香薰|空气清新|除臭|留香珠|柔顺剂|洗衣|洗洁精|果蔬净|油污净|洁厕|管道疏通|消毒|抑菌液|口腔喷雾|漱口水|牙膏|牙刷|牙线|棉签|化妆棉|湿巾|柔纸巾|抽纸|卷纸|手帕纸|厨房纸|卫生巾|护垫|安心裤|安全套|避孕套|润滑液|私处|清洗器|退热贴|创口贴|创可贴|碘伏|酒精棉|眼罩|耳塞|口罩|胎监带|暖宫贴|暖宝宝|足贴|拔罐|艾灸|温度计|温湿度|血压|血糖|内裤|文胸|胸贴|袜子|丝袜|船袜|拖鞋|凉鞋|鞋垫|鞋刷|鞋油|雨衣|雨伞|帽子|手套|袖套|围巾|发圈|发夹|发箍|皮筋|数据线|充电|耳机|转接头|拓展坞|鼠标|键盘|鼠标垫|U盘|优盘|内存卡|读卡器|手机壳|钢化膜|手机支架|自拍杆|充电宝|电池|纽扣电池|排插|插座|插线板|灯泡|台灯|小夜灯|手电筒|头灯|风扇|电蚊拍|蚊香|驱蚊|杀虫|蟑螂|老鼠贴|樟脑|除湿袋|干燥剂|计算器|剪刀|美工刀|壁纸刀|指甲刀|水果刀|菜刀|削皮刀|开瓶器|打火机|火柴|速燃炭|木炭|蜡烛|修正带|涂改|圆珠笔|中性笔|铅笔|马克笔|荧光笔|水彩笔|油画棒|蜡笔|尺子|橡皮|卷笔刀|笔袋|文具|印台|印泥|文件袋|文件夹|夹子|回形针|订书机|胶带|双面胶|胶水|502|玻璃胶|密封胶|扎带|绑带|打包带|绳|锁|挂钩|粘钩|防撞|地垫|门垫|桌布|纱窗|车贴|静电贴|垃圾袋|保鲜膜|保鲜袋|密封袋|一次性碗|一次性杯|纸杯|塑杯|吸管|筷子|勺子|叉子|牙签|竹签|锡纸|烘焙纸|空气炸锅纸|抹布|洗碗布|百洁布|钢丝球|海绵擦|扫把|拖把|垃圾桶|马桶刷|皮搋子|衣架|晾衣|收纳|整理箱|压缩袋|水杯|保温杯|马克杯|玻璃杯|茶壶|水壶|脸盆|水桶|皂盒|牙刷架|浴球|搓澡|浴帽|梳子|镜子|剃须刀|刮胡刀|镊子|挖耳勺|扑克|麻将|筛子|骰子|桌游|象棋|五子棋|气球|玩具|水枪|泡泡|风筝|跳绳|羽毛球|乒乓球|篮球|足球|口哨|望远镜|抄网|鱼竿|鱼线|鱼钩|猫粮|狗粮|猫砂|猫条|宠物|牵引绳|逗猫|多肉|盆栽|花盆|营养土|肥料|发财纸|金元宝|冥币|红包|对联|福字|灯笼|礼花|蜡烛/;

export function isNonFoodFor1688(item) {
  const txt = `${item.excelName || ""} ${item.qnhName || ""} ${item.excelSpec || ""}`;
  if (NON_FOOD_OVERRIDE.test(txt)) return true;
  if (FOOD_PAT.test(txt)) return false;
  return true;
}

export function format1688Spec(rawSpecAttrs) {
  if (!rawSpecAttrs) return "默认规格";
  const decoded = String(rawSpecAttrs)
    .replace(/&gt;/gi, "；")
    .replace(/&lt;/gi, "<")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/\s*>\s*/g, "；")
    .replace(/；+/g, "；")
    .trim();
  return cleanSkuSpecText(decoded) || "默认规格";
}

export function parseSalesCount(text, rawSales) {
  if (typeof rawSales === "number" && rawSales > 0) return rawSales;
  if (typeof rawSales === "string" && /^\d+$/.test(rawSales)) return parseInt(rawSales, 10);
  const s = String(text || "");
  const mWan = s.match(/([0-9.]+)\s*万\s*\+?\s*(?:件|元|笔)?/);
  if (mWan) return Math.round(parseFloat(mWan[1]) * 10000);
  const mNum = s.match(/(\d+)\s*\+?\s*(?:件|元|笔)/);
  if (mNum) return parseInt(mNum[1], 10);
  return 0;
}

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
  "502胶水", "扎带", "行李箱绑带", "工牌套", "卡套", "粘钩", "挂钩", "自粘窗帘", "窗帘", "松紧带", "德州扑克", "筹码", "地垫", "桌布", "垃圾袋", "保鲜膜", "保鲜袋",
  "密封袋", "一次性纸杯", "一次性杯", "吸管", "一次性筷", "空气炸锅纸", "烘焙纸", "锡纸", "洗碗布", "抹布", "百洁布",
  "钢丝球", "海绵擦", "扫把", "拖把", "垃圾桶", "马桶刷", "衣架", "收纳盒", "收纳袋", "压缩袋", "保温杯", "水杯",
  "脸盆", "水桶", "皂盒", "浴球", "搓澡巾", "浴帽", "梳子", "化妆镜", "剃须刀", "挖耳勺", "扑克牌", "麻将", "骰子",
  "五子棋", "象棋", "气球", "水枪", "泡泡水", "跳绳", "羽毛球", "乒乓球", "猫粮", "狗粮", "猫砂", "猫条", "胸背带", "牵引绳", "遛狗绳", "胸背",
  "逗猫棒", "花盆", "营养土", "红包",
  "玉米片", "薯片", "锅巴", "辣条", "方便面", "火鸡面", "酸辣粉", "螺蛳粉", "粉丝", "米线",
  "纯牛奶", "酸奶", "风味酸奶", "老酸奶", "饮料", "汽水", "苏打水", "乌龙茶", "红茶", "绿茶", "矿泉水", "啤酒",
  "辣椒酱", "辣椒面", "干碟", "火锅底料", "沙拉酱", "番茄酱", "食用油", "酱油", "生抽", "老抽", "陈醋", "白糖", "面粉", "高筋面粉", "小麦粉",
  "面包", "吐司", "蛋糕", "饼干", "蛋黄派", "火腿肠", "香肠", "午餐肉", "鸭脖", "鸡爪", "牛肉干", "瓜子", "花生", "坚果",
  "果冻", "巧克力", "薄荷糖", "口香糖", "奶茶", "芙蓉汤", "即食汤",
];

export function extract1688Keywords(item) {
  const name = item.excelName || item.qnhName || "";
  const spec = item.excelSpec || item.specName || "";
  const full = `${name} ${spec}`;
  const isDigitalStorage = /U盘|优盘|闪存|内存卡|TF卡|SD卡/.test(full);

  const noFreebieFull = full.replace(/[【\[（(][^】\]）)]*(?:送|赠)[^】\]）)]*[】\]）)]/g, " ");
  const brand = detectKnownBrand(name);
  const matchedNoun = CORE_NOUNS.find((n) => noFreebieFull.includes(n));
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
      "男士", "女士", "儿童", "婴儿", "一次性", "EVA", "不锈钢", "亚克力", "硅胶", "纯棉", "冰丝",
      "自粘", "魔术贴", "免打孔", "折叠", "磁吸", "无线", "有线", "Type-C", "苹果",
      "三分", "五分", "七分", "九分", "竖版", "横版", "密码锁",
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

// User-mandated high-sales priority & ghost-listing filter
export function prefilterSearchOffers(offers, pendingRows, maxReturn = 5) {
  if (!Array.isArray(offers) || offers.length === 0) return [];
  const maxRetailHalf = Math.max(
    ...pendingRows.map((r) => Number(r.suggestPrice || r.basicPrice || 0) * 0.5),
    0
  );
  const lead = pendingRows[0];
  const reqBrand = !/适用|兼容/.test(lead.excelName || "") ? detectKnownBrand(lead.excelName) : null;
  const matchedNoun = CORE_NOUNS.find((n) => (lead.excelName || "").includes(n));
  const cleanCore = String(lead.excelName || "")
    .replace(/【[^】]*】|（[^）]*）|\([^)]*\)/g, " ")
    .replace(/家有点点|龙猫购|优选好物|优选|无品牌|官方|正品|通用|家用|学生|便携|新款|宠物|中小型|家庭装|多规格|升级款|防爆冲|防挣脱|耐用|里衬随机/g, " ")
    .replace(/[^\u4e00-\u9fa5a-zA-Z]/g, "");
  const bigrams = [];
  for (let i = 0; i < cleanCore.length - 1; i++) {
    bigrams.push(cleanCore.slice(i, i + 2).toUpperCase());
  }

  const scored = [];
  for (let idx = 0; idx < Math.min(offers.length, 60); idx++) {
    const o = offers[idx];
    const normText = String(o.text || "")
      .replace(/¥\s*(\d+)\s*\.\s*(\d+)/g, "¥$1.$2")
      .replace(/(\d+)\s*\.\s*(\d+)\s*元/g, "$1.$2元");
    if (/补差价|邮费专拍|运费专拍|定金专拍|定制链接勿拍|扩容/.test(normText)) continue;
    if (o.moq && Number(o.moq) > 25) continue;

    // Enforce brand & core bigram/noun if full title is available
    if (o.fullTitle) {
      const upTitle = String(o.fullTitle).toUpperCase();
      if (reqBrand && !upTitle.includes(reqBrand.toUpperCase())) continue;
      if (matchedNoun) {
        let nounPattern = matchedNoun;
        if (/胸背带|背带式牵引绳|胸背/.test(matchedNoun)) nounPattern = "背带|胸背|牵引|狗绳|拉带|遛狗";
        else if (/牵引绳/.test(matchedNoun)) nounPattern = "牵引|狗绳|拉带|遛狗|胸背|背带";
        else if (/洗脸巾|洁面巾/.test(matchedNoun)) nounPattern = "洗脸巾|洁面巾|棉柔巾|擦脸巾";
        if (!new RegExp(nounPattern).test(upTitle)) continue;
      } else if (bigrams.length > 0 && !bigrams.some((bg) => upTitle.includes(bg))) {
        continue;
      }
    }

    const sales = parseSalesCount(normText, o.sales);
    // User mandate: "尽可能的销量要高点，要几万这种，不要找这种几十的，代表没有人买...有可能假货"
    // Strictly filter out low-sales ghost listings (< 50 units sold)
    if (sales < 50) continue;

    const pm = normText.match(/¥\s*(\d+(?:\.\d+)?)/) || normText.match(/(\d+\.\d+)\s*元/);
    const cardPrice = typeof o.cardPrice === "number" && o.cardPrice > 0 ? o.cardPrice : pm ? parseFloat(pm[1]) : null;
    let withinHalf = false;
    if (cardPrice !== null && cardPrice > 0 && maxRetailHalf > 0) {
      const estRatio = Math.max(1, computeRatio(lead.excelName, lead.excelSpec, normText, normText));
      const estUnit = cardPrice / estRatio;
      if (estUnit <= maxRetailHalf) {
        withinHalf = true;
      } else if (estUnit > maxRetailHalf * 1.45 + 1.5) {
        continue;
      }
    }
    scored.push({ ...o, rankIdx: idx, cardPrice, withinHalf, sales });
  }

  // Sorting hierarchy:
  // 1. withinHalf (unit price <= half retail)
  // 2. High Sales Volume (几万 > 几千 > 几百)
  // 3. Free Shipping
  scored.sort((a, b) => {
    if (a.withinHalf !== b.withinHalf) return a.withinHalf ? -1 : 1;
    const bucketA = a.sales >= 10000 ? 3 : a.sales >= 1000 ? 2 : a.sales >= 100 ? 1 : 0;
    const bucketB = b.sales >= 10000 ? 3 : b.sales >= 1000 ? 2 : b.sales >= 100 ? 1 : 0;
    if (bucketA !== bucketB) return bucketB - bucketA;
    if (b.sales !== a.sales && Math.abs(b.sales - a.sales) >= 500) {
      return b.sales - a.sales;
    }
    if (a.isFreeShip !== b.isFreeShip) {
      return Number(b.isFreeShip) - Number(a.isFreeShip);
    }
    return a.rankIdx - b.rankIdx;
  });

  return scored.slice(0, maxReturn);
}

export class PersistentCdpSession {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.seq = 1;
    this.pending = new Map();
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
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
  }

  send(method, params = {}, timeoutMs = 45000) {
    return new Promise((resolve, reject) => {
      const id = this.seq++;
      const timer = setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
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
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evalJs(expression, userGesture = false) {
    const res = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
      userGesture,
    });
    if (res?.exceptionDetails) {
      console.error("[evalJs Exception]", res.exceptionDetails.text, res.exceptionDetails.exception?.description);
    }
    return res?.result?.value;
  }

  close() {
    try {
      this.ws?.close();
    } catch {}
  }
}

async function ensureDefaultDownloadBehavior() {
  const ver = await (await fetch(`${CDP_HTTP}/json/version`)).json();
  const s = new PersistentCdpSession(ver.webSocketDebuggerUrl);
  await s.connect();
  try {
    await s.send("Browser.setDownloadBehavior", { behavior: "default" });
  } finally {
    s.close();
  }
}

function flushToExcel() {
  try {
    const out = execSync(`python3 "${FLUSH_SCRIPT_PATH}"`, { encoding: "utf8", timeout: 40000 });
    console.log(out.trim());
  } catch (e) {
    console.error("[Excel] Flush error:", e.message);
  }
}

export async function pruneExtraTabs(activeTabId) {
  try {
    const tabs = await (await fetch(`${CDP_HTTP}/json/list`)).json();
    for (const t of tabs) {
      if (t.type === "page" && t.id !== activeTabId && !t.url.includes("qnh.meituan.com")) {
        try {
          await fetch(`${CDP_HTTP}/json/close/${t.id}`);
        } catch {}
      }
    }
  } catch {}
}

async function checkRiskOrLoginBlock(pageSession) {
  const st = await pageSession.evalJs(`(() => {
    const u = location.href;
    const t = document.title || '';
    const body = (document.body?.innerText || '').slice(0, 500);
    const visSlider = [...document.querySelectorAll('.nc-container, #baxia-dialog-content, .J_MIDDLEWARE_FRAME_WIDGET, iframe[src*="punish"], iframe[src*="validate"]')].some(el => {
      const r = el.getBoundingClientRect();
      return r.width > 10 && r.height > 10;
    });
    const isLogin = u.includes('login.1688.com') || u.includes('login.taobao.com') || /请登录|扫码登录/.test(t);
    const isPunish = u.includes('sec.1688.com') || u.includes('_____tmd_____/punish') || visSlider || /验证码拦截/.test(t) || /通过验证以确保正常访问|拖动下方滑块|请按照说明拖动滑块/.test(body);
    return { url: u, title: t, isLogin, isPunish };
  })()`);
  return st || { isLogin: false, isPunish: false };
}

// User-discovered auto-recovery: Alibaba TMD rate-limit slider automatically lifts after cooling down and reloading!
async function ensureNoRiskWithAutoCooldown(pageSession) {
  let st = await checkRiskOrLoginBlock(pageSession);
  if (!st.isPunish && !st.isLogin) return true;
  if (st.isLogin) throw new Error(`RISK_OR_LOGIN:${JSON.stringify(st)}`);

  console.log(`[1688 Auto-Cooldown] 检测到频控拦截页面: ${st.title} (${st.url.slice(0, 90)})`);
  for (let attempt = 1; attempt <= 2; attempt++) {
    const waitSec = attempt === 1 ? 55 : 75;
    console.log(`[1688 Auto-Cooldown] 触发自动冷静期 (第 ${attempt}/2 次)，静默等待 ${waitSec} 秒让阿里令牌桶自动恢复...`);
    await sleep(waitSec * 1000);
    console.log(`[1688 Auto-Cooldown] 静默结束，导航回 1688 首页核验是否自动解除...`);
    try {
      await pageSession.send("Page.navigate", { url: "https://www.1688.com/" });
      await sleep(4000);
      st = await checkRiskOrLoginBlock(pageSession);
      if (!st.isPunish && !st.isLogin) {
        console.log(`[1688 Auto-Cooldown] ★ 频控已成功自动解除，恢复全自动运行！`);
        return true;
      }
    } catch (e) {
      console.log(`[1688 Auto-Cooldown] 恢复核验异常: ${e.message}`);
    }
  }

  throw new Error(`RISK_OR_LOGIN:${JSON.stringify(st)}`);
}

async function simulateHumanBrowse(pageSession) {
  try {
    const x = 360 + Math.floor(Math.random() * 380);
    const y = 260 + Math.floor(Math.random() * 260);
    await pageSession.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    await sleep(120 + Math.floor(Math.random() * 180));
    await pageSession.send("Input.dispatchMouseEvent", {
      type: "mouseWheel",
      x,
      y,
      deltaX: 0,
      deltaY: 180 + Math.floor(Math.random() * 220),
    });
  } catch {}
}

async function waitForPageReady(pageSession, checkExpr, minHumanMs = 1500, maxWaitMs = 5500) {
  await sleep(jitter(minHumanMs, 550));
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    try {
      const ok = await pageSession.evalJs(
        `Boolean((${checkExpr}) || document.querySelector('.nc-container, #baxia-dialog-content, iframe[src*="punish"]'))`
      );
      if (ok) return true;
    } catch {}
    await sleep(350);
  }
  return false;
}

let lastImageUploadTimestamp = 0;

// Step 1: 1688 以图搜款 (Image Search) - User Mandated #1 Priority for Non-Food Goods!
// Extract structured offers directly from window.offerList or fallback DOM
async function extractOffersFromImageSearchPage(pageSession) {
  const offers = await pageSession.evalJs(`(() => {
    const out = [];
    const seen = new Set();
    const list = window.offerList || [];
    if (Array.isArray(list) && list.length > 0) {
      for (const o of list) {
        const oid = String(o.offerId || '').trim();
        if (!oid || seen.has(oid)) continue;
        seen.add(oid);
        const fullTitle = String(o.title || o.subject || '').trim();
        const pVal = parseFloat(o.priceInfo?.price || '0');
        const sales = Number(o.saleQuantity || o.bookedCount || o.tradeQuantity || 0);
        const tags = Array.isArray(o.tags) ? o.tags.map(t => t?.text || '').join(' ') : '';
        const isFreeShip = /包邮|免运费/.test(tags) && !/运费\\d/.test(tags);
        const offerUrl = o.offerUrl || o.linkUrl || ('https://detail.1688.com/offer/' + oid + '.html');
        const shopName = String(o.shopName || o.shop?.text || '');
        out.push({
          offerId: oid,
          fullTitle,
          offerUrl,
          cardPrice: pVal > 0 ? pVal : null,
          sales,
          isFreeShip,
          shopName,
          text: fullTitle + (pVal > 0 ? (' ¥' + pVal) : '') + ' ' + sales + '件 ' + (isFreeShip ? '包邮' : '') + ' ' + shopName,
        });
      }
    }
    if (out.length === 0) {
      for (const a of document.querySelectorAll('a[href*="offerId="], a[href*="offer/"]')) {
        const m = a.href.match(/[?&]offerId=(\\d{8,16})/) || a.href.match(/offer\\/(\\d{8,16})\\.html/);
        if (!m || seen.has(m[1])) continue;
        seen.add(m[1]);
        let card = a;
        for (let i = 0; i < 6 && card.parentElement; i++) {
          card = card.parentElement;
          if ((card.innerText || '').length > 40) break;
        }
        const text = (card.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240);
        const isFreeShip = /包邮|免运费/.test(text) && !/运费\\d/.test(text);
        out.push({ offerId: m[1], offerUrl: a.href, text, isFreeShip });
      }
    }
    return out;
  })()`);
  return offers || [];
}

export async function search1688ByImage(pageSession, picUrl, pendingRows) {
  if (!picUrl || !picUrl.startsWith("http")) return [];
  try {
    execSync(`curl -sL --max-time 10 "${picUrl}" -o "${TMP_IMG_PATH}"`);
    const stat = await fs.stat(TMP_IMG_PATH);
    if (stat.size < 800) return [];
    execSync(`sips -s format jpeg "${TMP_IMG_PATH}" --out "${TMP_IMG_PATH}.jpg" >/dev/null 2>&1 && mv "${TMP_IMG_PATH}.jpg" "${TMP_IMG_PATH}"`);
  } catch {
    return [];
  }

  // Preventive rate-limiting cadence: space image searches by at least 15s to avoid tripping Alibaba token bucket
  const elapsed = Date.now() - lastImageUploadTimestamp;
  if (lastImageUploadTimestamp > 0 && elapsed < 15000) {
    const waitMs = 15000 - elapsed;
    console.log(`    [以图搜款频控保护] 距上次上传仅 ${(elapsed / 1000).toFixed(1)}s，平滑等待 ${(waitMs / 1000).toFixed(1)}s 保持安全频控...`);
    await sleep(waitMs);
  }

  await ensureNoRiskWithAutoCooldown(pageSession);

  // Always navigate to www.1688.com for clean, reliable image upload
  const curUrl = await pageSession.evalJs(`location.href`);
  if (!curUrl || !/^https:\/\/(www\.)?1688\.com\/?(\?.*)?$/.test(curUrl)) {
    await pageSession.send("Page.navigate", { url: "https://www.1688.com/" });
    await waitForPageReady(pageSession, `!!document.querySelector('input[type="file"]')`, 1800, 4500);
  }

  await ensureNoRiskWithAutoCooldown(pageSession);

  // Hook window.open so navigation stays in current tab without spawning background tabs
  await pageSession.evalJs(`window.open = (u) => { location.href = u; return window; }; true;`);

  // Use native C++ DOM.setFileInputFiles
  const doc = await pageSession.send("DOM.getDocument", { depth: -1 });
  const q = await pageSession.send("DOM.querySelector", {
    nodeId: doc.root.nodeId,
    selector: 'input[type="file"]',
  });
  if (!q?.nodeId) return [];

  lastImageUploadTimestamp = Date.now();
  await pageSession.send("DOM.setFileInputFiles", {
    nodeId: q.nodeId,
    files: [TMP_IMG_PATH],
  });

  // Wait for popover with search button
  for (let i = 0; i < 10; i++) {
    const hasPop = await pageSession.evalJs(`Boolean(document.querySelector('.imageSearchPopover--f82RkwsD') || document.querySelector('[class*="imageSearchPopover"]'))`);
    if (hasPop) break;
    await sleep(200);
  }

  // Click search button strictly inside popover (never query outside popover to prevent clicking homepage banners)
  const clickRes = await pageSession.evalJs(`(() => {
    const pop = document.querySelector('.imageSearchPopover--f82RkwsD') || document.querySelector('[class*="imageSearchPopover"]');
    if (!pop) return { found: false, error: 'no popover' };
    const btn = pop.querySelector('.actionPrimary--sz2L3jNq') || [...pop.querySelectorAll('button')].find(b => b.innerText && b.innerText.trim() === '搜索');
    if (!btn) return { found: false, error: 'no search button in popover' };
    btn.click();
    return { found: true };
  })()`);

  if (!clickRes?.found) {
    // Fallback: trigger change event on input
    await pageSession.evalJs(`(() => {
      const inp = document.querySelector('input[type="file"]');
      if (inp && inp.files && inp.files.length > 0) inp.dispatchEvent(new Event('change', { bubbles: true }));
    })()`);
  }

  // Wait for navigation to pc-image-search and offer list to load
  await waitForPageReady(
    pageSession,
    `location.href.includes('imageSearch') && (Array.isArray(window.offerList) || document.querySelectorAll('a[href*="offer"]').length > 2)`,
    2200,
    6000
  );

  if (pageSession.tabId) {
    await pruneExtraTabs(pageSession.tabId);
  }

  await ensureNoRiskWithAutoCooldown(pageSession);
  await simulateHumanBrowse(pageSession);

  // 1. Initial/default selected region evaluation
  let offers = await extractOffersFromImageSearchPage(pageSession);
  let qualified = prefilterSearchOffers(offers, pendingRows, 5);
  if (qualified.length > 0) {
    return qualified;
  }

  // 2. 1688 YOLO Auto-Recognition Correction (User requirement: auto-selected box frequently selects the wrong entity, e.g. dog instead of leash!)
  const regionCount = await pageSession.evalJs(`document.querySelectorAll('.cropRegion--gagAdM3S').length`);
  if (regionCount > 1) {
    console.log(`    [以图搜款多主体研判] 默认主体未命中目标品类，检测到页面有 ${regionCount} 个候选识别主体，依次切换重定主体框...`);
    for (let rIdx = 0; rIdx < regionCount; rIdx++) {
      const isAlreadySelected = await pageSession.evalJs(`(() => {
        const regions = document.querySelectorAll('.cropRegion--gagAdM3S');
        return Boolean(regions[${rIdx}]?.className?.includes('selectRegion'));
      })()`);
      if (isAlreadySelected) continue;

      await pageSession.evalJs(`(() => {
        const regions = document.querySelectorAll('.cropRegion--gagAdM3S');
        if (regions[${rIdx}]) regions[${rIdx}].click();
      })()`);
      await sleep(jitter(2000, 500));

      offers = await extractOffersFromImageSearchPage(pageSession);
      qualified = prefilterSearchOffers(offers, pendingRows, 5);
      if (qualified.length > 0) {
        console.log(`    ★ [以图搜款主体重定成功] 切换至主体 #${rIdx + 1} 后精准命中 ${qualified.length} 个符合要求的候选供货商!`);
        return qualified;
      }
    }
  }

  // 3. If all YOLO regions failed or only 1 region existed, activate manual "框选主体"
  const hasKuangxuan = await pageSession.evalJs(`Boolean(document.querySelector('.cutTxt--BegJKt5I'))`);
  if (hasKuangxuan) {
    console.log(`    [以图搜款自适应框选] 触发"框选主体"重定目标中心区域...`);
    try {
      await pageSession.evalJs(`(() => {
        const btn = document.querySelector('.cutTxt--BegJKt5I') || [...document.querySelectorAll('*')].find(el => el.innerText && el.innerText.trim() === '框选主体' && el.children.length === 0);
        if (btn) btn.click();
      })()`);
      await sleep(800);

      const canvasRect = await pageSession.evalJs(`(() => {
        const canvas = document.querySelector('#croper-canvas');
        if (!canvas) return null;
        const r = canvas.getBoundingClientRect();
        return { left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) };
      })()`);

      if (canvasRect && canvasRect.width > 20 && canvasRect.height > 20) {
        const sX = canvasRect.left + Math.round(canvasRect.width * 0.15);
        const sY = canvasRect.top + Math.round(canvasRect.height * 0.15);
        const eX = canvasRect.left + Math.round(canvasRect.width * 0.85);
        const eY = canvasRect.top + Math.round(canvasRect.height * 0.85);

        await pageSession.send("Input.dispatchMouseEvent", { type: "mousePressed", x: sX, y: sY, button: "left", clickCount: 1 });
        await sleep(100);
        await pageSession.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: eX, y: eY });
        await sleep(100);
        await pageSession.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: eX, y: eY, button: "left", clickCount: 1 });
        await sleep(600);

        await pageSession.evalJs(`document.querySelector('#croper-ok-btn')?.click()`);
        await sleep(jitter(2500, 600));

        offers = await extractOffersFromImageSearchPage(pageSession);
        qualified = prefilterSearchOffers(offers, pendingRows, 5);
        if (qualified.length > 0) {
          console.log(`    ★ [以图搜款自适应框选成功] 自定义选框后命中 ${qualified.length} 个候选供货商!`);
          return qualified;
        }
      }
    } catch (e) {
      console.log(`    [以图搜款自适应框选异常] ${e.message}`);
    }
  }

  return qualified;
}

// Step 2: 1688 关键词搜索 (Keyword Search) - Fallback when Image Search yields no match
export async function search1688ByKeyword(pageSession, keyword, pendingRows) {
  await ensureNoRiskWithAutoCooldown(pageSession);

  // Try typing into 1688's native top search bar
  const searchBox = await pageSession.evalJs(`(() => {
    window.open = (u) => { location.href = u; return window; };
    document.querySelectorAll('form').forEach(f => f.setAttribute('target', '_self'));
    document.querySelectorAll('base').forEach(b => b.setAttribute('target', '_self'));
    const inp = document.querySelector('#alisearch-input, input[name="keywords"], input[placeholder*="搜索"], input[type="text"]');
    if (!inp) return null;
    const r = inp.getBoundingClientRect();
    if (r.width < 40 || r.height < 14 || r.top < 0 || r.top > 320) return null;
    const btn = [...document.querySelectorAll('button, div, span, input[type="submit"]')].find(el => {
      const txt = (el.innerText || el.value || '').replace(/\\s+/g, '');
      if (txt !== '搜索' && txt !== '搜全站' && txt !== '搜本旺铺') return false;
      const br = el.getBoundingClientRect();
      return br.width > 20 && br.height > 14 && Math.abs(br.top - r.top) < 60 && txt !== '搜本旺铺';
    });
    const br = btn ? btn.getBoundingClientRect() : null;
    return {
      ix: Math.round(r.left + Math.min(80, r.width / 3)),
      iy: Math.round(r.top + r.height / 2),
      bx: br ? Math.round(br.left + br.width / 2) : null,
      by: br ? Math.round(br.top + br.height / 2) : null,
    };
  })()`);

  const prevUrl = await pageSession.evalJs(`location.href`);
  let submittedNatively = false;

  if (searchBox && searchBox.ix > 0) {
    await pageSession.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: searchBox.ix, y: searchBox.iy });
    await sleep(100);
    await pageSession.send("Input.dispatchMouseEvent", { type: "mousePressed", x: searchBox.ix, y: searchBox.iy, button: "left", clickCount: 1 });
    await sleep(65);
    await pageSession.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: searchBox.ix, y: searchBox.iy, button: "left", clickCount: 1 });
    await sleep(120);

    // Clear existing value and insert new keyword
    await pageSession.evalJs(`(() => {
      const el = document.activeElement;
      if (el && el.tagName === 'INPUT') {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
        if (setter) setter.call(el, '');
        else el.value = '';
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
    })()`);
    await sleep(90);
    await pageSession.send("Input.insertText", { text: keyword });
    await sleep(jitter(350, 200));

    if (searchBox.bx && searchBox.by) {
      await pageSession.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: searchBox.bx, y: searchBox.by });
      await sleep(90);
      await pageSession.send("Input.dispatchMouseEvent", { type: "mousePressed", x: searchBox.bx, y: searchBox.by, button: "left", clickCount: 1 });
      await sleep(75);
      await pageSession.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: searchBox.bx, y: searchBox.by, button: "left", clickCount: 1 });
    } else {
      await pageSession.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
      await sleep(50);
      await pageSession.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    }

    await waitForPageReady(
      pageSession,
      `location.href !== ${JSON.stringify(prevUrl)} && Boolean(window.data?.offerV2?.response?.data?.OFFER?.items || document.querySelectorAll('a[href*="offer/"]').length > 2)`,
      2400,
      5000
    );
    const afterUrl = await pageSession.evalJs(`location.href`);
    if (afterUrl && afterUrl !== prevUrl && afterUrl.includes("1688.com")) {
      submittedNatively = true;
    }
  }

  if (!submittedNatively) {
    const url = `https://s.1688.com/selloffer/offer_search.htm?keywords=${encodeURIComponent(keyword)}&spm=a26352.13672862.searchbox.input&charset=utf8`;
    await pageSession.send("Page.navigate", { url });
    await waitForPageReady(
      pageSession,
      `Boolean(window.data?.offerV2?.response?.data?.OFFER?.items || document.querySelectorAll('a[href*="offer/"]').length > 2)`,
      2400,
      5500
    );
  }

  await ensureNoRiskWithAutoCooldown(pageSession);
  await simulateHumanBrowse(pageSession);

  const offers = await pageSession.evalJs(`(() => {
    const out = [];
    const seen = new Set();
    const v2Items = window.data?.offerV2?.response?.data?.OFFER?.items || [];
    for (const it of v2Items) {
      const d = it?.data || it || {};
      const oid = String(d.offerId || d.id || '').trim();
      if (!/^\\d{8,16}$/.test(oid) || seen.has(oid)) continue;
      seen.add(oid);
      const cleanTitle = String(d.title || d.subject || '').replace(/<[^>]+>/g, '').trim();
      const pVal = parseFloat(d.price?.price || d.showbPrice || '0');
      const pDesc = String(d.price?.priceDescription || '');
      const sales = Number(d.saledCount || d.bookedCount || d.monthBookedCount || 0);
      const tags = JSON.stringify(d.serviceLabels || d.titleTags || '');
      const isFreeShip = /包邮|免运费/.test(pDesc + ' ' + tags) && !/运费\\d/.test(pDesc);
      const rawUrl = String(d.linkUrl || '');
      const offerUrl = rawUrl.startsWith('http') ? rawUrl : (rawUrl.startsWith('//') ? ('https:' + rawUrl) : ('https://detail.1688.com/offer/' + oid + '.html'));
      out.push({
        offerId: oid,
        fullTitle: cleanTitle,
        offerUrl,
        cardPrice: pVal > 0 ? pVal : null,
        sales,
        moq: Number(d.quantityBegin || 1),
        text: cleanTitle + (pVal > 0 ? (' ¥' + pVal) : '') + ' ' + sales + '件 ' + pDesc,
        isFreeShip,
      });
    }
    if (out.length === 0) {
      for (const a of document.querySelectorAll('a[href*="offer/"], a[href*="offerId="]')) {
        const m = a.href.match(/offer\\/(\\d{8,16})\\.html/) || a.href.match(/[?&]offerId=(\\d{8,16})/);
        if (!m || seen.has(m[1])) continue;
        seen.add(m[1]);
        const box = a.closest('[class*="card"], [class*="offer"], [class*="search-offer"]') || a.parentElement?.parentElement;
        const text = (box?.innerText || a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 220);
        const isFreeShip = /包邮|免运费/.test(text) && !/运费\\d/.test(text);
        out.push({ offerId: m[1], offerUrl: a.href, text, isFreeShip });
      }
    }
    return out;
  })()`);

  const topFiltered = prefilterSearchOffers(offers, pendingRows, 5);
  return topFiltered;
}

// Inspect detail.1688.com/offer/{offerId}.html
export async function inspect1688OfferDetail(pageSession, cand) {
  const offerId = typeof cand === "object" ? cand.offerId : cand;
  const targetUrl = (typeof cand === "object" && cand.offerUrl) ? cand.offerUrl : `https://detail.1688.com/offer/${offerId}.html`;

  await pageSession.send("Page.navigate", { url: targetUrl });
  await waitForPageReady(
    pageSession,
    `Boolean(window.context?.result?.data?.Root?.fields?.dataJson || window.context?.result?.data?.mainPrice)`,
    2400,
    5500
  );

  await ensureNoRiskWithAutoCooldown(pageSession);
  await simulateHumanBrowse(pageSession);

  const parsedDetail = await pageSession.evalJs(`(() => {
    const d = window.context?.result?.data || {};
    const dj = d?.Root?.fields?.dataJson || {};
    const temp = dj?.tempModel || {};
    if (!temp?.offerId && !dj?.skuModel && !d?.mainPrice) return { ok: false };

    const saledCount = Number(temp?.saledCount || dj?.saledCount || 0);
    const saledMonth = Number(temp?.saledMonth || 0);

    const ship = d?.shippingServices?.fields || {};
    const freeShip = Boolean(
      ship?.freeDeliverFee ||
      ship?.freightInfo?.freeDeliverFee ||
      ship?.freightInfo?.marketingFreePostage ||
      ship?.freightInfo?.deliveryFee?.name === 'FREE'
    );
    const freightCost = freeShip ? 0 : Number(ship?.totalCost ?? 0);

    const orderParam = dj?.orderParamModel?.orderParam || {};
    const beginNum = Math.max(1, Number(orderParam?.beginNum || 1));
    const rangePrices = orderParam?.skuParam?.skuRangePrices || d?.mainPrice?.fields?.priceModel?.currentPrices || [];
    const fallbackRangePrice = rangePrices.length > 0 ? parseFloat(rangePrices[0].price) : null;

    const images = dj?.images || [];
    const mainPic = images[0]?.fullPathImageURI || images[0]?.size310x310ImageURI || temp?.defaultOfferImg || '';

    // Map prop value imageUrls if needed
    const skuProps = dj?.skuModel?.skuProps || [];
    const propImgMap = {};
    for (const gp of skuProps) {
      for (const v of (gp?.value || [])) {
        if (v?.name && v?.imageUrl) propImgMap[v.name] = v.imageUrl;
      }
    }

    const skuMap = dj?.skuModel?.skuInfoMap || {};
    const skus = [];
    const entries = Object.entries(skuMap);
    if (entries.length > 0) {
      for (const [k, info] of entries) {
        const stock = Number(info?.canBookCount ?? 0);
        const p = parseFloat(info?.discountPrice || info?.price || fallbackRangePrice || '0');
        const rawSpec = info?.specAttrs || k;
        const firstPart = String(rawSpec).split(/&gt;|>/)[0]?.trim();
        skus.push({
          skuId: String(info?.skuId || ''),
          rawSpec,
          price: p,
          stock,
          pic: propImgMap[firstPart] || mainPic,
        });
      }
    } else if (fallbackRangePrice && fallbackRangePrice > 0) {
      skus.push({
        skuId: String(temp?.offerId || ''),
        rawSpec: temp?.offerUnit ? ('1' + temp.offerUnit) : '默认规格',
        price: fallbackRangePrice,
        stock: Number(orderParam?.canBookedAmount ?? 999),
        pic: mainPic,
      });
    }

    const feats = dj?.offerFeatureList || d?.productPackInfo?.fields?.featureList || [];
    const brandFeat = Array.isArray(feats) ? feats.find((f) => /品牌/.test(String(f?.name || ''))) : null;
    const brandVal = brandFeat?.value ? (' ' + String(brandFeat.value)) : '';

    return {
      ok: true,
      offerId: String(temp?.offerId || '${offerId}'),
      offerUrl: 'https://detail.1688.com/offer/' + String(temp?.offerId || '${offerId}') + '.html',
      offerTitle: (temp?.offerTitle || document.title || '') + brandVal,
      offerUnit: temp?.offerUnit || '',
      saledCount,
      saledMonth,
      beginNum,
      freeShip,
      freightCost: isNaN(freightCost) ? 0 : freightCost,
      mainPic,
      skus,
    };
  })()`);

  return parsedDetail;
}

async function main() {
  await ensureDefaultDownloadBehavior();

  const rawItems = JSON.parse(await fs.readFile(QNH_FIXED_PATH, "utf8"));
  const byRow = new Map();
  for (const it of rawItems) {
    const r = Number(it.row);
    if (r >= 49 && r <= 2791 && !byRow.has(r)) byRow.set(r, it);
  }
  const allItems = [...byRow.values()].sort((a, b) => a.row - b.row);

  let progress = {};
  try {
    progress = JSON.parse(await fs.readFile(PROGRESS_PATH, "utf8"));
  } catch {}

  // Group all items by SPU
  const spuGroups = [];
  const spuMap = new Map();
  for (const it of allItems) {
    const key = it.spuId ? String(it.spuId) : `ROW_${it.row}`;
    if (!spuMap.has(key)) {
      const grp = { spuId: key, rows: [] };
      spuMap.set(key, grp);
      spuGroups.push(grp);
    }
    spuMap.get(key).rows.push(it);
  }
  console.log(`[1688 Sourcing Engine] Total SPUs queued for 1688: ${spuGroups.length}`);

  const tabs = await (await fetch(`${CDP_HTTP}/json/list`)).json();
  const tab = tabs.find((t) => t.type === "page" && t.url.includes("1688.com"));
  if (!tab) throw new Error("未找到已登录的 1688 Chrome 标签页");

  const pageSession = new PersistentCdpSession(tab.webSocketDebuggerUrl);
  pageSession.tabId = tab.id;
  await pageSession.connect();
  await pageSession.send("Page.enable");
  await pageSession.send("DOM.enable");
  await pageSession.send("Runtime.enable");
  try {
    await pageSession.send("Emulation.setFocusEmulationEnabled", { enabled: true });
    await pageSession.send("Page.setWebLifecycleState", { state: "active" });
  } catch {}

  await pruneExtraTabs(tab.id);

  let processedSpus = 0;
  let newMatchesSinceFlush = 0;

  try {
    for (let gIdx = 0; gIdx < spuGroups.length; gIdx++) {
      if (processedSpus >= LIMIT_SPUS) break;

      const grp = spuGroups[gIdx];
      if (TARGET_ROW && !grp.rows.some((r) => r.row === TARGET_ROW)) continue;
      if (grp.rows.every((r) => r.row > MAX_ROW)) {
        console.log(`\n==================================================`);
        console.log(`★ [1688 Worker] 已达到任务上限行 (Row ${MAX_ROW})！`);
        console.log(`★ 经用户明确指示：最后 1000 个 SKU (1792~2791行) 已分配他人，本任务圆满完成！`);
        console.log(`==================================================`);
        flushToExcel();
        break;
      }
      const pendingRows = grp.rows.filter((r) => {
        if (r.row > MAX_ROW) return false;
        const st = progress[String(r.row)]?.status;
        return st !== "MATCHED" && st !== "UNMATCHED_1688" && st !== "UNMATCHED";
      });
      if (pendingRows.length === 0) continue;

      if (processedSpus > 0 && processedSpus % 12 === 0) {
        console.log(`[1688 Anti-Risk] Human reading breather 15s after ${processedSpus} SPUs...`);
        await sleep(jitter(15000, 4000));
      }
      await pruneExtraTabs(pageSession.tabId);
      processedSpus++;

      try {
        const lead = pendingRows[0];
      console.log(`\n==================================================`);
      console.log(`[1688 SPU ${gIdx + 1}/${spuGroups.length}] Rows [${pendingRows.map((r) => r.row).join(",")}] | ${lead.excelName}`);
      for (const r of pendingRows) {
        const rt = Number(r.suggestPrice || r.basicPrice || 0);
        console.log(`  - Row ${r.row} (${r.excelSpec}): 原价 ¥${rt} | 半价红线 <= ¥${(rt * 0.5).toFixed(2)}`);
      }

      const checkedOfferIds = new Set();

      const tryCandidates = async (candList, sourceTag) => {
        for (const cand of candList) {
          const rem = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
          if (rem.length === 0) break;
          if (!cand.offerId || checkedOfferIds.has(cand.offerId)) continue;
          checkedOfferIds.add(cand.offerId);

          let detail = null;
          try {
            detail = await inspect1688OfferDetail(pageSession, cand);
          } catch (e) {
            console.log(`    [候选研判异常] ${cand.offerId}: ${e.message}`);
            continue;
          }
          if (!detail || !detail.ok || !Array.isArray(detail.skus) || detail.skus.length === 0) continue;

          // Reject factory bulk MOQ traps (> 25 MOQ)
          if (detail.beginNum > 25) {
            console.log(`    [起批过滤] 起订量过高 (MOQ ${detail.beginNum} > 25): ${cand.offerId}`);
            continue;
          }
          // Reject exorbitant shipping traps (> 20 yuan shipping)
          if (!detail.freeShip && detail.freightCost > 20) {
            console.log(`    [运费过滤] 运费过高 (¥${detail.freightCost} > ¥20): ${cand.offerId}`);
            continue;
          }

          // User mandate: high sales priority and ghost listing filter (< 50 units sold)
          const effectiveSales = Math.max(Number(detail.saledCount || 0), Number(cand.sales || 0));
          if (effectiveSales < 50) {
            console.log(`    [低销过滤] 过滤低销链接 (累计销售仅 ${effectiveSales} 件 < 50件门槛): ${cand.offerId}`);
            continue;
          }

          console.log(`    [候选研判] ${cand.offerId} | 标题: ${detail.offerTitle?.slice(0, 32)} | 销量: ${effectiveSales}件 | MOQ: ${detail.beginNum} | ${detail.freeShip ? "包邮" : "运费:¥" + detail.freightCost} | SKU数: ${detail.skus?.length}`);

          for (const rowItem of rem) {
            const rowKey = String(rowItem.row);
            const retail = Number(rowItem.suggestPrice || rowItem.basicPrice || 0);
            if (retail <= 0) continue;
            const maxUnitPrice = parseFloat((retail * 0.5).toFixed(2));

            const validSkus = [];
            for (const s of detail.skus) {
              // Hard stock gate: >= 20 available units!
              if (!s.price || isNaN(s.price) || s.price <= 0 || s.stock < 20) continue;
              const formattedSpec = format1688Spec(s.rawSpec);
              if (!isSpecCompatible(rowItem.excelName, rowItem.excelSpec, detail.offerTitle, formattedSpec)) continue;

              const perSkuRatio =
                detail.skus.length === 1 && /^(?:默认规格|1[件个盒包袋套条支瓶双]?)$/.test(formattedSpec)
                  ? computeRatio(rowItem.excelName, rowItem.excelSpec, `${formattedSpec} ${detail.offerTitle}`, detail.offerTitle)
                  : computeRatio(rowItem.excelName, rowItem.excelSpec, formattedSpec, detail.offerTitle);
              const moq = detail.beginNum;
              if (moq * s.price + detail.freightCost > Math.max(160, retail * 3)) continue;

              const landedOrderTotal = moq * s.price + detail.freightCost;
              const landedOrderUnits = moq * perSkuRatio;
              const landedUnitCost = parseFloat((landedOrderTotal / landedOrderUnits).toFixed(2));
              const nominalUnitCost = parseFloat((s.price / perSkuRatio).toFixed(2));

              if (landedUnitCost <= maxUnitPrice && nominalUnitCost <= maxUnitPrice) {
                validSkus.push({
                  ...s,
                  formattedSpec,
                  perSkuRatio,
                  nominalUnitCost,
                  landedUnitCost,
                  freeShip: detail.freeShip,
                  freightCost: detail.freightCost,
                  moq,
                });
              }
            }

            if (validSkus.length === 0) continue;
            validSkus.sort((a, b) => {
              if (a.freeShip !== b.freeShip) return a.freeShip ? -1 : 1;
              return a.landedUnitCost - b.landedUnitCost;
            });

            const best = validSkus[0];
            const recRatio = best.perSkuRatio;
            const recPrice = parseFloat(best.price.toFixed(2));
            const recUnit = parseFloat((recPrice / recRatio).toFixed(2));

            progress[rowKey] = {
              row: rowItem.row,
              spuId: rowItem.spuId,
              skuId: rowItem.skuId,
              platform: "1688",
              match_method: sourceTag,
              goods_id: detail.offerId,
              goods_url: detail.offerUrl,
              sku_id: best.skuId,
              sku_specs: best.formattedSpec,
              checkout_url: detail.offerUrl,
              ratio: recRatio,
              group_price: recPrice,
              unit_price: recUnit,
              landed_unit_price: best.landedUnitCost,
              moq: best.moq,
              free_ship: best.freeShip,
              stock: best.stock,
              sales_volume: effectiveSales,
              retail_price: retail,
              main_pic: best.pic || detail.mainPic || "",
              coupon_checked: true,
              status: "MATCHED",
            };
            const serialized = JSON.stringify(progress, null, 2);
            await fs.writeFile(PROGRESS_PATH, serialized, "utf8");
            await fs.writeFile(PROGRESS_BACKUP_PATH, serialized, "utf8");
            newMatchesSinceFlush++;
            console.log(
              `  ★ [${sourceTag}] Row ${rowKey} 匹配成功! 销量=${effectiveSales}件 | ${detail.offerUrl} | 规格="${best.formattedSpec}" | 库存=${best.stock} | ${best.freeShip ? "包邮" : "运费¥" + best.freightCost} | 比例=${recRatio} | 采购价=¥${recPrice} | 单价=¥${recUnit} (<=¥${maxUnitPrice})`
            );
            if (newMatchesSinceFlush >= 10) {
              flushToExcel();
              newMatchesSinceFlush = 0;
            }
          }
        }
      };

      const hasKnownBrand = Boolean(!/适用|兼容/.test(lead.excelName || "") && detectKnownBrand(lead.excelName));
      const kws = extract1688Keywords(lead);

      if (!hasKnownBrand && lead.picUrl) {
        // 用户明确指示：百货/非标品以图搜款优先（视觉精准匹配，多主体框选纠偏，直达高销万单厂家源头）
        console.log(`  [Step 1 以图搜款优先（百货/非标品）] 主图视觉多主体匹配...`);
        let imgCands = await search1688ByImage(pageSession, lead.picUrl, pendingRows);
        console.log(`    以图搜款合格高销候选数: ${imgCands.length}`);
        if (imgCands.length > 0) {
          await tryCandidates(imgCands, "1688以图搜款");
        }

        const afterMainPicPending = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
        if (afterMainPicPending.length > 0 && Array.isArray(lead.allPics) && lead.allPics.length > 1) {
          const secondPic = lead.allPics.find((p) => p !== lead.picUrl && typeof p === "string" && p.startsWith("http"));
          if (secondPic) {
            console.log(`    [以图搜款副图补充] 主图未完全命中，启用副图视觉匹配...`);
            const secCands = await search1688ByImage(pageSession, secondPic, afterMainPicPending);
            if (secCands.length > 0) {
              await tryCandidates(secCands, "1688以图搜款副图");
            }
          }
        }

        // 以图搜款未完全命中时，用提纯关键词作为次级补充
        const stillPending = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
        if (stillPending.length > 0 && kws.length > 0) {
          for (const kw of kws) {
            const still = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
            if (still.length === 0) break;
            console.log(`  [Step 2 提纯关键词补充搜索] "${kw}"`);
            const kwCands = await search1688ByKeyword(pageSession, kw, still);
            console.log(`    词搜合格高销候选数: ${kwCands.length}`);
            if (kwCands.length > 0) {
              await tryCandidates(kwCands, "1688关键词");
            }
            await sleep(jitter(2000, 800));
          }
        }
      } else {
        // 知名大牌标品：特征词优先（大牌标品词搜极其精准）
        for (const kw of kws) {
          const still = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
          if (still.length === 0) break;
          console.log(`  [Step 1 提纯特征词优先（大牌标品）] "${kw}"`);
          const kwCands = await search1688ByKeyword(pageSession, kw, still);
          console.log(`    词搜合格高销候选数: ${kwCands.length}`);
          if (kwCands.length > 0) {
            await tryCandidates(kwCands, "1688关键词");
          }
          await sleep(jitter(2000, 800));
        }

        // 词搜未完全命中时，以图搜款兜底
        const stillPending = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
        if (stillPending.length > 0 && lead.picUrl) {
          console.log(`  [Step 2 以图搜款兜底] 启用主图视觉匹配...`);
          let imgCands = await search1688ByImage(pageSession, lead.picUrl, stillPending);
          console.log(`    以图搜款合格高销候选数: ${imgCands.length}`);
          if (imgCands.length > 0) {
            await tryCandidates(imgCands, "1688以图搜款");
          }
          const afterMainPicPending = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
          if (afterMainPicPending.length > 0 && Array.isArray(lead.allPics) && lead.allPics.length > 1) {
            const secondPic = lead.allPics.find((p) => p !== lead.picUrl && typeof p === "string" && p.startsWith("http"));
            if (secondPic) {
              console.log(`    [以图搜款副图补充] 启用副图视觉匹配...`);
              const secCands = await search1688ByImage(pageSession, secondPic, afterMainPicPending);
              if (secCands.length > 0) {
                await tryCandidates(secCands, "1688以图搜款副图");
              }
            }
          }
          await sleep(jitter(3200, 1500));
        }
      }

      // Mark remaining rows in this SPU as UNMATCHED_1688 so resume skips them
      for (const r of pendingRows) {
        const rk = String(r.row);
        if (progress[rk]?.status !== "MATCHED") {
          progress[rk] = {
            row: r.row,
            spuId: r.spuId,
            skuId: r.skuId,
            platform: "1688",
            retail_price: Number(r.suggestPrice || r.basicPrice || 0),
            status: "UNMATCHED_1688",
          };
        }
      }
      const serializedEnd = JSON.stringify(progress, null, 2);
      await fs.writeFile(PROGRESS_PATH, serializedEnd, "utf8");
      await fs.writeFile(PROGRESS_BACKUP_PATH, serializedEnd, "utf8");
    } catch (spuErr) {
      console.error(`[SPU 异常跳过] SPU ${gIdx + 1} 出错: ${spuErr.message}`);
      await sleep(3000);
    }
  }

    flushToExcel();
    console.log(`\n[1688 Sourcing Engine] Completed ${processedSpus} SPUs.`);
  } finally {
    pageSession.close();
  }
}

import { pathToFileURL } from "node:url";
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    console.error("[1688 Sourcing Engine] Stopped:", err.message || err);
    flushToExcel();
    process.exit(2);
  });
}
