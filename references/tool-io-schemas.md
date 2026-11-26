# 脚本工具 CLI 与 JSON 输入输出契约 (Tool I/O Schemas v3.5)

所有脚本位于本 Skill 的 `scripts/` 目录，全部自带 `argparse` 参数校验，**零 `/tmp` 硬编码依赖**。

---

## 1. `scripts/step1_prepare.py` — 数据预处理与分流

**调用命令**：
```sh
python3 scripts/step1_prepare.py \
  --excel /abs/path/to/sheet.xlsx \
  --workdir /abs/path/to/workdir \
  [--sheet 门店商品] \
  [--only-unmatched] \
  [--rows 2-421]
```

**输出文件**：
- `<workdir>/store/{row}.jpg`（门店高清主图本地缓存）
- `<workdir>/manifest.json`：
```json
{
  "excel": "/abs/path/to/sheet.xlsx",
  "sheet": "门店商品",
  "workdir": "/abs/path/to/workdir",
  "total": 420,
  "routes": {"1688": 210, "pdd": 205, "combo": 3, "fresh": 2},
  "rows": [
    {
      "row": 2,
      "spuid": "2112428...",
      "skuid": "2112428...",
      "name": "商品名称",
      "spec": "规格名称",
      "retail": 19.9,
      "store_img_url": "https://...",
      "store_img_local": "/abs/path/to/workdir/store/2.jpg",
      "status": "不匹配",
      "route": "1688"
    }
  ]
}
```

---

## 2. `scripts/step2_1688_search.py` — 1688 静默后台检索与详情抓取

### 模式 A：以图搜图 (`--mode img`)
```sh
python3 scripts/step2_1688_search.py \
  --workdir <dir> --mode img \
  --rows '[2,3,4]' \
  [--img-burst 12 --img-cooldown 45 --img-delay-min 5.2 --img-delay-max 6.8]
# 或 --rows-file <rows.json>
```
- 输出：`<workdir>/aliimg/{row}.json`（含 `items: [{id, title, price, text, img, url}]`，最多 60 条）。默认每 12 次图搜自动冷却 45 秒、单次随机间隔 `5.2~6.8s` 防限流。

### 模式 B：关键词补搜 (`--mode kw`)
```sh
python3 scripts/step2_1688_search.py \
  --workdir <dir> --mode kw \
  --jobs-file <kw_jobs.json> \
  [--kw-burst 4 --kw-cooldown 55]
```
- `kw_jobs.json` 输入格式：`[{"row": 121, "kw": "品牌 核心品名 规格"}]`
- 输出：`<workdir>/alikw/{row}.json`。连续 2 次空结果自动判定软限流并以退出码 `9` 安全中止。

### 模式 C：详情与二级 SKU 静默抓取 (`--mode detail`)
```sh
python3 scripts/step2_1688_search.py --workdir <dir> --mode detail --plan-file <detail_plan.json> [--burst 18 --cooldown 65]
```
- `detail_plan.json` 输入格式：
```json
[
  {"row": 121, "oid": "948931844389", "sales": "2900+瓶", "img": "https://..."},
  {"row": 121, "oid": "948931844389", "option": "【柔焦雾面】30ml"}
]
```
- 输出：`<workdir>/acard/{row}-{oid}.json`（带 `option` 点击时为 `{row}-{oid}-clicked.json`），含 `ready, title, offerTitle, goods, main, moq, order_multiple, ship, attrs, options, rows, skuProps, skuMap, qnh_specs, image, meta`。
- **退出码**：`0` 正常完成；`9` 触发风控/滑块已中止（必须立即停手回报用户）。

---

## 3. `scripts/step2_pdd_search.py` — 拼多多真机原生 App 检索与 SKU 核价

### 模式 A：防横幅智能词搜 (`--mode smart-kw`)
```sh
python3 scripts/step2_pdd_search.py --workdir <dir> --mode smart-kw --jobs-file <pdd_kw_jobs.json>
```
- `pdd_kw_jobs.json` 输入格式：
```json
[
  {"row": 340, "kw": "全棉时代 洗脸巾 100抽 6包", "max_cards": 2, "sort_sales": true},
  {"row": 377, "kw": "味滋源 葡萄干 25g", "max_cards": 2, "sort_sales": false}
]
```
- 输出：`<workdir>/pdd_kw/R{row}.json` + `R{row}_k{idx}_{gid}_hero.jpg`。

