from __future__ import annotations

import copy
import io
import json
import queue
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from scripts import codex_account_usage as usage


OBSERVED_AT = "2026-10-01T00:00:00Z"
THREAD_ID = "synthetic-thread-alpha"
PRIVATE_TEXT = (
    "SYNTHETIC_PRIVATE_PROVIDER_MESSAGE", "SYNTHETIC_PRIVATE_USERNAME",
    "synthetic-private@example.invalid", "SYNTHETIC_PRIVATE_ACCOUNT_ID",
    "SYNTHETIC_PRIVATE_PROMPT", "SYNTHETIC_PRIVATE_TOOL_OUTPUT",
    "SYNTHETIC_PRIVATE_CREDENTIAL", "SYNTHETIC_PRIVATE_BIN",
)
TOKEN_PAIRS = (
    ("net_new_input_tokens", "netNewInputTokens"),
    ("cached_input_tokens", "cachedInputTokens"),
    ("input_tokens", "inputTokens"), ("output_tokens", "outputTokens"),
    ("total_tokens", "totalTokens"),
)


def provider_rates() -> dict:
    return {
        "ordinaryUsageAllowed": True,
        "rateLimits": {
            "planType": "pro", "limitId": "SYNTHETIC_PRIVATE_ACCOUNT_ID",
            "credits": {"hasCredits": True, "unlimited": False, "balance": "12.5000",
                        "credential": "SYNTHETIC_PRIVATE_CREDENTIAL"},
            "primary": {"usedPercent": 12.5, "windowDurationMins": 300, "resetsAt": 1800000000},
            "secondary": None, "email": "synthetic-private@example.invalid",
            "prompt": "SYNTHETIC_PRIVATE_PROMPT",
        },
    }


def provider_thread(thread_id: str = THREAD_ID) -> dict:
    return {
        "threadId": thread_id, "estimatedUsageCreditsMicros": 1250001,
        "estimatedUsageUsdMicros": 12345,
        "groups": [{
            "model": "gpt-6.1-sol", "reasoningEffort": "high", "speed": "fast",
            "netNewInputTokens": 100, "cachedInputTokens": 200, "inputTokens": 300,
            "outputTokens": 400, "totalTokens": 700, "estimatedUsageCreditsMicros": 1250001,
            "prompt": "SYNTHETIC_PRIVATE_PROMPT", "toolOutput": "SYNTHETIC_PRIVATE_TOOL_OUTPUT",
        }],
        "username": "SYNTHETIC_PRIVATE_USERNAME", "accountId": "SYNTHETIC_PRIVATE_ACCOUNT_ID",
    }


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.notifications: list[tuple[str, dict]] = []
        self.closed = 0
        self.failures: set[str] = set()
        self.overrides: dict[str, dict] = {}

    def request(self, method: str, params: dict) -> dict:
        self.calls.append((method, copy.deepcopy(params)))
        if method in self.failures:
            raise usage._Unavailable()
        if method in self.overrides:
            return copy.deepcopy(self.overrides[method])
        if method == "initialize":
            return {"userAgent": "SYNTHETIC_PRIVATE_PROVIDER_MESSAGE"}
        if method == "account/read":
            return {"account": {"type": "chatgpt", "planType": "pro",
                                "email": "synthetic-private@example.invalid",
                                "id": "SYNTHETIC_PRIVATE_ACCOUNT_ID"}}
        if method == "account/rateLimits/read":
            return provider_rates()
        if method == "account/usage/read":
            return {"threadUsage": provider_thread(params["threadId"])}
        raise AssertionError("unexpected provider method")

    def notify(self, method: str, params: dict) -> None:
        self.notifications.append((method, copy.deepcopy(params)))

    def close(self) -> None:
        self.closed += 1


class FakeWorkdir:
    name = "C:/SYNTHETIC_PRIVATE_USERNAME/isolated-account-read"

    def __init__(self) -> None:
        self.cleaned = False

    def cleanup(self) -> None:
        self.cleaned = True


