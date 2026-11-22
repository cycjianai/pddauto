---
name: pddauto
description: 1688（双路径自适应：有牵牛花账号直连企业 1688 批量接口 0 滑块极速取真规格+导入前 100% 实库预检；无牵牛花账号走 Chrome CDP 100% 后台静默直读原始 skuInfoMap）+ 拼多多（Android 真机原生 App 防横幅智能词搜与相册单件原子流搜图，辅以 CDP 免拼收银台验价）双平台采购寻源、多模态大模型批量图文核验裁判、零人工备注逐字符原样规格强校验、常规店铺券/百亿补贴实付核价、双模式任务适配（模式 A：标准 15 列 Excel 原子回填与离线双向直检 HTML 看板；模式 B：原点闪购管理后台 `saas.fuliops.cn/procurement-sourcing` 12 列订单实时拉取/回填、动态规则同步、渠道对齐与红队自检）全流程 Skill (v3.3.0)。
---

# 1688 & 拼多多多模态采购寻源与双模式交付 Skill (`pddauto v3.3.0`)

本 Skill 是经 2,700+ 真实门店 SKU 实测、牵牛花 1688 接口导入验真与原点闪购管理后台联调沉淀的 **v3.3 生产标准架构**，支持：
- **双输入/输出模式自适应**：
  - **模式 A（本地 Excel 15 列工作簿模式）**：`step1_prepare.py` ➔ 通用双引擎寻源 & 多模态裁判 ➔ `step4_apply_and_export.py`（15 列原子回填 + 同步离线直检 HTML 看板）；
  - **模式 B（原点闪购管理后台实时订单模式）**：`step1_yuandian_pull.py`（从 9222 端口读取 `saas.fuliops.cn/procurement-sourcing` 当前订单与在线实时 `/rules`）➔ **100% 复用同一套 1688 + 拼多多真机 App + 视觉裁判高标准内核** ➔ `step4_yuandian_push.py`（零备注逐字节闸门 + `channel` 同步 + 服务端红队四项校验 + 安全停在「待回传」等人工结算）。
- **有牵牛花 / 无牵牛花双路径两手准备**：有牵牛花账号优先走企业 1688 批量接口 0 滑块取真规格并 100% 实库预检；无牵牛花账号走 100% 后台静默 CDP 直读 `skuInfoMap`。所有旧版盲填正则脚本、前台抢鼠标脚本均已彻底移除。

---

## 一、七大强制闸门（HARD GATES — 违背任何一条视为执行失败）

1. **【强制闸门 1：严禁盲填，必须过视觉拼图裁判】**
   - 严禁写脚本按正则/标题相似度直接把链接写入 Excel！
   - 每一批待入表商品，**必须**先运行 `scripts/step3_render_judge_sheet.py` 生成「门店主图 vs 供货商实拍图」对照拼图（每张 ≤10 行）和完整 SKU/属性文本，由**第一梯队多模态大模型**通过 `read_file` 实际看图 + 核对 SKU/属性/券后价并出具 `"visual_verified": true` 的 `decisions.json` 后，方可调用 `step4_apply_and_export.py` 入表。
   - **大模型能力硬要求**：Step 3 视觉裁判环节必须由具备细粒度视觉识别与多步算术推理能力的多模态强模型执行（如 Gemini Pro/旗舰多模态、Claude Sonnet/Opus、GPT-4o/5 视觉档）；切勿用纯文本或弱视觉模型硬跑该环节。
2. **【强制闸门 2：严禁抢占用户鼠标与浏览器焦点】**
   - 1688 全程通过 `scripts/step2_1688_search.py`（底层 `scripts/lib/cdp_1688.py`）以 **100% 后台静默 DOM 模式**运行：仅允许 `Page.navigate`、`DOM.setFileInputFiles`、`window.open` 同标签劫持、`el.click()`；**绝对禁止** `Input.dispatchMouseEvent`、`Page.bringToFront` 或弹出前台新标签。
3. **【强制闸门 3：严禁绕过任何验证码/滑块/风控】**
   - 任何脚本检测到 1688 滑块/登录拦截或拼多多风控/安全验证，必须**立即以退出码 `9` 停止**并回报用户。绝不尝试点击、计算、等待绕过验证码。
