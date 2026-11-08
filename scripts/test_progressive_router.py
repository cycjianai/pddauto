#!/usr/bin/env python3
"""Tests for pddauto progressive router."""

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
    pdd_route = run(
        "--request-text",
        "当前主浏览器登录了牵牛花，拿spu搜主图去拼多多搜图，f列填商品链接，g列填规格，h列填结算链接，i列填下单比例，j列填采购价，k列填单位采购价",
    )
    assert pdd_route["platform_adapter"] == "pdd"
    assert pdd_route["task_mode"] == "sourcing_and_similar_product_matching"
    assert pdd_route["intent"] == "execution"
    assert pdd_route["load_order"] == [
        "references/platforms/pdd.md",
        "references/tasks/sourcing-and-similar-product-matching.md",
        "references/platforms/pdd-sourcing-playbook.md",
    ]
    print(json.dumps({"passed": True, "cases": 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