class FakeStdout:
    def __init__(self) -> None:
        self.lines: queue.Queue[str] = queue.Queue()
        self.closed = False

    def readline(self, size: int = -1) -> str:
        line = self.lines.get()
        return line if size < 0 else line[:size]

    def close(self) -> None:
        self.closed = True
        self.lines.put("")


class FakeStdin:
    def __init__(self, process: "FakeProcess") -> None:
        self.process = process
        self.messages: list[dict] = []
        self.closed = False

    def write(self, text: str) -> int:
        if self.process.mode == "write_error":
            raise OSError("SYNTHETIC_PRIVATE_PROVIDER_MESSAGE")
        message = json.loads(text)
        self.messages.append(message)
        if "id" not in message or self.process.mode == "silent":
            return len(text)
        response = {"id": message["id"], "result": {"ok": True}}
        if self.process.mode == "error":
            response = {"id": message["id"], "error": {"message": "SYNTHETIC_PRIVATE_PROVIDER_MESSAGE"}}
        elif self.process.mode == "noise":
            self.process.emit({"method": "syntheticNotification", "params": {"prompt": "SYNTHETIC_PRIVATE_PROMPT"}})
            self.process.emit({"id": 9999, "result": {"private": "SYNTHETIC_PRIVATE_CREDENTIAL"}})
        elif self.process.mode == "boolean_id":
            self.process.emit({"id": True, "result": {"private": "SYNTHETIC_PRIVATE_CREDENTIAL"}})
        self.process.emit(response)
        return len(text)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, mode: str = "normal", *, hang_on_terminate: bool = False) -> None:
        self.mode = mode
        self.stdout = FakeStdout()
        self.stdin = FakeStdin(self)
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.hang_on_terminate = hang_on_terminate

    def emit(self, message: dict) -> None:
        self.stdout.lines.put(json.dumps(message) + "\n")

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self.hang_on_terminate:
            self.returncode = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("synthetic-process", timeout)
        return self.returncode


