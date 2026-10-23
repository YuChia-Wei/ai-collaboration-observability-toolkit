"""Numeric metadata parsing, version limits and read-only context selection."""

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from scripts import antigravity_desktop_context as context
from scripts import antigravity_local as local


NOW = datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc)
PRIVATE = "private-account@example.invalid private prompt C:\\private\\project"
CASCADE = "00000000-0000-0000-0000-000000000001"


def response(estimate=12345, capacity=100000, created="2026-10-23T00:59:00Z"):
    return {"generatorMetadata": [{
        "promptDebugStr": PRIVATE, "executionId": CASCADE,
        "chatModel": {"systemPrompt": PRIVATE, "messagePrompts": [PRIVATE],
            "usage": {"inputTokens": "10", "outputTokens": "2",
                      "messageId": PRIVATE},
            "chatStartMetadata": {"createdAt": created,
                "contextWindowMetadata": {
                    "estimatedTokensUsed": estimate, "maxContextTokens": capacity,
                    "tokenBreakdown": {"totalTokens": estimate,
                        "groups": [{"name": PRIVATE, "numTokens": estimate}]},
                }},
        },
    }]}


class ContextParserTests(unittest.TestCase):
    def test_extracts_server_estimate_and_reported_capacity_without_private_fields(self):
        result = context.parse_context_response(response(), NOW)
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["estimated_tokens_used"], 12345)
        self.assertEqual(result["max_context_tokens"], 100000)
        self.assertEqual(result["used_ratio"], 0.12345)
        self.assertEqual(result["source_age_seconds"], 60)
        self.assertEqual(result["measurement_kind"], "server-estimate")
        self.assertEqual(result["rpc_usage_cross_check"]["sums"],
                         {"inputTokens": 10, "outputTokens": 2})
        for forbidden in (PRIVATE, CASCADE, "systemPrompt", "messagePrompts", "groups"):
            self.assertNotIn(forbidden, json.dumps(result))

    def test_missing_capacity_remains_unknown_without_model_limit_lookup(self):
        result = context.parse_context_response(response(capacity=None), NOW)
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["max_context_tokens"])
        self.assertIsNone(result["used_ratio"])
        self.assertEqual(result["estimated_tokens_used"], 12345)

    def test_missing_context_cannot_be_substituted_by_cumulative_usage(self):
        raw = response()
        del raw["generatorMetadata"][0]["chatModel"]["chatStartMetadata"]["contextWindowMetadata"]
        result = context.parse_context_response(raw, NOW)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["estimated_tokens_used"])
        self.assertIsNone(result["used_ratio"])
        self.assertEqual(result["rpc_usage_cross_check"]["sums"]["inputTokens"], 10)

    def test_invalid_numeric_types_are_unknown_and_real_zero_is_retained(self):
        for invalid in (None, True, "100", -1, 2**31, float("nan"), []):
            with self.subTest(invalid_type=type(invalid).__name__):
                result = context.parse_context_response(response(estimate=invalid), NOW)
                self.assertEqual(result["status"], "unavailable")
                self.assertIsNone(result["estimated_tokens_used"])
        result = context.parse_context_response(response(estimate=0), NOW)
        self.assertEqual(result["estimated_tokens_used"], 0)
        self.assertEqual(result["used_ratio"], 0)

    def test_latest_context_wins_instead_of_summing_generations(self):
        raw = response(estimate=90000)
        raw["generatorMetadata"] += response(estimate=15000)["generatorMetadata"]
        result = context.parse_context_response(raw, NOW)
        self.assertEqual(result["estimated_tokens_used"], 15000)
        self.assertEqual(result["rpc_usage_cross_check"]["sums"]["inputTokens"], 20)

    def test_older_available_context_is_marked_partial_with_response_distance(self):
        raw = response()
        raw["generatorMetadata"].append({"chatModel": {"usage": {"inputTokens": "5"}}})
        result = context.parse_context_response(raw, NOW)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["generation_distance_from_response_end"], 1)

    def test_missing_invalid_or_future_timestamp_never_invents_source_age(self):
        for timestamp in (None, "invalid", "2026-10-23T02:00:00Z", "2026-10-23T00:59:00"):
            result = context.parse_context_response(response(created=timestamp), NOW)
            self.assertEqual(result["status"], "partial")
            self.assertIsNone(result["source_age_seconds"])
            self.assertIsNone(result["generation_started_at"])

    def test_protobuf_timestamp_object_uses_only_numeric_seconds_and_nanos(self):
        instant = int(datetime(2026, 10, 23, 0, 59, tzinfo=timezone.utc).timestamp())
        result = context.parse_context_response(response(created={"seconds": str(instant), "nanos": 0}), NOW)
        self.assertEqual(result["source_age_seconds"], 60)
        self.assertIsNone(context._timestamp({"seconds": True}))
        self.assertIsNone(context._timestamp({"seconds": instant, "nanos": 10**9}))

    def test_malformed_and_unbounded_response_is_fixed_unavailable(self):
        for raw in ({}, [], {"generatorMetadata": "private"},
                    {"generatorMetadata": [{}] * 1001}):
            result = context.parse_context_response(raw, NOW)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["reason"], "context_response_invalid")


