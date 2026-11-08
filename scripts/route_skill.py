#!/usr/bin/env python3
"""Progressive skill router for pddauto (PDD sourcing and link extraction)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = Path(__file__).with_name("capability_registry.json")

PLATFORMS = ("pdd",)
TASKS = ("sourcing_and_similar_product_matching",)
INTENTS = ("auto", "review", "diagnosis", "implementation", "execution")


def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def validate_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    statuses = set(registry.get("capability_statuses") or [])
    if statuses != {"implemented", "runtime_guided", "planned"}:
        errors.append("capability_statuses_invalid")
    platforms = registry.get("platforms") or {}
    if set(platforms) != set(PLATFORMS):
        errors.append("platform_registry_mismatch")
    for platform, platform_spec in platforms.items():
        adapter_reference = str(platform_spec.get("adapter_reference") or "")
        if not adapter_reference or not (ROOT / adapter_reference).is_file():
            errors.append(f"missing_platform_reference:{platform}:{adapter_reference}")
        for task, task_spec in (platform_spec.get("tasks") or {}).items():
            if task not in TASKS:
                errors.append(f"unknown_task:{platform}:{task}")
            if task_spec.get("status") not in statuses:
                errors.append(f"unknown_status:{platform}:{task}")
            paths = [task_spec.get("task_reference"), *(task_spec.get("detail_references") or [])]
            for path in paths:
                if not path or not (ROOT / str(path)).is_file():
                    errors.append(f"missing_task_reference:{platform}:{task}:{path}")
    return errors


def contains(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def infer_intent(request_text: str) -> str:
    text = request_text.lower()
    if contains(text, r"诊断", r"排查", r"为什么", r"失败原因", r"报错原因"):
        return "diagnosis"
    if contains(text, r"实现", r"修复代码", r"改代码", r"开发", r"重构", r"优化.*skill", r"修改.*skill"):
        return "implementation"
    if contains(text, r"解释", r"审查", r"阅读", r"分析", r"对比", r"设计", r"只读", r"不(?:要)?(?:执行|写入|修改|保存)"):
        return "review"
    if contains(text, r"执行", r"处理", r"填充", r"补齐", r"回填", r"搜图", r"寻源", r"填入", r"匹配", r"抓取", r"提取", r"比价", r"找链接"):
        return "execution"
    return "execution"


def route(args: argparse.Namespace, registry: dict[str, Any]) -> tuple[dict[str, Any], int]:
    platform = "pdd"
    task = "sourcing_and_similar_product_matching"
    platform_spec = registry["platforms"][platform]
    task_spec = platform_spec["tasks"][task]
    intent = infer_intent(args.request_text) if args.intent == "auto" else args.intent
    load_order = [
        platform_spec["adapter_reference"],
        task_spec["task_reference"],
        *(task_spec.get("detail_references") or []),
    ]
    payload = {
        "schema": registry["schema_version"],
        "routing_status": "ok",
        "platform_adapter": platform,
        "platform_display": platform_spec["display_name"],
        "task_mode": task,
        "intent": intent,
        "capability_status": task_spec["status"],
        "load_order": list(dict.fromkeys(load_order)),
    }
    return payload, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-text", default="")
    parser.add_argument("--page-url", default="")
    parser.add_argument("--platform", choices=PLATFORMS)
    parser.add_argument("--task", choices=TASKS)
    parser.add_argument("--intent", choices=INTENTS, default="auto")
    parser.add_argument("--validate-registry", action="store_true")
    args = parser.parse_args()

    registry = load_registry()
    errors = validate_registry(registry)
    if args.validate_registry:
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    if errors:
        print(json.dumps({"routing_status": "invalid_registry", "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    payload, code = route(args, registry)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