### 模式 B：相册单件原子流搜图 (`--mode img`)
```sh
python3 scripts/step2_pdd_search.py --workdir <dir> --mode img --jobs-file <pdd_img_jobs.json>
```
- `pdd_img_jobs.json` 输入格式：`[{"row": 121, "max_cards": 2, "sort_sales": false}]`
- 输出：`<workdir>/pdd_img/R{row}.json` + `R{row}_c{idx}_{gid}_hero.jpg`（手机临时图 `finally` 物理删除）。

### 模式 C：单品指定 SKU 点选核价 (`--mode inspect-sku`)
```sh
python3 scripts/step2_pdd_search.py --workdir <dir> --mode inspect-sku --gid 850377025829 --taps "性价款,智能升级款" --tag R367
```
- 输出：`<workdir>/pdd_inspect/R367_850377025829.json` + 每次点击后的抽屉实拍截图。
- **退出码**：`0` 正常；`9` 触发风控/验证码已中止。

---

## 4. `scripts/step3_render_judge_sheet.py` — 强制多模态裁判拼图生成

```sh
python3 scripts/step3_render_judge_sheet.py \
  --manifest <workdir>/manifest.json \
  --workdir <workdir> \
  --platform 1688 \
  --rows '[2,3,4,5,6,7,8,9,10,11]' \
  --out-prefix <workdir>/judge/b1_1688 \
  --chunk-size 10
```
- 输出：
  - `<out-prefix>[_pN].jpg`（每张 ≤10 行，左门店主图+品名/规格/售价，右候选实拍图+ID）
  - `<out-prefix>[_pN].txt`（逐候选完整 SKU 选项、价格、库存、券/补贴 OCR、`attrs` 属性）
- **强制要求**：多模态大模型必须通过 `read_file` 实际查看 `.jpg` 拼图并结合 `.txt` 文本逐行裁判后，才能生成 `decisions.json`。

---

## 5. `scripts/step4_apply_and_export.py` — 原子回填 + 零备注逐字节强校验 + 红队自检 + 同步出 HTML 看板

```sh
python3 scripts/step4_apply_and_export.py \
  --excel /abs/path/to/sheet.xlsx \
  --decisions <workdir>/decisions_b1.json \
  --pdd-img-dirs "<workdir>/pdd_kw,<workdir>/pdd_img" \
  [--acard-dirs "<workdir>/sku_live,<workdir>/acard"] \
  [--html-out /abs/path/to/sheet_直检看板.html]
```
- **内置零人工备注 + 逐字节规格 + 1688 起购数/下单倍数强校验闸门**：
  - 自动发现同目录 `sku_live/`、`acard/` 校验 1688 `spec` 必须逐字节命中真实 `skuMap/qnh_specs`（保留内部连续空格）；
  - 全平台（含拼多多）强制阻断任何人工括号备注（包邮/起批/券后/百亿补贴/店铺优惠/大促/随机同价）、合成多 SKU 套装算式及 `" / "` 分隔符；
  - **v3.5 标准 17 列强校验**：当工作表 `P/Q` 列为空或为 `起购数`/`下单倍数` 时自动启用 17 列模式（自动补齐 `P1="起购数"`、`Q1="下单倍数"` 表头），强制要求所有 1688 行提供正整数 `moq`（≥1）与 `order_multiple`（≥1），拼多多/组合/生鲜行自动清空 `P/Q` 列；红队自检强制核查 `miss_moq_1688=0` 与 `stale_moq_pdd=0`。

---

## 6. `scripts/qnh_1688_validator.py` — 路径 A（有牵牛花账号）1688 企业 API 极速取规格与预校验

> **鉴权前提**：仅当用户在常规 Chrome 登录了自身牵牛花账号时启用（无账号自动走路径 B，严禁跨用户共享 Cookie）。

