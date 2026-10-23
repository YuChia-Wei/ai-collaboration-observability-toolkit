from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from scripts import install_antigravity as installer


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_antigravity.py"
EXPORTER = ROOT / "examples" / "antigravity" / "antigravity_otel_exporter.py"
PRIVATE_SENTINEL = "INSTALLER_PRIVATE_SETTING_SENTINEL"


class InstallAntigravityTests(unittest.TestCase):
    def run_installer(self, home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(INSTALLER), "--home", str(home), *arguments],
            text=True, capture_output=True, cwd=ROOT, check=False,
        )
        self.assertNotIn(PRIVATE_SENTINEL, result.stdout + result.stderr)
        return result

    @staticmethod
    def config_paths(home: Path) -> tuple[Path, Path]:
        return home / ".gemini/config/hooks.json", home / ".gemini/antigravity-cli/settings.json"

    @staticmethod
    def write_json(path: Path, document: object) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        value = json.dumps(document, ensure_ascii=False).encode("utf-8")
        path.write_bytes(value)
        return value

    @staticmethod
    def commands(value: object) -> list[str]:
        if isinstance(value, list):
            return [command for item in value for command in InstallAntigravityTests.commands(item)]
        if isinstance(value, dict):
            return [item for key, item in value.items() if key == "command"] + [
                command for key, item in value.items() if key != "command"
                for command in InstallAntigravityTests.commands(item)
            ]
        return []

    def test_default_dry_run_does_not_create_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "uncreated home"
            result = self.run_installer(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Dry run", result.stdout)
            self.assertEqual(result.stdout.count("create:"), 2)
            self.assertFalse(home.exists())

    def test_windows_install_uses_canonical_absolute_paths_and_preserves_other_settings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="antigravity install ") as directory:
            home = Path(directory)
            hooks_path, settings_path = self.config_paths(home)
            self.write_json(hooks_path, {"other-owner": {"enabled": False, "private": PRIVATE_SENTINEL}})
            self.write_json(settings_path, {"theme": "dark", "secret": PRIVATE_SENTINEL})
            result = self.run_installer(home, "--apply", "--platform", "windows")
            self.assertEqual(result.returncode, 0, result.stderr)
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(hooks["other-owner"], {"enabled": False, "private": PRIVATE_SENTINEL})
            self.assertEqual(settings["theme"], "dark")
            self.assertEqual(settings["secret"], PRIVATE_SENTINEL)
            commands = self.commands(hooks["ai-observability"]) + self.commands(settings["statusLine"])
            expected_prefix = subprocess.list2cmdline([str(Path(sys.executable).resolve()), str(EXPORTER.resolve())])
            self.assertEqual(len(commands), 9)
            for command in commands:
                self.assertTrue(command.startswith(expected_prefix + " "), command)
                self.assertIn("--profile personal-local", command)
                self.assertNotIn(".agents\\observability", command)
            self.assertEqual(list(home.rglob(EXPORTER.name)), [])

    def test_posix_corporate_install_preserves_corporate_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = self.run_installer(home, "--apply", "--platform", "posix", "--profile", "corporate-local-redacted")
            self.assertEqual(result.returncode, 0, result.stderr)
            for path in self.config_paths(home):
                document = json.loads(path.read_text(encoding="utf-8"))
                for command in self.commands(document):
                    arguments = shlex.split(command)
                    self.assertEqual(arguments[:2], [str(Path(sys.executable).resolve()), str(EXPORTER.resolve())])
                    self.assertIn("corporate-local-redacted", arguments)
                    self.assertIn("--no-include-session-hash", arguments)

    def test_windows_paths_requiring_shell_quoting_are_refused(self) -> None:
        for path in ("C:/Program Files/Python/python.exe", "C:/repo&other/exporter.py", "C:/%USER%/python.exe"):
            with self.subTest(path=path), self.assertRaises(installer.InstallError):
                installer._shell_command([path, "C:/safe/exporter.py", "statusline"], "windows")
            with self.subTest(exporter=path), self.assertRaises(installer.InstallError):
                installer._shell_command(["C:/safe/python.exe", path, "statusline"], "windows")

    @unittest.skipUnless(os.name == "nt", "Windows Antigravity cmd.exe callback transport")
    def test_windows_callbacks_forward_stdin_through_antigravity_shell(self) -> None:
        with tempfile.TemporaryDirectory(prefix="antigravity callback ") as directory:
            home = Path(directory)
            result = self.run_installer(home, "--apply", "--platform", "windows")
            self.assertEqual(result.returncode, 0, result.stderr)
            hooks_path, settings_path = self.config_paths(home)
            hook = json.loads(hooks_path.read_text(encoding="utf-8"))["ai-observability"]
            status = json.loads(settings_path.read_text(encoding="utf-8"))["statusLine"]
            environment = os.environ.copy()
            environment.update({
                "AI_OBSERVABILITY_DRY_RUN": "true",
                "AI_OBSERVABILITY_STATE_DIR": str(home / "state"),
                "AI_OBSERVABILITY_CAPTURE_DIR": str(home / "capture"),
            })
            for command, payload, expected in (
                (hook["PreInvocation"][0]["command"], "{}", "injectSteps"),
                (status["command"], '{"product":"antigravity","agent_state":"idle"}', "AG"),
            ):
                # Match the Windows argv-to-cmd.exe boundary used by the real
                # Antigravity callback executor, from an unrelated directory.
                process = subprocess.run(
                    [os.environ.get("COMSPEC", "cmd.exe"), "/c", command],
                    input=payload, text=True, capture_output=True, env=environment,
                    cwd=home, check=False, timeout=10,
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertIn(expected, process.stdout)
            self.assertTrue(list((home / "capture").glob("*.json")))

    def test_statusline_conflict_refuses_all_writes_and_explicit_replacement_backs_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks_path, settings_path = self.config_paths(home)
            original = self.write_json(settings_path, {"secret": PRIVATE_SENTINEL, "statusLine": {"type": "command", "command": "other-statusline", "padding": 2}})
            refused = self.run_installer(home, "--apply")
            self.assertEqual(refused.returncode, 1)
            self.assertIn("--replace-statusline", refused.stderr)
            self.assertFalse(hooks_path.exists())
            self.assertEqual(settings_path.read_bytes(), original)
            self.assertEqual(list(home.rglob("*.bak")), [])
            installed = self.run_installer(home, "--apply", "--replace-statusline")
            self.assertEqual(installed.returncode, 0, installed.stderr)
            backups = list(settings_path.parent.glob("settings.json.*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8"))["secret"], PRIVATE_SENTINEL)

    def test_malformed_settings_refuse_before_changing_valid_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks_path, settings_path = self.config_paths(home)
            original = self.write_json(hooks_path, {"other-owner": {"private": PRIVATE_SENTINEL}})
            settings_path.parent.mkdir(parents=True)
            settings_path.write_text('{"private":"' + PRIVATE_SENTINEL, encoding="utf-8")
            result = self.run_installer(home, "--apply")
            self.assertEqual(result.returncode, 1)
            self.assertIn("Invalid JSON", result.stderr)
            self.assertEqual(hooks_path.read_bytes(), original)
            self.assertEqual(list(home.rglob("*.bak")), [])

    def test_non_object_or_ambiguous_json_is_rejected_without_creating_settings(self) -> None:
        for invalid in ('[]', '{"duplicate":1,"duplicate":2}', '{"number":NaN}'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                hooks_path, settings_path = self.config_paths(home)
                hooks_path.parent.mkdir(parents=True)
                hooks_path.write_text(invalid, encoding="utf-8")
                result = self.run_installer(home, "--apply")
                self.assertEqual(result.returncode, 1)
                self.assertFalse(settings_path.exists())
                self.assertEqual(hooks_path.read_text(encoding="utf-8"), invalid)
                self.assertEqual(list(home.rglob("*.bak")), [])

    def test_managed_update_backs_up_originals_preserves_options_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first = self.run_installer(home, "--apply")
            self.assertEqual(first.returncode, 0, first.stderr)
            hooks_path, settings_path = self.config_paths(home)
            self.assertEqual(list(home.rglob("*.bak")), [])
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            hooks["ai-observability"]["enabled"] = False
            self.write_json(hooks_path, hooks)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["statusLine"].update({"padding": 1, "stack_with_default": True, "enabled": False})
            self.write_json(settings_path, settings)
            before = {path: path.read_bytes() for path in (hooks_path, settings_path)}
            updated = self.run_installer(home, "--apply", "--profile", "corporate-local-redacted")
            self.assertEqual(updated.returncode, 0, updated.stderr)
            self.assertFalse(json.loads(hooks_path.read_text(encoding="utf-8"))["ai-observability"]["enabled"])
            self.assertIn("Managed Hooks: disabled (preserved preference)", updated.stdout)
            self.assertIn("Managed statusLine: disabled (preserved preference)", updated.stdout)
            for path, original in before.items():
                backups = list(path.parent.glob(f"{path.name}.*.bak"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), original)
            statusline = json.loads(settings_path.read_text(encoding="utf-8"))["statusLine"]
            self.assertEqual(statusline["padding"], 1)
            self.assertTrue(statusline["stack_with_default"])
            self.assertFalse(statusline["enabled"])
            current = {path: path.read_bytes() for path in before}
            again = self.run_installer(home, "--apply", "--profile", "corporate-local-redacted")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(again.stdout.count("unchanged:"), 2)
            self.assertEqual(len(list(home.rglob("*.bak"))), 2)
            self.assertEqual({path: path.read_bytes() for path in before}, current)

    def test_dry_run_update_creates_no_backups_and_keeps_original_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks_path, settings_path = self.config_paths(home)
            original = self.write_json(hooks_path, {"other-owner": {"enabled": True}})
            result = self.run_installer(home, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("update:", result.stdout)
            self.assertEqual(hooks_path.read_bytes(), original)
            self.assertFalse(settings_path.exists())
            self.assertEqual(list(home.rglob("*.bak")), [])


if __name__ == "__main__":
    unittest.main()
