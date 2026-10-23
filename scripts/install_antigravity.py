#!/usr/bin/env python3
"""Install the canonical Antigravity exporter callbacks without replacing settings.

The default is a read-only plan. Pass --apply to update user-level Hooks and the
CLI status line. Existing files are backed up alongside the originals before
they change. Configuration contents are never printed.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass


ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "examples" / "antigravity" / "antigravity_otel_exporter.py"
TEMPLATES = EXPORTER.parent / "config"
PROFILES = {"personal-local": "personal", "corporate-local-redacted": "corporate"}
HOOK_NAME = "ai-observability"


class InstallError(Exception):
    """A configuration error that can be reported without revealing its contents."""


@dataclass
class FilePlan:
    path: Path
    original: bytes | None
    document: dict
    changed: bool

    @property
    def action(self) -> str:
        if not self.changed:
            return "unchanged"
        return "create" if self.original is None else "update"


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _read_object(path: Path, label: str) -> tuple[bytes | None, dict]:
    try:
        original = path.read_bytes()
    except FileNotFoundError:
        return None, {}
    try:
        document = json.loads(
            original.decode("utf-8-sig"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise InstallError(f"Invalid JSON in {label}; no configuration was written.") from exc
    if not isinstance(document, dict):
        raise InstallError(f"{label} must contain a JSON object; no configuration was written.")
    return original, document


def _shell_command(arguments: list[str], platform: str) -> str:
    if platform == "windows":
        # Antigravity 1.4.5 passes the command through cmd.exe /c using argv
        # escaping. Quoted paths arrive as backslash-escaped quotes and fail to
        # launch. Refuse paths that would require shell quoting before writing.
        if any(
            any(character.isspace() or character in "\"'&|<>^()%!" for character in path)
            for path in arguments[:2]
        ):
            raise InstallError(
                "Windows Antigravity callbacks require Python and repository paths "
                "without spaces or shell metacharacters; no configuration was written."
            )
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def _render_commands(value: object, platform: str) -> object:
    if isinstance(value, list):
        return [_render_commands(item, platform) for item in value]
    if not isinstance(value, dict):
        return value
    rendered = {}
    for key, item in value.items():
        if key == "command":
            if not isinstance(item, str) or "antigravity_otel_exporter.py" not in item:
                raise InstallError("Unexpected command in the managed integration template.")
            _, _, suffix = item.partition("antigravity_otel_exporter.py")
            arguments = [
                str(Path(sys.executable).resolve()),
                str(EXPORTER.resolve()),
                *shlex.split(suffix),
            ]
            rendered[key] = _shell_command(arguments, platform)
        else:
            rendered[key] = _render_commands(item, platform)
    return rendered


def _managed_statusline(value: object, platform: str) -> bool:
    if not isinstance(value, dict) or value.get("type") != "command":
        return False
    command = value.get("command")
    if not isinstance(command, str):
        return False
    try:
        arguments = shlex.split(command, posix=platform != "windows")
        if platform == "windows":
            arguments = [item[1:-1] if item.startswith('"') and item.endswith('"') else item for item in arguments]
        return (
            len(arguments) >= 3
            and Path(arguments[1]).resolve() == EXPORTER.resolve()
            and arguments[2] == "statusline"
        )
    except (ValueError, OSError):
        return False


def plan_install(home: Path, profile: str, platform: str, replace_statusline: bool) -> list[FilePlan]:
    if not EXPORTER.is_file():
        raise InstallError("The repository canonical exporter is missing.")
    variant = PROFILES[profile]
    _, hook_template = _read_object(TEMPLATES / f"hooks.{variant}.{platform}.json.example", "Hooks template")
    _, status_template = _read_object(
        TEMPLATES / f"settings.statusline.{variant}.{platform}.json.fragment.example",
        "status-line template",
    )
    hook_template = _render_commands(hook_template, platform)
    status_template = _render_commands(status_template, platform)

    hook_path = home / ".gemini" / "config" / "hooks.json"
    status_path = home / ".gemini" / "antigravity-cli" / "settings.json"
    hook_bytes, hooks = _read_object(hook_path, "user Hooks configuration")
    status_bytes, settings = _read_object(status_path, "CLI settings")
    current_status = settings.get("statusLine")
    if (
        current_status is not None
        and not _managed_statusline(current_status, platform)
        and not replace_statusline
    ):
        raise InstallError(
            "The existing statusLine belongs to another command. "
            "Use --replace-statusline to replace it; no configuration was written."
        )

    desired_hooks = copy.deepcopy(hooks)
    desired_hooks[HOOK_NAME] = hook_template[HOOK_NAME]
    previous_hook = hooks.get(HOOK_NAME)
    if isinstance(previous_hook, dict) and isinstance(previous_hook.get("enabled"), bool):
        desired_hooks[HOOK_NAME]["enabled"] = previous_hook["enabled"]
    desired_settings = copy.deepcopy(settings)
    # Preserve layout options and explicit enable/disable preferences when this
    # exporter already owns the status line. A replacement uses the template.
    statusline = copy.deepcopy(current_status) if _managed_statusline(current_status, platform) else {}
    statusline.update(status_template["statusLine"])
    desired_settings["statusLine"] = statusline
    return [
        FilePlan(hook_path, hook_bytes, desired_hooks, hooks != desired_hooks),
        FilePlan(status_path, status_bytes, desired_settings, settings != desired_settings),
    ]


def apply_plan(plans: list[FilePlan]) -> None:
    # Validate every original snapshot before making the first change.
    for plan in plans:
        try:
            current = plan.path.read_bytes()
        except FileNotFoundError:
            current = None
        if current != plan.original:
            raise InstallError("Configuration changed during planning; rerun the installer.")

    for plan in plans:
        if not plan.changed:
            continue
        plan.path.parent.mkdir(parents=True, exist_ok=True)
        if plan.original is not None:
            backup = plan.path.with_name(f"{plan.path.name}.{uuid.uuid4().hex}.bak")
            shutil.copy2(plan.path, backup)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=plan.path.parent,
                prefix=f".{plan.path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(plan.document, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if plan.original is not None:
                shutil.copymode(plan.path, temporary)
            os.replace(temporary, plan.path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="User home containing .gemini.")
    parser.add_argument("--profile", choices=PROFILES, default="personal-local")
    parser.add_argument(
        "--platform", choices=("windows", "posix"),
        default="windows" if os.name == "nt" else "posix",
        help="Command quoting and configuration template platform (default: current OS).",
    )
    parser.add_argument(
        "--replace-statusline", action="store_true",
        help="Allow replacing an existing statusLine owned by another command.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Write the planned configuration updates.")
    mode.add_argument("--dry-run", action="store_true", help="Only report the plan (the default).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plans = plan_install(args.home.expanduser().resolve(), args.profile, args.platform, args.replace_statusline)
        if args.apply:
            apply_plan(plans)
        print("Applied integration configuration:" if args.apply else "Dry run; configuration was not written:")
        for plan in plans:
            print(f"  {plan.action}: {plan.path}")
        hook_enabled = plans[0].document[HOOK_NAME].get("enabled", True) is not False
        status_enabled = plans[1].document["statusLine"].get("enabled", True) is not False
        print(f"Managed Hooks: {'enabled' if hook_enabled else 'disabled (preserved preference)'}")
        print(f"Managed statusLine: {'enabled' if status_enabled else 'disabled (preserved preference)'}")
        if not args.apply:
            print("Run again with --apply to install these callbacks.")
        print("Restart Antigravity to load the configuration; live callback delivery still requires verification.")
        return 0
    except InstallError as exc:
        print(f"Antigravity installation refused: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(
            f"Antigravity installation failed ({type(exc).__name__}); "
            "existing-file backups are kept beside their configuration files.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