### 模式 A：批量拉取任意 1688 商品全量真规格/价/库存 (`--mode fetch-offers`)
```sh
python3 scripts/qnh_1688_validator.py \
  --mode fetch-offers \
  --oids-file <workdir>/candidate_oids.txt \
  --out-json <workdir>/qnh_1688_db.json \
  [--batch-size 25] [--port 9222]
```

### 模式 B：交付前全表 1688 规格实库预校验 (`--mode verify-excel`)
```sh
python3 scripts/qnh_1688_validator.py \
  --mode verify-excel \
  --excel /abs/path/to/sheet.xlsx \
  [--sheet Sheet1] [--out-json <workdir>/qnh_verify_cache.json]
```
- 校验全部 1688 行的规格是否 100% 命中牵牛花实库 `channelSpecName`、是否已下架（`status != 1`）或库存为 0（`stock <= 0`），并在工作表含 `起购数`/`下单倍数`（P/Q 列）时**逐行比对实库 `minOrderQuantity` 与 `batchNumber`（空/0 视作 1）**；任一规格不匹配或起购数/下单倍数不一致均以退出码 `1` 报错。

**`decisions.json` 强制输入格式**：
```json
[
  {
    "row": 309,
    "skuid": "1734489817187889185",
    "visual_verified": true,
    "source": "https://detail.1688.com/offer/948931844389.html",
    "spec": "【柔焦雾面】30ml; 1瓶",
    "checkout": "https://detail.1688.com/offer/948931844389.html",
    "units": 1,
    "paid": 9.9,
    "img_url": "https://cbu01.alicdn.com/img/ibank/O1CN01LHgEF42A1YIjZKP3g_!!2207263578143-0-cib.jpg",
    "moq": 2,
    "order_multiple": 1
  },
  {
    "row": 340,
    "skuid": "1734489817187889999",
    "visual_verified": true,
    "source": "https://mobile.yangkeduo.com/goods.html?goods_id=939364744313",
    "spec": "全棉柔巾M码100抽*6包",
    "checkout": "https://mobile.yangkeduo.com/goods.html?goods_id=939364744313",
    "units": 6,
    "paid": 58.9,
    "img_url": ""
  },
  {
    "row": 341,
    "skuid": "1734489817187889998",
    "visual_verified": true,
    "source": "https://detail.1688.com/offer/778162913201.html",
    "spec": "立顿绿茶25包*1盒",
    "checkout": "https://detail.1688.com/offer/778162913201.html",
    "units": 1,
    "paid": 8.9,
    "img_url": "https://cbu01.alicdn.com/img/ibank/xxx.jpg",
    "moq": 1,
    "order_multiple": 1,
    "pdd_fallback_reason": "pdd_low_margin",
    "pdd_best_unit_price": 12.5
  },
  {
    "row": 94,
    "skuid": "1734489817187888888",
    "status_only": "组合商品"
  }
]
```
> **v3.5 1688 必填字段**：模式 A Excel 写入 1688 行时，`decisions.json` **必须**包含正整数 `"moq"`（P 列 `起购数`，取牵牛花 `minOrderQuantity` 或 1688 起批量）与 `"order_multiple"`（Q 列 `下单倍数`，取牵牛花 `batchNumber` 或 1688 拍下倍数，为空/不限填 `1`）；拼多多与 `status_only` 行不填，写入时自动保持 P/Q 留空。
>
> **v3.4 食品/快消品二轮回退 1688 必填字段**：凡 `platform_policy == "pdd_first_lock"`（或类目/标题归属食品/快消）的商品，若第二轮回退写入 `1688.com`，**必须**在磁盘存在非阻断的 `pdd_*/R{row}.json` 实搜记录，且在 `decisions.json` 显式声明 `"pdd_fallback_reason"`（仅允许 `"pdd_no_match"` 或 `"pdd_low_margin"`；选 `"pdd_low_margin"` 时可选填 `"pdd_best_unit_price"`，若毛利已 `≥50%` 代码直接拦截报错）。

