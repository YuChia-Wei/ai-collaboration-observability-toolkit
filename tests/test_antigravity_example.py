from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/antigravity"
EXPORTER = EXAMPLE / "antigravity_otel_exporter.py"
FIXTURES = EXAMPLE / "fixtures"
CONFIG = EXAMPLE / "config"
RAW_CONVERSATION = "ec33ebf9-0cba-4100-8142-c61503f6c587"
FORBIDDEN_TEXT = (
    RAW_CONVERSATION,
    "developer@internal.example",
    "/secret/customer/project",
    "customer-secret-feature",
    "transcript.jsonl",
    "secret command output and internal file path must not be exported",
    "ANTIGRAVITY_PRIVATE_SENTINEL_93F2",
    "dotnet test",
    "run_command",
    "toolCall",
    "CommandLine",
)
EXPECTED_OPERATIONS = {
    "file-operation",
    "search-operation",
    "execution-operation",
    "agent-collaboration",
    "interaction-operation",
}


class AntigravityExampleTests(unittest.TestCase):
    maxDiff = None

    def run_exporter(
        self,
        args: list[str],
        fixture: str,
        *,
        state_dir: Path,
        capture_dir: Path,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(EXPORTER),
                *args,
                "--dry-run",
                "--capture-dir",
                str(capture_dir),
                "--state-dir",
                str(state_dir),
            ],
            input=(FIXTURES / fixture).read_text(encoding="utf-8"),
            text=True,
            capture_output=True,
            check=True,
            cwd=ROOT,
        )

    @staticmethod
    def captured_payloads(capture_dir: Path) -> list[dict]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(capture_dir.glob("*.json"))
        ]

    def test_direct_configuration_examples_are_valid_and_passive(self) -> None:
        hook_files = sorted(CONFIG.glob("hooks.*.json.example"))
        status_files = sorted(CONFIG.glob("settings.statusline.*.json.fragment.example"))
        self.assertEqual(len(hook_files), 4)
        self.assertEqual(len(status_files), 4)
        self.assertFalse((EXAMPLE / "plugin").exists())

        for path in hook_files:
            value = json.loads(path.read_text(encoding="utf-8"))
            hook = value["ai-observability"]
            self.assertNotIn("PreToolUse", hook)
            self.assertEqual(
                set(hook),
                {"PreInvocation", "PostInvocation", "PostToolUse", "Stop"},
            )
            self.assertEqual(len(hook["PostToolUse"]), 5)
            operations = set()
            for definition in hook["PostToolUse"]:
                self.assertNotIn(definition["matcher"], {"", "*"})
                command = definition["hooks"][0]["command"]
                self.assertIn(" --operation ", command)
                operations.add(command.split(" --operation ", 1)[1].split(" ", 1)[0])
            self.assertEqual(operations, EXPECTED_OPERATIONS)
            rendered = path.read_text(encoding="utf-8")
            self.assertIn("antigravity_otel_exporter.py", rendered)
            self.assertIn("--product antigravity", rendered)
            if ".corporate." in path.name:
                self.assertIn("--no-include-session-hash", rendered)

        for path in status_files:
            value = json.loads(path.read_text(encoding="utf-8"))
            command = value["statusLine"]["command"]
            self.assertEqual(value["statusLine"]["type"], "command")
            self.assertIn(" statusline ", f" {command} ")
            self.assertIn("--product antigravity", command)
            if ".corporate." in path.name:
                self.assertIn("--no-include-session-hash", command)

    def test_statusline_emits_safe_logs_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_exporter(
                [
                    "statusline",
                    "--profile",
                    "personal-local",
                    "--product",
                    "antigravity",
                    "--service-namespace",
                    "ai-collaboration-fixture",
                ],
                "statusline.json",
                state_dir=root / "state",
                capture_dir=root / "capture",
            )
            self.assertIn("AGY Gemini 3.6 Flash", result.stdout)
            payloads = self.captured_payloads(root / "capture")
            self.assertEqual(len(payloads), 2)
            rendered = json.dumps(payloads, sort_keys=True)
            for forbidden in FORBIDDEN_TEXT:
                self.assertNotIn(forbidden, rendered)
            for metric_name in (
                "antigravity_session_tokens",
                "antigravity_context_tokens",
                "antigravity_context_used_ratio",
                "antigravity_quota_remaining_ratio",
                "antigravity_background_task_count",
                "antigravity_artifact_count",
                "antigravity_context_exceeds_200k",
                "antigravity_pending_input_count",
                "antigravity_tool_confirmation_pending",
            ):
                self.assertIn(metric_name, rendered)
            self.assertIn("Gemini 3.6 Flash (High)", rendered)
            self.assertIn("antigravity.status.changed", rendered)
            self.assertIn("ai_context.session.id", rendered)
            self.assertIn('"ai_agent.provider"', rendered)
            self.assertIn('"stringValue": "google"', rendered)
            self.assertIn('"ai_agent.product"', rendered)
            self.assertIn('"ai_agent.surface"', rendered)
            self.assertIn('"stringValue": "status-line"', rendered)
            self.assertIn('"stringValue": "ai-collaboration-fixture"', rendered)
            self.assertIn('"ai_agent.evidence.class"', rendered)
            self.assertIn('"stringValue": "observed"', rendered)
            self.assertIn('"version": "0.1.5"', rendered)
            self.assertNotIn("ai_context.export.phoenix", rendered)

    def test_corporate_statusline_omits_session_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_exporter(
                [
                    "statusline",
                    "--profile",
                    "corporate-local-redacted",
                    "--product",
                    "antigravity",
                    "--no-include-session-hash",
                ],
                "statusline.json",
                state_dir=root / "state",
                capture_dir=root / "capture",
            )
            rendered = json.dumps(self.captured_payloads(root / "capture"), sort_keys=True)
            self.assertNotIn("ai_context.session.id", rendered)
            for forbidden in FORBIDDEN_TEXT:
                self.assertNotIn(forbidden, rendered)

    def test_hook_sequence_uses_documented_fields_and_excludes_sensitive_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            capture = root / "capture"
            cases = (
                ("PreInvocation", "pre-invocation.json", [], {"injectSteps": []}),
                (
                    "PostInvocation",
                    "post-invocation.json",
                    [],
                    {"injectSteps": [], "terminationBehavior": ""},
                ),
                (
                    "PostToolUse",
                    "post-tool-use.json",
                    ["--operation", "execution-operation"],
                    {},
                ),
                ("Stop", "stop.json", [], {"decision": ""}),
            )
            for event, fixture, extra, expected in cases:
                result = self.run_exporter(
                    [
                        "hook",
                        event,
                        *extra,
                        "--profile",
                        "personal-local",
                        "--product",
                        "antigravity",
                    ],
                    fixture,
                    state_dir=state,
                    capture_dir=capture,
                )
                self.assertEqual(json.loads(result.stdout), expected)

            payloads = self.captured_payloads(capture)
            rendered = json.dumps(payloads, sort_keys=True)
            for forbidden in FORBIDDEN_TEXT:
                self.assertNotIn(forbidden, rendered)
            self.assertIn("antigravity.agent.invocation", rendered)
            self.assertIn("antigravity.agent.execution", rendered)
            self.assertIn("antigravity.tool.completed", rendered)
            self.assertIn("tool_error", rendered)
            self.assertIn("execution-operation", rendered)
            self.assertIn("gemini-3.6-flash-medium", rendered)
            self.assertIn('"ai_agent.provider"', rendered)
            self.assertIn('"ai_agent.surface"', rendered)
            self.assertIn('"stringValue": "hooks"', rendered)
            self.assertIn('"ai_agent.operation"', rendered)
            self.assertNotIn("gen_ai.tool.name", rendered)
            self.assertNotIn("antigravity.tool.name", rendered)
            self.assertNotIn("tool.arguments", rendered)
            self.assertNotIn("tool.output", rendered)

            spans = [
                span
                for payload in payloads
                for resource_spans in payload.get("resourceSpans", [])
                for scope_spans in resource_spans.get("scopeSpans", [])
                for span in scope_spans.get("spans", [])
            ]
            self.assertEqual(len(spans), 2)
            self.assertEqual(len({span["traceId"] for span in spans}), 2)
            self.assertTrue(all("parentSpanId" not in span for span in spans))

    def test_statusline_deduplicates_unchanged_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = [
                "statusline",
                "--profile",
                "personal-local",
                "--product",
                "antigravity",
                "--heartbeat-seconds",
                "3600",
            ]
            self.run_exporter(
                args,
                "statusline.json",
                state_dir=root / "state",
                capture_dir=root / "capture",
            )
            first_count = len(list((root / "capture").glob("*.json")))
            self.run_exporter(
                args,
                "statusline.json",
                state_dir=root / "state",
                capture_dir=root / "capture",
            )
            second_count = len(list((root / "capture").glob("*.json")))
            self.assertEqual(first_count, 2)
            self.assertEqual(second_count, first_count)

    def test_live_otlp_http_export_uses_signal_paths_without_sensitive_values(self) -> None:
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
        try:
            with tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / "state"
                sequence = (
                    ("PreInvocation", "pre-invocation.json", []),
                    ("PostInvocation", "post-invocation.json", []),
                    (
                        "PostToolUse",
                        "post-tool-use.json",
                        ["--operation", "execution-operation"],
                    ),
                    ("Stop", "stop.json", []),
                )
                for event, fixture, extra in sequence:
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(EXPORTER),
                            "hook",
                            event,
                            *extra,
                            "--profile",
                            "personal-local",
                            "--product",
                            "antigravity",
                            "--endpoint",
                            f"http://127.0.0.1:{server.server_port}",
                            "--timeout",
                            "1",
                            "--state-dir",
                            str(state),
                        ],
                        input=(FIXTURES / fixture).read_text(encoding="utf-8"),
                        text=True,
                        capture_output=True,
                        check=True,
                        cwd=ROOT,
                    )
                    self.assertIsInstance(json.loads(result.stdout), dict)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertGreaterEqual(len(received), 6)
        paths = [path for path, _ in received]
        self.assertIn("/v1/logs", paths)
        self.assertIn("/v1/traces", paths)
        wire = b"\n".join(body for _, body in received).decode("utf-8")
        for forbidden in FORBIDDEN_TEXT:
            self.assertNotIn(forbidden, wire)
        self.assertIn("gemini-3.6-flash-medium", wire)
        self.assertIn("execution-operation", wire)


if __name__ == "__main__":
    unittest.main()