4. **【强制闸门 4：拼多多与 1688 核价口径写死】**
   - **拼多多**：必须计入常规 `店铺优惠 / 店铺券 / 无门槛店铺券 / 平台券 / 百亿补贴 / 官方补贴 / 大促直降` 后的**真实券后到手价**；**严禁计入**个人新客或客诉赔付类无门槛红包；严禁选用 `临期` 或已售罄 SKU；吃喝/洗护/纸品等标品优先选 `6/12/24` 整箱装，避免单瓶含运费高价陷阱。
   - **1688**：多维度双层 SKU（`options` 非空且目标不是首项）**必须**通过 `--mode detail` 传 `"option"` 静默点击后读取真价；必须核对 `attrs` 剔除假大牌/错类目链接；**必填** O 列无缩略后缀高清 CDN 主图 URL。
5. **【强制闸门 5：I 列《供货规格》零人工备注、逐字符原样匹配（1688 + 拼多多全平台死红线）】**
   - **所有平台（1688、拼多多及其他任何采购渠道）找链接填 `I 列（供货规格）` 时，绝对禁止添加任何人工备注、括号注释、品牌前缀或口语改写，必须一个字、一个符号、一个空格都不差地严格照抄商品页真实可选的原始规格！**
   - **严禁写入的垃圾注释示例**：`(包邮)`、`(N个起批)`、`（颜色随机同价）`、`（1袋3条）`、`（店铺优惠-X元券后）`、`（百亿补贴）`、`（大促直降）`、`（限量低价）`、`（官方旗舰店）`、`(共XX片)`、以及任何原文里不存在的单位换算/品牌前缀。
   - **严禁删改原文任何字符**：原文带条码（如 `6902890237754`）、带符号（`⚑☆`、`【建议拍10的倍数】`）、带连续多空格（如 `常规款   铜芯`）、带屏蔽星号（`半**田`）、带奇怪单字规格（如 `5`、`其他`、`如图`），都必须 **100% 逐字节照抄**，绝不“好心”补全或精简！
   - **1688 严格格式（直接取 `cdp_1688.py` 提取的底层 `skuModel.skuInfoMap` / `qnh_specs`）**：
     - **单层规格 / 工业规格型号表 / 3 层分号键值**：逐字节照抄 `skuInfoMap` 原始键（保留连续多空格与内部 `;`）。
     - **双层规格**：严格用英文分号+空格 **`第一层; 第二层`** 拼接（**绝对禁止**用 `" / "` 或纯空格，严禁漏写任一层）。
     - **无规格单品（`skuProps` / `skuInfoMap` 为空）**：严格填 1688 官方完整商品标题 `offerTitle`（去掉 ` - 阿里巴巴`）。
   - **拼多多严格格式**：逐字照抄拼多多 SKU 弹窗里对应真实选项的原文（双层用 `第一层; 第二层`），不得在末尾附加券后/补贴/大促/包邮等说明。
   - **严禁硬拼合成多 SKU**：如果门店卖 1 套（如 1 碗+1 勺、刀+叉、勾面+毛面、男戒+女戒），而供货商拆成了两个独立 SKU 售卖，**绝对禁止**自己写成 `A(¥x)+B(¥y)=1套` 这类不存在的假规格；必须另找“整套单 SKU”链接，找不到就如实标 `不匹配` 或 `组合商品`。
   - **代码层强拦截**：`step4_apply_and_export.py` 已内置零备注 + 1688 `skuMap` 逐字节强校验闸门，凡未逐字节命中真实规格或包含违规备注/分隔符的，直接报错阻断写入。