class ContextReaderTests(unittest.TestCase):
    def test_other_version_never_reads_local_conversations_or_rpc(self):
        with mock.patch.object(local, "get_desktop_version", return_value="2.26.0"), \
             mock.patch.object(context, "_recent_databases") as select, \
             mock.patch.object(local, "DesktopClient") as client:
            result = context.collect_desktop_context()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "desktop_version_review_required")
        select.assert_not_called()
        client.assert_not_called()

    def test_identity_guard_surrounds_bounded_recent_selector_and_safe_parse(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value.request.return_value = response()
        def guarded(callback):
            return callback(), {"status": "matched", "same_account": True,
                                "binding_stable_during_read": True}
        with mock.patch.object(local, "get_desktop_version", return_value="2.25.0"), \
             mock.patch.object(context, "_recent_databases", return_value=[(Path(CASCADE + ".db"), 1)]) as select, \
             mock.patch.object(context, "_metadata_offset", return_value=15), \
             mock.patch.object(local, "DesktopClient", return_value=fake), \
             mock.patch.object(local, "collect_verified", side_effect=guarded):
            result = context.collect_desktop_context(max_conversations=1)
        self.assertEqual(result["current_active_conversation"], "unknown")
        self.assertEqual(result["selection"], "recent-local-conversations")
        self.assertFalse(result["telemetry_exported"])
        self.assertEqual(select.call_args.args[1], 1)
        method, request = fake.__enter__.return_value.request.call_args.args
        self.assertEqual(method, "GetCascadeTrajectoryGeneratorMetadata")
        self.assertEqual(request, {"cascadeId": CASCADE, "generatorMetadataOffset": 15,
                                   "includeMessages": False})
        self.assertNotIn(CASCADE, json.dumps(result))
        self.assertNotIn(PRIVATE, json.dumps(result))

    def test_identity_failure_does_not_leak_or_return_unguarded_measurements(self):
        with mock.patch.object(local, "get_desktop_version", return_value="2.25.0"), \
             mock.patch.object(context, "_recent_databases", return_value=[(Path(CASCADE + ".db"), 1)]), \
             mock.patch.object(local, "collect_verified", side_effect=local.LocalVerificationError("account_mismatch")):
            result = context.collect_desktop_context()
        self.assertEqual(result["conversations"], [])
        self.assertEqual(result["reason"], "account_mismatch")

    def test_invalid_limit_is_rejected_before_read(self):
        with mock.patch.object(local, "get_desktop_version") as version:
            for invalid in (0, 4, True, "3"):
                self.assertEqual(context.collect_desktop_context(invalid)["reason"],
                                 "invalid_conversation_limit")
        version.assert_not_called()

    def test_sqlite_offset_reads_only_numeric_idx_and_keeps_database_readonly(self):
        scratch = Path(os.getenv("ANTIGRAVITY_QUOTA_TEST_ROOT",
            "F:/codex-tmp/antigravity-20261023/desktop-context-tests"))
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / (CASCADE + ".db")
            with closing(sqlite3.connect(path)) as database:
                database.execute("CREATE TABLE gen_metadata(idx INTEGER, data BLOB)")
                database.executemany("INSERT INTO gen_metadata VALUES (?,?)", [(0, PRIVATE.encode()), (20, PRIVATE.encode())])
                database.commit()
            before = path.read_bytes()
            self.assertEqual(context._metadata_offset(path), 18)
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
