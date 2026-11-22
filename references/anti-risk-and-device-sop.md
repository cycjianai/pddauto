# 防风控、静默不抢鼠标与设备接入 SOP (Anti-Risk & Device SOP v3.0)

本手册为**不可违背的工程操作红线**，保证连续处理数百个商品零滑块、零风控、零干扰用户正常使用电脑。

---

## 一、1688 浏览器控制铁律（100% 后台静默，绝不抢鼠标与焦点）

### 1. 启动常规调试 Chrome（严禁使用 webdriver/测试浏览器）
1. 从 `9222` 端口开始检查空闲端口（`lsof -i :9222`），占用则顺延 `9223`、`9224`...
2. 使用系统原生 Chrome 启动独立配置目录（完全避开 `navigator.webdriver` 与自动化横条）：
   ```sh
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --remote-debugging-port=9224 \
     --user-data-dir="/tmp/chrome_dev_session_9224" &
   ```
3. 请用户在其中登录一次 1688（及牵牛花，如需抓主图）。之后 `lib/cdp_1688.py` 自动嗅探 `9222..9229` 端口依附。
4. 每次依附浏览器后，`lib/cdp_1688.py` 自动执行 `Browser.setDownloadBehavior({"behavior": "default"})`，防止下载文件名变成无后缀 GUID。

### 2. 严禁抢占用户鼠标与窗口焦点（硬约束）
- **允许的操作**：`Page.navigate`、`DOM.setFileInputFiles`、在同标签页注入 `window.open = url => { location.href = url; return window; }` 钩子、纯 DOM `el.click()`、`Runtime.evaluate`。
- **绝对禁止的操作**：
  - ❌ 禁止调用 `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent`；
  - ❌ 禁止调用 `Page.bringToFront`；
  - ❌ 禁止在 1688 搜图时弹出新前台标签页。

### 3. 1688 防滑块节奏与遇验即停
- 详情页抓取严格执行 **`--burst 18 --cooldown 65`**（每抓 18 个详情强制静默冷却 65 秒，单次请求间隔 `3.8~4.7s`），或与以图搜图交替执行。
- 一旦 `RISK_JS` 检测到任何滑块、安全验证、登录失效或 `punish/captcha` 跳转，脚本**立刻以退出码 `9` 中止**并回报用户。**严禁绕过、破解或强行重试验证码**。

---

## 二、拼多多真机原生 App 原子流铁律（ADB + macOS Vision OCR）

### 1. 为什么必须用真机原生 App 而非 PC/H5 网页？
- 拼多多 Web/H5 端风控极严且商品价/券与 App 不一致；USB 连接已登录的 Android 真机（如 OPPO）驱动原生 App，可连续执行数百次检索零拦截，并读取真实店铺券与百亿补贴到手价。
- 设备序列号与 `adb` 路径由 `lib/adb_pdd.py` 自动检测（也可通过 `--device` / `ADB_DEVICE` 指定）；OCR 使用随 Skill 打包的 `scripts/bin/mac_ocr`（若缺失自动从 `scripts/tools/mac_ocr.swift` 编译，重启电脑不丢失）。

### 2. 拼多多检索双通道策略
1. **智能关键词通道（`--mode smart-kw`，标品首选）**：
   - **大牌横幅避让坐标**：威露士、海天、蒙牛、清扬、全棉时代、味滋源等大品牌搜索页顶部会渲染 `y=650~1000` 的旗舰店广告横幅，旧脚本点 `(300, 950)` 会全部点空。`smart_kw_search` 写死了四点级联探测坐标 `[(300, 1080), (900, 1080), (300, 1800), (900, 1800)]`，跳过已售罄/重复 `goods_id`，实测命中率 **100%**。
   - **迷你/旅行装必须关销量排**：搜索 `25g / 30ml / 180ml / 1.5L` 等小规格或冷门规格时，必须传 `"sort_sales": false`，防止按销量排序把正装大瓶顶到最前淹没目标小规格。
2. **相册单件原子流以图搜图通道（`--mode img`，非标品/词搜未命中兜底）**：
   - 推送单张门店图至 `/sdcard/DCIM/Camera/` 并发送 `MEDIA_SCANNER_SCAN_FILE` 广播；
   - 唤起 `pinduoduo://com.xunmeng.pinduoduo/search_image_capture.html`，经像素向量校验确认相册缩略图匹配后点击识图；
   - **`finally` 强制物理粉碎**：无论成功、超时还是报错，必执行 `rm -f` 删除手机临时图并再次广播刷新媒体库，保证真机相册 **0 留存、0 污染**。
3. **单品 SKU 实时核价通道（`--mode inspect-sku`）**：
   - 当某商品多规格默认未选中目标 SKU、或需确认点击目标规格后的真实券后价与缩略图时，直接深链打开 `goods_id` 并按关键词点击对应 SKU 截屏留证。

### 3. 拼多多遇验即停与隐私脱敏
- 任何页面 OCR 出现 `请完成验证|安全验证|请先登录|操作频繁|访问频繁|实名认证|账号存在风险` 时，脚本**立即以退出码 `9` 中止**并汇报用户，绝不绕过。
- 抓取 SKU 抽屉 OCR 文本时自动正则过滤收货地址、手机号尾号、门牌号等隐私字段，绝不落盘到 JSON 或 Excel。