6. **【强制闸门 6：双模式原子回填 + 红队自检必跑 + 结算安全锁】**
   - **模式 A（本地 Excel 15 列）**：所有写入必须经过 `scripts/step4_apply_and_export.py`：强制校验 `SKUID` 防串行、`A~G` 只读保护、`I` 列零备注逐字节规格强校验、`M` 列强制写 `=ROUND(L{r}/K{r},2)` 公式、自动清理 C/O 列旧图残留、写入前执行 `zipfile.testzip()` 校验，写入后自动输出红队自检。
   - **模式 B（原点闪购管理后台 12 列）**：所有回填必须经过 `scripts/step4_yuandian_push.py`：强制校验 `SKUID` 锁行、复用零备注逐字节 `skuMap` 强校验闸门、自动同步 `channel`（`1688`/`pdd`）、核验服务端 `red_team_checks` 四项全绿（`zero_manual_notes` / `unit_price_formula` / `supply_url_valid` / `checkout_url_valid`）及本地红队审计。**最高安全红线：脚本与 Agent 严禁自动点击或调用「回传客户并结算（`/deliver`）」或「取消订单（`/cancel`）」**，必须安全停在 `ready_to_deliver`（待回传）状态交由操作员复核结算。
7. **【强制闸门 7：模式对应交付物强制验收】**
   - **模式 A（本地 Excel）**：`step4_apply_and_export.py` 每次提交 Excel 后**默认自动调用** `scripts/export_visual_audit_html.py`，基于最新落盘的 Excel 同步生成单文件离线直检看板 `<表名>_直检看板.html`，跑完必须同时交付 Excel 与同步 HTML 看板。
   - **模式 B（原点闪购后台）**：`step4_yuandian_push.py` 回填后默认静默刷新后台标签页并落盘 `yuandian_push_report.json`，确认四项红队自检全绿、`pending=0` 且状态为 `ready_to_deliver` 后交付清单与人工复核提示。

---

## 二、固定端到端执行流水线（严禁跳步）

> 详细业务规则、防风控设备配置、原点后台适配与脚本 JSON Schema 见四份随附合同：
> - 核价、匹配容差与 15 列表格枚举：[references/pricing-and-matching-contract.md](references/pricing-and-matching-contract.md)
> - 原点闪购管理后台适配规程（12 列/动态规则/安全锁）：[references/yuandian-saas-adapter.md](references/yuandian-saas-adapter.md)
> - 浏览器静默控制与真机 ADB 规程：[references/anti-risk-and-device-sop.md](references/anti-risk-and-device-sop.md)
> - 全部脚本 CLI 与 JSON 输入输出契约：[references/tool-io-schemas.md](references/tool-io-schemas.md)

### Step 0：任务模式判定 + 环境核对与「有/无牵牛花」双路径分流（开工必查）
0. **【首先判定任务输入/输出模式】**：
   - 用户提供本地 `.xlsx` 路径 → 走 **模式 A（Excel 模式）**；
   - 用户要求处理原点闪购「采购寻源订单」或 9222 浏览器已打开 `saas.fuliops.cn/procurement-sourcing` → 走 **模式 B（原点闪购管理后台模式）**（先读在线 `/rules`，详看 `references/yuandian-saas-adapter.md`）。
1. **【开工必问：确认用户是否有牵牛花账号 → 自动分流两手准备】**
   - 先自动检查本机常规 Chrome（`9222..9229`）是否已有登录态的牵牛花标签页（`qnh.meituan.com`）；若未检测到，**开工前必须明确询问用户是否有牵牛花账号**：
   - **路径 A（有牵牛花账号 — 极速 100% 企业 API 实库直连路径）**：
     - 牵牛花 1688 接口（`/qnh-gw2/scm/online-procure/batch-query-channel-goods` 等）受网关鉴权与美团 H5Guard 保护，**必须使用当前用户自己在常规 Chrome 登录后的会话**（严禁硬编码或跨用户共享他人 Cookie）。
     - 请用户在常规 Chrome 登录牵牛花后：1688 候选的详情/全规格/价/库存拉取优先直走 `scripts/qnh_1688_validator.py --mode fetch-offers`（25~50 品/批、~65ms/品、0 1688 滑块），模式 A 交付前必跑 `--mode verify-excel` 对全部 1688 行做 **100% 实库预校验**；模式 B 亦可顺手通过牵牛花按 SPUID 抓取全套副图以提升 1688 以图搜图命中率。
   - **路径 B（无牵牛花账号 — 独立通用零备注直抓路径）**：
     - 完全不依赖牵牛花账号；1688 详情统一走 `scripts/step2_1688_search.py --mode detail`（底层 `cdp_1688.py` 自动在后台新建独立 1688 标签页，绝不劫持 `saas.fuliops.cn`/`qnh.meituan.com` 等业务标签页，并直读 `window.context...skuModel.skuInfoMap` + `offerTitle` 提取原始规范键）；
     - 严格配合 `step3_render_judge_sheet.py` 与 Step 4 零人工备注 + 逐字节 `skuMap` 强校验闸门，**绝不自造或改写规格**。
