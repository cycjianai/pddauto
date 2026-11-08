# 拼多多采购端实战规程与三级极速架构指南 (PDD Sourcing Playbook)

本文件是第 3 层深度实战合同，定义拼多多采购寻源、同 SPU 多规格一次性提取、真实结算链接（`order_checkout.html`）合成、相册单件原子流搜图及防风控自愈的底层技术细节与可直接复用的代码配方。

---

## 一、 三级极速架构对比与自动调度准则（速率拉到最高）

`PDDSourcingEngine` 支持三种执行通道，实战中严格按 **通道 A ➔ 通道 B ➔ 通道 C** 优先级调度：

| 对比维度 | 通道 A：Chrome CDP 白盒直提 (`cdp_whitebox`，首选最快) | 通道 B：USB 调试 ADB 白盒与原子流搜图 (`usb_debug`) | 通道 C：ESP32 物理拟真 + 原生 OCR (`esp32_physical`，防风控兜底) |
| :--- | :--- | :--- | :--- |
| **底层通道** | WebSocket 直连本机已登录常规 Chrome（端口 `9222`） | Android ADB 调试协议 + Intent DeepLink + Activity 内存转储 | ESP32-S3 BLE HID 物理蓝牙鼠标 + 投屏 + 预编译 `mac_ocr` |
| **核心优势** | **无需操作手机屏幕、不打扰用户日常使用手机**；直接读取 JS 内存 `window.rawData`，一次性拿出全部子规格 | 支持调用拼多多 App 原生**相册以图搜图**（`search_image_capture.html`），同款视觉识别极准 | **纯物理外设零系统调试特征**，可完美穿透高对抗人机滑块与设备指纹风控 |
| **单 SPU 耗时** | **~1.2 ~ 1.5 秒/SPU**（含同 SPU 下全部子 SKU 一次性匹配） | **关键词 0.1s 秒开 + 105ms 内存提取**；以图搜图约 **2.0s/SPU** | **2.5 ~ 3.5 秒/SPU**（配合预编译 `mac_ocr` 50ms 视觉识别） |
| **规格与价格获取** | 直读 `window.rawData.store.initDataObj.goods.skus`（零点击弹窗） | WebView 内存 / `dumpsys activity com.xunmeng.pinduoduo` | 点击分享复制短链 ➔ 302 还原 `goods_id` ➔ CDP/服务端提取规格 |

---

## 二、 通道 A 实战配方：Chrome CDP `window.rawData` 极速白盒提取（首选）

当本机常规 Chrome（端口 `9222`）已登录拼多多移动端网页（`mobile.yangkeduo.com`）时，无需点击任何规格弹窗，直接通过以下代码一次性提取真实 `goods_id` 与全量在售 `skus`：

### 1. 搜索结果页防误点店铺横幅（`mall_page.html`）铁律
在 `search_result.html?search_key=...` 页面定位首个有效商品卡片时，顶部可能存在品牌店铺横幅广告（点击会跳转到 `mall_page.html` 导致无商品数据）。必须执行以下过滤：
```javascript
// 过滤顶部店铺横幅广告 (rect.top > 200) 并排除 mall_page.html
const imgs = Array.from(document.querySelectorAll('img')).filter(img => {
  const r = img.getBoundingClientRect();
  const a = img.closest('a');
  const href = a ? a.href : '';
  return r.width > 100 && r.height > 100 && r.top > 200 && !href.includes('mall_page.html');
});
if (imgs.length > 0) imgs[0].click();
```

