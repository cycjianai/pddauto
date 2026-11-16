# 1688 与拼多多防风控与单标签内存保护手册 (Anti-Risk & Memory Playbook)

## 1. 痛点根源分析

在过去多轮批量测试中，主要暴露了两个严重破坏自动化运行的系统问题：
1. **Chrome 标签页爆炸导致内存暴涨**：
   - 1688 首页嵌入了许多全屏推广组件（例如“商机组货”、“跟风热卖”等），带有 `target="_blank"`。
   - 当页面异步加载较慢时，通用的模糊选择器（如全局匹配 innerText 为“搜索”的按钮）容易点中 banner 卡片，从而在后台无限弹新标签页，最终占用数十 GB 内存，致使 Chrome 崩溃。
2. **滑块验证码（Baxia / nc_1_n1z）频繁弹窗**：
   - 当连续上传图片间隔过短（$< 10$ 秒）或请求被高频触发时，触发阿里云 WAF 安全风控。
   - 人工介入或脚本乱拖会导致滑块被彻底锁死。

## 2. 单标签严格生命周期管控规范

为彻底杜绝标签页爆炸，必须实施以下三层闭环防护：

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
    const tabs = await (await fetch('http://127.0.0.1:9224/json/list')).json();
    for (const t of tabs) {
      // 保护美团牵牛花页面和当前正在操作的 1688 主活动页，其余临时衍生页立刻关闭
      if (t.type === "page" && t.id !== activeTabId && !t.url.includes("qnh.meituan.com")) {
        await fetch(`http://127.0.0.1:9224/json/close/${t.id}`);
      }
    }
  } catch {}
}
```

---

## 3. 55秒滑块自然冷却自愈机制

实测证实的阿里巴巴滑块挑战自愈规律：
- **核心机制**：滑块并非永久阻断，而是阿里云风控网关颁发给当前 IP 和会话的有界凭证挑战（有效期约 50~60 秒）。
- **禁忌动作**：
  - 严禁用脚本通过模拟 MouseEvent 或 CDP 暴力拖拽滑块（行为特征极度僵硬，100% 触发二次甚至三次拦截封禁）。
  - 严禁在滑块激活期间持续发起重试或网络请求。
- **自动化自愈流程**：
  ```javascript
  async function ensureNoRiskWithAutoCooldown(pageSession) {
    const hasSlider = await pageSession.evalJs(`Boolean(document.querySelector('.nc-container, #baxia-dialog-content, iframe[src*="punish"]'))`);
    if (!hasSlider) return;

    console.log(`[风控滑块触发] 检测到阿里风控拦截，启动 55s 自然冷却自愈...`);
    // 严格静置 55 秒，等待风控挑战在服务端和前端令牌过期
    await sleep(55000);

    // 重新刷新页面
    await pageSession.send("Page.reload", { ignoreCache: true });
    await sleep(4000);

    // 检查刷新后滑块是否消失
    const stillRisk = await pageSession.evalJs(`Boolean(document.querySelector('.nc-container, #baxia-dialog-content, iframe[src*="punish"]'))`);
    if (!stillRisk) {
      console.log(`[风控自然自愈成功] 滑块已自动解除，恢复正常寻源业务!`);
      return;
    }
  }
  ```

---

## 4. 平滑请求节流节奏 (Throttling)

- 两次搜图上传时间间隔强制保证 $\ge 15$ 秒。
- 详情页访问添加 800~1500ms 的随机鼠标微幅滑动和滚动抖动（Jitter），保持正常人工浏览特征。
