# 1688 与拼多多防风控与单标签内存保护手册 (Anti-Risk & Memory Playbook)

## 一、 浏览器控制原理与反爬指纹规范

### 1. 为什么坚决不用 Puppeteer / Selenium 的“测试浏览器”？
普通自动化框架（如 Puppeteer、Playwright 默认模式、Selenium WebDriver）新启动浏览器时，会自动注入大量自动化测试特征：
- `navigator.webdriver = true`
- 窗口顶部显示“Chrome 正受到自动测试软件的控制”黄色横条
- 缺失真实的 GPU 硬件渲染管线、标准声卡指纹和普通用户缓存
- `window.chrome.runtime` 被篡改

阿里巴巴 1688、拼多多以及美团牵牛花等平台的顶层 WAF 风控对自动化指纹极其敏感。一旦检测到带有 WebDriver 标记的会话，会瞬间判定为高危爬虫，触发永久性滑块拦截甚至直接拒绝服务。

### 2. 标准生产浏览器启动规程（真实原生 Chrome + CDP 依附）
我们必须使用**系统原版安装的官方 Google Chrome**（`/Applications/Google Chrome.app`），通过开启远程调试端口（CDP，Chrome DevTools Protocol）进行白盒控制：

```bash
# 1. 检查 9222 端口是否已被占用
lsof -i :9222

# 2. 启动原生 Chrome（若 9222 被占用则顺延至 9223 或 9224）
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="/tmp/chrome_dev_session_9222" &
```

- **真实性**：该浏览器是 100% 正版的系统浏览器内核，`navigator.webdriver = undefined`，拥有完全真实的渲染环境与设备指纹，完美避开所有自动化标记检测。
- **登录态持久化**：用户在此浏览器中扫码登录牵牛花与 1688 后，自动化脚本通过 WebSocket 依附（Attach）进入该标签页，直接复用已授权的登录 Cookie 与 Session。

### 3. CDP 端口自适应嗅探机制（拒绝端口写死）
在最新工具链中，脚本不再死认单个固定端口，而是通过 `ensureCdpHttp()` 实施自适应探测：
```javascript
export async function ensureCdpHttp() {
  if (process.env.CDP_HTTP) return process.env.CDP_HTTP;
  if (process.env.CDP_PORT) return `http://127.0.0.1:${process.env.CDP_PORT}`;
  // 依次探测活跃的调试端口
  for (const port of [9222, 9223, 9224, 9225]) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(600) });
      if (res.ok) return `http://127.0.0.1:${port}`;
    } catch {}
  }
  return "http://127.0.0.1:9222";
}
```

---

## 二、 表格输出字段规范与动态列映射（F~K 六列规范）

### 1. 字段区域划分与数据契约

工作簿分为“输入区”和“输出区”，严格遵循单向读写隔离：

| 列号范围 | 区域属性 | 对应字段 | 权限与处理规则 |
| :---: | :---: | :--- | :--- |
| **A ~ E 列** | **原始输入区** | `SPUID`、`SKUID`、`门店名称`、`商品名称`、`规格名称` | **严格只读保护**：脚本严禁修改、覆盖或清空前 5 列任何数据（杜绝改动门店名称或条码）。 |
| **F ~ K 列** | **采购输出区** | `供货商品链接`、`供货规格`、`结算链接`、`下单比例`、`采购价`、`单位采购价` | **自动化回填区**：匹配成功后写入，未命中时置空。最后一列为 Excel 动态公式 `=ROUND(J{r}/I{r}, 2)`。 |

### 2. 标准 6 列详细数据字典
- **F 列 (商品链接)**：供货源头商品详情页 URL（1688 `https://detail.1688.com/offer/{id}.html` 或 拼多多 `goods.html?goods_id={id}`）。
- **G 列 (供货规格)**：供货商具体子规格名称。多级规格必须使用中文分号 `；` 隔开（例如：`蓝（牵引+胸背）；S（宽1.0长120CM）`）。
- **H 列 (结算链接)**：拼多多为一键 checkout 链接（`order_checkout.html?goods_id=...&sku_id=...`），1688 为详情直购链接。
- **I 列 (下单比例)**：换算倍率 $N$（如供货商规格为 240 片大包装，门店为 80 片/包，则比率为 3；整箱 24 罐则比率为 24）。
- **J 列 (采购价)**：供货商当前规格的整件采购价格（元，保留 2 位小数）。
- **K 列 (单位采购价)**：Excel 动态计算公式 `=ROUND(J{row}/I{row}, 2)`，自动根据总价与比例核算出最小销售单元的单价。

### 3. 表头动态解析与行数自适应
脚本 `flush_excel.py` 绝不依赖固定的列序号硬编码：
1. **动态解析表头**：读取第 1 行表头内容，自动模糊匹配“商品链接”、“规格”、“结算”、“比例”、“采购价”、“单位采购价”，动态获取列索引。如果列位置被调换，程序自动按表头位置写入。
2. **动态行数识别**：自动根据 `ws.max_row` 确定需要回填的有效范围，支持 500 行、2,700 行乃至数万行不同规模的表格。
3. **保护基准模板**：默认保留前 48 行基准模板（可通过 `--start-row` 参数自由指定起始行）。

---

## 三、 单标签严格生命周期管控规范（防止标签页爆炸）

