import fs from "node:fs/promises";
import fsSync from "node:fs";
import { execSync } from "node:child_process";

const QNH_FIXED_PATH = "/tmp/qnh_all_details_fixed.json";
const QNH_FALLBACK_PATH = "/tmp/qnh_all_details.json";
const PROGRESS_PATH = "/tmp/pdd_sourcing_progress.json";
const EXCEL_PATH = "/Users/cenbusi/Desktop/2743.xlsx";
const FLUSH_SCRIPT_PATH = "/Users/cenbusi/.gemini/antigravity/brain/da210e82-b25c-40ef-abb7-464dde2672c8/scratch/flush_excel.py";
const OCR_BIN = "/tmp/mac_ocr";
const DEVICE_ID = "b78d30ef";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (baseMs, spreadMs = 450) => baseMs + Math.floor(Math.random() * spreadMs);

function adb(cmdStr, timeout = 9000) {
  try {
    return execSync(`adb -s ${DEVICE_ID} shell "${cmdStr}"`, { timeout, encoding: "utf8" });
  } catch {
    return "";
  }
}

// Atomic screencap with PNG header + IEND integrity verification (prevents truncated PNGs permanently)
function hasValidPngSignatureAndIend(filePath) {
  try {
    const buf = fsSync.readFileSync(filePath);
    if (buf.length < 64) return false;
    const pngSig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    if (!buf.subarray(0, 8).equals(pngSig)) return false;
    const iend = Buffer.from([0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82]);
    return buf.subarray(buf.length - 12).equals(iend);
  } catch {
    return false;
  }
}

function capturePhoneAndOcr(tmpPng = "/tmp/pdd_phone_frame.png") {
  const tmpWrite = `${tmpPng}.tmp`;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      execSync(`adb -s ${DEVICE_ID} exec-out screencap -p > "${tmpWrite}"`, { timeout: 6000 });
      if (!hasValidPngSignatureAndIend(tmpWrite)) {
        try {
          fsSync.unlinkSync(tmpWrite);
        } catch {}
        continue;
      }
      fsSync.renameSync(tmpWrite, tmpPng);
      const raw = execSync(`"${OCR_BIN}" "${tmpPng}"`, { timeout: 4000, encoding: "utf8" });
      const parsed = JSON.parse(raw);
      return (parsed.observations || []).map((o) => {
        const normX = o.x + o.width / 2;
        const normY = 1.0 - (o.y + o.height / 2);
        return {
          text: String(o.text || "").trim(),
          normX,
          normY,
          px: Math.round(normX * 1216),
          py: Math.round(normY * 2640),
          leftPx: Math.round(o.x * 1216),
          rightPx: Math.round((o.x + o.width) * 1216),
        };
      });
    } catch {
      try {
        fsSync.unlinkSync(tmpWrite);
      } catch {}
    }
  }
  return [];
}

function isValidNumericId(val) {
  return typeof val === "string" && /^\d{6,22}$/.test(val.trim());
}

export function cleanSkuSpecText(rawSpec) {
  if (!rawSpec) return "";
  let s = String(rawSpec)
    .replace(/^[•·🔥✓✔\s]+/, "")
    .replace(/^(?:已选[:：]\s*|已包邮\s*)/, "")
    .replace(/\s*(?:快要抢光|最后\d+件|仅剩\d+件|11\.11官方补贴[，,]?限购\d+件|最多人选择|热销\d+.*)$/g, "")
    .replace(/\s*(?:1\s*[+＋|｜]\s*\+?|[+＋]|十)\s*$/g, "")
    .replace(/\s*(?:快要抢光|最后\d+件|仅剩\d+件)\s*$/g, "")
    .trim();
  return s;
}

const CN_NUM_MAP = { 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };

// Strip non-count numeric patterns (dimensions, magnification like 500x25, 30*30cm, 5mm*6m, 0.5/0.7mm, and freebie parentheses like "(带两个适配器)" / "送2个")
export function stripDimensionExpressions(str) {
  return String(str || "")
    .replace(/[（(][^）)]*(?:送|赠|带|含|配)[^）)]*[）)]/g, " ")
    .replace(/(?:送|赠)\s*[一二两三四五六七八九十\d]+\s*[个只支条包袋片张把根套]/g, " ")
    .replace(/(?<![a-zA-Z\d])\d+\s*[*xX×]\s*\d+\s*(?:cm|mm|m|厘米|毫米|米)(?![a-zA-Z\d])/gi, " ")
    .replace(/(?<![a-zA-Z\d])\d+(?:\.\d+)?\s*(?:cm|mm|m|厘米|毫米|米)\s*[*xX×]\s*\d+(?:\.\d+)?\s*(?:cm|mm|m|厘米|毫米|米)?(?![a-zA-Z\d])/gi, " ")
    .replace(/(?<![a-zA-Z\d])(?:100|200|300|400|500|1000)\s*[*xX×]\s*(?:20|25|30|40|50)(?![a-zA-Z\d])/g, " ")
    .replace(/(?<!\d)\d+\s*丝(?!\d)/g, " ")
    .replace(/买\s*\d+\s*\S*\s*送\s*\d+\s*\S*/g, " ");
}

const DURABLE_GOODS_RE = /菜板|案板|砧板|剪刀|剪子|美工刀|壁纸刀|水龙头|雨伞|雨衣|生料带|锅|盆|杯|碗|盘|刀|架|锁|箱|包|椅|凳|马扎|球拍|羽毛球拍|网球拍|乒乓球拍|奶瓶|冲洗器|清洗器|套圈|修正带|数据线|充电器|充电头|插座|插排|手表|手环|手电筒|收纳盒|收纳架|挂钩|镜子|梳子|指甲刀|指甲剪|耳挖|手电|放大镜|计算器|电子秤|皮尺|卷尺|温度计|温湿度计/;

export function extractStorePackDetails(storeName, storeSpec) {
  const combined = (storeName || "") + " " + (storeSpec || "");
  const mPai = combined.match(/拍几份(?:发|剪|截)?几(片|个|米|条|块|袋)/);
  if (mPai) {
    return { isDurable: false, innerCount: 1, innerUnit: mPai[1], outerCount: 1, outerUnit: mPai[1] };
  }

  const isDurable = DURABLE_GOODS_RE.test(storeName || "") && !/纸|巾|签|袋|膜|套|垫|片|粒|包|条|袜/.test(storeSpec || "");

  let innerCount = null;
  let innerUnit = null;
  let outerCount = 1;
  let outerUnit = "";

  const mInner1 = combined.match(/(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只|条|双)\s*(?:[/／每装*xX×]|(?:装\s*[*xX×]?\s*1?))\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|份|条|双)/);
  if (mInner1) {
    innerCount = parseInt(mInner1[1], 10);
    innerUnit = mInner1[2];
    outerUnit = mInner1[3];
    const withoutInner = combined.replace(mInner1[0], " ");
    const reOuter = new RegExp("(?:[*xX×]|共|到手)?\\s*(\\d+)\\s*" + outerUnit);
    const mOuterMulti = withoutInner.match(reOuter);
    if (mOuterMulti) {
      outerCount = parseInt(mOuterMulti[1], 10);
    } else {
      outerCount = 1;
    }
  } else {
    const mInner2 = combined.match(/(?:约|共|装|家庭装|超值装)?\s*(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴)\s*(?:装)?\s*[/／]\s*(包|袋|盒|提|卷|卡|份)/);
    if (mInner2) {
      innerCount = parseInt(mInner2[1], 10);
      innerUnit = mInner2[2];
      outerUnit = mInner2[3];
      outerCount = 1;
    } else {
      const mInner3 = combined.match(/(?:家庭装|超值装|大容量)?\s*(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴)\s*(?:装)?/);
      if (mInner3 && !isDurable) {
        innerCount = parseInt(mInner3[1], 10);
        innerUnit = mInner3[2];
      }
      const mOuter = combined.match(/(?<![.\d])(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|副|双|对|把|台|本|个|条|杯|听|碗|筒|件)(?![a-zA-Z\d])/);
      if (mOuter) {
        outerCount = parseInt(mOuter[1], 10);
        outerUnit = mOuter[2];
      }
    }
  }

  return { isDurable, innerCount, innerUnit, outerCount, outerUnit };
}