2. **数据与门店主图**：模式 A 若原表缺 `G/F` 列可用 `qnh_spu_extractor.mjs` 补全；模式 B 直接由 `step1_yuandian_pull.py` 从后台拉取订单与主图。
3. **1688 浏览器**：确认常规 Chrome 调试端口已开（`9222..9229` 任意端口，模式 B 优先复用已登录 `saas.fuliops.cn` 的 `9222` 端口）且 1688 可正常访问。
4. **拼多多真机**：确认 `adb devices` 在线（同时支持 USB 序列号与无线 ADB `ip:port`）且真机已登录拼多多 App。

### Step 1：数据预处理、主图缓存与双平台分流（按模式二选一，产出同构 `manifest.json`）

- **模式 A（本地 Excel 15 列）**：
```sh
python3 scripts/step1_prepare.py \
  --excel /abs/path/to/target.xlsx \
  --workdir /abs/path/to/workdir \
  --only-unmatched
```
- **模式 B（原点闪购管理后台 12 列订单）**：
```sh
# 可选：先查看后台队列中有哪些订单
python3 scripts/step1_yuandian_pull.py --list-tasks --port 9222

# 拉取当前页面打开的订单（或传 --task-no 指定订单号）及在线实时规则
python3 scripts/step1_yuandian_pull.py \
  --workdir /abs/path/to/workdir \
  [--task-no YD-20261122-CG-000001] \
  --only-pending --port 9222
```
- **统一产出**：`<workdir>/store/{row}.jpg` 与 `<workdir>/manifest.json`（含锁定 `skuid` 与 `route`: `1688` / `pdd` / `combo` / `fresh`；模式 B 额外落盘 `yuandian_rules.json` 与 `yuandian_task.json`）。
- 对 `combo` / `fresh` 行核对确认后，直接写入 `status_only: "组合商品"` / `"生鲜蔬果本地采购"`（免检索）。

### Step 2：双引擎静默/真机并发采集（不调视觉模型，纯确定性脚本）

#### 通道 A — 1688 静默后台采集（百货 / 五金 / 文具 / 家居 / 宠物 / 贴牌日化优先）
1. **先以图搜图**（获取前 60 个候选）：
   ```sh
   python3 scripts/step2_1688_search.py --workdir <dir> --mode img --rows-file <1688_rows.json>
   ```
2. **轻量规则粗筛 Top 2~4**：从 `<workdir>/aliimg/{row}.json` 过滤掉异品类和低销幽灵店，按「品牌/规格词命中 + 高销量 + 合理价位」挑出 Top 2~4 写入 `<detail_plan.json>`。图搜无结果的补跑 `--mode kw`。
3. **获取候选详情与全量真规格（按 Step 0 选定的路径执行）**：
   - **路径 A（有牵牛花账号 — 极速 0 滑块通道）**：直接运行 `scripts/qnh_1688_validator.py --mode fetch-offers --oids-file <oids.txt> --out-json <workdir>/qnh_1688_db.json` 调用牵牛花 `POST /qnh-gw2/scm/online-procure/batch-query-channel-goods`（单次 25~50 个 offerId，~65ms/品，0 1688 滑块），一次性拿齐**牵牛花官方规范 `channelSpecName`、全规格价、实时库存、起订量、混批量与高清主图**；交付前必跑 `scripts/qnh_1688_validator.py --mode verify-excel --excel <表.xlsx>` 做 100% 实库预校验。
   - **路径 B（无牵牛花账号 — 或需补看 1688 `attrs` 商品属性页时）**：运行静默详情抓取（每 18 个自动冷却 65 秒）：
     ```sh
     python3 scripts/step2_1688_search.py --workdir <dir> --mode detail --plan-file <detail_plan.json>
     ```
     - 底层 `cdp_1688.py` 已升级直读 `window.context...skuModel.skuInfoMap` + `offerTitle`（保留连续多空格、3 层分号键、同名双层去重），严禁自己编造或改写规格；若目标规格不在默认首项且需核对实价，必须追加带 `"option": "目标一级规格名"` 的计划再跑一次 `--mode detail`。

