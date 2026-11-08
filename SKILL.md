---
name: pddauto
description: 拼多多采购寻源、控制安卓手机以图搜图/关键词搜索、同SPU多规格聚合提取、相似品多模态核验与真实结算链接六列（F~K列）回填自动化 Skill。支持 Chrome CDP 白盒直提（首选最快）、Android ADB 单件原子流搜图与内存提取、ESP32 物理拟真 + 原生 Vision OCR 三级极速通道自动调度。
---

# 拼多多自动寻源与结算链接提取 Skill (pddauto)

本 Skill 专用于即时零售闪电仓与多渠道货盘的**拼多多上游采购寻源、同 SPU 多规格一次性提取、相似品多模态核验及标准六列（`F~K` 列）结算链接回填**。

---

## 一、 按需加载顺序（Load Order）

执行拼多多寻源任务时，按以下顺序阅读规范与调用引擎：

1. **第 1 层（平台入口与三级通道总览）**：[`references/platforms/pdd.md`](references/platforms/pdd.md)
2. **第 2 层（寻源 SOP、相似品打分矩阵与六列交付 Schema）**：[`references/tasks/sourcing-and-similar-product-matching.md`](references/tasks/sourcing-and-similar-product-matching.md)
3. **第 3 层（CDP / Android ADB / ESP32 底层实战配方与防风控规程）**：[`references/platforms/pdd-sourcing-playbook.md`](references/platforms/pdd-sourcing-playbook.md)
4. **核心执行引擎与单测**：
   - 执行引擎：[`scripts/pdd_sourcing_engine.py`](scripts/pdd_sourcing_engine.py)（`PDDSourcingEngine`）
   - 原生 OCR 组件：[`scripts/vision_ocr.swift`](scripts/vision_ocr.swift)
   - 自动化单测：[`scripts/test_pdd_sourcing_engine.py`](scripts/test_pdd_sourcing_engine.py)

---

## 二、 三级极速通道优先级

| 优先级 | 通道模式 | 适用场景与核心机制 | 单 SPU 耗时 |
| :---: | :--- | :--- | :---: |
| **1（首选）** | **通道 A：`cdp_whitebox`** | 依附本机已登录常规 Chrome（端口 `9222`），直读 `window.rawData.store.initDataObj.goods`，零弹窗一次性提取全部在售 `skus` | **~1.2 ~ 1.5s** |
| **2（手机控制）** | **通道 B：`usb_debug`** | 通过 Android ADB 控制安卓手机：<br>• **无图搜词**：DeepLink `pinduoduo://.../search_result.html` 0.1s 秒开；<br>• **有图搜同款**：相册单件原子流（`pdd_task_tmp_` 传一搜一删一，四重防误删锁保护个人相册）；<br>• **内存直提**：`dumpsys activity com.xunmeng.pinduoduo` 105ms 提取 `goods_id` 与 `sku_id` | **0.1s ~ 2.0s** |
| **3（风控兜底）** | **通道 C：`esp32_physical`** | 触发滑块或强风控时自动切换：手机投屏窗口坐标点击 + ESP32 BLE HID + 预编译 `mac_ocr`（50ms）+ 分享短链 302 还原 `goods_id` | **2.5 ~ 3.5s** |

---

## 三、 采购寻源六大最高铁律（严禁违背）

1. **同 SPU 多 SKU 预聚合（Step 0 必做）**：先调用 `aggregate_rows_by_spu` 按 `SPUID` 聚合表格行，同一 SPU 仅获取 1 次主图、检索 1 次详情页，从 `goods.skus` 一次性提取全量规格批量匹配。
2. **严禁算法伪造或推算 ID**：不存在的 `goods_id`/`sku_id` 会触发拼多多 WAF 100% 重定向至“当前访问人数较多，排队中”；所有 ID 必须从真实页面 `rawData` 或 ADB Activity 内存真实提取并通过 `validate_numeric_id` 校验。
3. **标准结算链接唯一规范**：`https://mobile.yangkeduo.com/order_checkout.html?goods_id={goods_id}&sku_id={sku_id}&goods_number=1`，**严禁拼接失效 `group_id`**。
4. **价格单位防除以 100 陷阱**：`goods.skus[i].group_price` 原生已是以**元**为单位的字符串（如 `"33.90"`），严禁除以 100。
5. **相册零污染单件原子流**：ADB 推图搜同款严格遵循“传一张 ➔ 搜一张 ➔ `finally` 销毁一张”，强制校验 `/sdcard/` 与 `pdd_task_tmp_` 前缀，绝不触碰手机日常个人照片。
6. **物理装量/净含量与单位 100% 绝对一致（一票否决项）**：标准回填原表 `F~K` 六列（`F` 拼多多商品链接、`G` 拼多多规格、`H` 结算链接、`I` 下单比例、`J` 采购价、`K` 单位采购价公式 `=ROUND(J{row}/I{row}, 2)`）。
