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


def _command(arguments: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def build_config(
    *, python_executable: Path, exporter: Path, profile: str
) -> dict[str, Any]:
    if not SAFE_PROFILE.fullmatch(profile):
        raise ValueError("profile must be a bounded identifier")
    command = _command(
        [str(python_executable), str(exporter), "--profile", profile]
    )
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