class AccountUsageNormalizerTests(unittest.TestCase):
    maxDiff = None

    def assert_private_removed(self, value: dict | None) -> None:
        rendered = json.dumps(value, allow_nan=False)
        for text in PRIVATE_TEXT:
            self.assertNotIn(text, rendered)

    def test_provider_camelcase_and_offline_snakecase_match(self) -> None:
        offline = {
            "plan_type": "pro", "ordinary_usage_allowed": True,
            "credits": {"has_credits": True, "unlimited": False, "balance": "12.5000"},
            "primary": {"used_percent": 12.5, "window_minutes": 300, "resets_at": 1800000000},
            "secondary": None,
        }
        normalized = usage.normalize_rate_limits(provider_rates(), OBSERVED_AT)
        self.assertEqual(normalized, usage.normalize_rate_limits(offline, OBSERVED_AT))
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["credits"]["balance"], "12.5")
        self.assertEqual(set(normalized), {"observed_at", "plan_type", "credits", "primary", "secondary", "ordinary_usage_allowed"})
        self.assert_private_removed(normalized)

    def test_provider_snapshot_ordinary_usage_flag_is_authoritative(self) -> None:
        raw = provider_rates()
        raw["ordinaryUsageAllowed"] = False
        raw["rateLimits"]["ordinaryUsageAllowed"] = True
        self.assertTrue(usage.normalize_rate_limits(raw, OBSERVED_AT)["ordinary_usage_allowed"])
        raw["rateLimits"]["ordinaryUsageAllowed"] = None
        self.assertIsNone(usage.normalize_rate_limits(raw, OBSERVED_AT)["ordinary_usage_allowed"])
        raw["rateLimits"].pop("ordinaryUsageAllowed")
        self.assertFalse(usage.normalize_rate_limits(raw, OBSERVED_AT)["ordinary_usage_allowed"])

    def test_codex_limit_is_preferred_without_exporting_other_limit_identifiers(self) -> None:
        raw = provider_rates()
        selected = copy.deepcopy(raw["rateLimits"])
        raw["rateLimits"]["primary"]["usedPercent"] = 99
        raw["rateLimitsByLimitId"] = {"codex": selected, "SYNTHETIC_PRIVATE_ACCOUNT_ID": {"prompt": "SYNTHETIC_PRIVATE_PROMPT"}}
        normalized = usage.normalize_rate_limits(raw, OBSERVED_AT)
        self.assertEqual(normalized["primary"]["used_percent"], 12.5)
        self.assert_private_removed(normalized)

    def test_legacy_limit_fallback_and_unrelated_limits_fail_closed(self) -> None:
        raw = provider_rates()
        raw["rateLimitsByLimitId"] = {"other": {}}
        self.assertIsNotNone(usage.normalize_rate_limits(raw, OBSERVED_AT))
        self.assertIsNone(usage.normalize_rate_limits({"rateLimitsByLimitId": {"other": {"credits": {}}}}, OBSERVED_AT))

    def test_missing_nullable_account_values_are_not_fabricated(self) -> None:
        normalized = usage.normalize_rate_limits({"primary": None, "credits": None}, OBSERVED_AT)
        self.assertEqual(normalized["plan_type"], "unknown")
        for field in ("primary", "secondary", "credits", "ordinary_usage_allowed"):
            self.assertIsNone(normalized[field])
        raw = provider_rates()
        raw["rateLimits"]["credits"].pop("balance")
        self.assertIsNone(usage.normalize_rate_limits(raw, OBSERVED_AT)["credits"]["balance"])

    def test_nullable_incomplete_window_stays_null(self) -> None:
        raw = provider_rates()
        raw["rateLimits"]["primary"].pop("resetsAt")
        normalized = usage.normalize_rate_limits(raw, OBSERVED_AT)
        self.assertIsNone(normalized["primary"])
        self.assertIsNotNone(normalized["credits"])

    def test_decimal_credit_balance_preserves_exact_precision(self) -> None:
        for original, expected in (
            ("0.000000", "0"), ("0.000001", "0.000001"), ("1e3", "1000"),
            ("123456789012345678901234567890.123456", "123456789012345678901234567890.123456"),
        ):
            with self.subTest(original=original):
                raw = provider_rates()
                raw["rateLimits"]["credits"]["balance"] = original
                self.assertEqual(usage.normalize_rate_limits(raw, OBSERVED_AT)["credits"]["balance"], expected)

    def test_nonfinite_and_malformed_credit_balances_are_rejected(self) -> None:
        for invalid in ("NaN", "Infinity", "-Infinity", "-1", "1e128", "1.2.3", "12 credits", "SYNTHETIC_PRIVATE_CREDENTIAL", 12, 12.5, True, {}):
            with self.subTest(invalid=type(invalid).__name__):
                raw = provider_rates()
                raw["rateLimits"]["credits"]["balance"] = invalid
                self.assertIsNone(usage.normalize_rate_limits(raw, OBSERVED_AT))

    def test_credit_flags_require_actual_booleans(self) -> None:
        for field in ("hasCredits", "unlimited"):
            for invalid in (0, 1, "true", None):
                with self.subTest(field=field, invalid=invalid):
                    raw = provider_rates()
                    raw["rateLimits"]["credits"][field] = invalid
                    self.assertIsNone(usage.normalize_rate_limits(raw, OBSERVED_AT))

    def test_rate_windows_reject_wrong_types_and_out_of_range_numbers(self) -> None:
        for field, invalid in (
            ("usedPercent", True), ("usedPercent", "12.5"), ("usedPercent", float("nan")),
            ("usedPercent", float("inf")), ("usedPercent", -1), ("usedPercent", 101),
            ("windowDurationMins", True), ("windowDurationMins", 1.0), ("windowDurationMins", 0),
            ("resetsAt", True), ("resetsAt", 1.0), ("resetsAt", -1),
        ):
            with self.subTest(field=field, kind=type(invalid).__name__):
                raw = provider_rates()
                raw["rateLimits"]["primary"][field] = invalid
                self.assertIsNone(usage.normalize_rate_limits(raw, OBSERVED_AT))

    def test_partial_window_with_invalid_present_field_is_not_silently_null(self) -> None:
        raw = provider_rates()
        raw["rateLimits"]["primary"].pop("resetsAt")
        raw["rateLimits"]["primary"]["windowDurationMins"] = True
        self.assertIsNone(usage.normalize_rate_limits(raw, OBSERVED_AT))

    def test_unknown_plan_and_extra_private_metadata_are_bounded(self) -> None:
        raw = provider_rates()
        raw["rateLimits"]["planType"] = "SYNTHETIC_PRIVATE_USERNAME"
        normalized = usage.normalize_rate_limits(raw, OBSERVED_AT)
        self.assertEqual(normalized["plan_type"], "unknown")
        self.assert_private_removed(normalized)

    def test_observed_timestamp_requires_timezone_and_normalizes_to_utc(self) -> None:
        normalized = usage.normalize_rate_limits(provider_rates(), "2026-10-01T08:00:00+08:00")
        self.assertEqual(normalized["observed_at"], "2026-10-01T00:00:00.000000Z")
        for value in (None, "2026-10-01T00:00:00", "SYNTHETIC_PRIVATE_PROVIDER_MESSAGE"):
            self.assertIsNone(usage.normalize_rate_limits(provider_rates(), value))

    def test_thread_micros_remain_exact_int64_and_private_extras_are_removed(self) -> None:
        raw = provider_thread()
        raw["estimatedUsageCreditsMicros"] = 2**63 - 1
        raw["groups"][0]["estimatedUsageCreditsMicros"] = 2**63 - 1
        normalized = usage.normalize_thread_usage(raw)
        self.assertEqual(normalized["thread_id"], THREAD_ID)
        self.assertIs(type(normalized["estimated_usage_credits_micros"]), int)
        self.assertEqual(normalized["estimated_usage_credits_micros"], 2**63 - 1)
        self.assertEqual(normalized["groups"][0]["estimated_usage_credits_micros"], 2**63 - 1)
        self.assert_private_removed(normalized)

    def test_micros_reject_float_boolean_string_negative_and_overflow(self) -> None:
        for field in ("estimatedUsageCreditsMicros", "estimatedUsageUsdMicros"):
            for invalid in (True, False, 1.0, "1", -1, 2**63):
                with self.subTest(field=field, kind=type(invalid).__name__):
                    raw = provider_thread()
                    raw[field] = invalid
                    self.assertIsNone(usage.normalize_thread_usage(raw))
        raw = provider_thread()
        raw["estimatedUsageCreditsMicros"] = None
        self.assertIsNone(usage.normalize_thread_usage(raw))

    def test_missing_usd_and_group_tokens_stay_null_without_inference(self) -> None:
        raw = provider_thread()
        raw.pop("estimatedUsageUsdMicros")
        for _, camel in TOKEN_PAIRS:
            raw["groups"][0].pop(camel)
        normalized = usage.normalize_thread_usage(raw)
        self.assertIsNone(normalized["estimated_usage_usd_micros"])
        for snake, _ in TOKEN_PAIRS:
            self.assertIsNone(normalized["groups"][0][snake])

    def test_group_token_and_credit_types_are_strict(self) -> None:
        for field in ("estimatedUsageCreditsMicros", *(camel for _, camel in TOKEN_PAIRS)):
            for invalid in (True, 1.0, "1", -1, 2**63):
                with self.subTest(field=field, kind=type(invalid).__name__):
                    raw = provider_thread()
                    raw["groups"][0][field] = invalid
                    self.assertIsNone(usage.normalize_thread_usage(raw))

    def test_present_thread_token_totals_and_cached_subset_must_reconcile(self) -> None:
        raw = provider_thread()
        raw["groups"][0]["totalTokens"] = 701
        self.assertIsNone(usage.normalize_thread_usage(raw))
        raw = provider_thread()
        raw["groups"][0]["cachedInputTokens"] = 301
        self.assertIsNone(usage.normalize_thread_usage(raw))

    def test_unknown_model_effort_and_speed_never_leak_or_infer(self) -> None:
        raw = provider_thread()
        raw["groups"][0].update(model="gpt-6.1-sol-future", reasoningEffort="SYNTHETIC_PRIVATE_USERNAME", speed="priority")
        normalized = usage.normalize_thread_usage(raw)
        group = normalized["groups"][0]
        self.assertEqual((group["model_id"], group["reasoning_effort"], group["speed"]), ("unmapped", "unknown", "unknown"))
        self.assertEqual(group["estimated_usage_credits_micros"], 1250001)
        self.assertNotIn("gpt-6.1-sol-future", json.dumps(normalized))
        self.assert_private_removed(normalized)

    def test_missing_groups_or_identity_are_rejected(self) -> None:
        for invalid in (None, {}, "groups", [None]):
            raw = provider_thread()
            raw["groups"] = invalid
            self.assertIsNone(usage.normalize_thread_usage(raw))
        for invalid in (None, "", 1, "x" * 513):
            raw = provider_thread()
            raw["threadId"] = invalid
            self.assertIsNone(usage.normalize_thread_usage(raw))
        raw = provider_thread()
        raw["groups"] = []
        self.assertEqual(usage.normalize_thread_usage(raw)["groups"], [])


