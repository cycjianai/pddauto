#!/usr/bin/env python3
"""Tests for pddauto v3.3 progressive router."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTER = ROOT / "scripts" / "route_skill.py"


def run(*args: str, expected: int = 0) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROUTER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == expected, completed.stderr or completed.stdout
    return json.loads(completed.stdout)


def main() -> int:
    assert run("--validate-registry")["valid"] is True

    yd_route = run(
        "--request-text",
        "控制9222浏览器，把原点闪购采购寻源订单里的商品找到采购链接并回填进去",
        "--page-url",
        "https://saas.fuliops.cn/procurement-sourcing",
    )
    assert yd_route["platform_adapter"] == "yuandian_saas"
    assert yd_route["task_mode"] == "yuandian_order_sourcing"
    assert yd_route["intent"] == "execution"
    assert yd_route["load_order"] == [
        "references/yuandian-saas-adapter.md",
        "references/pricing-and-matching-contract.md",
        "references/anti-risk-and-device-sop.md",
        "references/tool-io-schemas.md",
    ]

    pdd_route = run(
        "--request-text",
        "拿spu主图去拼多多真机搜同款，提取真实商品链接和结算链接回填表格",
    )
    assert pdd_route["platform_adapter"] == "pdd"
    assert pdd_route["task_mode"] == "sourcing_and_similar_product_matching"
    assert pdd_route["intent"] == "execution"
    assert pdd_route["load_order"] == [
        "references/anti-risk-and-device-sop.md",
        "references/pricing-and-matching-contract.md",
        "references/tool-io-schemas.md",
    ]

    ali_route = run(
        "--request-text",
        "用1688以图搜款静默抓取百货日用商品并走多模态拼图裁判",
    )
    assert ali_route["platform_adapter"] == "ali1688"
    assert ali_route["task_mode"] == "visual_and_keyword_sourcing"
    assert ali_route["intent"] == "execution"
    assert ali_route["load_order"] == [
        "references/anti-risk-and-device-sop.md",
        "references/pricing-and-matching-contract.md",
        "references/tool-io-schemas.md",
    ]

    print(json.dumps({"passed": True, "cases": 4}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