### 2. 商品详情页 `window.rawData` 一次性全规格提取配方
进入 `https://mobile.yangkeduo.com/goods.html?goods_id=...` 后，直接执行：
```javascript
(() => {
  const g = window?.rawData?.store?.initDataObj?.goods;
  if (!g || !g.goods_id) return { ok: false, error: 'rawData_goods_missing' };
  const goodsId = String(g.goods_id);
  const skus = (g.skus || [])
    .filter(s => s.is_onsale !== 0 && (s.quantity === undefined || s.quantity > 0))
    .map(s => ({
      sku_id: String(s.sku_id),
      // 多规格严格以中文分号 "；" 拼接
      specs: (s.specs || []).map(sp => sp.spec_value).join('；'),
      // ★ 铁律：s.group_price 原生已是【元】为单位的字符串（如 "33.90"），严禁除以 100！
      group_price: parseFloat(s.group_price),
      normal_price: parseFloat(s.normal_price || s.group_price),
      thumb_url: s.thumb_url || ''
    }));
  return {
    ok: true,
    goods_id: goodsId,
    goods_name: g.goods_name || '',
    goods_url: `https://mobile.yangkeduo.com/goods.html?goods_id=${goodsId}`,
    skus
  };
})();
```

---

## 三、 通道 B 实战配方：相册“单件原子流”以图搜图与防误删四重锁

当货盘商品需要通过图片视觉寻找同款且使用 Android ADB 时，必须严格遵循**单件原子流（Single Piece Flow）**与**防误删四重安全锁**：

### 1. 相册零污染“单件原子流”生命周期
- **严禁批量堆积上传**：绝对禁止一次性把几十张商品图塞入手机相册；
- **原子闭环**：
  $$\text{下载单张主图} \to \text{ADB Push } \texttt{pdd\_task\_tmp\_\{ts\}.jpg} \to \text{广播刷新媒体库} \to \text{DeepLink 呼起拍照搜图并选第1张} \to \texttt{finally} \text{ 立即物理销毁并刷新}$$
- **相册中永远至多只存在 1 张临时业务图**，搜图完成后 10ms 内物理蒸发。

### 2. 防误删四重防御锁（代码级强制门禁）
任何删除手机相册文件的操作必须通过 `_safe_cleanup_remote_temp_photo(remote_file_path)`，强制校验：
1. **路径前缀锁**：必须以 `/sdcard/` 开头；
2. **无通配符锁**：严禁包含 `*`、`?`、`..` 或空格，防止批量误伤；
3. **专属文件名前缀锁**：`os.path.basename(path)` 必须严格以 **`pdd_task_tmp_`** 开头，凡不含此前缀的文件立即抛 `ValueError` 熔断，**100% 保护用户日常个人照片（`IMG_...`、`mmexport...`）**；
4. **媒体库同步刷新锁**：`rm -f` 后立即发送 `android.intent.action.MEDIA_SCANNER_SCAN_FILE` 广播，清除相册缩略图缓存。

### 3. ADB 极速命令铁律
- **限定包名 `dumpsys`**：提取前台 Activity 内存时，必须执行 `adb shell "dumpsys activity com.xunmeng.pinduoduo"`（耗时 ~100ms）；**严禁执行不带包名的 `dumpsys activity top`**（全系统转储耗时 >5s）。

---

## 四、 致命避坑：彻底杜绝“当前访问人数较多，排队中”与价格失真

### 1. 【铁律 A：为什么会出现“当前访问人数较多，排队中”？】
- **真实机理**：拼多多后端 WAF 为防止爬虫遍历商品库，对**任何不存在的 `goods_id` 或无效/不匹配的 `sku_id`**，绝不返回 404 页面，而是 **100% 重定向至通用排队拦截页（“当前访问人数较多，排队中”）**；
- **硬门禁**：
  1. 严禁任何形式的 ID 伪造、哈希生成、规律递增推算或跨商品混拼；
  2. 所有 `goods_id` 与 `sku_id` 必须来自同一次真实商品详情页 `window.rawData.store.initDataObj.goods` 提取；
  3. 合成结算链接时必须且仅使用三参数标准公式（**严禁携带 `group_id`**）：
     $$\mathbf{https://mobile.yangkeduo.com/order\_checkout.html?goods\_id=\{goods\_id\}\&sku\_id=\{sku\_id\}\&goods\_number=1}$$

### 2. 【铁律 B：价格字段元/分精确区分（防除以 100 缩水陷阱）】
| 字段路径 | 原始值示例 | 真实单位 | 正确解析方式 |
| :--- | :--- | :---: | :--- |
| `goods.skus[i].group_price` | `"33.90"` / `"202.55"` | **元 (Yuan)** | `parseFloat(s.group_price)`（**严禁除以 100！**） |
| `goods.skus[i].normal_price` | `"39.90"` | **元 (Yuan)** | `parseFloat(s.normal_price)`（**严禁除以 100！**） |
| `goods.min_on_sale_group_price` | `3390` | 分 (Cents) | 仅作整品最低价参考，回填 J 列一律用 `skus[i].group_price` |

### 3. 【铁律 C：同 SPU 多 SKU 聚合与下单比例（I列）自动推算】
- **同 SPU 聚合**：例如同一 SPU 下含 `M`、`L`、`XL`、`XXL` 4 个尺码，只进 1 次详情页，遍历 `goods.skus` 按尺码/克重词根逐一匹配对应 `sku_id`；
- **下单比例（I列）计算规则**：
  - 提取拼多多选中规格的内含件数 $N_{\text{pdd}}$（如 `10枚装` $\to 10$，`480ml*9瓶` $\to 9$，`250ml*12瓶` $\to 12$）；
  - 提取门店销售 SKU 的内含件数 $N_{\text{store}}$（如 `1颗` $\to 1$，`1瓶` $\to 1$，`330ml*12瓶/箱` $\to 12$）；
  - 计算 $\text{下单比例} = \max(1, \text{round}(N_{\text{pdd}} / N_{\text{store}}))$：
    - 门店卖 `1颗` 皮蛋，拼多多选 `10枚` $\implies \text{I列} = 10$；
    - 门店卖 `330ml*12瓶/箱`，拼多多选 `330ml*12瓶整箱` $\implies \text{I列} = 1$。

---

## 五、 通道 C 实战配方：ESP32 物理拟真与预编译 `mac_ocr` 极速视觉

1. **预编译 Apple Vision OCR（提速 40 倍）**：
   - 严禁在循环中使用 `swift scripts/vision_ocr.swift` 解释执行（每次启动耗时 ~2.0s）；
   - 任务启动时先编译一次原生 Mach-O 二进制：
     ```bash
     swiftc scripts/vision_ocr.swift -O -o /tmp/mac_ocr
     ```
   - 后续每次调用 `/tmp/mac_ocr /tmp/frame.png` 仅需 **50ms**。
2. **挽留弹窗与下单抽屉自愈**：
   - 遇退出挽留弹窗（`继续支付` / `先去逛逛`），严禁点继续支付，OCR 定位 **`先去逛逛`** 中心坐标点击关闭；
   - 固件烧录波特率锁定 `460800`，仅连 `2.4GHz` Wi-Fi，开启 `enableScanResponse(true)`。