#### 通道 B — 拼多多真机原生 App 采集（吃喝 / 零食饮料 / 品牌个护美妆 / 小家电优先）
1. **标品先跑防横幅智能关键词搜**（迷你装 `25g/30ml/180ml` 必须设 `"sort_sales": false`）：
   ```sh
   python3 scripts/step2_pdd_search.py --workdir <dir> --mode smart-kw --jobs-file <pdd_kw_jobs.json>
   ```
2. **非标品或词搜未命中 → 跑相册单件原子流以图搜图**（`finally` 自动删手机图，0 相册污染）：
   ```sh
   python3 scripts/step2_pdd_search.py --workdir <dir> --mode img --jobs-file <pdd_img_jobs.json>
   ```
3. **跨平台互救**：1688 无合适源头或单价过高的百货切拼多多；拼多多仅剩高价零售装或断货的日化/文具/休闲品切 1688。
4. **单品 SKU 实时点选核价**（遇到多 SKU 需确认选中后券后实价与缩略图时）：
   ```sh
   python3 scripts/step2_pdd_search.py --workdir <dir> --mode inspect-sku --gid <goods_id> --taps "目标规格词" --tag R<row>
   ```

### Step 3：强制多模态图文核验裁判（分水岭闸门）
1. **生成对照拼图与完整证据文本**（每批 ≤10 行，确保图片文字清晰可读）：
   ```sh
   python3 scripts/step3_render_judge_sheet.py \
     --manifest <workdir>/manifest.json \
     --workdir <workdir> \
     --platform 1688 \
     --rows '[...]' \
     --out-prefix <workdir>/judge/b1_1688
   ```
   （拼多多批次将 `--platform` 改为 `pdd`。）
2. **多模态大模型逐行审图决策**：
   - 使用 `read_file` 查看每张 `<out-prefix>.jpg` 拼图，结合 `<out-prefix>.txt` 中的 SKU 列表、券/补贴 OCR、`attrs` 属性，按 `references/pricing-and-matching-contract.md` 逐行输出 `decisions.json`。
   - **每一条命中项必须核实**：视觉同款 + 品牌吻合 + 包装比例 `units` 正确（拒绝单片错算）+ 拼多多常规券/补贴已计入 + 1688 已带高清 `img_url` + `"visual_verified": true`。
   - 确属全网无在售同款或线下专供迷你装的，绝不硬填，归入交付时的“待拍板清单”并附最优替代参考。

### Step 4：双模式原子回填 + 红队自检 + 交付验收（按模式二选一，消费同构 `decisions.json`）

#### 模式 A — 本地 15 列 Excel + 同步 HTML 直检看板
```sh
python3 scripts/step4_apply_and_export.py \
  --excel /abs/path/to/target.xlsx \
  --decisions <workdir>/decisions_b1.json \
  --pdd-img-dirs "<workdir>/pdd_kw,<workdir>/pdd_img"
```
- **必检红队自检输出**：
  - `bad_formula=0`、`stale_c_matched=0`、`stale_o_pdd=0`、`miss_o_1688=0`；
  - 若 `tiny_cost_suspects`（疑似单片错算）非空，必须立即复核 `K` 比例；
  - 若 `single_pack_low_margin`（`K=1` 且毛利 `<25%`）中存在标品单瓶/单包高价陷阱，必须回炉 Step 2 补搜整箱/多包装降本后重新运行 Step 4；
  - 若存在 `price_inversions`（单位采购价 > 门店原价），必须二次核实是否为全网真实底价倒挂并在交付说明中单列。
- **同步交付物验收**：
  - 确认 `<excel_stem>.xlsx` 与 `<excel_stem>_直检看板.html` 均已落盘更新，看板中 1688 CDN 图与拼多多内嵌实拍头图均正常展示，且导入导出已核对 Excel 严格保留单 `.xlsx` 后缀与全部 `不匹配` 标记。