在过去批量测试中，1688 首页嵌入了海量带有 `target="_blank"` 的营销推广 banner（如“商机组货”、“跟风热卖”等）。通用的模糊点击很容易点中这些推广卡片，在后台瞬间开出几十个标签页引发 Chrome 内存溢出。

实施三层闭环防护：

### 防护 1：弹窗搜索按钮作用域深度隔离
禁止在 `document` 全局查找搜索按钮。必须将搜索按钮严格限制在搜图专用的弹窗容器内：
```javascript
const pop = document.querySelector('.imageSearchPopover--f82RkwsD') || 
            document.querySelector('[class*="imageSearchPopover"]');
if (pop) {
  const btn = pop.querySelector('.actionPrimary--sz2L3jNq') || 
              [...pop.querySelectorAll('button')].find(b => b.innerText?.trim() === '搜索');
  if (btn) btn.click();
}
```

### 防护 2：拦截 `window.open`
在页面上下文注入拦截器，强制所有外跳跳转到当前页自身，杜绝新 Tab 产生：
```javascript
window.open = (u) => { location.href = u; return window; };
```

### 防护 3：CDP Tab 周期性主动收割 (Pruning)
在每次开始处理一个 SPU 之前和之后，脚本通过 CDP HTTP 接口查询当前打开的 Tab 列表：
```javascript
export async function pruneExtraTabs(activeTabId) {
  try {
    const cdpUrl = await ensureCdpHttp();
    const tabs = await (await fetch(`${cdpUrl}/json/list`)).json();
    for (const t of tabs) {
      // 保护美团牵牛花页面和当前正在操作的 1688 主活动页，其余临时衍生页立刻关闭
      if (t.type === "page" && t.id !== activeTabId && !t.url.includes("qnh.meituan.com")) {
        await fetch(`${cdpUrl}/json/close/${t.id}`);
      }
    }
  } catch {}
}
```

---

## 四、 55 秒滑块自然冷却自愈机制

实测证实的阿里巴巴滑块挑战自愈规律：
- **核心机制**：滑块并非永久阻断，而是阿里云风控网关颁发给当前 IP 和会话的有界凭证挑战（有效期约 50~60 秒）。
- **禁忌动作**：
  - 严禁用脚本通过模拟 MouseEvent 或 CDP 暴力拖拽滑块（行为特征极度僵硬，100% 触发二次甚至三次拦截封禁）。
  - 严禁在滑块激活期间持续发起重试或网络请求。
- **自动化自愈流程**：
  1. 检测到滑块弹窗后，立刻停止任何点击与拖拽动作；
  2. 保持当前页面静置挂起 **55 秒** 等待风控挑战超时降级；
  3. 55 秒后直接执行 `location.reload()` 重新刷新页面；
  4. 刷新后该滑块拦截挑战自动解除消失，会话无缝恢复正常操作！
- **平滑频控保护**：两次搜图上传时间间隔强制保证 $\ge 15$ 秒。

---

## 五、 拼多多 Web 移动端反爬防护与免反反复复登录铁律（实战踩坑与工程方案）

在拼多多 H5 移动网页版（`mobile.yangkeduo.com`）自动化比价寻源过程中，平台部署了针对 Web 端的严格防护策略。必须严格遵循以下工程实践铁律，防止反反复复被踢回登录态：

### 1. 绝对禁止自动化脚本通过 CDP 强跳 `login.html`
* **历史教训**：当脚本检测不到期望数据时，绝不可自作主张调用 `Page.navigate('https://mobile.yangkeduo.com/login.html')`。这种强制导航会人为直接切断浏览器当前已经建立的合法用户会话，造成用户屏幕上突然被迫跳入登录页的恶劣体验。
* **准则**：所有鉴权检测一律只读读取 Cookie（`pdd_user_id` / `pdd_user_uin`）或 `window.rawData`，若状态异常仅停留在原页面并发出警报，坚决禁止擅自主动跳转登录 URL。

### 2. 严禁短时间极速暴力换词导航（必须引入拟人呼吸节奏）
* **底层原理**：拼多多服务端 WAF 会严格统计当前会话单位时间内的 URL 换词频次。若以 1~2 秒/词的速度连续刷新 `search_result.html` 50 次以上，WAF 会判定为高危爬虫行为，主动在服务端降级会话甚至注销临时凭证，导致后续搜索一律返回 0 个候选商品或触发风控重定向。
* **防护参数标准**：
  * 单次搜索与详情页跳转必须留出 **3.2s ~ 5.5s** 的自然随机延时；
  * 每连续检索 **8 个 SPU**，脚本强制在后台挂起休眠 **15 秒** 进行深度冷却；
  * 检索时自适应在 URL 中保留 `uin` 参数，维持会话粘性。

### 3. 连续 0 候选硬阻断与自愈机制
* 若因关键词特殊导致单次搜索为 0 属于正常情况；但当出现**连续 4 次搜索候选均为 0** 时：
  1. 脚本立即暂停后续搜索；
  2. 探测当前页面的 `location.href` 与标题：如果页面确实发生跳转（如包含 `login` 或滑块），立即硬中断退出并弹窗/终端报警提示人工处理；
  3. 若页面未退登，则执行 **20 秒静默冷却** 让服务端令牌桶恢复，之后再行尝试，坚决禁止连续空跑几十次浪费时间。
