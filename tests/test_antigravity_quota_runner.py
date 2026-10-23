from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import antigravity_local as local
from scripts import antigravity_quota as runner


SCRATCH_ROOT = Path(os.getenv(
    "ANTIGRAVITY_QUOTA_TEST_ROOT",
    str(Path(tempfile.gettempdir()) / "antigravity-quota-tests"),
))
PRIVATE_TEXT = "private-account@example.invalid private-provider-response private-command-output"


def report_fixture() -> dict:
    return {
        "status": "SUCCESS",
        "num_turns": 0,
        "account": PRIVATE_TEXT,
        "command": {
            "name": "usage",
            "data": {
                "groups": [{
                    "name": "Gemini Models",
                    "buckets": [{
                        "id": "gemini-5h", "window": "5h",
                        "remaining_fraction": 0.75,
                        "reset_time": "2026-10-23T18:00:00Z",
                    }],
                }],
            },
        },
    }


def arguments(**overrides) -> argparse.Namespace:
    values = {
        "agy_bin": None, "timeout": 20, "scratch_root": SCRATCH_ROOT,
        "export": False, "endpoint": "http://127.0.0.1:4318",
        "service_namespace": "ai-collaboration-fixture", "profile": "personal-local",
        "output": None, "watch": False, "interval_seconds": 120,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def metrics_from(payload: dict) -> list[dict]:
    return [
        metric
        for resource in payload["resourceMetrics"]
        for scope in resource["scopeMetrics"]
        for metric in scope["metrics"]
    ]


class AntigravityQuotaRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="runner-", dir=SCRATCH_ROOT)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.executable = self.root / "agy.exe"
        self.executable.write_bytes(b"not-executed-test-placeholder")
        # Unit fixtures replace only the reviewed installation boundary; live
        # acceptance separately exercises the installed native executable.
        source_check = mock.patch.object(runner, "_is_native_cli_installation", return_value=True)
        source_check.start()
        self.addCleanup(source_check.stop)

    def test_official_report_uses_only_fixed_zero_turn_command_and_isolates_callbacks(self) -> None:
        report = report_fixture()
        process_results = [
            subprocess.CompletedProcess([], 0, "1.1.11\n", ""),
            subprocess.CompletedProcess([], 0, json.dumps(report), PRIVATE_TEXT),
        ]
        with mock.patch.object(runner.subprocess, "run", side_effect=process_results) as run:
            with mock.patch.dict(os.environ, {"AI_OBSERVABILITY_CAPTURE_DIR": PRIVATE_TEXT}):
                actual = runner.read_official_report(
                    agy_bin=str(self.executable), timeout=17, scratch_root=self.root,
                )
        self.assertEqual(actual, report)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], [str(self.executable.resolve()), "--version"])
        read_call = run.call_args_list[1]
        self.assertEqual(read_call.args[0], [
            str(self.executable.resolve()), "--log-file", os.devnull,
            "-p", "/usage", "--output-format", "json", "--print-timeout", "17s",
        ])
        self.assertEqual(read_call.kwargs["timeout"], 22)
        self.assertTrue(Path(read_call.kwargs["cwd"]).is_relative_to(self.root))
        environment = read_call.kwargs["env"]
        self.assertEqual(environment["AI_OBSERVABILITY_DRY_RUN"], "true")
        self.assertEqual(environment["AI_OBSERVABILITY_SERVICE_NAMESPACE"], "ai-collaboration-fixture")
        self.assertNotIn("AI_OBSERVABILITY_CAPTURE_DIR", environment)
        self.assertFalse(Path(read_call.kwargs["cwd"]).exists())

    def test_unsupported_cli_version_never_runs_usage_command(self) -> None:
        for version in ("1.1.10", "unrecognized " + PRIVATE_TEXT):
            with self.subTest(version=version):
                with mock.patch.object(runner.subprocess, "run", return_value=
                    subprocess.CompletedProcess([], 0, version, PRIVATE_TEXT)) as run:
                    with self.assertRaisesRegex(runner.QuotaCollectionError, "^unsupported_cli_version$"):
                        runner.read_official_report(agy_bin=str(self.executable), scratch_root=self.root)
                self.assertEqual(run.call_count, 1)

    def test_unverified_installation_is_rejected_before_running_any_command(self) -> None:
        with mock.patch.object(runner, "_is_native_cli_installation", return_value=False):
            with mock.patch.object(runner.subprocess, "run") as run:
                with self.assertRaisesRegex(runner.QuotaCollectionError, "^unverified_cli_installation$"):
                    runner.read_official_report(agy_bin=str(self.executable), scratch_root=self.root)
        run.assert_not_called()

    def test_provider_timeout_and_failures_do_not_echo_provider_content(self) -> None:
        cases = [
            (subprocess.TimeoutExpired([PRIVATE_TEXT], 20, output=PRIVATE_TEXT), "cli_report_timeout"),
            (OSError(PRIVATE_TEXT), "cli_report_unavailable"),
            (subprocess.CompletedProcess([], 1, PRIVATE_TEXT, PRIVATE_TEXT), "cli_report_failed"),
            (subprocess.CompletedProcess([], 0, PRIVATE_TEXT, PRIVATE_TEXT), "cli_report_unavailable"),
        ]
        for result, code in cases:
            with self.subTest(code=code, result_type=type(result).__name__):
                side_effect = [subprocess.CompletedProcess([], 0, "1.1.11", ""), result]
                with mock.patch.object(runner.subprocess, "run", side_effect=side_effect):
                    with self.assertRaises(runner.QuotaCollectionError) as raised:
                        runner.read_official_report(agy_bin=str(self.executable), scratch_root=self.root)
                self.assertEqual(str(raised.exception), code)
                self.assertNotIn(PRIVATE_TEXT, str(raised.exception))

    def test_report_size_and_non_object_results_are_rejected(self) -> None:
        for stdout, code in (("x" * (runner.MAX_REPORT_BYTES + 1), "cli_report_too_large"),
                             ("[]", "invalid_cli_report")):
            with self.subTest(code=code):
                with mock.patch.object(runner.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 0, "1.1.11", ""),
                    subprocess.CompletedProcess([], 0, stdout, ""),
                ]):
                    with self.assertRaisesRegex(runner.QuotaCollectionError, f"^{code}$"):
                        runner.read_official_report(agy_bin=str(self.executable), scratch_root=self.root)

    def test_verified_collection_exports_sanitized_account_gauges(self) -> None:
        def guarded_read(reader):
            return reader(), {"same_account": True, "binding_stable_during_read": True}

        with mock.patch.object(local, "collect_verified", side_effect=guarded_read) as verify:
            with mock.patch.object(runner, "read_official_report", return_value=report_fixture()) as read:
                with mock.patch.object(runner, "export_metrics") as export:
                    snapshot = runner.collect_snapshot(arguments(export=True))
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(snapshot["identity_status"], "matched")
        self.assertEqual(snapshot["export_status"], "otlp-accepted")
        self.assertTrue(snapshot["identity_verification"]["account_stable_during_report"])
        payload = export.call_args.args[0]
        self.assertNotIn(PRIVATE_TEXT, json.dumps(payload))
        self.assertNotIn(PRIVATE_TEXT, json.dumps(snapshot))
        self.assertEqual({m["name"] for m in metrics_from(payload)}, {
            "antigravity_account_quota_remaining_ratio",
            "antigravity_account_quota_reset_timestamp_seconds",
            "antigravity_account_quota_snapshot_timestamp_seconds",
            "antigravity_account_quota_identity_match",
        })

    def test_identity_failure_closes_gate_without_refreshing_snapshot_or_reading_report(self) -> None:
        for code in ("account_mismatch", "desktop_identity_unavailable", "account_binding_changed"):
            with self.subTest(code=code):
                output = io.StringIO()
                with mock.patch.object(local, "collect_verified", side_effect=local.LocalVerificationError(code)):
                    with mock.patch.object(runner, "read_official_report") as read:
                        with mock.patch.object(runner, "export_metrics") as export:
                            with contextlib.redirect_stdout(output):
                                result = runner.run(arguments(export=True))
                self.assertEqual(result, 1)
                read.assert_not_called()
                export.assert_called_once()
                metrics = metrics_from(export.call_args.args[0])
                self.assertEqual([m["name"] for m in metrics], ["antigravity_account_quota_identity_match"])
                self.assertEqual(metrics[0]["gauge"]["dataPoints"][0]["asDouble"], 0)
                self.assertEqual(json.loads(output.getvalue())["error"], code)

    def test_expired_native_binding_discards_probe_and_reverifies_a_separate_report(self) -> None:
        verified_reads = 0

        def verify(reader):
            nonlocal verified_reads
            verified_reads += 1
            if verified_reads == 1:
                raise local.LocalVerificationError("cli_auth_expired")
            return reader(), {"same_account": True}

        probe_report, final_report = report_fixture(), report_fixture()
        probe_report["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"] = 0.99
        final_report["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"] = 0.25
        with mock.patch.object(local, "collect_verified", side_effect=verify):
            with mock.patch.object(local, "refresh_expired_cli_binding", side_effect=lambda probe: probe()):
                with mock.patch.object(runner, "_is_native_cli_installation", return_value=True):
                    with mock.patch.object(runner, "read_official_report", side_effect=[probe_report, final_report]) as read:
                        result = runner.collect_snapshot(arguments())
        self.assertEqual(verified_reads, 2)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(result["buckets"][0]["remaining_ratio"], 0.25)

    def test_untrusted_executable_cannot_probe_expired_native_credentials(self) -> None:
        with mock.patch.object(local, "collect_verified", side_effect=local.LocalVerificationError("cli_auth_expired")):
            with mock.patch.object(runner, "_is_native_cli_installation", return_value=False):
                with mock.patch.object(local, "refresh_expired_cli_binding") as refresh:
                    with self.assertRaisesRegex(runner.QuotaCollectionError, "^native_refresh_unavailable$"):
                        runner.collect_snapshot(arguments(agy_bin=str(self.executable)))
        refresh.assert_not_called()

    def test_failed_refresh_never_exports_probe_quota(self) -> None:
        with mock.patch.object(local, "collect_verified", side_effect=local.LocalVerificationError("cli_auth_expired")):
            with mock.patch.object(runner, "_is_native_cli_installation", return_value=True):
                with mock.patch.object(local, "refresh_expired_cli_binding", side_effect=local.LocalVerificationError("account_binding_changed")):
                    with mock.patch.object(runner, "export_metrics") as export:
                        with self.assertRaisesRegex(local.LocalVerificationError, "^account_binding_changed$"):
                            runner.collect_snapshot(arguments(export=True))
        export.assert_not_called()

    def test_unexpected_provider_exception_and_export_error_are_sanitized(self) -> None:
        output = io.StringIO()
        with mock.patch.object(runner, "collect_snapshot", side_effect=RuntimeError(PRIVATE_TEXT)):
            with mock.patch.object(runner, "export_metrics", side_effect=OSError(PRIVATE_TEXT)):
                with contextlib.redirect_stdout(output):
                    result = runner.run(arguments(export=True))
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue()), {
            "source": "official-cli-report", "status": "unavailable", "error": "collection_unavailable",
        })
        self.assertNotIn(PRIVATE_TEXT, output.getvalue())

    def test_non_loopback_endpoints_are_refused_before_opening_transport(self) -> None:
        endpoints = (
            "https://127.0.0.1:4318", "http://example.invalid:4318",
            "http://127.0.0.1.example.invalid:4318", "http://127.0.0.2:4318",
            "http://user:secret@localhost:4318", "http://localhost:4318/v1/metrics",
            "http://localhost:4318/?secret=value", "http://localhost:4318/#fragment",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with mock.patch.object(runner.urllib.request, "build_opener") as opener:
                    with self.assertRaisesRegex(runner.QuotaCollectionError, "^collector_endpoint_must_be_loopback$"):
                        runner.export_metrics({}, endpoint)
                opener.assert_not_called()

    def test_redirect_handler_refuses_retargeting(self) -> None:
        handler = runner._NoRedirect()
        with self.assertRaisesRegex(runner.QuotaCollectionError, "^collector_redirect_refused$"):
            handler.redirect_request(None, None, 307, PRIVATE_TEXT, {}, "http://example.invalid")

    def test_otlp_partial_rejection_and_invalid_responses_do_not_appear_successful(self) -> None:
        cases = (
            (b'{"partialSuccess":{"rejectedDataPoints":"1","errorMessage":"private-provider-response"}}', "collector_rejected_metrics"),
            (b"[]", "collector_export_failed"),
            (b"x" * 16385, "collector_response_too_large"),
            (PRIVATE_TEXT.encode(), "collector_export_failed"),
        )
        for body, code in cases:
            with self.subTest(code=code):
                response = mock.MagicMock()
                response.__enter__.return_value.read.return_value = body
                opener = mock.Mock()
                opener.open.return_value = response
                with mock.patch.object(runner.urllib.request, "build_opener", return_value=opener):
                    with self.assertRaisesRegex(runner.QuotaCollectionError, f"^{code}$"):
                        runner.export_metrics({}, "http://127.0.0.1:4318")

    def test_loopback_export_disables_proxies_and_posts_only_metrics(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        opener = mock.Mock()
        opener.open.return_value = response
        payload = {"resourceMetrics": []}
        with mock.patch.object(runner.urllib.request, "build_opener", return_value=opener) as build:
            runner.export_metrics(payload, "http://127.0.0.1:4318/")
        proxy_handler, redirect_handler = build.call_args.args
        self.assertEqual(proxy_handler.proxies, {})
        self.assertIsInstance(redirect_handler, runner._NoRedirect)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:4318/v1/metrics")
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), payload)


if __name__ == "__main__":
    unittest.main()
