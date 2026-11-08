#!/usr/bin/env python3
"""快速校验入口：编译检查全部 Python 脚本并运行单元测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"


def run(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, end="", file=sys.stderr)
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        raise SystemExit(completed.returncode)


def main() -> int:
    python_sources = sorted(SCRIPTS.rglob("*.py"))
    python_tests = sorted(SCRIPTS.rglob("test_*.py"))

    for path in python_sources:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    for path in python_tests:
        run([sys.executable, str(path)])

    print(
        json.dumps(
            {
                "passed": True,
                "python_sources": len(python_sources),
                "python_tests": len(python_tests),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