class AccountUsageCollectorTests(unittest.TestCase):
    def collect(self, client: FakeClient, identities: list[str] | None = None, **kwargs) -> tuple[dict, list[str]]:
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(usage, "_StdioClient", return_value=client) as factory, \
             patch.object(usage, "_mcp_names", return_value={"synthetic_enabled_server"}), \
             redirect_stdout(output), redirect_stderr(errors):
            result = usage.collect_account_usage(
                identities if identities is not None else [THREAD_ID],
                codex_bin="C:/SYNTHETIC_PRIVATE_BIN/codex.exe", **kwargs,
            )
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), "")
        for text in PRIVATE_TEXT:
            self.assertNotIn(text, json.dumps(result))
        command = factory.call_args.args[0] if factory.called else []
        return result, command

    def test_requests_only_metadata_with_no_refresh_and_unique_thread_lookup(self) -> None:
        client = FakeClient()
        result, command = self.collect(client, [THREAD_ID, THREAD_ID, "synthetic-thread-beta"])
        self.assertEqual([method for method, _ in client.calls], [
            "initialize", "account/read", "account/rateLimits/read", "account/usage/read", "account/usage/read",
        ])
        self.assertEqual(client.calls[1][1], {"refreshToken": False})
        self.assertEqual(client.calls[2][1], {"supportsLunaReserve": False, "excludeResetCreditDetails": True})
        self.assertEqual(client.calls[3][1], {"threadId": THREAD_ID})
        self.assertEqual(client.notifications, [("initialized", {})])
        self.assertEqual(client.calls[0][1]["capabilities"], None)
        self.assertIn("analytics.enabled=false", command)
        self.assertTrue(any(option in command for option in (
            'mcp_servers."synthetic_enabled_server".enabled=false',
            "mcp_servers.synthetic_enabled_server.enabled=false",
        )), "the configured MCP server must be explicitly disabled")
        self.assertEqual(command[-3:], ["app-server", "--listen", "stdio://"])
        self.assertEqual(client.closed, 1)
        self.assertEqual(result["diagnostics"], {"official_requests": 4, "official_unavailable": 0,
                                                "official_thread_usage_missing": 0, "official_invalid_records": 0})
        self.assertEqual(len(result["thread_estimates"]), 2)
        self.assertEqual(set(result["thread_observations"]), {THREAD_ID, "synthetic-thread-beta"})
        for estimate in result["thread_estimates"]:
            self.assertRegex(estimate["observed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
            self.assertEqual(estimate["observed_at"], result["thread_observations"][estimate["thread_id"]])

    def test_account_plan_fallback_strips_raw_account_identity(self) -> None:
        client = FakeClient()
        rates = provider_rates()
        rates["rateLimits"].pop("planType")
        client.overrides["account/rateLimits/read"] = rates
        result, _ = self.collect(client)
        self.assertEqual(result["account_snapshot"]["plan_type"], "pro")

    def test_independently_available_reads_survive_one_account_failure(self) -> None:
        client = FakeClient()
        client.failures.add("account/read")
        result, _ = self.collect(client)
        self.assertEqual(result["diagnostics"]["official_requests"], 3)
        self.assertEqual(result["diagnostics"]["official_unavailable"], 1)
        self.assertIsNotNone(result["account_snapshot"])
        self.assertEqual(len(result["thread_estimates"]), 1)
        self.assertEqual(client.closed, 1)

    def test_thread_usage_missing_is_distinct_from_failed_read(self) -> None:
        client = FakeClient()
        client.overrides["account/usage/read"] = {"threadUsage": None}
        result, _ = self.collect(client)
        self.assertEqual(result["thread_estimates"], [])
        self.assertEqual(result["diagnostics"]["official_thread_usage_missing"], 1)
        self.assertEqual(result["diagnostics"]["official_unavailable"], 0)
        self.assertIn(THREAD_ID, result["thread_observations"])
        failed = FakeClient()
        failed.failures.add("account/usage/read")
        result, _ = self.collect(failed)
        self.assertEqual(result["thread_estimates"], [])
        self.assertEqual(result["diagnostics"]["official_thread_usage_missing"], 0)
        self.assertEqual(result["diagnostics"]["official_unavailable"], 1)
        self.assertIn(THREAD_ID, result["thread_observations"])

    def test_malformed_snapshot_and_wrong_thread_identity_are_counted(self) -> None:
        client = FakeClient()
        rates = provider_rates()
        rates["rateLimits"]["credits"]["balance"] = "NaN"
        client.overrides["account/rateLimits/read"] = rates
        client.overrides["account/usage/read"] = {"threadUsage": provider_thread("wrong-synthetic-thread")}
        result, _ = self.collect(client)
        self.assertIsNone(result["account_snapshot"])
        self.assertEqual(result["thread_estimates"], [])
        self.assertEqual(result["diagnostics"]["official_invalid_records"], 2)

    def test_handshake_failure_closes_client_without_exporting_external_message(self) -> None:
        client = FakeClient()
        client.failures.add("initialize")
        result, _ = self.collect(client)
        self.assertEqual(result["diagnostics"]["official_requests"], 0)
        self.assertEqual(result["diagnostics"]["official_unavailable"], 1)
        self.assertIsNone(result["account_snapshot"])
        self.assertEqual(client.closed, 1)

    def test_startup_failure_is_bounded_and_missing_cli_never_launches(self) -> None:
        with patch.object(usage, "_mcp_names", return_value=set()), \
             patch.object(usage, "_StdioClient", side_effect=usage._Unavailable()):
            result = usage.collect_account_usage([THREAD_ID], codex_bin="synthetic-codex")
        self.assertEqual(result["diagnostics"]["official_unavailable"], 1)
        with patch.object(usage.shutil, "which", return_value=None), \
             patch.object(usage, "_StdioClient") as factory:
            result = usage.collect_account_usage([THREAD_ID])
        self.assertFalse(factory.called)
        self.assertEqual(result["diagnostics"]["official_requests"], 0)

    def test_invalid_timeouts_and_thread_inputs_do_not_start_provider(self) -> None:
        for timeout in (True, 0, 61, float("nan"), float("inf"), 2**1024):
            with self.subTest(kind=type(timeout).__name__):
                with patch.object(usage, "_StdioClient") as factory:
                    result = usage.collect_account_usage([THREAD_ID], codex_bin="synthetic-codex", timeout=timeout)
                self.assertFalse(factory.called)
                self.assertEqual(result["diagnostics"]["official_invalid_records"], 1)
        with patch.object(usage, "_StdioClient") as factory:
            result = usage.collect_account_usage(None, codex_bin="synthetic-codex")
        self.assertFalse(factory.called)
        self.assertEqual(result["diagnostics"]["official_invalid_records"], 1)
        result, _ = self.collect(FakeClient(), [None, "", "x" * 513, THREAD_ID])
        self.assertEqual(result["diagnostics"]["official_invalid_records"], 3)
        self.assertEqual(len(result["thread_estimates"]), 1)

    def test_only_safe_configured_mcp_names_are_retained(self) -> None:
        safe = b'[mcp_servers.synthetic_server]\ncommand="SYNTHETIC_PRIVATE_CREDENTIAL"\n'
        with patch.object(usage.Path, "open", side_effect=lambda *args, **kwargs: io.BytesIO(safe)):
            self.assertEqual(usage._mcp_names(), {"synthetic_server"})
        unsafe = b'[mcp_servers."unsafe.name"]\ncommand="SYNTHETIC_PRIVATE_CREDENTIAL"\n'
        with patch.object(usage.Path, "open", side_effect=lambda *args, **kwargs: io.BytesIO(unsafe)):
            with self.assertRaises(usage._Unavailable) as raised:
                usage._mcp_names()
        self.assertEqual(str(raised.exception), "")


class AccountUsageTransportTests(unittest.TestCase):
    def client(self, process: FakeProcess, *, timeout: float = 0.5) -> tuple[usage._StdioClient, FakeWorkdir]:
        workdir = FakeWorkdir()
        with patch.object(usage.tempfile, "TemporaryDirectory", return_value=workdir), \
             patch.object(usage.subprocess, "Popen", return_value=process) as popen:
            client = usage._StdioClient(["synthetic-codex", "app-server", "--listen", "stdio://"], timeout)
        self.assertIs(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(popen.call_args.kwargs["cwd"], workdir.name)
        self.addCleanup(client.close)
        return client, workdir

    def test_transport_skips_notifications_and_other_request_ids(self) -> None:
        process = FakeProcess("noise")
        client, workdir = self.client(process)
        self.assertEqual(client.request("account/read", {"refreshToken": False}), {"ok": True})
        self.assertEqual(process.stdin.messages[0]["params"], {"refreshToken": False})
        client.close()
        self.assertTrue(workdir.cleaned)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertEqual(process.terminate_calls, 1)

    def test_boolean_response_id_does_not_match_integer_request_id(self) -> None:
        client, _ = self.client(FakeProcess("boolean_id"))
        self.assertEqual(client.request("account/read", {"refreshToken": False}), {"ok": True})

    def test_provider_error_and_send_failure_never_expose_private_message(self) -> None:
        for mode in ("error", "write_error"):
            with self.subTest(mode=mode):
                client, _ = self.client(FakeProcess(mode))
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    with self.assertRaises(usage._Unavailable) as raised:
                        client.request("account/read", {"refreshToken": False})
                self.assertEqual(str(raised.exception), "")
                self.assertEqual(output.getvalue() + errors.getvalue(), "")
                client.close()

    def test_timeout_and_forced_kill_cleanup_are_bounded(self) -> None:
        process = FakeProcess("silent", hang_on_terminate=True)
        client, workdir = self.client(process, timeout=0.05)
        with self.assertRaises(usage._Unavailable):
            client.request("account/read", {"refreshToken": False})
        client.close()
        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1)
        self.assertTrue(workdir.cleaned)
        self.assertTrue(process.stdin.closed and process.stdout.closed)

    def test_malformed_and_oversized_stdout_fail_without_echoing_content(self) -> None:
        for line in ("SYNTHETIC_PRIVATE_PROVIDER_MESSAGE\n", "x" * 129 + "\n"):
            with self.subTest(kind="malformed" if line.startswith("SYNTHETIC") else "oversized"):
                process = FakeProcess("silent")
                process.stdout.lines.put(line)
                with patch.object(usage, "MAX_LINE", 128):
                    client, workdir = self.client(process)
                    with self.assertRaises(usage._Unavailable) as raised:
                        client.request("account/read", {"refreshToken": False})
                    self.assertEqual(str(raised.exception), "")
                    client.close()
                self.assertTrue(workdir.cleaned)

    def test_popen_failure_cleans_workdir_and_strips_external_exception(self) -> None:
        workdir = FakeWorkdir()
        with patch.object(usage.tempfile, "TemporaryDirectory", return_value=workdir), \
             patch.object(usage.subprocess, "Popen", side_effect=OSError("SYNTHETIC_PRIVATE_PROVIDER_MESSAGE")):
            with self.assertRaises(usage._Unavailable) as raised:
                usage._StdioClient(["synthetic-codex"], 0.05)
        self.assertEqual(str(raised.exception), "")
        self.assertTrue(workdir.cleaned)


if __name__ == "__main__":
    unittest.main()
