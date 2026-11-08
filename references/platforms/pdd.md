# 拼多多采购端平台总入口 (PDD Sourcing Platform)

本文件是第 1 层平台入口，用于引导 Agent 快速进入拼多多商品自动化寻源、同 SPU 多规格聚合提取、相似品核验、真实结算链接合成与标准六列回填流程。

---

## 一、 平台定位与三级极速通道优先级（速率拉满）

- **平台定位**：上游采购寻源与成本控制端（买家视角，直接对接 `mobile.yangkeduo.com` 与移动端 App）。
- **Step 0 必做（同 SPU 多 SKU 预聚合，提速 300%~500%）**：
  - 执行任何检索或图片流转前，**必须先按 `SPUID` 聚合表格内所有 SKU 行**；
  - 同一 SPU 下无论包含多少个子 SKU（如多尺码拖鞋、多码数内裤、多克重商品），**上游主图只获取 1 次、拼多多只搜索 1 次、商品详情页只进入 1 次**，从底层 `window.rawData.store.initDataObj.goods.skus` 一次性拉取全量规格并在内存完成所有子 SKU 的成对匹配。
- **三级极速执行通道（按速率由高到低优先选用）**：
  1. **通道 A（最快首选，~1.2s/SPU）：Chrome CDP 白盒直提模式（`cdp_whitebox`）**
     - 直接依附（Attach）本地已登录拼多多的常规 Chrome（CDP 端口 `9222`，严禁新启带 `--enable-automation` 的受控实例）；
     - 导航搜索页或详情页后，直接读取页面全局变量 `window.rawData.store.initDataObj.goods`，**零 UI 弹窗点击**即可毫秒级拿到真实 `goods_id` 与全量 `skus`（含真实 `sku_id`、`specs`、`group_price`）。
  2. **通道 B（以图搜图/App 原生通道，~0.1s~2.0s/SPU）：Android ADB 白盒与单件原子流模式（`usb_debug`）**
     - **有图搜同款**：走【相册单件原子流】（`pdd_task_tmp_` 前缀传一张 ➔ 广播刷新 ➔ `pinduoduo://.../search_image_capture.html` 搜一张 ➔ `finally` 块强制物理删一张并刷新媒体库）；
     - **无图搜关键词**：走 DeepLink `pinduoduo://com.xunmeng.pinduoduo/search_result.html?search_key=...` 0.1s 秒开搜索页；
     - **ADB 内存直提**：限定包名执行 `adb shell "dumpsys activity com.xunmeng.pinduoduo"`（105ms 极速返回，严禁不带包名跑全局 `dumpsys activity top`）。
     - **前台礼貌守则**：若用户正在手机前台高频使用微信等个人应用，优先走通道 A（Chrome CDP），避免抢占手机屏幕焦点。
  3. **通道 C（高对抗防风控兜底）：ESP32 物理拟真 + 预编译原生 OCR 模式（`esp32_physical`）**
     - 当触发人机滑块或强风控拦截时，自动降级至 ESP32-S3 BLE HID 物理鼠标点击 + 跨屏剪贴板；
     - **OCR 极速铁律**：必须将 `scripts/vision_ocr.swift` 预编译为二进制（`swiftc scripts/vision_ocr.swift -O -o /tmp/mac_ocr`），单次识别耗时从 2.0s 降至 **50ms**。

---

## 二、 核心任务能力与按需加载链路

- **采购比价与相似品多模态核验 (`sourcing_and_similar_product_matching`, `implemented`)**：
  1. 第 1 层（本文件）：`references/platforms/pdd.md`
  2. 第 2 层（任务规范与六列交付 Schema）：[`references/tasks/sourcing-and-similar-product-matching.md`](../tasks/sourcing-and-similar-product-matching.md)
  3. 第 3 层（实战规程与代码配方）：[`references/platforms/pdd-sourcing-playbook.md`](pdd-sourcing-playbook.md)
  4. 自动化执行引擎与校验器：`scripts/pdd_sourcing_engine.py`

---

## 三、 平台最高致命红线（违者直接导致链接报排队或成本严重失真）

1. **【红线 1：绝对禁止算法伪造/推算 `goods_id` 或 `sku_id`（“排队中”唯一根因）】**
   - 拼多多后端 WAF 对不存在的 `goods_id` 或无效的 `sku_id` **绝不返回 404，而是 100% 强制重定向至“当前访问人数较多，排队中”拦截页**；
   - 严禁通过哈希、数字推算或占位符拼凑 ID！所有 ID 必须 100% 从真实详情页 `window.rawData.store.initDataObj.goods` 或真实 ADB Activity 内存中提取，且满足纯数字格式校验（`^\d+$`）。
2. **【红线 2：标准结算链接极简合同（严禁携带 `group_id`）】**
   - 唯一合法结算链接格式：
     `https://mobile.yangkeduo.com/order_checkout.html?goods_id={goods_id}&sku_id={sku_id}&goods_number=1`
   - **绝对禁止附带失效或编造的 `group_id`**；批量回填后必须抽样在已登录 Chrome CDP 中实测打开，确认页面包含 `立即支付 / 实付款` 且不含 `当前访问人数较多，排队中`。
3. **【红线 3：采购价格单位防除以 100 陷阱】**
   - 在 `window.rawData.store.initDataObj.goods.skus[i]` 中，**`group_price` 与 `normal_price` 原生就是以“元”为单位的字符串（如 `"33.90"`、`"44.00"`）**，直接 `parseFloat(s.group_price)` 即可，**绝对禁止除以 100**！（注：仅商品根节点的 `min_on_sale_group_price` 为分，子规格 `skus[i].group_price` 恒为元）。
4. **【红线 4：搜索结果页防误点店铺装修横幅（`mall_page.html`）】**
   - 搜索结果顶部可能存在品牌店铺广告横幅（点击会跳往 `mall_page.html` 导致无 `goods` 数据）；定位商品卡片时必须过滤 `rect.top > 200` 且 `rect.width > 100`，排除含 `mall_page.html` 的节点。
5. **【红线 5：相册零污染单件原子流与四重防误删锁】**
   - 传一张 ➔ 搜一张 ➔ `finally` 销毁一张；临时图必须严格以 **`pdd_task_tmp_`** 开头，严禁使用通配符，绝不触碰用户个人照片。
6. **【红线 6：物理装量/净含量与单位 100% 绝对一致（一票否决项）及六列标准交付】**
   - 严禁不同克重、容量、只数错配；标准回填 `F列（拼多多商品链接）`、`G列（拼多多规格，多规格以“；”分隔）`、`H列（结算链接）`、`I列（下单比例）`、`J列（采购价）`、`K列（单位采购价 =ROUND(J{row}/I{row}, 2)）`。