export function extractSupplierPackDetails(supplierSpec, supplierTitle) {
  const cleanedSpec = stripDimensionExpressions(cleanSkuSpecText(supplierSpec));
  const cleanedTitle = stripDimensionExpressions(supplierTitle || "");

  // Check if explicitly single pack (e.g. 120片/包, 1包, 单包, 60抽单包, 【80片装】1包, 1盒)
  const isExplicitSinglePack =
    /(?:单[包盒袋瓶罐提杯听碗]|1[包盒袋瓶罐提杯听碗]|装\*1[包盒袋瓶罐提杯听碗]?|\/包|\/盒|\/袋|\/罐|\/提|\/杯|\/听|\/碗)(?![a-zA-Z\d])/.test(cleanedSpec) &&
    !/(?:[2-9]|\d{2,})\s*(?:包|盒|袋|瓶|罐|提|箱|杯|听|碗)/.test(cleanedSpec);

  // Check compound outer + inner (e.g. 3包【共240片】, 240片【3包】, 600支【3盒装】, 3盒装共600支)
  const mCompound1 = cleanedSpec.match(
    /(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|杯|听|碗|筒)\s*(?:装)?(?:[【\[（(]?\s*(?:共|到手|实发)?\s*(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只|条|双))?/
  );
  const mCompound2 = cleanedSpec.match(
    /(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只|条|双)\s*[【\[（(]?\s*(?:共|实发|到手)?\s*(\d+)\s*(包|袋|盒|箱|提|卷|杯|听|碗|筒)/
  );

  let outerCount = null;
  let outerUnit = null;
  let innerTotal = null;
  let innerUnit = null;

  if (mCompound2) {
    innerTotal = parseInt(mCompound2[1], 10);
    innerUnit = mCompound2[2];
    outerCount = parseInt(mCompound2[3], 10);
    outerUnit = mCompound2[4];
  } else if (mCompound1) {
    outerCount = parseInt(mCompound1[1], 10);
    outerUnit = mCompound1[2];
    if (mCompound1[3]) {
      innerTotal = parseInt(mCompound1[3], 10);
      innerUnit = mCompound1[4];
    }
  }

  // Multiplier pattern (e.g. *24罐, *24, 250ml*24罐)
  if (!outerCount) {
    const mMult = cleanedSpec.match(/[*xX×]\s*(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|瓶|听|杯|碗|筒|双|副|条|个|把|支|张|片)?/);
    if (mMult) {
      const val = parseInt(mMult[1], 10);
      const unit = mMult[2] || "";
      if (/包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|瓶|听|杯|碗|筒|双|副|条|个|把/.test(unit)) {
        outerCount = val;
        outerUnit = unit;
      } else if (/片|抽|张|支|枚|颗|粒|节|贴|只/.test(unit)) {
        innerTotal = val;
        innerUnit = unit;
      } else {
        outerCount = val;
      }
    }
  }

  // Check outer pack patterns (e.g. 共3包, 到手5盒, 24瓶整箱, 3包)
  if (!outerCount && !isExplicitSinglePack) {
    const mOuter = cleanedSpec.match(/(?:共|合计|实发|到手|整箱)?\s*(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|杯|听|碗|筒)(?:装)?(?![a-zA-Z\d])/);
    if (mOuter) {
      outerCount = parseInt(mOuter[1], 10);
      outerUnit = mOuter[2];
    }
  }

  // Check standalone piece count (e.g. 240片, 480片, 600支, 20节, 75片, 1000只)
  if (!innerTotal) {
    const mInner = cleanedSpec.match(/(?<![.\d])(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只)(?:装)?(?![a-zA-Z\d])/);
    if (mInner) {
      innerTotal = parseInt(mInner[1], 10);
      innerUnit = mInner[2];
    }
  }

  // Fallback to title if spec is devoid of quantity details
  if (!outerCount && !innerTotal && !isExplicitSinglePack && cleanedTitle) {
    const titleCompound2 = cleanedTitle.match(
      /(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只|条|双)\s*[【\[（(]?\s*(?:共|实发|到手)?\s*(\d+)\s*(包|袋|盒|箱|提|卷|杯|听|碗|筒)/
    );
    const titleCompound1 = cleanedTitle.match(
      /(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|杯|听|碗|筒)\s*(?:装)?(?:[【\[（(]?\s*(?:共|到手|实发)?\s*(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只|条|双))?/
    );
    if (titleCompound2) {
      innerTotal = parseInt(titleCompound2[1], 10);
      innerUnit = titleCompound2[2];
      outerCount = parseInt(titleCompound2[3], 10);
      outerUnit = titleCompound2[4];
    } else if (titleCompound1) {
      outerCount = parseInt(titleCompound1[1], 10);
      outerUnit = titleCompound1[2];
      if (titleCompound1[3]) {
        innerTotal = parseInt(titleCompound1[3], 10);
        innerUnit = titleCompound1[4];
      }
    } else {
      const mTitleOuter = cleanedTitle.match(/(?:共|合计|实发|到手|整箱)\s*(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|杯|听|碗|筒)(?:装)?(?![a-zA-Z\d])/);
      if (mTitleOuter) {
        outerCount = parseInt(mTitleOuter[1], 10);
        outerUnit = mTitleOuter[2];
      } else {
        const mTitleInner = cleanedTitle.match(/(?<![.\d])(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只)(?:装)?(?![a-zA-Z\d])/);
        if (mTitleInner) {
          innerTotal = parseInt(mTitleInner[1], 10);
          innerUnit = mTitleInner[2];
        }
      }
    }
  }

  return { isExplicitSinglePack, outerCount, outerUnit, innerTotal, innerUnit, cleanedSpec };
}

export function extractPackInfo(text) {
  const sup = extractSupplierPackDetails(text, "");
  if (sup.outerCount) {
    return { count: sup.outerCount, unit: sup.outerUnit || "", innerTotal: sup.innerTotal, innerUnit: sup.innerUnit };
  }
  if (sup.innerTotal) {
    return { count: sup.innerTotal, unit: sup.innerUnit || "", innerTotal: sup.innerTotal, innerUnit: sup.innerUnit };
  }
  return { count: 1, unit: "" };
}

export function computeRatio(storeName, storeSpec, supplierSpec, supplierTitle) {
  const store = extractStorePackDetails(storeName, storeSpec);
  const sup = extractSupplierPackDetails(supplierSpec, supplierTitle);

  // 1. Durable goods: NEVER divide by loose inner pieces or sheets!
  if (store.isDurable) {
    if (sup.outerCount && sup.outerCount > 1 && /个|把|副|张|台|本/.test(sup.outerUnit || "")) {
      return sup.outerCount;
    }
    return 1;
  }

  // 2. Explicit single pack on supplier (e.g. 【120片/包】1包, 60抽单包, 1包80片)
  if (sup.isExplicitSinglePack) {
    return 1;
  }

  // 3. Store has an inner piece count (e.g. 80片/包, 60抽/包, 200支/盒, 2节/卡, 25片/包)
  if (store.innerCount && store.innerCount > 0) {
    // 3a. Supplier gives outer package count directly (e.g. 3包, 6盒, 3包【共240片】)
    if (sup.outerCount && sup.outerCount >= 1) {
      return Math.max(1, Math.round(sup.outerCount / (store.outerCount || 1)));
    }
    // 3b. Supplier only gives bulk inner piece count (e.g. 240片, 480片, 600支, 20节)
    if (sup.innerTotal && sup.innerTotal >= store.innerCount) {
      const ratio = sup.innerTotal / store.innerCount;
      return Math.max(1, Math.round(ratio));
    }
    return 1;
  }

  // 4. Store does NOT have inner count, but has outer count (e.g. 24罐 vs 1罐, 3包 vs 1包)
  if (sup.outerCount && sup.outerCount > 1) {
    return Math.max(1, Math.round(sup.outerCount / (store.outerCount || 1)));
  }

  // 5. Pair vs single (e.g. 拖鞋/手套 1双 vs 1000只 -> 500双)
  const isPairStore = /双|对/.test(store.outerUnit || "") || /拖鞋|手套|袜|耳环|鞋垫/.test(storeName || "");
  if (isPairStore && sup.innerUnit === "只" && sup.innerTotal && sup.innerTotal >= 2) {
    return Math.max(1, Math.round(sup.innerTotal / 2));
  }

  return 1;
}

function extractSingleUnitMeasure(text) {
  if (!text) return null;
  const s = String(text);
  const m = s.match(/(?<![a-zA-Z\d])(\d+(?:\.\d+)?)\s*(kg|g|ml|mL|L|千克|克|毫升|升)(?![a-zA-Z])/);
  if (!m) return null;
  let val = parseFloat(m[1]);
  let unit = m[2].toLowerCase();
  if (unit === "kg" || unit === "千克") {
    val *= 1000;
    unit = "g";
  } else if (unit === "克") {
    unit = "g";
  } else if (unit === "l" || unit === "升") {
    val *= 1000;
    unit = "ml";
  } else if (unit === "毫升") {
    unit = "ml";
  }
  return { val, unit, raw: m[0] };
}

const COLOR_FAMILIES = [
  { id: "grey", words: ["灰色", "深灰", "浅灰", "银灰", "烟灰", "花灰", "高级灰", "灰"], shortRe: /(?:^|[；;/\s【(（+])灰(?=[；;/\s】)）+码XLMS\d]|$)/i },
  { id: "black", words: ["黑色", "雅黑", "亮黑", "哑黑"], shortRe: /(?:^|[；;/\s【(（+])黑(?=[；;/\s】)）+码XLMS\d]|$)/i },
  { id: "white", words: ["白色", "乳白", "米白", "奶白", "古董白", "象牙白"], shortRe: /(?:^|[；;/\s【(（+])白(?=[；;/\s】)）+码XLMS\d]|$)/i },
  { id: "pink", words: ["粉色", "浅粉", "樱花粉", "皮粉", "玫粉", "粉红"], shortRe: /(?:^|[；;/\s【(（+])粉(?=[；;/\s】)）+码XLMS\d]|$)/i },
  { id: "purple", words: ["紫色", "香芋紫", "浅紫", "深紫"], shortRe: /(?:^|[；;/\s【(（+])紫(?=[；;/\s】)）+码XLMS\d]|$)/i },
  { id: "green", words: ["绿色", "草绿", "军绿", "墨绿", "浅绿", "果绿", "牛油果绿", "薄荷绿", "豆绿"], shortRe: /(?:^|[；;/\s【(（+])绿(?=[；;/\s】)）+码XLMS\d]|$)/i },
  { id: "blue", words: ["蓝色", "天蓝", "浅蓝", "深蓝", "藏青", "雾霾蓝", "宝蓝", "湖蓝", "冰蓝"], shortRe: /(?:^|[；;/\s【(（+])蓝(?=[；;/\s】)）+码XLMS\d]|$)/i },
  { id: "yellow", words: ["黄色", "鹅黄", "浅黄", "柠檬黄", "姜黄", "奶黄"], shortRe: /(?:^|[；;/\s【(（+])黄(?=[；;/\s】)）+码XLMS\d]|$)/i },
  { id: "red", words: ["红色", "大红", "酒红", "中国红", "西瓜红", "枣红"], shortRe: /(?:^|[；;/\s【(（+])红(?=[；;/\s】)）+码XLMS\d]|$)/i },
  { id: "brown", words: ["咖色", "深咖", "浅咖", "棕色", "卡其", "驼色", "焦糖", "杏色", "美拉德"], shortRe: null },
  { id: "skin", words: ["肤色", "裸色", "肉色"], shortRe: null },
  { id: "silver", words: ["银色", "亮银", "金属银"], shortRe: null },
  { id: "gold", words: ["金色", "香槟金", "玫瑰金", "土豪金"], shortRe: null },
  { id: "clear", words: ["透明", "高透"], shortRe: null },
];

function detectColorFamily(text) {
  const s = String(text || "");
  if (!s) return null;
  for (const fam of COLOR_FAMILIES) {
    // Check multi-char words first (excluding 1-char "灰" which uses shortRe)
    if (fam.words.some((w) => w.length >= 2 && s.includes(w))) return fam.id;
  }
  for (const fam of COLOR_FAMILIES) {
    if (fam.shortRe && fam.shortRe.test(s)) return fam.id;
  }
  return null;
}
const WELL_KNOWN_BRANDS = [
  "海氏海诺", "英吉利", "理然", "得力", "晨光", "真彩", "爱好", "齐心", "广博", "公牛", "南孚", "双鹿", "超霸", "松下",
  "苏泊尔", "爱仕达", "张小泉", "十八子作", "品胜", "绿联", "倍思", "罗马仕", "安克",
  "超能", "雕牌", "立白", "蓝月亮", "奥妙", "汰渍", "威露士", "滴露", "六神", "隆力奇", "郁美净", "大宝", "凡士林",
  "曼秀雷敦", "妮维雅", "欧莱雅", "美宝莲", "百雀羚", "自然堂", "相宜本草", "美加净", "片仔癀", "云南白药", "舒适达",
  "好来", "黑人", "高露洁", "佳洁士", "冷酸灵", "狮王", "舒客", "清风", "维达", "心相印", "洁柔", "斑布", "漫花", "植护",
  "苏菲", "七度空间", "护舒宝", "高洁丝", "自由点", "ABC", "冈本", "杜蕾斯", "杰士邦", "第6感", "第六感", "倍力乐", "名流",
  "海昌", "海俪恩", "博士伦", "卫仕", "麦富迪", "皇家", "伟嘉", "宝路", "洁客", "茶花", "美丽雅", "妙洁", "思高", "绿伞",
  "老管家", "活力28", "白猫", "斧头牌", "枪手", "雷达", "榄菊", "超威", "润本", "宝宝金水", "强生", "青蛙王子", "袋鼠妈妈",
  "十月结晶", "开丽", "子初", "三笑", "倍加洁", "马利", "英雄", "百乐", "三菱", "斑马", "飞科", "博朗", "吉列", "阿道夫",
  "清扬", "海飞丝", "飘柔", "潘婷", "沙宣", "力士", "多芬", "舒肤佳", "拉芳", "蜂花", "滋源", "霸王", "珊珂", "旁氏", "碧柔",
  "马应龙", "仁和", "修正", "葵花", "三九", "999", "江中", "同仁堂", "白云山", "振德", "稳健", "可孚", "鱼跃", "三诺",
  "康师傅", "统一", "农夫山泉", "怡宝", "百岁山", "娃哈哈", "旺仔", "三只松鼠", "百草味", "良品铺子", "卫龙", "洽洽", "劲仔",
  "海天", "李锦记", "老干妈", "苏伯", "太太乐", "双汇", "金锣", "无穷", "奥利奥", "德芙", "士力架", "炫迈", "绿箭", "益达",
  "阿尔卑斯", "不二家", "徐福记", "大白兔", "喜之郎", "旺旺", "达利园", "盼盼", "桃李", "豪士", "卡尔顿", "元气森林",
  "东鹏", "红牛", "脉动", "尖叫", "王老吉", "加多宝", "维他", "椰树", "露露", "银鹭", "雀巢", "立顿", "香飘飘", "优乐美",
  "多力多滋", "乐事", "可口可乐", "百事可乐", "雪碧", "芬达", "美年达", "展艺", "味阳", "虎邦", "君乐宝", "蒙牛", "伊利",
  "光明", "三元", "安慕希", "纯甄", "莫斯利安", "特仑苏", "金典", "千禾", "欣和", "恒顺", "厨邦", "王守义", "十三香",
  "好人家", "海底捞", "桥头", "大红袍", "白象", "今麦郎", "汤达人", "拉面说", "阿宽",
];

export function detectKnownBrand(text) {
  const s = String(text || "");
  for (const b of WELL_KNOWN_BRANDS) {
    if (s.toUpperCase().includes(b.toUpperCase())) return b;
  }
  return null;
}

const FLAVORS = [
  ["桃桃", "蜜桃", "白桃"],
  ["生椰", "椰子"],
  ["青提", "葡萄"],
  ["薄荷"],
  ["草莓"],
  ["柠檬"],
  ["西红柿", "番茄"],
  ["紫菜"],
  ["鲜蔬", "芙蓉"],
  ["菠菜"],
  ["香菇炖鸡"],
  ["红烧牛肉"],
  ["老坛酸菜"],
  ["红豆"],
  ["香芋"],
  ["抹茶"],
];

export function isSpecCompatible(storeName, storeSpec, pddContextText, rawPddSkuSpec) {
  const pddSkuSpec = cleanSkuSpecText(rawPddSkuSpec);
  if (!pddSkuSpec || pddSkuSpec.length < 1) return false;

  const storeFull = `${storeName || ""} ${storeSpec || ""}`;
  const pddFull = `${pddContextText || ""} ${pddSkuSpec}`;
  const pddUpper = pddFull.toUpperCase();

  // 1. Reject low-stock ("最后X件" / "仅剩X件" / "限购1件") AND pure stepper / banner / trial / accessory-only traps
  if (/最后\s*\d+\s*件|仅剩\s*\d+\s*件|剩\s*[1-9]\s*件|限购\s*1\s*件|即将售罄|库存紧张/.test(String(rawPddSkuSpec || ""))) {
    return false;
  }
  if (/^(?:1\s*\+?|十|官方旗舰.*)$/.test(pddSkuSpec)) return false;
  if (/体验装|试用装|空瓶|仅盒子|仅盖子|不含主机|配件拍此|不带充电|单线|刀片|胶枪\+胶嘴|仅胶嘴|扩容|虚标|模型机|展示机|定金|补差价|专拍链接/i.test(pddSkuSpec)) {
    if (!/体验装|空瓶|刀片|胶枪/.test(storeFull)) return false;
  }
  // Category / accessory mismatch guard:
  // If store item is a cosmetic skincare / cream / cleanser, reject combs, clips, puffs, bags, blades, etc.
  if (/素颜霜|粉底|面霜|眼霜|乳液|洁面|洗面奶|护手霜|身体乳|润唇膏|口红|遮瑕/.test(storeFull)) {
    if (/梳|夹|刷|镜|包|袋|棉签|粉扑|修眉|双眼皮|化妆包|巾|纸|泥|喷雾/.test(pddSkuSpec) && !/霜|乳|洁面|奶|液|膏|红|正装|\d+\s*(?:g|ml|支|瓶)/i.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/剃须泡沫|刮胡泡|剃须膏/.test(storeFull)) {
    if (!/泡沫|泡|膏|柠檬|薄荷|240|200|瓶|罐|支|ml|原味/.test(pddSkuSpec) && /刀|架|片|盒|梳/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/口腔喷雾|口腔抑菌液/.test(storeFull)) {
    if (!/喷雾|抑菌|液|桃|葡萄|提|薄荷|清新|20ml|ml|支|瓶/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/洗发水|沐浴露|护发素/.test(storeFull)) {
    if (/浴球|搓澡|梳|夹|毛巾|起泡/.test(pddSkuSpec) && !/洗发|沐浴|护发|液|露|水|\d+\s*(?:ml|g|瓶|袋)/i.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/剪刀|剪子/.test(storeFull)) {
    if (/美工刀|壁纸刀|水果刀|菜刀|小刀|削皮刀|刀片|磨刀|刀套|保护套|剪套/.test(pddSkuSpec) && !/剪/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/美工刀|壁纸刀/.test(storeFull)) {
    if (/剪刀|剪子/.test(pddSkuSpec) && !/美工刀|壁纸刀/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/菜板|砧板|案板/.test(storeFull)) {
    if (/自粘袋|塑料袋|包装袋|密封袋|\d+丝|磨刀|菜刀|刀架/.test(pddSkuSpec) && !/板/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/羽毛球拍|球拍/.test(storeFull)) {
    if (/羽毛球(?![拍架包])|手胶|吸汗带|拍线|拍套|球线/.test(pddSkuSpec) && !/拍|双拍|对拍|支拍/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/奶瓶/.test(storeFull)) {
    if (/(?:吸嘴|奶嘴|重力球|背带|手柄|杯盖|盖子|刷子)(?![+＋&及和与]|\w*奶瓶)/.test(pddSkuSpec) && !/奶瓶|瓶身|整套/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/清洗器|冲洗器|洗鼻器|灌肠器/.test(storeFull)) {
    if (/凝胶|洗液|药水|生理盐水|抑菌液|胶囊|湿巾/.test(pddSkuSpec) && !/器|瓶|壶/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/套圈/.test(storeFull)) {
    const storeDia = storeFull.match(/(?<!\d)(\d{1,2})\s*cm/i);
    if (storeDia) {
      const targetDia = parseInt(storeDia[1], 10);
      const pddDia = pddSkuSpec.match(/(?<!\d)(\d{1,2})\s*cm/i);
      if (pddDia && Math.abs(parseInt(pddDia[1], 10) - targetDia) > 3) {
        return false;
      }
    }
  }
  if (/胸背带|背带式牵引绳|胸背/.test(storeFull)) {
    if (/单独项圈|单项圈|仅项圈|单独项|单独绳|单绳|仅绳子|单独牵引绳/.test(pddSkuSpec)) {
      return false;
    }
    if (/项圈/.test(pddSkuSpec) && !/胸背|背带/.test(pddSkuSpec)) {
      return false;
    }
    if (/仅绳|单独绳|单牵引/.test(pddSkuSpec) && !/胸背|背带/.test(pddSkuSpec)) {
      return false;
    }
    if (!/背带|胸背|牵引|狗绳|拉带|遛狗|防爆冲/.test(pddFull)) {
      return false;
    }
    if (/衣服|卫衣|雨衣|马甲/.test(pddFull) && !/背带|胸背|牵引|狗绳/.test(pddFull)) {
      return false;
    }
    if (/1套|套装|带式牵引绳/.test(storeFull) && /单独|单项圈|单绳|仅/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/窗帘/.test(storeFull)) {
    if (/魔术贴配件|仅魔术贴|绑带|挂钩/.test(pddSkuSpec) && !/帘|遮光|布|\d+[*xX×]\d+/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/筹码|德州扑克/.test(storeFull)) {
    if (/仅桌布|仅庄码|仅铁盒|仅扑克/.test(pddSkuSpec) && !/筹码|套装|200/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/辣椒面|辣椒粉|干碟|蘸料/.test(storeFull)) {
    if (/桂皮|八角|花椒|香叶|丁香|肉蔻|白糖|冰糖|生抽|老抽|陈醋|孜然粉|胡椒粉/.test(pddSkuSpec) && !/辣椒/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/折叠椅|月亮椅|露营椅|钓鱼凳|小马扎/.test(storeFull)) {
    if (/收纳袋|收纳包|背带|防滑脚垫|仅布套|配件/.test(pddSkuSpec) && !/椅|凳|小号|中号|大号|加大|马扎/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/松紧带/.test(storeFull)) {
    if (/穿带器|别针/.test(pddSkuSpec) && !/带|绳|\dm/.test(pddSkuSpec)) {
      return false;
    }
  }
  if (/充电器套装|充电头\+线|头\+线/.test(storeFull) && /单线|数据线|闪充线|快充线|充电线/.test(pddSkuSpec) && !/充电器|充电头|头\+线|套/.test(pddSkuSpec)) {
    return false;
  }
  if (/美工刀/.test(storeFull) && !/刀片/.test(storeFull) && /刀片/.test(pddSkuSpec) && !/刀\+/.test(pddSkuSpec)) {
    return false;
  }
  if (/飞科/.test(storeFull) && /博锐/.test(pddSkuSpec) && !/博锐/.test(storeFull)) {
    return false;
  }
  if (/温湿度计/.test(storeFull) && /不测湿度/.test(pddSkuSpec)) {
    return false;
  }
  if (/三件套/.test(storeFull) && !/三件套|勺.*筷|筷.*勺/.test(pddFull)) {
    return false;
  }
  // Bucket vs Bag instant noodles
  if (/桶/.test(storeFull) && !/袋/.test(storeFull) && /袋装|\d+袋/.test(pddSkuSpec) && !/桶/.test(pddSkuSpec)) {
    return false;
  }
  if (/袋/.test(storeFull) && !/桶/.test(storeFull) && /桶装|\d+桶/.test(pddSkuSpec) && !/袋/.test(pddSkuSpec)) {
    return false;
  }

  // 2. Core noun relevance check (strip colors, materials & generic adjectives so "黑色" alone never counts as product relevance!)
  const cleanStoreCore = String(storeName || "")
    .replace(/【[^】]*】|（[^）]*）|\([^)]*\)/g, " ")
    .replace(
      /家有点点|龙猫购|优选好物|优选|无品牌|官方|正品|通用|家用|学生|便携|新款|男士|女士|男女|儿童|成人|黑色|白色|灰色|粉色|紫色|绿色|蓝色|黄色|红色|透明|银色|金色|咖色|棕色|肤色|卡其|材质|塑料|不锈钢|硅胶|纯棉|加厚|防水|防滑/g,
      " "
    )
    .replace(/\b(?:EVA|PVC|ABS|PP|PE|PET|TPE|TPU)\b/gi, " ")
    .replace(/[^\u4e00-\u9fa5a-zA-Z]/g, "");
  if (cleanStoreCore.length >= 2 && pddFull.trim().length >= 2) {
    const bigrams = [];
    for (let i = 0; i < cleanStoreCore.length - 1; i++) {
      bigrams.push(cleanStoreCore.slice(i, i + 2).toUpperCase());
    }
    if (bigrams.length > 0 && !bigrams.some((bg) => pddUpper.includes(bg))) {
      return false;
    }
  }

  // 3. Digital storage capacity (strictly check SKU spec first so 128MB/4GB never matches 64GB!)
  const isDigitalStorage = /U盘|优盘|闪存|内存卡|TF卡|SD卡|固态硬盘/.test(storeFull);
  const storeCap = storeFull.match(/(?<!\d)(\d+)\s*(GB|TB)\b/i) || (isDigitalStorage ? storeFull.match(/(?<!\d)(\d+)\s*G(?![a-zA-Z])/i) : null);
  if (storeCap) {
    const capVal = storeCap[1];
    const capUnit = storeCap[2].toUpperCase().startsWith("T") ? "TB" : "GB";
    // Reject MB immediately if store wants GB/TB!
    if (/\d+\s*MB?\b/i.test(pddSkuSpec)) return false;
    const skuCaps = [...pddSkuSpec.matchAll(/(?<!\d)(\d+)\s*(TB|GB|G)(?![a-zA-Z])/gi)];
    if (skuCaps.length > 0) {
      const exactOnSku = skuCaps.some((m) => {
        const u = m[2].toUpperCase().startsWith("T") ? "TB" : "GB";
        return m[1] === capVal && u === capUnit;
      });
      if (!exactOnSku) return false;
    } else if (!new RegExp(`(?<!\\d)${capVal}\\s*${capUnit === "TB" ? "TB" : "(?:GB|G)"}(?![a-zA-Z])`, "i").test(pddFull)) {
      return false;
    }
  }

  // 3b. Orientation / Lock / Size-class / Age-group strict qualifiers
  if (/竖版|竖款/.test(storeFull) && !/横版|横款/.test(storeFull) && /横版|横款/.test(pddSkuSpec) && !/竖/.test(pddSkuSpec)) return false;
  if (/横版|横款/.test(storeFull) && !/竖版|竖款/.test(storeFull) && /竖版|竖款/.test(pddSkuSpec) && !/横/.test(pddSkuSpec)) return false;
  if (/密码锁|密码捆扎|密码绑带/.test(storeFull) && !/密码/.test(pddSkuSpec)) {
    return false;
  }
  if (/大号/.test(storeSpec || "") && /小号|中号|迷你/.test(pddSkuSpec) && !/大号/.test(pddSkuSpec)) return false;
  if (/小号/.test(storeSpec || "") && /大号|中号|特大/.test(pddSkuSpec) && !/小号/.test(pddSkuSpec)) return false;
  if (/中号/.test(storeSpec || "") && /大号|小号|迷你/.test(pddSkuSpec) && !/中号/.test(pddSkuSpec)) return false;
  if (/婴儿|新生儿|宝宝/.test(storeFull) && !/成人/.test(storeFull) && /成人/.test(pddSkuSpec) && !/婴|宝宝|儿童/.test(pddSkuSpec)) return false;
  if (/成人/.test(storeFull) && !/儿童|宝宝/.test(storeFull) && /儿童|宝宝|婴儿/.test(pddSkuSpec) && !/成人/.test(pddSkuSpec)) return false;

  // Flavor / key ingredient consistency guard (e.g. 牛肉 never matches 蒜蓉, 红豆 never matches 香芋/草莓)
  const MEAT_FLAVORS = [
    { key: "牛肉", pat: /牛肉/ },
    { key: "羊肉", pat: /羊肉/ },
    { key: "猪肉", pat: /猪肉/ },
    { key: "鸡肉", pat: /鸡肉/ },
    { key: "鸭肉", pat: /鸭肉/ },
    { key: "蒜蓉", pat: /蒜蓉/ },
    { key: "香菇", pat: /香菇/ },
    { key: "红豆", pat: /红豆/ },
    { key: "椰果", pat: /椰果/ },
    { key: "香芋", pat: /香芋/ },
    { key: "草莓", pat: /草莓/ },
    { key: "芝士", pat: /芝士/ },
    { key: "海苔", pat: /海苔/ },
    { key: "番茄", pat: /番茄/ },
    { key: "青提", pat: /青提/ },
    { key: "白桃", pat: /蜜桃|白桃|桃桃/ },
  ];
  for (const f of MEAT_FLAVORS) {
    if (f.pat.test(storeFull)) {
      const conflicts = MEAT_FLAVORS.filter((other) => other.key !== f.key && other.pat.test(pddSkuSpec));
      if (conflicts.length > 0 && !f.pat.test(pddSkuSpec)) {
        return false;
      }
    }
  }

  // Age group check (e.g. 13岁以上 NEVER matches 3-5岁 or 0-6个月!)
  const ageMatch = storeFull.match(/(\d{1,2})\s*岁\s*(?:以上|\+)?/);
  if (ageMatch) {
    const minAge = parseInt(ageMatch[1], 10);
    if (/个月|婴儿|新生儿/.test(pddSkuSpec) && minAge >= 2) return false;
    const pddAgeRange = pddSkuSpec.match(/(\d{1,2})\s*[-~至到]\s*(\d{1,2})\s*岁/);
    if (pddAgeRange) {
      const pddMax = parseInt(pddAgeRange[2], 10);
      if (pddMax < minAge) return false;
    }
  }

  // Sock / tube length (e.g. 50cm never matches 7-9cm or 13-15cm)
  const lenMatch = storeFull.match(/(?<!\d)(\d{2})\s*cm\b/i);
  if (lenMatch && /袜/.test(storeFull)) {
    const targetLen = parseInt(lenMatch[1], 10);
    const pddLens = [...pddSkuSpec.matchAll(/(?<!\d)(\d{1,2})\s*[-~至到]\s*(\d{1,2})\s*cm/gi)];
    if (pddLens.length > 0) {
      const maxPddLen = Math.max(...pddLens.map((m) => parseInt(m[2], 10)));
      if (maxPddLen < targetLen * 0.6) return false;
    }
  }

  // Gender check for kids/clothing
  if (/男孩|男童/.test(storeSpec || storeName) && !/女孩|女童/.test(storeSpec || storeName)) {
    if (/女孩|女童|玫红|芭比粉/.test(pddSkuSpec)) return false;
  }
  if (/女孩|女童/.test(storeSpec || storeName) && !/男孩|男童/.test(storeSpec || storeName)) {
    if (/男孩|男童/.test(pddSkuSpec)) return false;
  }

  // 4. Electrical power (e.g. 100W, 90W, 66W)
  const storePower = storeFull.match(/(?<!\d)(\d+)\s*(W|瓦)(?![a-zA-Z])/i);
  if (storePower) {
    const pwVal = storePower[1];
    const skuPowers = [...pddSkuSpec.matchAll(/(?<!\d)(\d+)\s*(?:W|瓦)(?![a-zA-Z])/gi)];
    if (skuPowers.length > 0) {
      if (!skuPowers.some((m) => m[1] === pwVal)) return false;
    } else if (!new RegExp(`(?<!\\d)${pwVal}\\s*(?:W|瓦)`, "i").test(pddFull)) {
      return false;
    }
  }

  // Electrical plug pin standard (Reject foreign 欧规/美规/英规 for domestic stores unless specified!)
  if (!/欧规|美规|英规/.test(storeFull) && /欧规|美规|英规/.test(pddSkuSpec)) {
    return false;
  }

  // Exact model code check (e.g. FH6231 vs PH1628)
  const storeModelMatch = storeFull.match(/\b([A-Za-z]{1,4}\d{3,5})\b/);
  if (storeModelMatch) {
    const storeModel = storeModelMatch[1].toUpperCase();
    const skuModelMatch = pddSkuSpec.match(/\b([A-Za-z]{1,4}\d{3,5})\b/);
    if (skuModelMatch) {
      const skuModel = skuModelMatch[1].toUpperCase();
      if (skuModel !== storeModel && !pddFull.toUpperCase().includes(storeModel)) {
        return false;
      }
    }
  }

  // Smart Watch charger vs Phone charger
  if (/手表|手环|Watch|GT4|GT5/i.test(storeFull) && /充/.test(storeFull)) {
    if (!/手表|手环|Watch|GT/i.test(pddSkuSpec) && !/手表|手环|Watch|GT/i.test(pddContextText)) {
      return false;
    }
  }

  // 5. Lead diameter (0.5 vs 0.7)
  const leadMatch = storeFull.match(/(?<!\d)(0\.[57]|0\.38)(?!\d)/);
  if (leadMatch) {
    const lead = leadMatch[1];
    const otherLeads = ["0.38", "0.5", "0.7"].filter((x) => x !== lead);
    if (otherLeads.some((ol) => pddSkuSpec.includes(ol)) && !pddSkuSpec.includes(lead)) return false;
  }

  // 6. Cosmetic shade number (#1 / 01# vs 02#)
  const shadeMatch = String(storeSpec || "").match(/(?:#\s*0?(\d)|0?(\d)\s*#)/);
  if (shadeMatch) {
    const shadeNum = shadeMatch[1] || shadeMatch[2];
    const pddShade = pddSkuSpec.match(/(?:#\s*0?(\d)|0?(\d)\s*#)/);
    if (pddShade && (pddShade[1] || pddShade[2]) !== shadeNum) return false;
  }

  // 7. iPhone model exact suffix check (17 vs 17 Pro vs 17 Pro Max vs 17 Air)
  const ipMatch = storeFull.match(/(?:iPhone|苹果)\s*(\d{2})\s*(Pro\s*Max|ProMax|Pro|Plus|Air|mini)?/i);
  if (ipMatch && /壳|膜/.test(storeFull)) {
    const num = ipMatch[1];
    const suffix = (ipMatch[2] || "").replace(/\s+/g, "").toLowerCase();
    const pddIp = pddSkuSpec.match(/(?:iPhone|苹果)\s*(\d{2})\s*(Pro\s*Max|ProMax|Pro|Plus|Air|mini)?/i);
    if (!pddIp || pddIp[1] !== num) return false;
    const pddSuffix = (pddIp[2] || "").replace(/\s+/g, "").toLowerCase();
    if (pddSuffix !== suffix) return false;
  }

  // 8. Color check (when store is NOT 颜色随机)
  if (!/颜色随机|随机色|混色|混装/.test(storeFull)) {
    const storeColorFam = detectColorFamily(storeSpec) || detectColorFamily(storeName);
    if (storeColorFam) {
      const pddColorFam = detectColorFamily(pddSkuSpec);
      if (pddColorFam && pddColorFam !== storeColorFam) {
        return false;
      }
      // If storeSpec explicitly asks for a specific color (e.g. "灰色XL") and pddSkuSpec is a multi-option SKU without any mention of that color family when other SKUs typically have colors, ensure color isn't "随机"
      if (detectColorFamily(storeSpec) && /随机/.test(pddSkuSpec)) {
        return false;
      }
    }
  }

  // 8b. Well-known brand consistency check (never buy off-brand when store specifies a real brand, unless it's a "适用..." accessory)
  const reqBrand = !/适用|兼容/.test(storeName || "") ? detectKnownBrand(storeName) : null;
  if (reqBrand && !pddUpper.includes(reqBrand.toUpperCase())) {
    return false;
  }

  // 8c. Apparel cut / pant-length / sleeve-length strict check (e.g. 五分裤 != 三分裤!)
  const pantCuts = ["三分", "四分", "五分", "七分", "八分", "九分", "长裤"];
  const storeCut = pantCuts.find((c) => storeFull.includes(c));
  if (storeCut) {
    const otherCuts = pantCuts.filter((c) => c !== storeCut);
    if (otherCuts.some((oc) => pddSkuSpec.includes(oc)) && !pddSkuSpec.includes(storeCut)) {
      return false;
    }
  }
  if (/长袖/.test(storeFull) && !/短袖/.test(storeFull) && /短袖|无袖|背心/.test(pddSkuSpec) && !/长袖/.test(pddSkuSpec)) return false;
  if (/短袖/.test(storeFull) && !/长袖/.test(storeFull) && /长袖|无袖/.test(pddSkuSpec) && !/短袖/.test(pddSkuSpec)) return false;

  // 9. Flavor check (if storeSpec explicitly names a flavor, pddSkuSpec MUST match that flavor family)
  if (!/随机|混装|混合/.test(storeFull)) {
    for (const group of FLAVORS) {
      const inSpec = group.some((f) => String(storeSpec || "").includes(f));
      if (inSpec) {
        const sameFlavorOnSku = group.some((f) => pddSkuSpec.includes(f));
        const isGenericSku = /^(?:默认规格|常规|正装|1[瓶支盒袋包])$/.test(pddSkuSpec);
        if (!sameFlavorOnSku && !isGenericSku) return false;
      }
    }
  }

  // 9b. Oral spray / breath spray category guard
  if (/口腔抑菌液|口腔喷雾|口喷/.test(storeFull)) {
    if (/清洗液|生理盐水|鼻腔|漱口水|牙膏/.test(pddSkuSpec)) {
      return false;
    }
  }

  // 9b. Product form check (e.g., 喷雾/瓶装液体 != 清洁器/袋装棉签/湿巾)
  if (/喷雾/.test(storeFull) && !/清洁器|棉签|牙线/.test(storeFull) && /清洁器|棉签|牙线|湿巾/.test(pddSkuSpec) && !/喷雾/.test(pddSkuSpec)) {
    return false;
  }

  // 10. Net weight / volume consistency (strictly within 12% single or integer multiple, including g <-> ml cosmetic equivalence)
  if (!/克\*1份|10g\*1份|拍几份/.test(storeFull)) {
    const storeMeasure = extractSingleUnitMeasure(storeSpec) || extractSingleUnitMeasure(storeName);
    if (storeMeasure) {
      const pddSkuMeasure = extractSingleUnitMeasure(pddSkuSpec);
      if (pddSkuMeasure) {
        const pddPack = extractPackInfo(pddSkuSpec);
        const isMultiPack = pddPack.count >= 2 || /\b[xX*×]\s*\d+/.test(pddSkuSpec);
        const ratioByWeight = pddSkuMeasure.val / storeMeasure.val;
        const nearestInt = Math.round(ratioByWeight);
        const isExactSingle = Math.abs(pddSkuMeasure.val - storeMeasure.val) / storeMeasure.val <= 0.12;
        const isExactMultiple = isMultiPack && nearestInt >= 2 && Math.abs(ratioByWeight - nearestInt) <= 0.12;
        if (!isExactSingle && !isExactMultiple) return false;
      } else {
        // If store specifies a weight/volume (e.g. 35g, 240ml), reject non-weight count accessories (e.g. 30抽, 1把, 1把梳子)
        if (/\d+\s*(?:抽|把|张|片|双|条|卷|对|本|块)/.test(pddSkuSpec) && !/默认|常规|正装/.test(pddSkuSpec)) {
          return false;
        }
        // Fallback to title only if SKU is purely a color/shade/flavor/pack descriptor (e.g. "自然色", "薄荷味")
        const titleMeasure = extractSingleUnitMeasure(pddContextText);
        if (titleMeasure) {
          const ratioByWeight = titleMeasure.val / storeMeasure.val;
          const nearestInt = Math.round(ratioByWeight);
          const isExactSingle = Math.abs(titleMeasure.val - storeMeasure.val) / storeMeasure.val <= 0.12;
          const isExactMultiple = nearestInt >= 2 && Math.abs(ratioByWeight - nearestInt) <= 0.12;
          if (!isExactSingle && !isExactMultiple) return false;
        }
      }
    }
  }

  // 11. Strict word-boundary Apparel Size check (XL NEVER matches XXL!)
  const sizeMatch = String(storeSpec || "").match(/(?<![A-Za-z0-9])(XXXL|3XL|XXL|2XL|4XL|XL|XS|S|M|L)(?:码)?(?![A-Za-z0-9])/i);
  if (sizeMatch) {
    const normSize = (s) => s.toUpperCase().replace("3XL", "XXXL").replace("2XL", "XXL").replace("码", "");
    const targetSz = normSize(sizeMatch[1]);
    const pddSizes = [...pddSkuSpec.matchAll(/(?<![A-Za-z0-9])(XXXL|3XL|XXL|2XL|4XL|XL|XS|S|M|L)(?:码)?(?![A-Za-z0-9])/gi)].map((m) =>
      normSize(m[1])
    );
    if (!pddSizes.includes(targetSz)) return false;
  }

  // 12. Cup / cm width-length check
  const cupMatch = String(storeSpec || "").match(/([ABCD])\s*(?:罩杯|杯)/i);
  if (cupMatch) {
    const cup = cupMatch[1].toUpperCase();
    if (!new RegExp(`(?<![A-Za-z])${cup}\\s*(罩杯|杯|码)`, "i").test(pddSkuSpec)) return false;
  }

  const widthCmMatch = storeFull.match(/(?<!\d)(\d{2,3})\s*cm\s*宽/i);
  if (widthCmMatch) {
    const wVal = widthCmMatch[1];
    const mVal = (parseInt(wVal, 10) / 100).toString();
    if (!pddUpper.includes(`${wVal}CM`) && !pddFull.includes(`${wVal}厘米`) && !pddFull.includes(`宽${mVal}米`) && !pddFull.includes(`高${wVal}cm`)) {
      return false;
    }
  }

  // 12b. 2D Sheet/Curtain/Mat dimension check (checks SKU spec directly when SKU has 2D dimensions, so 宽1.2m*高1.7m NEVER matches 200*170cm!)
  const dim2d = storeFull.match(/(?<!\d)(\d{2,3})\s*[*xX×]\s*(\d{2,3})\s*(?:cm|厘米)?/i);
  if (dim2d) {
    const targetDims = [parseInt(dim2d[1], 10), parseInt(dim2d[2], 10)].sort((a, b) => a - b);
    const skuMatches = [...pddSkuSpec.matchAll(/(\d+(?:\.\d+)?)\s*(m|cm|米|厘米)?(?![a-zA-Z\d])/gi)];
    const parsed = [];
    for (const m of skuMatches) {
      let val = parseFloat(m[1]);
      const unit = m[2];
      if (unit === "m" || unit === "米" || (!unit && val < 10)) {
        val = Math.round(val * 100);
      }
      if (val >= 30 && val <= 500) parsed.push(val);
    }
    if (parsed.length >= 2) {
      parsed.sort((a, b) => a - b);
      const diff0 = Math.abs(parsed[0] - targetDims[0]);
      const diff1 = Math.abs(parsed[1] - targetDims[1]);
      if (diff0 > 15 || diff1 > 15) return false;
    } else {
      const matchDim = (txt, cm, m, mf) =>
        new RegExp(`(?<!\\d)${cm}(?!\\d)`).test(txt) ||
        txt.includes(`${m}m`) ||
        txt.includes(`${m}米`) ||
        txt.includes(`${mf}m`) ||
        txt.includes(`${mf}米`);
      const d1 = parseInt(dim2d[1], 10);
      const d2 = parseInt(dim2d[2], 10);
      const m1 = (d1 / 100).toString();
      const m2 = (d2 / 100).toString();
      const m1Fixed = (d1 / 100).toFixed(1);
      const m2Fixed = (d2 / 100).toFixed(1);
      if (!matchDim(pddFull, d1, m1, m1Fixed) || !matchDim(pddFull, d2, m2, m2Fixed)) {
        return false;
      }
    }
  }
  if (/筹码/.test(storeFull) && !/筹码/.test(pddFull)) return false;
  if (/套镜/.test(storeFull) && !/套镜|夹片/.test(pddFull)) return false;

  // 13. Footwear size check (supports both ASCII ~ and fullwidth ～, e.g. 36-37, 44～45)
  if (/拖鞋|凉鞋|鞋垫|雨鞋|棉鞋|鞋套/.test(storeFull)) {
    const shoePair = storeFull.match(/(?<!\d)(3[5-9]|4[0-6])\s*[-~～/—至]\s*(3[6-9]|4[0-7])(?!\d)/);
    if (shoePair) {
      const s1 = shoePair[1];
      const s2 = shoePair[2];
      const pddPair = pddSkuSpec.match(/(?<!\d)(3[5-9]|4[0-6])\s*[-~～/—至]\s*(3[6-9]|4[0-7])(?!\d)/);
      if (pddPair && (pddPair[1] !== s1 || pddPair[2] !== s2)) return false;
      if (!pddPair && !pddSkuSpec.includes(s1) && !pddSkuSpec.includes(s2)) return false;
    }
  }

  // 14. Digital cable / connector interface check (Type-C vs Apple Lightning vs Micro/Android)
  if (/数据线|充电线|快充线|转接头|耳机|音频线/.test(storeFull) && !/三合一|一拖三/.test(storeFull)) {
    const wantsTypeC = /Type-?C|C口|TC口|双C|CtoC/i.test(storeFull) && !/苹果|Lightning|iPhone/i.test(storeFull);
    const wantsApple = /苹果|Lightning|iPhone/i.test(storeFull) && !/Type-?C|C口|安卓/i.test(storeFull);
    const wantsMicro = /安卓|Micro/i.test(storeFull) && !/Type-?C|苹果|Lightning/i.test(storeFull);
    if (wantsTypeC && /苹果|Lightning|安卓|Micro/i.test(pddSkuSpec) && !/Type-?C|C口|TC|三合一|一拖三/i.test(pddSkuSpec)) return false;
    if (wantsApple && /Type-?C|C口|安卓|Micro/i.test(pddSkuSpec) && !/苹果|Lightning|iOS|iPhone|C转L|PD苹果|三合一|一拖三/i.test(pddSkuSpec)) return false;
    if (wantsMicro && /Type-?C|C口|苹果|Lightning/i.test(pddSkuSpec) && !/安卓|Micro|三合一|一拖三/i.test(pddSkuSpec)) return false;
  }

  return true;
}

function cleanKeywords(item) {
  const name = item.excelName || item.qnhName || "";
  const spec = item.excelSpec || item.specName || "";
  const isDigitalStorage = /U盘|优盘|闪存|内存卡|TF卡|SD卡/.test(name + " " + spec);

  let raw = name
    .replace(/【[^】]*】/g, " ")
    .replace(/（[^）]*）/g, " ")
    .replace(/\([^)]*\)/g, " ")
    .replace(/家有点点|龙猫购|优选好物|优选|无品牌|zxc|nis/gi, " ")
    .replace(/^\s*\d+\s*[个盒袋瓶双件套份条罐听杯卷台对把本盆只张支装]+\s*/g, " ")
    .replace(/[/／+*#_，,、|]+/g, " ");

  const noise = [
    "大容量", "便携小巧", "防震防尘防水", "颜色随机", "颜色可选", "休闲怀旧", "送绳子",
    "多色可选", "厚度可选", "耐磨耐用", "全家可用", "有效控油", "持久防水不脱妆",
    "男女通用", "夏季新款", "高级感", "纯色透明", "天然橡胶胶乳", "外用液体剂型",
    "拍几份发几片", "生日礼物", "学习用品", "开学推荐", "新老包装随机"
  ];
  for (const n of noise) raw = raw.replace(new RegExp(n, "g"), " ");
  raw = raw.replace(/\s+\d*\s*[个盒袋瓶双件套份条罐听杯卷台对把本盆只张支]\s*$/g, " ");
  raw = raw.replace(/\s+/g, " ").trim();

  const measure = !/克\*1份/.test(spec) ? extractSingleUnitMeasure(spec) || extractSingleUnitMeasure(name) : extractSingleUnitMeasure(name);
  const measureStr = measure ? measure.raw.replace(/\s+/g, "") : "";

  const tokens = raw.split(" ").filter(Boolean);
  let baseKw = "";
  if (tokens.length >= 2) {
    baseKw = `${tokens[0]} ${tokens[1].slice(0, 10)}`.trim();
  } else if (tokens.length === 1) {
    baseKw = tokens[0].slice(0, 14);
  } else {
    baseKw = name.slice(0, 12);
  }

  const kws = [];
  if (measureStr && !baseKw.includes(measureStr)) {
    kws.push(`${baseKw} ${measureStr}`.trim());
  }
  kws.push(`${baseKw} 整箱批发`.trim());
  kws.push(baseKw);

  const capMatch = (name + " " + spec).match(/\b(\d+)\s*(GB|TB)\b/i) || (isDigitalStorage ? (name + " " + spec).match(/\b(\d+)\s*G\b/) : null);
  if (capMatch) kws.unshift(`${capMatch[1]}GB U盘 批发`);

  return [...new Set(kws.map((k) => k.replace(/\s+/g, " ").trim()).filter((k) => k.length >= 2))].slice(0, 2);
}

function getPhoneTopBundle() {
  const out = adb("dumpsys activity com.xunmeng.pinduoduo");
  if (!out) return { inPdd: false, hasDrawer: false, lastBundle: "", goodsId: null, skuId: null, goodsNumber: "1", thumbUrl: "" };

  const inPdd = /mResumed=true/.test(out);
  const hasDrawer = /CheckoutFrameLayout\{[0-9a-f]+ V\.E/.test(out);
  const bundles = [...out.matchAll(/mArguments=Bundle\[\{props=\{([\s\S]*?)\}\]/g)];
  const lastBundle = bundles.length > 0 ? bundles[bundles.length - 1][1] : "";

  const gidM = lastBundle.match(/goods_id[=\\": ]+(\d{6,20})/);
  const sidM = lastBundle.match(/sku_id[=\\": ]+(\d{6,20})/);
  const numM = lastBundle.match(/goods_number[=\\": ]+(\d+)/);
  let thumbUrl = "";
  const thM = lastBundle.match(/thumb_url=([^&"\\]+)/);
  if (thM) {
    try {
      thumbUrl = decodeURIComponent(thM[1]).split("?")[0];
    } catch {}
  }

  return {
    inPdd,
    hasDrawer,
    lastBundle,
    isGoodsPage: /goods\.html|pdd_goods_detail/.test(lastBundle) && !!gidM,
    isCheckoutPage: /order_checkout\.html/.test(lastBundle) && !!gidM && !!sidM,
    isLikesPage: /likes\.html/.test(lastBundle),
    goodsId: gidM ? gidM[1] : null,
    skuId: sidM ? sidM[1] : null,
    goodsNumber: numM ? numM[1] : "1",
    thumbUrl,
  };
}

async function clearPhoneFavorites() {
  adb("am start --activity-clear-top -a android.intent.action.VIEW -d 'pinduoduo://com.xunmeng.pinduoduo/likes.html'");
  await sleep(1200);
  const obs = capturePhoneAndOcr("/tmp/pdd_likes_clean.png");
  if (obs.some((o) => /暂无收藏/.test(o.text))) return;

  const manageBtn = obs.find((o) => o.py < 350 && o.px > 950 && /管理/.test(o.text));
  adb(`input tap ${manageBtn ? manageBtn.px : 1095} ${manageBtn ? manageBtn.py : 221}`);
  await sleep(500);
  adb("input tap 127 2498");
  await sleep(380);
  adb("input tap 988 2496");
  await sleep(520);
  adb("input tap 861 1527");
  await sleep(480);
}

// Claim store coupon if unclaimed & extract clean spec + post-coupon price from order_checkout.html (NEVER tap bottom bar!)
async function phoneVerifyCheckoutClaimCouponAndReadPrice(expectedGoodsId, expectedSkuId, fallbackPrice, fallbackSpec) {
  const st = getPhoneTopBundle();
  if (!st.isCheckoutPage || st.goodsNumber !== "1" || st.skuId !== expectedSkuId) {
    adb(
      `am start --activity-clear-top -a android.intent.action.VIEW -d 'pinduoduo://com.xunmeng.pinduoduo/order_checkout.html?goods_id=${expectedGoodsId}&sku_id=${expectedSkuId}&goods_number=1'`
    );
    await sleep(1650);
  }

  let obs = capturePhoneAndOcr("/tmp/pdd_checkout_verify.png");
  const fullText = obs.map((o) => o.text).join(" ");
  if (/当前访问人数较多|排队中/.test(fullText)) {
    return { ok: false, error: "QUEUED" };
  }
  if (/最后\s*\d+\s*件|仅剩\s*\d+\s*件|限购\s*1\s*件/.test(fullText)) {
    console.log(`      [低库存淘汰] 结算页提示低库存/限购（最后几件），放弃该SKU！`);
    return { ok: false, error: "LOW_STOCK" };
  }

  // Claim store coupon if available ("领券可减X元" / "可用优惠券")
  const alreadyDiscounted = obs.some((o) => /已自动领取|已优惠|店铺优惠\s*-\s*¥?\d|-\s*¥?\d+(\.\d+)?\s*元/.test(o.text));
  const claimableRow = obs.find(
    (o) =>
      o.py > 1000 &&
      o.py < 1850 &&
      /领券|可领|点击领|可用优惠券|领券可减/.test(o.text) &&
      !/已自动领取/.test(o.text)
  );

  if (!alreadyDiscounted && claimableRow) {
    console.log(`      [支付页领券] 发现未领店铺优惠 "${claimableRow.text}"，自动领券...`);
    adb(`input tap ${claimableRow.px} ${claimableRow.py}`);
    await sleep(950);
    const popObs = capturePhoneAndOcr("/tmp/pdd_checkout_coupon_pop.png");
    const getBtns = popObs.filter((o) => o.py > 650 && o.py < 2300 && /领取|立即领券|领券并使用|使用|一键领取/.test(o.text));
    for (const b of getBtns.slice(0, 2)) {
      adb(`input tap ${b.px} ${b.py}`);
      await sleep(650);
    }
    const confirmBtn = popObs.find((o) => o.py > 1800 && o.py < 2360 && /^(确定|完成|确认)$/.test(o.text));
    if (confirmBtn) {
      adb(`input tap ${confirmBtn.px} ${confirmBtn.py}`);
    } else {
      adb("input keyevent 4");
    }
    await sleep(850);
    obs = capturePhoneAndOcr("/tmp/pdd_checkout_after_coupon.png");
  }

  // Read post-coupon payable total strictly via OCR (NEVER tap bottom bar!)
  let postCouponPrice = null;
  for (const o of obs) {
    if (o.py > 2380) {
      const m = o.text.match(/(?:立即支付|提交订单|去支付|实付款)\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)/);
      if (m) {
        postCouponPrice = parseFloat(m[1]);
        break;
      }
    }
  }
  if (!postCouponPrice) {
    for (const o of obs) {
      if (o.py > 650 && o.py < 1100) {
        const m = o.text.match(/(?:券后|折后|一口价|限量低价)\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)/);
        if (m) {
          postCouponPrice = parseFloat(m[1]);
          break;
        }
      }
    }
  }

  // Extract clean SKU spec from checkout card area (py ~ 940..1220, right of product thumbnail px > 280)
  const specLines = obs
    .filter(
      (o) =>
        o.py >= 940 &&
        o.py <= 1220 &&
        o.px > 280 &&
        o.leftPx < 900 &&
        !/^(品牌|正品险|免费服务|退货包运费|7天无理由|假一赔十|\d+)$/.test(o.text) &&
        !/100%保障|官方正品/.test(o.text)
    )
    .sort((a, b) => a.py - b.py)
    .map((o) => cleanSkuSpecText(o.text))
    .filter(Boolean);

  let checkoutSpec = cleanSkuSpecText(fallbackSpec);
  if ((!checkoutSpec || checkoutSpec.length <= 2) && specLines.length > 0) {
    checkoutSpec = specLines[0].replace(/\.\.\.$|…$/, "").trim();
  }

  const discountLine = obs.find((o) => /已自动领取|店铺优惠|领券|已享.*折/.test(o.text))?.text || "";
  const finalPrice = postCouponPrice && postCouponPrice > 0 ? parseFloat(postCouponPrice.toFixed(2)) : parseFloat(fallbackPrice.toFixed(2));

  return {
    ok: true,
    postCouponPrice: finalPrice,
    checkoutSpec: checkoutSpec || cleanSkuSpecText(fallbackSpec),
    discountDesc: discountLine,
  };
}

function isLowStockRawText(txt) {
  return /最后\s*\d+\s*件|仅剩\s*\d+\s*件|剩\s*\d+\s*件|即将售罄|库存紧张|限购\s*1\s*件/.test(String(txt || ""));
}

function parseDrawerSkuCandidates(obs) {
  const candidates = [];

  const rawSelectedJoined = obs
    .filter((o) => o.py >= 930 && o.py <= 1125 && o.px > 380)
    .map((o) => o.text)
    .join(" ");
  const selectedLines = obs
    .filter((o) => o.py >= 930 && o.py <= 1125 && o.px > 380)
    .sort((a, b) => a.py - b.py)
    .map((o) => cleanSkuSpecText(o.text.replace(/^已选[:：]\s*/, "")))
    .filter(Boolean);
  const selectedSpec = cleanSkuSpecText(selectedLines.join("").replace(/…|\.\.\.$/, ""));

  let headerPrice = null;
  for (const o of obs) {
    if ((o.py >= 730 && o.py <= 925 && o.px > 380) || o.py >= 2440) {
      const m =
        o.text.match(/(?:折后|券后|一口价|限量低价|仅|提交订单|立即支付)\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)/) ||
        o.text.match(/[¥￥]\s*(\d+(?:\.\d{1,2})?)/);
      if (m) {
        headerPrice = parseFloat(m[1]);
        break;
      }
    }
  }
  if (!isLowStockRawText(rawSelectedJoined) && selectedSpec && selectedSpec.length >= 2 && headerPrice && headerPrice > 0) {
    candidates.push({
      spec: selectedSpec,
      price: headerPrice,
      px: null,
      py: null,
      isDefaultSelected: true,
    });
  }

  const bodyLines = obs
    .filter(
      (o) =>
        o.py >= 1360 &&
        o.py <= 2310 &&
        !isLowStockRawText(o.text) &&
        !/^(款式|颜色|型号|口味|规格|尺码|尺寸|优惠|店铺券|使用|多多支付|更换支付|数量)/.test(o.text) &&
        !/^(最多人选择|零差评|\d+%人选择|热销.*经典款|1\s*\+?|十)$/.test(o.text)
    )
    .sort((a, b) => a.py - b.py);

  for (let i = 0; i < bodyLines.length; i++) {
    const cur = bodyLines[i];
    const inlinePrice = cur.text.match(/^(.*?)\s*[¥￥]\s*(\d+(?:\.\d{1,2})?)\s*$/);
    if (inlinePrice) {
      const sp = cleanSkuSpecText(inlinePrice[1]);
      if (sp.length >= 2) {
        candidates.push({
          spec: sp,
          price: parseFloat(inlinePrice[2]),
          px: cur.px,
          py: cur.py,
          isDefaultSelected: false,
        });
        continue;
      }
    }
    const next = bodyLines[i + 1];
    if (next && next.py - cur.py >= 18 && next.py - cur.py <= 105) {
      const nextOnlyPrice = next.text.match(/^[¥￥]\s*(\d+(?:\.\d{1,2})?)$/);
      const sp = cleanSkuSpecText(cur.text);
      if (nextOnlyPrice && sp.length >= 2) {
        candidates.push({
          spec: sp,
          price: parseFloat(nextOnlyPrice[1]),
          px: cur.px,
          py: cur.py,
          isDefaultSelected: false,
        });
        i++;
      }
    }
  }

  return candidates;
}

// Dynamically locate 销量 tab and real product card coordinates below sort/filter bar!
async function sortBySalesAndGetCardTargets() {
  let obs = capturePhoneAndOcr("/tmp/pdd_sr_cur.png");
  const salesTab = obs.find((o) => o.text === "销量" && o.py > 260 && o.py < 1380);
  if (salesTab) {
    adb(`input tap ${salesTab.px} ${salesTab.py}`);
    await sleep(jitter(900, 300));
    obs = capturePhoneAndOcr("/tmp/pdd_sr_sorted.png");
  }

  const sortAnchorY = Math.max(
    360,
    ...obs.filter((o) => /^(综合|销量|价格|品牌)/.test(o.text) && o.py < 1450).map((o) => o.py)
  );
  const minCardY = sortAnchorY + 220;

  // Locate product cards via price / 已拼 lines below minCardY (avoiding 旗舰店 / 进店 banners)
  const cardAnchors = obs
    .filter(
      (o) =>
        o.py >= minCardY + 180 &&
        o.py <= 2460 &&
        (/[¥￥]\s*\d/.test(o.text) || /已拼\d/.test(o.text)) &&
        !/参考价/.test(o.text)
    )
    .sort((a, b) => a.py - b.py);

  const targets = [];
  for (const a of cardAnchors) {
    const colX = a.px < 608 ? 300 : 910;
    const tapY = Math.max(minCardY, a.py - 220);
    if (!targets.some(([tx, ty]) => tx === colX && Math.abs(ty - tapY) < 380)) {
      targets.push([colX, tapY]);
    }
    if (targets.length >= 4) break;
  }

  if (targets.length === 0) {
    const y1 = Math.min(2050, minCardY + 260);
    targets.push([300, y1], [910, y1]);
    if (y1 + 780 <= 2350) {
      targets.push([300, y1 + 780], [910, y1 + 780]);
    }
  }
  return targets;
}

function flushToExcel() {
  try {
    const out = execSync(`python3 "${FLUSH_SCRIPT_PATH}"`, { encoding: "utf8", timeout: 40000 });
    console.log(out.trim());
  } catch (e) {
    console.error("[Excel] Flush error:", e.message);
  }
}

async function runSourcingLoop() {
  const srcPath = fsSync.existsSync(QNH_FIXED_PATH) ? QNH_FIXED_PATH : QNH_FALLBACK_PATH;
  const rawItems = JSON.parse(await fs.readFile(srcPath, "utf8"));

  const byRow = new Map();
  for (const it of rawItems) {
    const r = Number(it.row);
    if (r >= 49 && r <= 2791 && !byRow.has(r)) byRow.set(r, it);
  }
  const allItems = [...byRow.values()].sort((a, b) => a.row - b.row);
  console.log(`[Phone Worker v3] Loaded ${allItems.length} unique rows (49..2791).`);

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
  console.log(`[Phone Worker v3] Grouped into ${spuGroups.length} unique SPUs.`);

  let progress = {};
  try {
    progress = JSON.parse(await fs.readFile(PROGRESS_PATH, "utf8"));
  } catch {}

  adb("svc power stayon true && input keyevent 224");
  await sleep(400);
  await clearPhoneFavorites();

  let newMatchesSinceFlush = 0;
  let consecutiveSoldOutWall = 0;
  let processedSpuSinceRest = 0;

  for (let gIdx = 0; gIdx < spuGroups.length; gIdx++) {
    const grp = spuGroups[gIdx];
    const pendingRows = grp.rows.filter((r) => !progress[String(r.row)]?.status);
    if (pendingRows.length === 0) continue;

    if (processedSpuSinceRest > 0 && processedSpuSinceRest % 25 === 0) {
      console.log(`[Anti-Risk] Resting 6s after ${processedSpuSinceRest} SPUs...`);
      await sleep(jitter(6000, 2000));
    }
    processedSpuSinceRest++;

    const lead = pendingRows[0];
    const searchKws = cleanKeywords(lead);

    console.log(`\n==================================================`);
    console.log(`[SPU ${gIdx + 1}/${spuGroups.length}] Rows [${pendingRows.map((r) => r.row).join(",")}] | ${lead.excelName}`);
    for (const r of pendingRows) {
      const rt = Number(r.suggestPrice || r.basicPrice || 0);
      console.log(`  - Row ${r.row} (${r.excelSpec}): 原价 ¥${rt} | 半价红线 <= ¥${(rt * 0.5).toFixed(2)}`);
    }

    const seenGoodsIds = new Set();

    for (const kw of searchKws) {
      const rem0 = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
      if (rem0.length === 0) break;

      console.log(`  >>> [搜索] "${kw}"`);
      const encoded = encodeURIComponent(kw);
      adb(`am start --activity-clear-top -a android.intent.action.VIEW -d 'pinduoduo://com.xunmeng.pinduoduo/search_result.html?search_key=${encoded}'`);
      await sleep(jitter(1650, 500));

      const cardTargets = await sortBySalesAndGetCardTargets();

      for (const [cx, cy] of cardTargets) {
        const rem = pendingRows.filter((r) => progress[String(r.row)]?.status !== "MATCHED");
        if (rem.length === 0) break;

        adb(`input tap ${cx} ${cy}`);
        await sleep(jitter(1450, 450));

        const st = getPhoneTopBundle();
        if (!st.inPdd) {
          adb(`am start --activity-clear-top -a android.intent.action.VIEW -d 'pinduoduo://com.xunmeng.pinduoduo/search_result.html?search_key=${encoded}'`);
          await sleep(1400);
          continue;
        }
        if (!st.isGoodsPage || !st.goodsId) {
          // Probably tapped a store banner -> press back if navigated away
          if (/mall_page|subject/.test(st.lastBundle)) {
            adb("input keyevent 4");
            await sleep(700);
          }
          continue;
        }

        const goodsId = st.goodsId;
        const mainPic = st.thumbUrl || "";
        if (!isValidNumericId(goodsId) || seenGoodsIds.has(goodsId)) {
          adb("input keyevent 4");
          await sleep(600);
          continue;
        }
        seenGoodsIds.add(goodsId);

        const goodsPageObs = capturePhoneAndOcr("/tmp/pdd_goods_cur.png");
        const allGoodsScreenText = goodsPageObs.map((o) => o.text).join(" ");

        // CIRCUIT BREAKER: Check for PDD detail-page throttle ("商品已售罄，推荐以下相似商品") or verification slider!
        if (/请完成验证|滑动验证|安全验证|账号登录/.test(allGoodsScreenText)) {
          console.error(`[CIRCUIT_BREAKER] 检测到拼多多验证/登录拦截，立即安全暂停保护进度！`);
          flushToExcel();
          process.exit(42);
        }
        if (/商品已售罄.*推荐以下相似商品|商品已下架/.test(allGoodsScreenText)) {
          consecutiveSoldOutWall++;
          console.warn(`    [风控预警] 商品 ${goodsId} 返回 "商品已售罄，推荐以下相似商品" (连续 ${consecutiveSoldOutWall}/3)`);
          adb("input keyevent 4");
          await sleep(700);
          if (consecutiveSoldOutWall >= 3) {
            console.error(
              `[CIRCUIT_BREAKER] 连续 3 个在售商品详情页返回 "商品已售罄，推荐以下相似商品"，当前买家号详情页已被限流！安全熔断退出（绝不污染未匹配标记）。`
            );
            flushToExcel();
            process.exit(43);
          }
          continue;
        }
        consecutiveSoldOutWall = 0;

        const goodsTitleText = goodsPageObs
          .filter((o) => o.py >= 1150 && o.py <= 2350)
          .map((o) => o.text)
          .join(" ");

        // Open SKU drawer
        adb("input tap 900 2500");
        await sleep(jitter(1300, 350));

        let drawerObs = capturePhoneAndOcr("/tmp/pdd_drawer_cur.png");

        const listToggle = drawerObs.find((o) => o.px > 920 && o.py > 1150 && o.py < 1550 && /列表/.test(o.text));
        if (listToggle) {
          adb(`input tap ${listToggle.px} ${listToggle.py}`);
          await sleep(650);
          drawerObs = capturePhoneAndOcr("/tmp/pdd_drawer_list.png");
        }

        const hasDrawerDiscount = drawerObs.some((o) => /店铺券\s*-\s*\d|已优惠/.test(o.text));
        const drawerCouponBtn = drawerObs.find(
          (o) => o.py > 1150 && o.py < 1600 && /领券|可领|点击领/.test(o.text) && !/店铺券\s*-/.test(o.text)
        );
        if (!hasDrawerDiscount && drawerCouponBtn) {
          adb(`input tap ${drawerCouponBtn.px} ${drawerCouponBtn.py}`);
          await sleep(900);
          const popObs = capturePhoneAndOcr("/tmp/pdd_drawer_cpop.png");
          for (const b of popObs.filter((o) => o.py > 700 && o.py < 2300 && /^(领取|立即领券|一键领取)$/.test(o.text)).slice(0, 2)) {
            adb(`input tap ${b.px} ${b.py}`);
            await sleep(550);
          }
          adb("input keyevent 4");
          await sleep(700);
          drawerObs = capturePhoneAndOcr("/tmp/pdd_drawer_after_c.png");
        }

        let skuCands = parseDrawerSkuCandidates(drawerObs);
        let didScrollDrawer = false;

        for (const rowItem of rem) {
          const rowKey = String(rowItem.row);
          const retail = Number(rowItem.suggestPrice || rowItem.basicPrice || 0);
          if (retail <= 0) continue;
          const maxUnitPrice = parseFloat((retail * 0.5).toFixed(2));

          const findBestInCands = (cands) => {
            const valid = [];
            for (const c of cands) {
              if (!c.price || isNaN(c.price) || c.price <= 0) continue;
              if (!isSpecCompatible(rowItem.excelName, rowItem.excelSpec, goodsTitleText, c.spec)) continue;
              const ratio = computeRatio(rowItem.excelName, rowItem.excelSpec, c.spec);
              const unitP = parseFloat((c.price / ratio).toFixed(2));
              if (unitP <= maxUnitPrice || c.price <= maxUnitPrice * ratio + 2) {
                valid.push({ ...c, ratio, unitP });
              }
            }
            valid.sort((a, b) => a.unitP - b.unitP);
            return valid[0] || null;
          };

          let bestCand = findBestInCands(skuCands);
          if (!bestCand && !didScrollDrawer && skuCands.length >= 3) {
            adb("input swipe 600 2180 600 1580 280");
            await sleep(650);
            didScrollDrawer = true;
            const scrolledObs = capturePhoneAndOcr("/tmp/pdd_drawer_scroll.png");
            skuCands = parseDrawerSkuCandidates(scrolledObs);
            bestCand = findBestInCands(skuCands);
          }

          if (!bestCand) continue;

          if (!bestCand.isDefaultSelected && bestCand.px && bestCand.py) {
            adb(`input tap ${bestCand.px} ${bestCand.py}`);
            await sleep(600);
            const selObs = capturePhoneAndOcr("/tmp/pdd_drawer_sel.png");
            const fullSel = cleanSkuSpecText(
              selObs
                .filter((o) => o.py >= 930 && o.py <= 1125 && o.px > 380)
                .sort((a, b) => a.py - b.py)
                .map((o) => o.text.replace(/^已选[:：]\s*/, "").trim())
                .join("")
            );
            if (fullSel && fullSel.length > bestCand.spec.length && !fullSel.endsWith("…")) {
              bestCand.spec = fullSel;
            }
          }

          adb("input tap 1135 359");
          await sleep(480);
          adb("input tap 263 2500");
          await sleep(800);

          let extractedSkuId = null;
          let postCouponTotal = null;
          let finalSpec = cleanSkuSpecText(bestCand.spec);
          let discountDesc = "";

          try {
            adb("am start --activity-clear-top -a android.intent.action.VIEW -d 'pinduoduo://com.xunmeng.pinduoduo/likes.html'");
            await sleep(1500);
            adb("input tap 67 790");
            await sleep(480);
            adb("input tap 980 2530");
            await sleep(1650);

            const ckState = getPhoneTopBundle();
            if (ckState.isCheckoutPage && isValidNumericId(ckState.skuId)) {
              extractedSkuId = ckState.skuId;
              const verifyRes = await phoneVerifyCheckoutClaimCouponAndReadPrice(
                goodsId,
                extractedSkuId,
                bestCand.price,
                bestCand.spec
              );
              if (verifyRes.ok) {
                postCouponTotal = verifyRes.postCouponPrice;
                finalSpec = verifyRes.checkoutSpec || finalSpec;
                discountDesc = verifyRes.discountDesc;
              }
            }
          } finally {
            await clearPhoneFavorites();
          }

          if (extractedSkuId && postCouponTotal !== null && isSpecCompatible(rowItem.excelName, rowItem.excelSpec, goodsTitleText, finalSpec)) {
            const finalRatio = computeRatio(rowItem.excelName, rowItem.excelSpec, finalSpec);
            const finalUnitPrice = parseFloat((postCouponTotal / finalRatio).toFixed(2));
            console.log(
              `    [结算核验] Row ${rowKey} | gid=${goodsId} sid=${extractedSkuId} | 规格="${finalSpec}" | 实付=¥${postCouponTotal} | 比例=${finalRatio} | 单价=¥${finalUnitPrice} (上限<=¥${maxUnitPrice})`
            );

            if (finalUnitPrice <= maxUnitPrice) {
              progress[rowKey] = {
                row: rowItem.row,
                spuId: rowItem.spuId,
                skuId: rowItem.skuId,
                goods_id: goodsId,
                goods_url: `https://mobile.yangkeduo.com/goods.html?goods_id=${goodsId}`,
                sku_id: extractedSkuId,
                sku_specs: finalSpec || "默认规格",
                checkout_url: `https://mobile.yangkeduo.com/order_checkout.html?goods_id=${goodsId}&sku_id=${extractedSkuId}&goods_number=1`,
                ratio: finalRatio,
                group_price: postCouponTotal,
                unit_price: finalUnitPrice,
                retail_price: retail,
                discount_desc: discountDesc,
                main_pic: mainPic,
                coupon_checked: true,
                status: "MATCHED",
              };
              await fs.writeFile(PROGRESS_PATH, JSON.stringify(progress, null, 2), "utf8");
              newMatchesSinceFlush++;
              console.log(`    ★ 成功匹配 Row ${rowKey}! 券后单价 ¥${finalUnitPrice} <= ¥${maxUnitPrice}`);
              if (newMatchesSinceFlush >= 10) {
                flushToExcel();
                newMatchesSinceFlush = 0;
              }
            }
          }

          if (pendingRows.some((r) => progress[String(r.row)]?.status !== "MATCHED")) {
            adb(`am start --activity-clear-top -a android.intent.action.VIEW -d 'pinduoduo://com.xunmeng.pinduoduo/search_result.html?search_key=${encoded}'`);
            await sleep(jitter(1450, 350));
            await sortBySalesAndGetCardTargets();
          }
        }

        const curSt = getPhoneTopBundle();
        if (curSt.hasDrawer) {
          adb("input tap 1135 359");
          await sleep(400);
        }
        if (getPhoneTopBundle().isGoodsPage) {
          adb("input keyevent 4");
          await sleep(600);
        }
      }
    }

    for (const r of pendingRows) {
      const rk = String(r.row);
      if (progress[rk]?.status !== "MATCHED") {
        progress[rk] = {
          row: r.row,
          spuId: r.spuId,
          skuId: r.skuId,
          retail_price: Number(r.suggestPrice || r.basicPrice || 0),
          status: "UNMATCHED_ABOVE_THRESHOLD",
        };
      }
    }
    await fs.writeFile(PROGRESS_PATH, JSON.stringify(progress, null, 2), "utf8");
  }

  flushToExcel();
  console.log("\nALL 2743 ROWS PROCESSED ON PHONE!");
}

if (import.meta.url === `file://${process.argv[1]}`) {
  runSourcingLoop().catch((e) => {
    console.error("Fatal phone worker v3 error:", e);
    process.exit(1);
  });
}
