/**
 * 包装语义解析与单位对齐核心算法 (Unit Alignment Engine)
 * 解决门店基础包装与供货商大包装/散片/多包的对齐换算问题。
 */

export function cleanSkuSpecText(rawSpec) {
  return String(rawSpec || "")
    .replace(/^[•·🔥✓✔\s]+/, "")
    .replace(/^(?:已选[:：]\s*|已包邮\s*)/, "")
    .replace(/\s*(?:快要抢光|最后\d+件|仅剩\d+件|11\.11官方补贴[，,]?限购\d+件|最多人选择|热销\d+.*)$/g, "")
    .replace(/\s*(?:1\s*[+＋|｜]\s*\+?|[+＋]|十)\s*$/g, "")
    .trim();
}

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

export const DURABLE_GOODS_RE =
  /菜板|案板|砧板|剪刀|剪子|美工刀|壁纸刀|水龙头|雨伞|雨衣|生料带|锅|盆|杯|碗|盘|刀|架|锁|箱|包|椅|凳|马扎|球拍|羽毛球拍|网球拍|乒乓球拍|奶瓶|冲洗器|清洗器|套圈|修正带|数据线|充电器|充电头|插座|插排|手表|手环|手电筒|收纳盒|收纳架|挂钩|镜子|梳子|指甲刀|指甲剪|耳挖|手电|放大镜|计算器|电子秤|皮尺|卷尺|温度计|温湿度计/;

/**
 * 提取门店基础包装信息
 */
export function extractStorePackDetails(storeName, storeSpec) {
  const combined = (storeName || "") + " " + (storeSpec || "");
  const isDurable = DURABLE_GOODS_RE.test(storeName || "") && !/纸|巾|签|袋|膜|套|垫|片|粒|包|条|袜/.test(storeSpec || "");

  let innerCount = null;
  let innerUnit = null;
  let outerCount = 1;
  let outerUnit = "";

  const mInner1 = combined.match(
    /(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只|条|双)\s*(?:[/／每装*xX×]|(?:装\s*[*xX×]?\s*1?))\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|份|条|双)/
  );
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
    const mInner2 = combined.match(
      /(?:约|共|装|家庭装|超值装)?\s*(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴)\s*(?:装)?\s*[/／]\s*(包|袋|盒|提|卷|卡|份)/
    );
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
      const mOuter = combined.match(/(?<![.\d])(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|副|双|对|把|台|本|个|条)(?![a-zA-Z\d])/);
      if (mOuter) {
        outerCount = parseInt(mOuter[1], 10);
        outerUnit = mOuter[2];
      }
    }
  }

  return { isDurable, innerCount, innerUnit, outerCount, outerUnit };
}

/**
 * 提取供货商规格与包装信息
 */