#### 模式 B — 原点闪购管理后台 12 列订单实时回填（安全停在「待回传」）
```sh
# 可选预演校验（不写后台，只跑零备注/skuMap/SKUID/拼多多结算链全套硬闸门）：
python3 scripts/step4_yuandian_push.py \
  --workdir /abs/path/to/workdir \
  --decisions <workdir>/decisions.json \
  --port 9222 --dry-run

# 正式回填 + 自动同步 channel(1688/pdd) + 服务端四项红队自检 + 静默刷新页面：
python3 scripts/step4_yuandian_push.py \
  --workdir /abs/path/to/workdir \
  --decisions <workdir>/decisions.json \
  --port 9222
```
- **必检红队验收**：
  - 确认服务端 `red_team_checks` 四项全为 `true`（`zero_manual_notes`、`unit_price_formula`、`supply_url_valid`、`checkout_url_valid`），`channel_mismatches=0`，且 `status == "ready_to_deliver"`；
  - 核对 `tiny_cost_suspects`、`single_pack_low_margin`、`price_inversions` 及套装/单条比例歧义项；
  - **严禁自动点击/调用「回传客户并结算」**，交付汇总清单与复核提示后由操作员在页面手动确认结算。

---

## 三、目录结构与核心脚本清单

```text
procurement-sourcing/
├── SKILL.md                                      # 主执行规程与七大强制闸门 (v3.3.0，双模式自适应)
├── references/
│   ├── pricing-and-matching-contract.md          # 15 列架构、核价口径、匹配容差与状态枚举
│   ├── yuandian-saas-adapter.md                  # 原点闪购管理后台 12 列适配、动态规则与结算安全锁
│   ├── anti-risk-and-device-sop.md               # 1688 静默防抢鼠标、防滑块节奏与真机 ADB 规范
│   └── tool-io-schemas.md                        # 全部脚本 CLI 参数与 JSON 输入输出契约
└── scripts/
    ├── bin/mac_ocr                               # macOS Vision OCR 可执行文件（不依赖 /tmp）
    ├── tools/mac_ocr.swift                       # mac_ocr Swift 源码（缺失时自动编译）
    ├── lib/
    │   ├── cdp_1688.py                           # 1688 静默后台 Chrome CDP 引擎（自动保护业务标签页）
    │   ├── cdp_yuandian.py                       # 原点闪购管理后台静默 CDP API 客户端（物理禁调用结算/取消）
    │   └── adb_pdd.py                            # 拼多多真机 ADB + Vision OCR 原子流引擎
    ├── step1_prepare.py                          # Step 1A (Excel): 读表锁 SKUID、下门店图、路由分类
    ├── step1_yuandian_pull.py                    # Step 1B (原点后台): 拉队列/当前订单/在线规则 -> 同构 manifest.json
    ├── step2_1688_search.py                      # Step 2A: 1688 静默图搜/词搜/详情与二级 SKU 点击
    ├── step2_pdd_search.py                       # Step 2B: 拼多多防横幅词搜/相册原子搜图/SKU 点选
    ├── step3_render_judge_sheet.py               # Step 3: 强制多模态审图拼图与证据文本生成
    ├── step4_apply_and_export.py                 # Step 4A (Excel): 原子写回 + 红队自检 + 自动同步出 HTML
    ├── step4_yuandian_push.py                    # Step 4B (原点后台): 零备注强校验回填 + 渠道同步 + 服务端红队验证
    ├── test_yuandian_adapter.py                  # 原点后台双模式适配与安全闸门确定性单元测试
    ├── export_visual_audit_html.py               # 单文件离线双向直检看板导出器（支持直读 Excel + 嵌 PDD 图）
    ├── qnh_spu_extractor.mjs                     # 牵牛花后台 SPU 主图与指导价高速抓取器
    ├── qnh_1688_validator.py                     # 牵牛花企业 1688 批量查真规格/价/库存与导入前预校验器
    └── audit_server.mjs                          # 可选本机 8899 看板直连写盘服务
```
