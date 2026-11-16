---
name: pddauto
description: 拼多多与1688上游供应链采购寻源、牵牛花全店SPU高清主图/副图自动并发抓取、以图搜图多主体修正与YOLO选框自愈、高销源头工厂严选、基础包装语义对齐（拒绝单片错算）、单标签防风控自愈（55秒滑块自然冷却、阻断营销活动推广页穿透）及真实结算链接六列/十一列自动化回填全流程 Skill。
---

# 拼多多与 1688 供应链自动化寻源与比价治理 Skill (pddauto v2.1.0)

本 Skill 专用于即时零售闪电仓与多渠道货盘的**跨平台（美团牵牛花全店 SPU 主图抓取 + 1688 源头工厂 + 拼多多单件包邮）全流程自动化采购寻源、同 SPU 多规格聚合比价、相似品多模态核验及标准结算链接回填**。

---

## 一、 全流程端到端闭环架构（从开浏览器到抓图比价落盘）

```mermaid
flowchart TD
    Start["🚀 启动主控命令<br>node scripts/start_procurement_workflow.mjs"] --> Phase1["🌐 Phase 1: 环境探测与浏览器自启<br>• 自动探测/启动官方 Chrome (9222/9223/9224)<br>• 自动开启牵牛花后台与 1688 官网"]

    Phase1 --> Phase2{"🔐 Phase 2: 登录态检测与引导"}
    Phase2 -->|"未登录"| PromptUser["📢 交互引导用户登录<br>• 牵牛花: 登录并切到指定门店<br>• 1688: 登录采购账号<br>提示完成后重新运行"]
    Phase2 -->|"已登录"| Phase3["📸 Phase 3: SPU 主图与多规格并发抓取<br>• 自动读取待比价 Excel (SPUID/SKUID)<br>• 在牵牛花页面上下文分批直调内部接口<br>• 提取高清主图 (picUrl) + 全套副图 (allPics)<br>• 秒级生成本地结构化元数据缓存"]

    Phase3 --> Phase4["🏭 Phase 4: 1688 & 拼多多自动化比价寻源<br>• 非标百货强制以图搜款优先<br>• YOLO 多候选主体切换与框选自愈<br>• 几万/几千头部高销量实力工厂严选<br>• 包装语义层级对齐 (80片 vs 240片=3包)<br>• 单标签防爆内存 + 55秒滑块自然冷却自愈"]

    Phase4 --> Phase5["📊 Phase 5: Excel 原子增量回填 (F~K 列)<br>• 严格保护 A~E 前五列只读不动<br>• 动态解析表头，回填供货链接、规格、结算链接、比例与公式"]
```

---

## 二、 自动化工作流执行规程（同事操作指南）

同事协作时，只需执行以下标准步骤即可实现全自动作业：

### 步骤 1：一键启动全流程主控脚本
```bash
# 启动工作流（支持传入自定义 Excel 工作簿路径，未传时默认读取桌面表格）
node scripts/start_procurement_workflow.mjs /path/to/your_store_spus.xlsx
```

### 步骤 2：环境自启与账号登录就绪
- 脚本会自动检测或在后台唤起系统原生 Google Chrome（带远程调试端口，零 WebDriver 标记，彻底避开风控）；
- 自动打开两个核心标签页：
  - **Tab 1（牵牛花）**：`https://qnh.meituan.com/home.html#/unifiedGoods/store/spu-list`
  - **Tab 2（1688）**：`https://www.1688.com/`
- **账号登录指引**：
  若检测到尚未登录，脚本会在终端及会话中给出明确提示：
  > “请在已打开的 Chrome 窗口中完成以下账号登录：
  > 1. **美团牵牛花后台**：完成登录并切换至本次要比价的门店（确保能打开商品列表）；
  > 2. **1688 采购账号**：完成登录（确保首页右上角显示用户名，方便以图搜款与查看供货商优惠）；
  > 完成登录后，重新执行命令即可自动开始作业！”

### 步骤 3：自动高速抓取 SPU 主图与多规格详情（无需人工下载图片）
- 登录就绪后，脚本自动读取 Excel 表格中的全部待比价行；
- 依附到牵牛花页面，直接在页面会话上下文调用内部轻量级接口（`/qnh-gw3/api/product/tenant/page-query`），以 100 件/批的高并发分批直提：
  - 提取每个 SPU 的高清主图 URL（`picUrl`）；
  - 提取全量副图数组（`allPics`，主图命中不准时自动切换副图）；
  - 提取规格名（`specName`）、零售价（`suggestPrice`/`basicPrice`）、UPC 条码；
- 数千个商品的主图与规格将在 **10~20 秒内全量抽取完毕** 并存入本地缓存，杜绝逐个商品手动保存图片的低效操作。

