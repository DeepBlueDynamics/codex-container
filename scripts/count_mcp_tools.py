#!/usr/bin/env python3
"""
Count MCP-exposed tools (functions decorated with @mcp.tool) in a directory.

Usage:
    python scripts/count_mcp_tools.py [--root MCP] [--include-disabled]

Defaults:
    root: MCP
    skip disabled/: True
"""

import argparse
import ast
import pathlib
from typing import Iterable


def iter_py_files(root: pathlib.Path, include_disabled: bool = False) -> Iterable[pathlib.Path]:
    for path in root.rglob("*.py"):
        if path.is_dir():
            continue
        parts = path.parts
        # skip disabled directory unless explicitly included
        if not include_disabled and "disabled" in parts:
            continue
        # skip hidden/versioned snapshots (any path component starting with '.')
        if any(p.startswith(".") for p in parts):
            continue
        yield path


def is_tool_decorator(deco: ast.AST) -> bool:
    """
    Detect @mcp.tool (with or without call parens).
    """
    target = deco
    # If decorator is a call, unwrap func
    if isinstance(target, ast.Call):
        target = target.func

    # mcp.tool or x.tool where x id "mcp"
    if isinstance(target, ast.Attribute) and target.attr == "tool":
        # mcp.tool or something.tool
        if isinstance(target.value, ast.Name) and target.value.id == "mcp":
            return True
    # plain @tool (unlikely but cheap to check)
    if isinstance(target, ast.Name) and target.id == "tool":
        return True
    return False


def count_tools_in_file(path: pathlib.Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(is_tool_decorator(deco) for deco in node.decorator_list):
                count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Count @mcp.tool functions in MCP files.")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("MCP"), help="Root directory to scan (default: MCP)")
    parser.add_argument("--include-disabled", action="store_true", help="Include MCP/disabled directory")
    args = parser.parse_args()

    total = 0
    per_file = []
    for pyfile in iter_py_files(args.root, include_disabled=args.include_disabled):
        c = count_tools_in_file(pyfile)
        if c:
            per_file.append((pyfile, c))
            total += c

    print(f"Total tools: {total}")
    for path, c in sorted(per_file, key=lambda x: x[0].as_posix()):
        print(f"{path.as_posix()}: {c}")


if __name__ == "__main__":
    main()
