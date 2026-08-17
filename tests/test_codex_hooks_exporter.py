from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import unittest
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/codex-hooks"
EXPORTER = EXAMPLE / "codex_hooks_otel_exporter.py"
INSTALLER = EXAMPLE / "install_hooks.py"
FIXTURES = EXAMPLE / "fixtures"
CONFIG = EXAMPLE / "config/hooks.personal.json.example"
FORBIDDEN_TEXT = (
    "thr_PRIVATE_4c296a99",
    "turn_PRIVATE_b717195c",
    "tool_PRIVATE_f2dfef51",
    "CODEX_HOOK_PRIVATE_SENTINEL_72C9",
    "developer@internal.example",
    "customer-secret-repository",
    "rollout.jsonl",
    "secret.txt",
    "secret command output",
    "Get-Content",
    "private assistant response",
)

EXPORTER_SPEC = importlib.util.spec_from_file_location(
    "codex_hooks_otel_exporter_under_test", EXPORTER
)
if EXPORTER_SPEC is None or EXPORTER_SPEC.loader is None:
    raise RuntimeError("Could not load the Codex Hooks exporter for direct privacy tests")
EXPORTER_MODULE = importlib.util.module_from_spec(EXPORTER_SPEC)
EXPORTER_SPEC.loader.exec_module(EXPORTER_MODULE)


@contextmanager
def workspace_test_directory():
    # Windows Python creates TemporaryDirectory with an ACL that sandboxed child
    # processes cannot traverse. Let the exporter create this unique ignored path.
    root = ROOT / "artifacts" / f"codex-hooks-test-{uuid.uuid4().hex}"
    try:
        yield root
    finally:
        if root.exists():
            shutil.rmtree(root)


class CodexHooksExporterTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        (ROOT / "artifacts").mkdir(parents=True, exist_ok=True)

    def run_fixture(
        self,
        fixture: str,
        *,
        state_dir: Path,
        capture_dir: Path,
        extra: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(EXPORTER),
                "--dry-run",
                "--state-dir",
                str(state_dir),
                "--capture-dir",
                str(capture_dir),
                *(extra or []),
            ],
            input=(FIXTURES / fixture).read_text(encoding="utf-8"),
            text=True,
            capture_output=True,
            check=True,
            cwd=ROOT,
        )

    @staticmethod
    def captured_payloads(capture_dir: Path) -> list[dict[str, object]]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(capture_dir.glob("*.json"))
        ]

    @staticmethod
    def spans(payloads: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            span
            for payload in payloads
            for resource_spans in payload.get("resourceSpans", [])
            for scope_spans in resource_spans.get("scopeSpans", [])
            for span in scope_spans.get("spans", [])
        ]

    @staticmethod
    def metrics(payloads: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            metric
            for payload in payloads
            for resource_metrics in payload.get("resourceMetrics", [])
            for scope_metrics in resource_metrics.get("scopeMetrics", [])
            for metric in scope_metrics.get("metrics", [])
        ]

    @staticmethod
    def attributes(span: dict[str, object]) -> dict[str, object]:
        values: dict[str, object] = {}
        for item in span.get("attributes", []):
            value = item["value"]
            values[item["key"]] = next(iter(value.values()))
        return values

    def test_hook_sequence_correlates_agent_and_tool_without_sensitive_content(self) -> None:
        with workspace_test_directory() as root:
            state = root / "state"
            capture = root / "capture"

            user = self.run_fixture(
                "user-prompt-submit.json", state_dir=state, capture_dir=capture
            )
            pre = self.run_fixture(
                "pre-tool-use.json", state_dir=state, capture_dir=capture
            )
            self.assertEqual(user.stdout, "")
            self.assertEqual(pre.stdout, "")

            state_text = "\n".join(
                [str(path.relative_to(state)) for path in state.rglob("*")]
                + [
                    path.read_text(encoding="utf-8")
                    for path in state.rglob("*.json")
                ]
            )
            for forbidden in FORBIDDEN_TEXT:
                self.assertNotIn(forbidden, state_text)

            post = self.run_fixture(
                "post-tool-use.json", state_dir=state, capture_dir=capture
            )
            stop = self.run_fixture("stop.json", state_dir=state, capture_dir=capture)
            self.assertEqual(post.stdout, "")
            self.assertEqual(json.loads(stop.stdout), {})

            payloads = self.captured_payloads(capture)
            rendered = json.dumps(payloads, sort_keys=True)
            for forbidden in FORBIDDEN_TEXT:
                self.assertNotIn(forbidden, rendered)
            self.assertNotIn("ai_context.", rendered)
            self.assertNotIn('"stringValue": "LLM"', rendered)

            spans = self.spans(payloads)
            self.assertEqual(len(spans), 2)
            by_name = {span["name"]: span for span in spans}
            agent = by_name["codex.agent.turn"]
            tool = by_name["codex.tool.execution"]
            self.assertEqual(agent["traceId"], tool["traceId"])
            self.assertEqual(tool["parentSpanId"], agent["spanId"])
            self.assertEqual(agent["status"], {"code": 0})
            self.assertEqual(tool["status"], {"code": 0})

            agent_attributes = self.attributes(agent)
            tool_attributes = self.attributes(tool)
            self.assertEqual(agent_attributes["openinference.span.kind"], "AGENT")
            self.assertEqual(tool_attributes["openinference.span.kind"], "TOOL")
            self.assertEqual(tool_attributes["tool.name"], "execution")
            self.assertEqual(tool_attributes["ai_agent.tool.category"], "execution")
            self.assertEqual(agent_attributes["gen_ai.request.model"], "gpt-5.6-sol")
            self.assertEqual(agent_attributes["ai_agent.coverage"], "partial")
            self.assertFalse(list(state.rglob("*.json")))

    def test_metadata_only_does_not_access_prompt_field(self) -> None:
        class PromptPoison(dict[str, object]):
            def get(self, key: str, default: object = None) -> object:
                if key == "prompt":
                    raise AssertionError("metadata-only mode must not read prompt")
                return super().get(key, default)

        with workspace_test_directory() as root:
            payload = PromptPoison(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "thr_PRIVATE_4c296a99",
                    "turn_id": "turn_PRIVATE_b717195c",
                    "model": "gpt-5.6-sol",
                    "prompt": "CODEX_HOOK_PRIVATE_SENTINEL_72C9",
                }
            )
            EXPORTER_MODULE._handle_event(
                payload,
                argparse.Namespace(
                    state_dir=str(root / "state"),
                    capture_mode="metadata-only",
                ),
            )
            state_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (root / "state").rglob("*.json")
            )
            self.assertNotIn("CODEX_HOOK_PRIVATE_SENTINEL_72C9", state_text)

    def test_size_only_exports_exact_utf8_bytes_without_content(self) -> None:
        with workspace_test_directory() as root:
            state = root / "state"
            capture = root / "capture"
            self.run_fixture(
                "user-prompt-submit.json",
                state_dir=state,
                capture_dir=capture,
                extra=["--capture-mode", "size-only"],
            )

            payloads = self.captured_payloads(capture)
            rendered = json.dumps(payloads, sort_keys=True)
            for forbidden in FORBIDDEN_TEXT:
                self.assertNotIn(forbidden, rendered)
            self.assertFalse(self.spans(payloads))

            metrics = self.metrics(payloads)
            self.assertEqual(len(metrics), 1)
            metric = metrics[0]
            self.assertEqual(metric["name"], "ai_agent.observed.user_prompt.bytes")
            self.assertEqual(metric["unit"], "By")
            histogram = metric["histogram"]
            self.assertEqual(histogram["aggregationTemporality"], 1)
            point = histogram["dataPoints"][0]
            expected = len(
                json.loads(
                    (FIXTURES / "user-prompt-submit.json").read_text(encoding="utf-8")
                )["prompt"].encode("utf-8")
            )
            self.assertEqual(point["sum"], expected)
            self.assertEqual(point["count"], "1")
            self.assertEqual(point["bucketCounts"].count("1"), 1)
            self.assertEqual(
                self.attributes(point),
                {
                    "operation": "turn",
                    "evidence_class": "observed",
                    "content_scope": "user_prompt",
                    "measurement_method": "utf8_bytes",
                },
            )
            state_text = "\n".join(
                path.read_text(encoding="utf-8") for path in state.rglob("*.json")
            )
            for forbidden in FORBIDDEN_TEXT:
                self.assertNotIn(forbidden, state_text)

    def test_size_only_is_rejected_for_corporate_profile(self) -> None:
        with workspace_test_directory() as root:
            self.run_fixture(
                "user-prompt-submit.json",
                state_dir=root / "state",
                capture_dir=root / "capture",
                extra=[
                    "--capture-mode",
                    "size-only",
                    "--profile",
                    "corporate-local-redacted",
                ],
            )
            self.assertEqual(self.captured_payloads(root / "capture"), [])

    def test_live_otlp_export_uses_collector_path_and_explicit_opt_out_header(self) -> None:
        received: list[tuple[str, str | None, bytes]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                received.append(
                    (
                        self.path,
                        self.headers.get("x-ai-observability-phoenix"),
                        self.rfile.read(length),
                    )
                )
                self.send_response(200)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with workspace_test_directory() as root:
                state = root / "state"
                for fixture in (
                    "user-prompt-submit.json",
                    "pre-tool-use.json",
                    "post-tool-use.json",
                    "stop.json",
                ):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(EXPORTER),
                            "--endpoint",
                            f"http://127.0.0.1:{server.server_port}",
                            "--state-dir",
                            str(state),
                            "--no-phoenix",
                        ],
                        input=(FIXTURES / fixture).read_text(encoding="utf-8"),
                        text=True,
                        capture_output=True,
                        check=True,
                        cwd=ROOT,
                    )
                    self.assertEqual(result.stderr, "")
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(len(received), 2)
        self.assertTrue(all(path == "/v1/traces" for path, _, _ in received))
        self.assertTrue(all(header == "false" for _, header, _ in received))
        rendered = b"\n".join(body for _, _, body in received).decode("utf-8")
        for forbidden in FORBIDDEN_TEXT:
            self.assertNotIn(forbidden, rendered)

    def test_live_size_only_metric_uses_metrics_path_without_content(self) -> None:
        received: list[tuple[str, bytes]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                received.append((self.path, self.rfile.read(length)))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        fixture = json.loads(
            (FIXTURES / "user-prompt-submit.json").read_text(encoding="utf-8")
        )
        fixture["prompt"] = "CODEX_HOOK_PRIVATE_SENTINEL_72C9 \u91cf\u6e2c\U0001F512"
        try:
            with workspace_test_directory() as root:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(EXPORTER),
                        "--endpoint",
                        f"http://127.0.0.1:{server.server_port}/v1/metrics",
                        "--capture-mode",
                        "size-only",
                        "--state-dir",
                        str(root / "state"),
                    ],
                    input=json.dumps(fixture),
                    text=True,
                    capture_output=True,
                    check=True,
                    cwd=ROOT,
                )
                self.assertEqual(result.stderr, "")
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "/v1/metrics")
        rendered = received[0][1].decode("utf-8")
        for forbidden in FORBIDDEN_TEXT:
            self.assertNotIn(forbidden, rendered)
        metric = self.metrics([json.loads(rendered)])[0]
        self.assertEqual(metric["name"], "ai_agent.observed.user_prompt.bytes")
        point = metric["histogram"]["dataPoints"][0]
        self.assertEqual(point["sum"], len(fixture["prompt"].encode("utf-8")))

    def test_config_uses_documented_passive_events(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        hooks = config["hooks"]
        self.assertEqual(
            set(hooks), {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
        )
        for groups in hooks.values():
            self.assertEqual(len(groups), 1)
            handler = groups[0]["hooks"][0]
            self.assertEqual(handler["type"], "command")
            self.assertLessEqual(handler["timeout"], 5)
            self.assertIn("codex_hooks_otel_exporter.py", handler["command"])
            self.assertIn("codex_hooks_otel_exporter.py", handler["commandWindows"])
            self.assertIn("ABSOLUTE", handler["commandWindows"])
            self.assertNotIn("powershell", handler["commandWindows"].lower())
            self.assertNotIn("--phoenix", handler["command"])
            self.assertIn("--capture-mode metadata-only", handler["command"])

    def test_non_loopback_endpoint_is_rejected_without_blocking_stop(self) -> None:
        with workspace_test_directory() as root:
            self.run_fixture(
                "user-prompt-submit.json",
                state_dir=root / "state",
                capture_dir=root / "capture",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(EXPORTER),
                    "--endpoint",
                    "https://telemetry.invalid.example",
                    "--state-dir",
                    str(root / "state"),
                    "--debug",
                ],
                input=(FIXTURES / "stop.json").read_text(encoding="utf-8"),
                text=True,
                capture_output=True,
                check=True,
                cwd=ROOT,
            )
            self.assertEqual(json.loads(result.stdout), {})
            self.assertIn("ValueError", result.stderr)
            self.assertFalse(list((root / "state").rglob("*.json")))

    def test_installer_generates_direct_command_and_forwards_stdin(self) -> None:
        with workspace_test_directory() as root:
            target = root / ".codex" / "hooks.json"
            installed = subprocess.run(
                [sys.executable, str(INSTALLER), "--target", str(target)],
                text=True,
                capture_output=True,
                check=True,
                cwd=ROOT,
            )
            self.assertIn("Created Codex hook configuration", installed.stdout)
            config_text = target.read_text(encoding="utf-8")
            config = json.loads(config_text)
            handler = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]
            command = handler["commandWindows" if os.name == "nt" else "command"]
            self.assertIn(str(Path(sys.executable).resolve()), command)
            self.assertIn(str(EXPORTER.resolve()), command)
            self.assertNotIn("powershell", command.lower())
            self.assertIn("--capture-mode metadata-only", command)

            environment = os.environ.copy()
            environment["AI_OBSERVABILITY_DRY_RUN"] = "true"
            environment["AI_OBSERVABILITY_STATE_DIR"] = str(root / "state")
            environment["AI_OBSERVABILITY_CAPTURE_DIR"] = str(root / "capture")
            result = subprocess.run(
                command,
                input=(FIXTURES / "user-prompt-submit.json").read_text(
                    encoding="utf-8"
                ),
                text=True,
                capture_output=True,
                check=True,
                shell=True,
                cwd=ROOT / "docs",
                env=environment,
            )
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            self.assertEqual(len(list((root / "state").rglob("*.json"))), 1)

            refused = subprocess.run(
                [sys.executable, str(INSTALLER), "--target", str(target)],
                text=True,
                capture_output=True,
                check=False,
                cwd=ROOT,
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("Refusing to replace existing hook configuration", refused.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), config_text)

    def test_installer_can_render_explicit_size_only_command(self) -> None:
        rendered = subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                "--print",
                "--capture-mode",
                "size-only",
            ],
            text=True,
            capture_output=True,
            check=True,
            cwd=ROOT,
        )
        config = json.loads(rendered.stdout)
        for group in config["hooks"].values():
            command = group[0]["hooks"][0]["command"]
            self.assertIn("--capture-mode size-only", command)


if __name__ == "__main__":
    unittest.main()