### 步骤 4：全自动高销以图搜款、包装对齐与 Excel 原子回填
- 自动拉起 1688 单标签引擎，逐个 SPU 进行视觉搜索；
- 自动执行 YOLO 多主体框选修正、几万高销工厂筛选、基础包装语义对齐（家庭装 80 片 vs 240片/480片）；
- 实时通过 `openpyxl` 将标准 6 列（F~K 列）增量回填至原工作簿。

---

## 三、 采购寻源八大最高红线（严禁违背）

1. **保底毛利红线（半价门槛）**：
   - **含运费到手单价 $\le$ 门店零售价的 50%**（即 $\text{采购单价} \le \text{零售价} \times 0.50$）。
   - 保底毛利率 $\ge 50\%$，低于此毛利的货源直接剔除或降级候选。
2. **起订量与库存硬指标**：
   - **起订量（MOQ）**：$\text{MOQ} \le 25$（首单轻量化试错，禁止推荐动辄起订几百上千件的工业大单品）。
   - **现货可用库存**：$\text{库存} \ge 20$（防止虚假挂单或即将断货的链接）。
3. **供货商高销严选（杜绝低销幽灵店）**：
   - **强力优先高销量**：优先选取近 30 天或累计成交 **几万**（10,000+）或 **几千**（1,000+）件的源头实力工厂、金牌制造档口。
   - **坚决剔除低销幽灵店**：对于成交量仅有几十件（$< 50$ 件）或 0 件的链接，**一律直接剔除**（防虚假标价、防无货倒卖、防假冒伪劣）。
4. **到手成本必须全额平摊阶梯运费**：
   $$\text{Landed Cost (到手单价)} = \frac{\text{SKU裸价} \times \text{起订量} + \text{首重运费}}{\text{起订量} \times \text{包装换算比率 } N}$$
5. **同 SPU 多 SKU 预聚合（Step 0 必做）**：
   - 先按 `SPUID` 聚合表格行，同一 SPU 仅获取 1 次主图、检索 1 次详情页，从 `goods.skus` 一次性提取全量规格批量匹配。
6. **严禁算法伪造或推算 ID**：
   - 不存在的 `goods_id`/`sku_id` 会触发拼多多/1688 WAF 100% 拦截；所有 ID 必须从真实页面 `rawData` 或 ADB 内存真实提取。
7. **标准结算链接唯一规范**：
   - 拼多多结算链接格式：`https://mobile.yangkeduo.com/order_checkout.html?goods_id={goods_id}&sku_id={sku_id}&goods_number=1`。
   - 1688 链接格式：`https://detail.1688.com/offer/{offerId}.html`。
8. **价格单位防除以 100 陷阱**：
   - 拼多多 `sku.group_price` 原生已是以**元**为单位的字符串（如 `"33.90"`），严禁除以 100。

---

## 四、 核心参考规范清单

1. **平台与底层通道**：
   - 1688 单标签防风控与 55s 滑块自愈：[`references/platforms/ali1688-sourcing-playbook.md`](references/platforms/ali1688-sourcing-playbook.md)
   - 拼多多三级极速通道：[`references/platforms/pdd.md`](references/platforms/pdd.md)、[`references/platforms/pdd-sourcing-playbook.md`](references/platforms/pdd-sourcing-playbook.md)
2. **任务与业务合同**：
   - 基础销售单位与多层级包装语义对齐：[`references/tasks/unit-alignment-spec.md`](references/tasks/unit-alignment-spec.md)
   - 以图搜款多主体修正与 YOLO 框选 SOP：[`references/tasks/visual-bounding-box-sop.md`](references/tasks/visual-bounding-box-sop.md)
   - 相似品打分矩阵与六列交付规范：[`references/tasks/sourcing-and-similar-product-matching.md`](references/tasks/sourcing-and-similar-product-matching.md)
3. **核心脚本库**：
   - 一键全流程主控：[`scripts/start_procurement_workflow.mjs`](scripts/start_procurement_workflow.mjs)
   - 牵牛花 SPU 主图与规格并发抓取器：[`scripts/qnh_spu_extractor.mjs`](scripts/qnh_spu_extractor.mjs)
   - 包装语义对齐解析器：[`scripts/unit_alignment.mjs`](scripts/unit_alignment.mjs)
   - 算法回归测试集（13 用例）：[`scripts/test_ratio.mjs`](scripts/test_ratio.mjs)
   - 1688 单标签以图搜款引擎：[`scripts/ali1688_sourcing_worker.mjs`](scripts/ali1688_sourcing_worker.mjs)
   - Excel 动态 6 列原子回填工具：[`scripts/flush_excel.py`](scripts/flush_excel.py)
