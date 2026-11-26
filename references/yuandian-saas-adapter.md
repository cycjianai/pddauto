# 原点闪购管理后台适配规程 (Yuandian SaaS Admin Adapter Contract v3.3)

本规程定义 `pddauto` **模式 B（原点闪购管理后台 `https://saas.fuliops.cn/procurement-sourcing` 实时寻源订单）** 的拉取、校验、回填与安全停机标准。

> **核心架构原则**：仅替换 **Step 1（任务读取）** 与 **Step 4（结果回填）**；**Step 2（1688 静默搜图/牵牛花企业 API + 拼多多真机原生 App / 免拼收银台验价）** 与 **Step 3（多模态视觉拼图裁判）** 100% 复用与本地 Excel 模式完全相同的高标准内核。

---

## 一、双模式对照与自动分流

| 维度 | 模式 A：本地 Excel 17 列模式（含 1688 起购数/下单倍数） | 模式 B：原点闪购管理后台模式 (`yuandian_saas`) |
| :--- | :--- | :--- |
| **触发场景** | 用户指定本地 `.xlsx` 工作簿路径 | 用户要求处理 `saas.fuliops.cn/procurement-sourcing` 采购寻源订单，或 9222 浏览器当前打开管理后台订单 |
| **Step 1 入口** | `scripts/step1_prepare.py --excel <表.xlsx>` | `scripts/step1_yuandian_pull.py --workdir <dir> [--task-no ...]` |
| **规则源** | `references/pricing-and-matching-contract.md` | **先拉取在线实时规则** `GET /api/v1/admin/procurement-sourcing/rules`（落盘 `yuandian_rules.json`），与本 Skill 硬闸门叠加取严 |
| **中间契约** | `<workdir>/manifest.json` + `store/{row}.jpg` | **完全同构**（附带 `source_mode: "yuandian_saas"`, `task_no`, `yuandian_item_id`） |
| **Step 2 & 3** | 1688 静默 + 拼多多真机 App + 视觉裁判拼图 | **100% 复用**（零改动直接跑 `step2_1688_search.py` / `step2_pdd_search.py` / `step3_render_judge_sheet.py`） |
| **Step 4 入口** | `scripts/step4_apply_and_export.py`（写 17 列 + 出 HTML 看板） | `scripts/step4_yuandian_push.py`（PATCH 12 列 + 同步 `channel` + 红队校验） |
| **安全边界** | 原子替换 `.xlsx` + ZIP 校验 | **严禁自动调用 `/deliver` 或 `/cancel`**，推进至 `ready_to_deliver`（待回传）后暂停等人工点击「回传客户并结算」 |

---

## 二、原点闪购管理后台 12 列与 API 映射契约

后台页面 `https://saas.fuliops.cn/procurement-sourcing` 内嵌 `<script type="application/json" id="agent-task-payload">` 并暴露标准 REST 接口（通过页面 `localStorage.getItem("admin_token")` 鉴权）：

| 后台列 | 字段名 (`PATCH` Key) | 权限与写入规范 |
| :---: | :--- | :--- |
| **A** | `skuid` | 🔒 只读锁行主键（`step4_yuandian_push.py` 强制校验与 `decisions.json` 100% 吻合） |
| **B** | `spuid` | 🔒 只读 |
| **C** | `product_name` | 🔒 只读 |
| **D** | `spec_name` | 🔒 只读（门店基础销售规格） |
| **E** | `retail_price` | 🔒 只读（若为 `0.00` 则不判 50% 毛利，但仍按全网低价高销严选） |
| **F** | `main_image_url` | 🔒 只读（若需 1688 副图补搜且同浏览器登录牵牛花，可按 SPUID 调牵牛花抓全套 `picUrlList`） |
| **G** | `supply_url` | ✏️ 干净详情页 URL：`https://detail.1688.com/offer/{oid}.html` 或 `https://mobile.yangkeduo.com/goods.html?goods_id={gid}` |
| **H** | `supply_spec` | ✏️ **零人工备注逐字符原值**（双层严格用英文分号加空格 `; `，100% 过 `step4_apply_and_export.validate_verbatim_spec` 闸门） |
| **I** | `checkout_url` | ✏️ 1688 同 `supply_url`；拼多多填实测无排队的 `https://mobile.yangkeduo.com/order_checkout.html?goods_id={gid}&sku_id={sid}&goods_number=1`（严禁带 `group_id`）或详情页 URL |
| **J** | `order_ratio` | ✏️ 正数，按“一份采购可拆为多少个门店基础销售包装”计算 |
| **K** | `purchase_price` | ✏️ 浮点数保留两位小数（1688 核对阶梯价/起订量/分摊运费；拼多多核对常规店铺券/平台券/百亿补贴/大促直降后实付） |
| **L** | `unit_purchase_price` | 🔒 服务端自动按 `ROUND(purchase_price / order_ratio, 2)` 计算 |
| **隐藏字段** | `channel` | ✏️ **必须同步修正**：按 `supply_url` 自动推导为 `"1688"` 或 `"pdd"`，杜绝后台默认值 `"1688"` 污染拼多多行 |
| **判定字段** | `match_status` / `unmatched_reason` | ✏️ 命中写 `"matched"`；找不到同款/组合/生鲜写 `"unmatched"` 并清空 G~K 字段、填入简明原因 |

---

## 三、原点闪购专项工程与安全红线

1. **严禁自动触发扣款结算（最高安全红线）**：
   - `lib/cdp_yuandian.py` 与 `step4_yuandian_push.py` 在代码层**物理不实现** `/deliver`（「回传客户并结算」）和 `/cancel`（「取消订单」）接口。
   - 回填完成后，所有行必须已判定且服务端 `red_team_checks` 四项全绿（`zero_manual_notes`、`unit_price_formula`、`supply_url_valid`、`checkout_url_valid`），订单进入 `ready_to_deliver`（待回传）状态，静默刷新页面后交由操作员复核并手动点击「回传客户并结算」。
2. **保护 9222 业务标签页（严禁劫持或误关）**：
   - `lib/cdp_1688.py` 已内置受保护域名白名单（`saas.fuliops.cn`、`qnh.meituan.com`、`shangoue.meituan.com`、`nr.ele.me`、`saas-retail.ele.me`、`mini.guodongcheng.cn` 等）。
   - 若 9222 浏览器尚无 `1688.com` 标签页，必须通过 CDP `Target.createTarget(..., background=True)` 在后台静默新建独立标签页，**严禁**覆盖或关闭用户已打开的业务标签页。
3. **在线规则优先与版本留痕**：
   - 每次执行 `step1_yuandian_pull.py` 时，必先调用 `GET /api/v1/admin/procurement-sourcing/rules` 并落盘 `<workdir>/yuandian_rules.json`；若后台规则升级（如新增排除品类或格式要求），以在线最新版与本 Skill 强制闸门的**并集最严标准**执行。
4. **多人协作锁定保护**：
   - 若某行已被其他客服认领（`assignee_staff_id != current_staff.id`），`step4_yuandian_push.py` 立即拒绝覆盖，防止多人并发互踩。
5. **套装/规格表述歧义显式标注**：
   - 遇到门店标题写明多色套装（如 `柔雾粉+海盐蓝+缎光肤`）而 `spec_name` 误标 `1条` 等 ERP 脏数据时，在最终汇报中必须单独向操作员点明所填 `order_ratio` 的换算口径，方便人工点击结算前一键微调。
