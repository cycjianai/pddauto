# 供应链采购寻源模块能力映射表

机器唯一能力注册表为 [`scripts/capability_registry.json`](../scripts/capability_registry.json)，路由脚本为 [`scripts/route_skill.py`](../scripts/route_skill.py)。

## 上游采购寻源与比价能力

| `platform_adapter` | `sourcing_and_similar_product_matching` | `visual_and_keyword_sourcing` |
|---|---|---|
| `pdd` | `implemented` | - |
| `ali1688` | - | `implemented` |

1. **拼多多采购寻源（`pdd`）**：通过 `references/platforms/pdd.md` ➔ `references/tasks/sourcing-and-similar-product-matching.md` ➔ `references/platforms/pdd-sourcing-playbook.md` 三级按需加载，向原货盘工作簿回填标准 6 列（`F~K` 列：商品链接、拼多多规格、结算链接、下单比例、采购价、单位采购价）。
2. **1688 源头工厂寻源（`ali1688`）**：通过 `references/platforms/ali1688-sourcing-playbook.md` ➔ `references/tasks/visual-bounding-box-sop.md` ➔ `references/tasks/unit-alignment-spec.md` 渐进加载，支持单标签防爆、55s 滑块自然冷却自愈、YOLO 多主体框选及包装层级语义对齐。