export function extractSupplierPackDetails(supplierSpec, supplierTitle) {
  const cleanedSpec = stripDimensionExpressions(cleanSkuSpecText(supplierSpec));
  const cleanedTitle = stripDimensionExpressions(supplierTitle || "");

  // 是否为显式单包（如 120片/包, 1包, 单包, 60抽单包, 【80片装】1包）
  const isExplicitSinglePack =
    /(?:单[包盒袋瓶罐提]|1[包盒袋瓶罐提]|装\*1[包盒袋瓶罐提]?|\/包|\/盒|\/袋|\/罐|\/提)(?![a-zA-Z\d])/.test(cleanedSpec) &&
    !/(?:[2-9]|\d{2,})\s*(?:包|盒|袋|瓶|罐|提|箱)/.test(cleanedSpec);

  // 复合包装匹配 (如 3包【共240片】, 240片【3包】, 600支【3盒装】)
  const mCompound1 = cleanedSpec.match(
    /(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套)\s*(?:装)?(?:[【\[（(]?\s*(?:共|到手|实发)?\s*(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只|条|双))?/
  );
  const mCompound2 = cleanedSpec.match(
    /(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只|条|双)\s*[【\[（(]?\s*(?:共|实发|到手)?\s*(\d+)\s*(包|袋|盒|箱|提|卷)/
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

  // 乘号整件匹配 (*24罐, *24, 250ml*24罐)
  if (!outerCount) {
    const mMult = cleanedSpec.match(/[*xX×]\s*(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|瓶|听|双|副|条|个|把|支|张|片)?/);
    if (mMult) {
      const val = parseInt(mMult[1], 10);
      const unit = mMult[2] || "";
      if (/包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套|瓶|听|双|副|条|个|把/.test(unit)) {
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

  // 常规外包装包数匹配 (共3包, 到手5盒, 24瓶整箱)
  if (!outerCount && !isExplicitSinglePack) {
    const mOuter = cleanedSpec.match(/(?:共|合计|实发|到手|整箱)?\s*(\d+)\s*(包|袋|盒|箱|提|罐|瓶|桶|卷|卡|板|打|套)(?:装)?(?![a-zA-Z\d])/);
    if (mOuter) {
      outerCount = parseInt(mOuter[1], 10);
      outerUnit = mOuter[2];
    }
  }

  // 散装总片数匹配 (240片, 480片, 600支, 20节, 75片, 1000只)
  if (!innerTotal) {
    const mInner = cleanedSpec.match(/(?<![.\d])(\d+)\s*(片|抽|张|支|枚|颗|粒|节|贴|只)(?:装)?(?![a-zA-Z\d])/);
    if (mInner) {
      innerTotal = parseInt(mInner[1], 10);
      innerUnit = mInner[2];
    }
  }

  return { isExplicitSinglePack, outerCount, outerUnit, innerTotal, innerUnit, cleanedSpec };
}

/**
 * 换算比率计算核心函数
 * 计算供货商当前规格相当于门店销售单元的多少倍 (N)
 */
export function computeRatio(storeName, storeSpec, supplierSpec, supplierTitle) {
  const store = extractStorePackDetails(storeName, storeSpec);
  const sup = extractSupplierPackDetails(supplierSpec, supplierTitle);

  // 1. 耐用品保护：坚决不除以附赠散片/袋数
  if (store.isDurable) {
    if (sup.outerCount && sup.outerCount > 1 && /个|把|副|张|台|本/.test(sup.outerUnit || "")) {
      return sup.outerCount;
    }
    return 1;
  }

  // 2. 供货商为显式单包装
  if (sup.isExplicitSinglePack) {
    return 1;
  }

  // 3. 门店含有内含件数 (如 80片/包, 60抽/包, 200支/盒)
  if (store.innerCount && store.innerCount > 0) {
    // 3a. 供货商给出外包装数 (如 3包, 6盒, 3包【共240片】)
    if (sup.outerCount && sup.outerCount >= 1) {
      return Math.max(1, Math.round(sup.outerCount / (store.outerCount || 1)));
    }
    // 3b. 供货商仅给出总片数 (如 240片, 480片, 600支)
    if (sup.innerTotal && sup.innerTotal >= store.innerCount) {
      const ratio = sup.innerTotal / store.innerCount;
      return Math.max(1, Math.round(ratio));
    }
    return 1;
  }

  // 4. 门店无内含片数，但供货商有多件外包装 (如 24罐 vs 1罐, 3包 vs 1包)
  if (sup.outerCount && sup.outerCount > 1) {
    return Math.max(1, Math.round(sup.outerCount / (store.outerCount || 1)));
  }

  // 5. 对称成双品散只换算 (1双 vs 1000只 -> 500双)
  const isPairStore = /双|对/.test(store.outerUnit || "") || /拖鞋|手套|袜|耳环|鞋垫/.test(storeName || "");
  if (isPairStore && sup.innerUnit === "只" && sup.innerTotal && sup.innerTotal >= 2) {
    return Math.max(1, Math.round(sup.innerTotal / 2));
  }

  return 1;
}
