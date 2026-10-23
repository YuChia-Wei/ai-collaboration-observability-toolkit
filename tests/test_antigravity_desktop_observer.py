from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from scripts import antigravity_desktop_observer as observer
from scripts.antigravity_desktop_generations import GenerationRead, GenerationRecord


def record(identity=b"native-private-response", *, age=600, index=3):
    return GenerationRecord(identity, "private-selector", index,
                            {"uncached_input_tokens": 80, "total_output_tokens": 20},
                            time.time()-age, "first-referenced-step-created-at", 1, 1, (8,))


class ObserverBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="desktop-observer-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.args = SimpleNamespace(state_dir=self.root, max_conversations=3, max_rows=128,
                                    export=True, endpoint="http://127.0.0.1:4318",
                                    service_namespace="ai-collaboration-fixture", profile="personal-local",
                                    interval_seconds=60, watch=False, output=None)

    def client(self, response):
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.request.return_value = response
        return client

    def test_latest_means_source_time_not_row_index_and_rpc_identity_must_match(self):
        latest = record(age=100, index=1)
        older = record(b"older-native-id", age=600, index=999)
        response = {"generatorMetadata": [{"stepIndices": [8], "chatModel": {
            "usage": {"responseId": "native-private-response"},
            "chatStartMetadata": {"contextWindowMetadata": {"estimatedTokensUsed": 1000, "maxContextTokens": 5000}},
        }}]}
        client = self.client(response)
        with mock.patch.object(observer.local, "DesktopClient", return_value=client):
            result = observer.read_latest_context(GenerationRead((older, latest), {}))
        self.assertTrue(result["generation_verified"])
        self.assertEqual(result["source_timestamp_seconds"], latest.source_timestamp_seconds)
        self.assertEqual(result["estimated_tokens_used"], 1000)
        self.assertEqual(client.request.call_args.args[1]["generatorMetadataOffset"], 1)
        self.assertIs(client.request.call_args.args[1]["includeMessages"], False)

    def test_raced_generation_cannot_reuse_an_earlier_context(self):
        latest = record()
        response = {"generatorMetadata": [{"stepIndices": [8], "chatModel": {
            "usage": {"responseId": "a-new-different-native-response"},
            "chatStartMetadata": {"contextWindowMetadata": {"estimatedTokensUsed": 1000}},
        }}]}
        with mock.patch.object(observer.local, "DesktopClient", return_value=self.client(response)):
            result = observer.read_latest_context(GenerationRead((latest,), {}))
        self.assertFalse(result["generation_verified"])
        self.assertNotIn("estimated_tokens_used", result)
        self.assertNotIn("private-selector", json.dumps(result))

    def test_ambiguous_latest_source_is_not_guessed(self):
        first = record()
        other = GenerationRecord(b"different", "other-selector", 0, first.tokens,
                                 first.source_timestamp_seconds, first.source_time_kind, 1, 1, (2,))
        with mock.patch.object(observer.local, "DesktopClient") as rpc:
            result = observer.read_latest_context(GenerationRead((first, other), {}))
        self.assertEqual(result["reason"], "latest_generation_ambiguous")
        rpc.assert_not_called()

    def test_unknown_generation_time_cannot_be_silently_excluded_from_latest_selection(self):
        known = record()
        unknown = replace(record(b"unknown-source-time"), source_timestamp_seconds=None)
        with mock.patch.object(observer.local, "DesktopClient") as rpc:
            result = observer.read_latest_context(GenerationRead((known, unknown), {}))
        self.assertEqual(result["reason"], "generation_source_time_unavailable")
        rpc.assert_not_called()

    def test_publication_is_locked_through_export_and_repeat_is_idempotent(self):
        item = record()
        sample = GenerationRead((item,), {"coverage": {"read_limited": False}})
        context = {"read_success": True, "generation_verified": True, "is_latest_generation": True,
                   "source_timestamp_seconds": item.source_timestamp_seconds,
                   "estimated_tokens_used": 1000, "max_context_tokens": 5000}

        def export(_payload, _endpoint):
            with self.assertRaisesRegex(observer.ObservationError, "^desktop_observer_busy$"):
                with observer.publication_lock(self.root):
                    pass

        with mock.patch.object(observer.local, "collect_verified", side_effect=lambda read: (read(), {"same_account": True})):
            with mock.patch.object(observer.generations, "collect_desktop_generations", return_value=sample):
                with mock.patch.object(observer, "read_latest_context", return_value=context):
                    with mock.patch.object(observer, "export_metrics", side_effect=export):
                        first = observer.collect_observation(self.args)
                        second = observer.collect_observation(self.args)
        self.assertEqual(first["deduplication"]["new_generations"], 1)
        self.assertEqual(second["deduplication"]["new_generations"], 0)
        self.assertEqual(second["deduplication"]["duplicate_generations"], 1)
        self.assertEqual(first["deduplication"]["totals"], second["deduplication"]["totals"])
        rendered = json.dumps(second)
        self.assertNotIn("native-private-response", rendered)
        self.assertNotIn("private-selector", rendered)
        self.assertEqual(second["active_conversation"], "deferred")

    def test_private_error_outputs_only_health_failure_without_values(self):
        output = io.StringIO()
        with mock.patch.object(observer, "_collect_locked", side_effect=RuntimeError("C:/private credential@example.invalid")):
            with mock.patch.object(observer, "export_metrics") as export:
                with contextlib.redirect_stdout(output):
                    code = observer.run(self.args)
        self.assertEqual(code, 1)
        self.assertNotIn("private", output.getvalue())
        self.assertNotIn("@", output.getvalue())
        names = {metric["name"] for resource in export.call_args.args[0]["resourceMetrics"]
                 for scope in resource["scopeMetrics"] for metric in scope["metrics"]}
        self.assertNotIn("antigravity_desktop_generation_observed_tokens_total", names)
        self.assertNotIn("antigravity_desktop_latest_context_estimated_tokens", names)

    def test_failure_health_is_published_before_releasing_the_publication_lock(self):
        def export(_payload, _endpoint):
            with self.assertRaisesRegex(observer.ObservationError, "^desktop_observer_busy$"):
                with observer.publication_lock(self.root):
                    pass

        with mock.patch.object(observer, "_collect_locked", side_effect=RuntimeError("private")):
            with mock.patch.object(observer, "export_metrics", side_effect=export) as send:
                with self.assertRaises(RuntimeError):
                    observer.collect_observation(self.args)
        self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