**执行后同步产出的双交付物**：
1. 校验通过的 17 列标准 Excel（原子替换 + ZIP 校验 + 红队自检报告）；
2. 与 Excel 100% 同步的单文件离线直检看板 `<excel_stem>_直检看板.html`（含 1688 高清 CDN 图 + 起购数/下单倍数标签 + 拼多多内嵌实拍头图 + 导入 Excel 双向同步结尾「不匹配」 + 一键跳至最后不匹配 + 单 `.xlsx` 规范下载）。

---

## 7. `scripts/export_visual_audit_html.py` — 独立看板导出器

`step4_apply_and_export.py` 默认自动调用它；如需单独重出看板：
```sh
python3 scripts/export_visual_audit_html.py \
  --excel /abs/path/to/sheet.xlsx \
  --sheet 门店商品 \
  --pdd-img-dirs "<workdir>/pdd_kw,<workdir>/pdd_img" \
  --output /abs/path/to/sheet_直检看板.html
```

---

## 8. `scripts/step1_yuandian_pull.py` — 模式 B：原点闪购管理后台订单拉取

> 自动连接本机常规 Chrome（`9222..9229`）中已登录 `saas.fuliops.cn/procurement-sourcing` 的标签页，静默拉取当前打开的订单（或指定 `--task-no`）与在线实时寻源规则，产出与 `step1_prepare.py` 100% 同构的 `manifest.json` + `store/{row}.jpg`，下游 `step2_*` / `step3_*` 零改动直接复用。

```sh
# 1) 查看后台订单队列
python3 scripts/step1_yuandian_pull.py --list-tasks [--status all|pending|sourcing|ready_to_deliver|completed] [--port 9222]

# 2) 拉取当前页面订单（或指定任务号）至 workdir
python3 scripts/step1_yuandian_pull.py \
  --workdir /abs/path/to/workdir \
  [--task-no YD-20261122-CG-000001] \
  [--only-pending] \
  [--port 9222]
```
- **输出文件**：
  - `<workdir>/yuandian_rules.json`（在线 `/api/v1/admin/procurement-sourcing/rules` 最新版）
  - `<workdir>/yuandian_task.json`（订单原始快照）
  - `<workdir>/store/{row}.jpg`（按 `row_index` 缓存的门店高清主图）
  - `<workdir>/manifest.json`（含 `source_mode: "yuandian_saas"`, `task_no`, `yuandian_item_id`, `rows[]`）

---

## 9. `scripts/step4_yuandian_push.py` — 模式 B：原点闪购管理后台原子回填与服务端红队验证

> 复用 `step4_apply_and_export.py` 全部硬闸门（`visual_verified: true`、`skuid` 锁行、零人工备注 + 1688 `skuMap` 逐字节强校验），叠加拼多多结算链防 `group_id` 校验与 `channel`（`1688`/`pdd`）自动同步。**物理不实现 `/deliver` 与 `/cancel`**，确保绝不误触发扣款结算。

```sh
# 预演校验（不写后台）
python3 scripts/step4_yuandian_push.py \
  --workdir /abs/path/to/workdir \
  --decisions <workdir>/decisions.json \
  --port 9222 --dry-run

# 正式回填 + 渠道同步 + 服务端红队校验 + 静默刷新后台页
python3 scripts/step4_yuandian_push.py \
  --workdir /abs/path/to/workdir \
  --decisions <workdir>/decisions.json \
  [--acard-dirs "<workdir>/sku_live,<workdir>/acard"] \
  [--port 9222] [--no-reload]

# 仅执行只读红队审计（不写后台）
python3 scripts/step4_yuandian_push.py --task-no YD-20261122-CG-000001 --audit-only --port 9222
```
- **输入契约**：与 `step4_apply_and_export.py` 100% 相同格式的 `decisions.json`（`status_only` 如 `"组合商品"` / `"生鲜蔬果本地采购"` / `"未匹配"` 自动映射为 `match_status="unmatched"` 并清空 G~K 列）。
- **退出码**：`0` 全部通过且服务端 `red_team_checks` 四项全绿；`2` 服务端红队校验未全通过。
