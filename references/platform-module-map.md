# 拼多多采购寻源模块能力映射表

机器唯一能力注册表为 [`scripts/capability_registry.json`](../scripts/capability_registry.json)，路由脚本为 [`scripts/route_skill.py`](../scripts/route_skill.py)。

## 上游采购寻源与比价能力

| `platform_adapter` | `sourcing_and_similar_product_matching` |
|---|---|
| `pdd` | `implemented` |

拼多多采购寻源（`pdd`）通过 `references/platforms/pdd.md` ➔ `references/tasks/sourcing-and-similar-product-matching.md` ➔ `references/platforms/pdd-sourcing-playbook.md` 三级按需加载，直接向原货盘工作簿回填标准 6 列（`F~K` 列：商品链接、拼多多规格、结算链接、下单比例、采购价、单位采购价）。
