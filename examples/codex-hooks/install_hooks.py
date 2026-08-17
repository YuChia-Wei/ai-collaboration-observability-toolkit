#!/usr/bin/env python3
"""Generate a project-local Codex hooks.json with direct absolute commands."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


EXAMPLE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = EXAMPLE_DIR.parents[1]
DEFAULT_EXPORTER = EXAMPLE_DIR / "codex_hooks_otel_exporter.py"
DEFAULT_TARGET = REPOSITORY_ROOT / ".codex" / "hooks.json"
EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
SAFE_PROFILE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$", re.ASCII)
CAPTURE_MODES = ("metadata-only", "size-only")
SIZE_SCOPES = ("user-prompt", "mcp-tool-response")
SAFE_MCP_SIZE_TOOL = re.compile(
    r"^mcp__[A-Za-z0-9_.:-]+=[a-z0-9][a-z0-9_.-]{0,63}$", re.ASCII
)


def _command(arguments: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def build_config(
    *,
    python_executable: Path,
    exporter: Path,
    profile: str,
    capture_mode: str,
    size_scopes: tuple[str, ...] = ("user-prompt",),
    mcp_size_tools: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not SAFE_PROFILE.fullmatch(profile):
        raise ValueError("profile must be a bounded identifier")
    if capture_mode not in CAPTURE_MODES:
        raise ValueError("capture_mode must be metadata-only or size-only")
    if not size_scopes or any(scope not in SIZE_SCOPES for scope in size_scopes):
        raise ValueError("size_scopes must contain only supported explicit scopes")
    if any(not SAFE_MCP_SIZE_TOOL.fullmatch(value) for value in mcp_size_tools):
        raise ValueError(
            "mcp_size_tools must use EXACT_MCP_TOOL_NAME=SAFE_LOGICAL_ID"
        )
    arguments = [
        str(python_executable),
        str(exporter),
        "--profile",
        profile,
        "--capture-mode",
        capture_mode,
    ]
    for scope in size_scopes:
        arguments.extend(("--size-scope", scope))
    for tool in mcp_size_tools:
        arguments.extend(("--mcp-size-tool", tool))
    command = _command(arguments)
    hooks: dict[str, Any] = {}
    for event in EVENTS:
        handler: dict[str, Any] = {
            "type": "command",
            "command": command,
            "timeout": 5,
        }
        if os.name == "nt":
            handler["commandWindows"] = command
        hooks[event] = [{"hooks": [handler]}]
    return {
        "description": (
            "Privacy-safe Codex lifecycle traces for the local observability Collector."
        ),
        "hooks": hooks,
    }


def _write_new(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(
            f"Refusing to replace existing hook configuration: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name,
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--exporter", type=Path, default=DEFAULT_EXPORTER)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--profile", default="personal-local")
    parser.add_argument(
        "--capture-mode",
        choices=CAPTURE_MODES,
        default="metadata-only",
        help="Prompt-content handling: metadata-only (default) or opt-in size-only.",
    )
    parser.add_argument(
        "--size-scope",
        action="append",
        choices=SIZE_SCOPES,
        default=None,
        help=(
            "Repeat to select size-only sources. Defaults to user-prompt for "
            "backward compatibility."
        ),
    )
    parser.add_argument(
        "--mcp-size-tool",
        action="append",
        default=None,
        metavar="EXACT_MCP_TOOL_NAME=SAFE_LOGICAL_ID",
        help=(
            "Repeat to allow one MCP tool response to be measured under a safe "
            "logical label."
        ),
    )
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Print the generated JSON without writing it.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    python_executable = args.python.expanduser().resolve()
    exporter = args.exporter.expanduser().resolve()
    if not python_executable.is_file():
        raise FileNotFoundError(f"Python executable not found: {python_executable}")
    if not exporter.is_file():
        raise FileNotFoundError(f"Codex Hook exporter not found: {exporter}")
    config = build_config(
        python_executable=python_executable,
        exporter=exporter,
        profile=args.profile,
        capture_mode=args.capture_mode,
        size_scopes=tuple(args.size_scope or ("user-prompt",)),
        mcp_size_tools=tuple(args.mcp_size_tool or ()),
    )
    if args.print_only:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0
    target = args.target.expanduser().resolve()
    _write_new(target, config)
    print(f"Created Codex hook configuration: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
