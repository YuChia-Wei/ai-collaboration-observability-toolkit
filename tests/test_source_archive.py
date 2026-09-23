from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


toolkit = load_module("toolkit_source_tests", ROOT / "scripts/toolkit.py")
archive = load_module("archive_source_tests", ROOT / "scripts/source_archive_server.py")


def attribute(key, value, kind="stringValue"):
    return {"key": key, "value": {kind: value}}


def attribute_sets(value):
    """Walk genuine OTLP attribute locations, including nested AnyValue maps."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"attributes", "filteredAttributes"}:
                yield child
            yield from attribute_sets(child)
    elif isinstance(value, list):
        for child in value:
            yield from attribute_sets(child)


def signal_document(signal, attributes):
    """One producer record plus resource/scope metadata for each OTLP signal."""
    base = {
        "resource": {"attributes": deepcopy(attributes)},
        "schemaUrl": "https://opentelemetry.io/schemas/1.28.0",
    }
    scope = {"scope": {"name": "unknown-client", "version": "1.2.3", "attributes": deepcopy(attributes)}}
    if signal == "traces":
        record = {
            "traceId": "0123456789abcdef0123456789abcdef", "spanId": "0123456789abcdef",
            "parentSpanId": "fedcba9876543210", "name": "unknown.operation", "kind": 1,
            "startTimeUnixNano": "1770000000000000000", "endTimeUnixNano": "1770000000100000000",
            "traceState": "private-trace-state", "status": {"code": 2, "message": "private-status-text"},
            "attributes": deepcopy(attributes),
            "events": [{"name": "unknown.event", "timeUnixNano": "1770000000050000000", "attributes": deepcopy(attributes)}],
            "links": [{"traceId": "fedcba9876543210fedcba9876543210", "spanId": "fedcba9876543210", "flags": 1,
                       "traceState": "private-link-state", "attributes": deepcopy(attributes)}],
        }
        scope["spans"] = [record]
        base["scopeSpans"] = [scope]
        return {"resourceSpans": [base]}
    if signal == "logs":
        scope["logRecords"] = [{
            "timeUnixNano": "1770000000000000000", "observedTimeUnixNano": "1770000000100000000",
            "severityNumber": 9, "severityText": "INFO", "body": {"stringValue": "private-body-text"},
            "traceId": "0123456789abcdef0123456789abcdef", "spanId": "0123456789abcdef",
            "attributes": deepcopy(attributes),
        }]
        base["scopeLogs"] = [scope]
        return {"resourceLogs": [base]}
    if signal == "metrics":
        scope["metrics"] = [{
            "name": "codex.websocket.event.duration_ms", "unit": "ms", "description": "private-description",
            "histogram": {"aggregationTemporality": 1, "dataPoints": [{
                "startTimeUnixNano": "1770000000000000000", "timeUnixNano": "1770000000100000000",
                "count": "3", "sum": 14.5, "min": 1.5, "max": 8.0,
                "bucketCounts": ["1", "1", "1"], "explicitBounds": [2.0, 5.0],
                "attributes": deepcopy(attributes), "exemplars": [{
                    "timeUnixNano": "1770000000050000000", "asDouble": 8.0,
                    "traceId": "0123456789abcdef0123456789abcdef", "spanId": "0123456789abcdef",
                    "filteredAttributes": deepcopy(attributes),
                }],
            }]},
        }]
        base["scopeMetrics"] = [scope]
        return {"resourceMetrics": [base]}
    raise ValueError(signal)


class SourceArchiveTests(unittest.TestCase):
    maxDiff = None

    def configurations(self):
        for mode in ("core", "evaluation"):
            yield mode, toolkit.yaml_load(ROOT / "config/otel-collector" / f"{mode}.yaml")

    def test_source_receives_every_signal_without_analytical_filters(self):
        for mode, config in self.configurations():
            for signal in ("logs", "metrics", "traces"):
                with self.subTest(mode=mode, signal=signal):
                    pipeline = config["service"]["pipelines"][f"{signal}/source"]
                    self.assertEqual(pipeline["receivers"], ["otlp"])
                    self.assertEqual(pipeline["processors"], ["memory_limiter", "resource/source_metadata"])
                    self.assertEqual(pipeline["exporters"], ["otlphttp/source"])
                    self.assertTrue(any(
                        name.split("/")[0] == signal and name != f"{signal}/source"
                        and "otlp" in value["receivers"] and "transform/ai_agent" in value["processors"]
                        for name, value in config["service"]["pipelines"].items()
                    ))

    def test_source_route_stays_internal_and_does_not_queue_unredacted_data(self):
        for mode, config in self.configurations():
            exporter = config["exporters"]["otlphttp/source"]
            self.assertEqual(exporter["endpoint"], "http://source-archive:4320", mode)
            self.assertEqual(exporter["encoding"], "json", mode)
            self.assertIs(exporter["sending_queue"]["enabled"], False, mode)
            self.assertEqual(exporter.get("compression", "none"), "none", mode)
            self.assertFalse(any(name.startswith("file/") for name in config["exporters"]))
        service = toolkit.yaml_load(ROOT / "compose.yaml")["services"]["source-archive"]
        self.assertNotIn("ports", service)
        self.assertIn("collector-source-data:/var/lib/otelcol/source", service["volumes"])

    def test_corporate_cannot_bypass_its_allowlist_through_source_archive(self):
        config = toolkit.yaml_load(ROOT / "config/otel-collector/corporate.yaml")
        self.assertNotIn("otlphttp/source", config["exporters"])
        self.assertFalse(any(name.startswith("file/") for name in config["exporters"]))
        self.assertFalse(any(name.endswith("/source") for name in config["service"]["pipelines"]))
        for pipeline in config["service"]["pipelines"].values():
            self.assertIn("transform/corporate_allowlist", pipeline["processors"])

    def test_source_storage_initialization_is_bounded_and_required(self):
        config = toolkit.yaml_load(ROOT / "compose.yaml")
        initializer = config["services"]["source-storage-init"]
        service = config["services"]["source-archive"]
        self.assertEqual(initializer["user"], "0:0")
        self.assertEqual(initializer["network_mode"], "none")
        self.assertEqual(initializer["restart"], "no")
        self.assertEqual(initializer["volumes"], ["collector-source-data:/source"])
        self.assertEqual(initializer["entrypoint"], ["sh", "-c"])
        self.assertEqual(initializer["command"], ["chown 10001:10001 /source && chmod 700 /source"])
        self.assertNotIn("ports", initializer)
        self.assertNotIn("networks", initializer)
        self.assertEqual(service["depends_on"]["source-storage-init"], {"condition": "service_completed_successfully"})
        self.assertIn("collector-source-data", config["volumes"])

    def test_source_metadata_is_additive(self):
        for mode, config in self.configurations():
            metadata = config["processors"]["resource/source_metadata"]["attributes"]
            self.assertGreaterEqual(len(metadata), 2, mode)
            self.assertTrue(all(item["action"] == "insert" for item in metadata), mode)
            self.assertTrue(all(item["key"].startswith("ai_observability.") for item in metadata), mode)
            self.assertIn("source-preserving", [item["value"] for item in metadata], mode)

    def test_static_validator_rejects_lossy_or_unsafe_source_routes(self):
        mutations = (
            ("normalization", lambda c: c["service"]["pipelines"]["metrics/source"]["processors"].insert(1, "transform/ai_agent")),
            ("missing signal", lambda c: c["service"]["pipelines"].pop("logs/source")),
            ("external endpoint", lambda c: c["exporters"]["otlphttp/source"].update(endpoint="http://example.invalid:4320")),
            ("raw queue", lambda c: c["exporters"]["otlphttp/source"].update(sending_queue={"enabled": True})),
            ("wrong encoding", lambda c: c["exporters"]["otlphttp/source"].update(encoding="proto")),
        )
        for mode, original in self.configurations():
            self.assertEqual(toolkit.source_archive_policy_errors(original, mode), [])
            for name, mutate in mutations:
                config = deepcopy(original)
                mutate(config)
                with self.subTest(mode=mode, mutation=name):
                    self.assertTrue(toolkit.source_archive_policy_errors(config, mode))

    def test_static_validator_rejects_an_archive_in_corporate(self):
        config = toolkit.yaml_load(ROOT / "config/otel-collector/corporate.yaml")
        self.assertEqual(toolkit.source_archive_policy_errors(config, "corporate"), [])
        config["exporters"]["otlphttp/source"] = {"endpoint": "http://source-archive:4320"}
        self.assertTrue(toolkit.source_archive_policy_errors(config, "corporate"))


class SourceSanitizerTests(unittest.TestCase):
    maxDiff = None

    def test_all_contexts_preserve_unknown_metadata_and_drop_sensitive_keys(self):
        forbidden = (
            "prompt", "input", "output", "response", "body", "gen_ai.prompt", "gen_ai.input.messages",
            "tool.arguments", "tool.call.result", "command.output", "user.email", "account.id",
            "authorization", "api_key", "ACCESS-TOKEN", "refresh_token", "password", "secret",
            "file.path", "absolute_path", "nested.input", "nested.response.body",
            "operator@example.invalid", r"C:\private\source.cs", "/private/source.py",
        )
        safe = [attribute("tool.name", "unknown_tool"), attribute("model", "new-model-family"),
                attribute("deployment.environment.name", "personal-local"), attribute("custom.latency.p99", 5.5, "doubleValue"),
                attribute("streaming", True, "boolValue"), attribute("input_tokens", "42", "intValue"),
                attribute("output_tokens", "11", "intValue"), attribute("prompt_tokens", "42", "intValue"),
                attribute("completion_tokens", "11", "intValue"), attribute("unknown.dimension", "future-value")]
        attrs = safe + [attribute(key, "private-content-sentinel") for key in forbidden]
        for signal in ("logs", "metrics", "traces"):
            with self.subTest(signal=signal):
                original = signal_document(signal, attrs)
                before = deepcopy(original)
                result = archive.sanitize_document(signal, original)
                self.assertEqual(original, before)
                sets = list(attribute_sets(result))
                self.assertGreaterEqual(len(sets), {"logs": 3, "metrics": 4, "traces": 5}[signal])
                for retained in sets:
                    for item in safe:
                        self.assertIn(item, retained)
                    self.assertFalse(set(forbidden) & {item["key"] for item in retained})
                self.assertNotIn("private-content-sentinel", json.dumps(result))

    def test_nested_maps_and_arrays_keep_shape_and_types_without_sensitive_leaves(self):
        nested = attribute("custom", {"values": [
            attribute("count", "7", "intValue"), attribute("secret", "private-secret-sentinel"),
            attribute("items", {"values": [
                {"doubleValue": 2.5}, {"boolValue": False}, {"stringValue": "safe"},
                {"kvlistValue": {"values": [attribute("enabled", True, "boolValue"), attribute("password", "private-password-sentinel")]}}
            ]}, "arrayValue"),
        ]}, "kvlistValue")
        expected = deepcopy(nested)
        expected["value"]["kvlistValue"]["values"].pop(1)
        expected["value"]["kvlistValue"]["values"][1]["value"]["arrayValue"]["values"][3]["kvlistValue"]["values"].pop()
        for signal in ("logs", "metrics", "traces"):
            result = archive.sanitize_document(signal, signal_document(signal, [nested]))
            for attrs in attribute_sets(result):
                self.assertIn(expected, attrs)
            self.assertNotIn("private-secret-sentinel", json.dumps(result))
            self.assertNotIn("private-password-sentinel", json.dumps(result))

    def test_values_are_masked_in_anyvalue_arrays_and_record_names(self):
        sensitive = ["operator@example.invalid", r"C:\private\workspace\source.cs", "/home/operator/source.py",
                     r"\\fileserver\private\source.cs", "Bearer synthetic-token-value", "api_key=synthetic-credential"]
        attrs = [attribute("unknown.samples", {"values": [{"stringValue": value} for value in sensitive]}, "arrayValue")]
        original = signal_document("traces", attrs)
        original["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] = "run operator@example.invalid"
        result = archive.sanitize_document("traces", original)
        serialized = json.dumps(result)
        for value in sensitive:
            self.assertNotIn(json.dumps(value)[1:-1], serialized)
        values = next(attribute_sets(result))[0]["value"]["arrayValue"]["values"]
        self.assertEqual(len(values), len(sensitive))
        self.assertTrue(all("stringValue" in item for item in values))

    def test_links_events_and_trace_identity_are_retained(self):
        original = signal_document("traces", [attribute("safe", "retained"), attribute("prompt", "private-prompt")])
        result = archive.sanitize_document("traces", original)
        before = original["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        after = result["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        for key in ("traceId", "spanId", "parentSpanId", "name", "kind", "startTimeUnixNano", "endTimeUnixNano"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(len(after["links"]), 1)
        self.assertEqual(len(after["events"]), 1)
        for key in ("traceId", "spanId", "flags"):
            self.assertEqual(after["links"][0][key], before["links"][0][key])
        self.assertIn(attribute("safe", "retained"), after["links"][0]["attributes"])
        self.assertNotIn("prompt", {item["key"] for item in after["links"][0]["attributes"]})
        self.assertEqual(after["status"]["code"], 2)
        self.assertEqual(after["status"]["message"], "")
        self.assertEqual(after["traceState"], "")
        self.assertEqual(after["links"][0]["traceState"], "")

    def test_metric_measurements_temporality_and_exemplars_are_unchanged(self):
        original = signal_document("metrics", [attribute("model", "unknown-model")])
        metrics = original["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        metrics.extend([
            {"name": "future.gauge", "unit": "1", "gauge": {"dataPoints": [{"asDouble": 3.75, "timeUnixNano": "1770000000000000000"}]}},
            {"name": "future.sum", "unit": "1", "sum": {"aggregationTemporality": 2, "isMonotonic": True, "dataPoints": [{"asInt": "9007199254740993"}]}},
            {"name": "future.exponential", "unit": "ms", "exponentialHistogram": {"aggregationTemporality": 1, "dataPoints": [{"scale": 3, "count": "5", "sum": 17.0, "zeroCount": "1", "positive": {"offset": -1, "bucketCounts": ["1", "3"]}, "negative": {"offset": 0, "bucketCounts": []}}]}},
            {"name": "future.summary", "unit": "ms", "summary": {"dataPoints": [{"count": "8", "sum": 13.0, "quantileValues": [{"quantile": 0.5, "value": 1.25}]}]}},
        ])
        result = archive.sanitize_document("metrics", original)
        observed = result["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        self.assertEqual(len(observed), len(metrics))
        for before, after in zip(metrics, observed):
            self.assertEqual(after["name"], before["name"])
            self.assertEqual(after["unit"], before["unit"])
            for kind in ("gauge", "sum", "histogram", "exponentialHistogram", "summary"):
                if kind in before:
                    self.assertEqual(after[kind], before[kind])
        self.assertEqual(observed[0]["description"], "")

    def test_numeric_prompt_lengths_survive_but_text_does_not(self):
        attrs = [attribute("prompt.length", "42", "intValue"), attribute("prompt_length", 2.5, "doubleValue"),
                 attribute("prompt-length", "private-length-sentinel"), attribute("completion_tokens", "11", "intValue")]
        protected_numeric = [
            attribute(key, "123", "intValue") for key in (
                "secret.prompt.length", "password.usage.prompt", "user.email.prompt.length",
                "account.id.output.size", "file.path.input.tokens", "access_token.prompt.length",
            )
        ]
        attrs.extend(protected_numeric)
        result = archive.sanitize_document("logs", signal_document("logs", attrs))
        for retained in attribute_sets(result):
            self.assertIn(attrs[0], retained)
            self.assertIn(attrs[1], retained)
            self.assertIn(attrs[3], retained)
            self.assertFalse(any(item["key"] == "prompt-length" for item in retained))
            self.assertFalse(
                {item["key"] for item in protected_numeric} & {item["key"] for item in retained}
            )
        self.assertNotIn("private-length-sentinel", json.dumps(result))
        log = result["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        self.assertEqual(log["body"], {"stringValue": "AI telemetry metadata event"})
        self.assertEqual(log["severityNumber"], 9)

    def test_content_containers_cannot_override_sensitive_ancestor_keys(self):
        attrs = [
            attribute(key, {"values": [attribute("length", "123", "intValue")]}, "kvlistValue")
            for key in ("secret.prompt", "password.input", "user.email.output", "account.id.completion")
        ]
        for signal in ("logs", "metrics", "traces"):
            with self.subTest(signal=signal):
                result = archive.sanitize_document(signal, signal_document(signal, attrs))
                forbidden = {item["key"] for item in attrs}
                for retained in attribute_sets(result):
                    self.assertFalse(forbidden & {item["key"] for item in retained})

    def test_invalid_documents_fail_closed(self):
        for signal, payload in (("unknown", {}), ("logs", []), ("logs", {}), ("traces", {"resourceSpans": {}})):
            with self.subTest(signal=signal, payload=payload), self.assertRaises(ValueError):
                archive.sanitize_document(signal, payload)

    def test_nested_context_sensitive_attributes_cannot_escape_redaction(self):
        attrs = [
            attribute("user", {"values": [attribute("name", "private-person-sentinel"), attribute("role", "developer")]}, "kvlistValue"),
            attribute("account", {"values": [attribute("id", "private-account-sentinel")]}, "kvlistValue"),
            attribute("process", {"values": [attribute("command", "private-command-sentinel")]}, "kvlistValue"),
        ]
        result = archive.sanitize_document("traces", signal_document("traces", attrs))
        serialized = json.dumps(result)
        for sentinel in ("private-person-sentinel", "private-account-sentinel", "private-command-sentinel"):
            self.assertNotIn(sentinel, serialized)
        self.assertIn("developer", serialized)

    def test_malformed_anyvalue_scalars_fail_closed(self):
        invalid = (
            {"intValue": "private-text"}, {"intValue": True}, {"boolValue": "private-text"},
            {"doubleValue": {"private": "text"}}, {"doubleValue": True},
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                archive.sanitize_document("logs", signal_document("logs", [{"key": "unknown", "value": value}]))

    def test_opaque_binary_values_are_redacted_without_deleting_the_record(self):
        payload = signal_document("logs", [attribute("opaque", "cHJpdmF0ZS1jb250ZW50", "bytesValue")])
        result = archive.sanitize_document("logs", payload)
        self.assertEqual(len(result["resourceLogs"][0]["scopeLogs"][0]["logRecords"]), 1)
        self.assertNotIn("cHJpdmF0ZS1jb250ZW50", json.dumps(result))


class SourceStoreTests(unittest.TestCase):
    def test_append_is_durable_and_restart_does_not_truncate_existing_records(self):
        with tempfile.TemporaryDirectory() as directory:
            store = archive.ArchiveStore(Path(directory))
            with patch.object(archive.os, "fsync", wraps=archive.os.fsync) as sync:
                store.append("logs", {"sequence": 1})
                sync.assert_called()
                sync.reset_mock()
                store.append("logs", {"sequence": 2})
                sync.assert_called()
                restarted = archive.ArchiveStore(Path(directory))
                sync.reset_mock()
                restarted.append("logs", {"sequence": 3})
                sync.assert_called()
            documents = [json.loads(line) for line in (Path(directory) / "logs.jsonl").read_text().splitlines()]
            self.assertEqual(documents, [{"sequence": 1}, {"sequence": 2}, {"sequence": 3}])

    def test_concurrent_short_writes_produce_complete_json_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            store = archive.ArchiveStore(Path(directory))
            real_write = archive.os.write
            with patch.object(archive.os, "write", side_effect=lambda fd, data: real_write(fd, data[:7])):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(lambda number: store.append("traces", {"sequence": number, "safe": "x" * 128}), range(16)))
            documents = [json.loads(line) for line in (Path(directory) / "traces.jsonl").read_text().splitlines()]
            self.assertEqual({item["sequence"] for item in documents}, set(range(16)))
            self.assertEqual(len(documents), 16)
            self.assertTrue(all(item["safe"] == "x" * 128 for item in documents))

    def test_failed_append_rolls_back_only_unacknowledged_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = archive.ArchiveStore(Path(directory))
            store.append("metrics", {"sequence": "already-durable"})
            path = Path(directory) / "metrics.jsonl"
            before = path.read_bytes()
            with patch.object(archive.os, "fsync", side_effect=OSError("synthetic disk failure")):
                with self.assertRaises(OSError):
                    store.append("metrics", {"sequence": "unacknowledged"})
            self.assertEqual(path.read_bytes(), before)

    def test_startup_preserves_incomplete_tail_before_resuming_json_lines(self):
        complete = b'{"sequence":1}\n{"sequence":2}\n'
        partial = b'{"sequence":3,"unfinished":"\xe4\xb8'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "logs.jsonl"
            source.write_bytes(complete + partial)
            store = archive.ArchiveStore(root)
            recovered = list(root.glob("recovered-logs-*.partial"))
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0].read_bytes(), partial)
            self.assertEqual(source.read_bytes(), complete)
            store.append("logs", {"sequence": 4})
            records = [json.loads(line) for line in source.read_bytes().splitlines()]
            self.assertEqual(records, [{"sequence": 1}, {"sequence": 2}, {"sequence": 4}])
            archive.ArchiveStore(root)
            self.assertEqual(list(root.glob("recovered-logs-*.partial")), recovered)
            self.assertEqual(recovered[0].read_bytes(), partial)

    def test_failed_recovery_fsync_leaves_original_file_untouched(self):
        original = b'{"sequence":1}\n{"incomplete":'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "logs.jsonl"
            source.write_bytes(original)
            real_open, real_sync = archive.os.open, archive.os.fsync
            recovery_descriptors = set()

            def track_open(path, *args, **kwargs):
                descriptor = real_open(path, *args, **kwargs)
                if Path(path).name.startswith("recovered-logs-"):
                    recovery_descriptors.add(descriptor)
                return descriptor

            def fail_recovery_sync(descriptor):
                if descriptor in recovery_descriptors:
                    raise OSError("synthetic recovery sync failure")
                return real_sync(descriptor)

            with (
                patch.object(archive.os, "open", side_effect=track_open),
                patch.object(archive.os, "fsync", side_effect=fail_recovery_sync),
            ):
                with self.assertRaisesRegex(OSError, "synthetic recovery sync failure"):
                    archive.ArchiveStore(root)
            self.assertTrue(recovery_descriptors)
            self.assertEqual(source.read_bytes(), original)


class SourceRequestTests(unittest.TestCase):
    def handler(self, payload, *, content_type="application/json", encoding="identity"):
        body = json.dumps(payload).encode("utf-8")
        handler = object.__new__(archive.ArchiveHandler)
        handler.path = "/v1/logs"
        handler.headers = {"Content-Type": content_type, "Content-Encoding": encoding, "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.connection = Mock()
        handler.store = Mock()
        handler._reply = Mock()
        return handler

    def test_success_acknowledges_only_after_sanitized_append_completes(self):
        handler = self.handler(signal_document("logs", [attribute("prompt", "private-request-sentinel")]))
        order = []

        def append(signal, document):
            self.assertEqual(signal, "logs")
            self.assertNotIn("private-request-sentinel", json.dumps(document))
            order.append("persisted")

        handler.store.append.side_effect = append
        handler._reply.side_effect = lambda status: order.append(status)
        handler.do_POST()
        self.assertEqual(order, ["persisted", 200])

    def test_storage_failure_returns_retryable_status_without_success(self):
        handler = self.handler(signal_document("logs", []))
        handler.store.append.side_effect = OSError("private-provider-failure")
        handler.do_POST()
        handler._reply.assert_called_once_with(503)

    def test_invalid_or_unsupported_requests_never_reach_storage(self):
        cases = (
            ({}, "application/json", "identity", 400),
            (signal_document("logs", []), "application/x-protobuf", "identity", 415),
            (signal_document("logs", []), "application/json", "gzip", 415),
        )
        for payload, content_type, encoding, status in cases:
            with self.subTest(status=status, content_type=content_type, encoding=encoding):
                handler = self.handler(payload, content_type=content_type, encoding=encoding)
                handler.do_POST()
                handler.store.append.assert_not_called()
                handler._reply.assert_called_once_with(status)


class SourceExportTests(unittest.TestCase):
    def test_export_refuses_corporate_and_existing_output_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(toolkit, "require_compose") as docker:
            existing = Path(directory)
            marker = existing / "keep.jsonl"
            marker.write_bytes(b"keep-existing-data")
            with self.assertRaises(ValueError):
                toolkit.source_export("corporate", existing / "corporate")
            with self.assertRaises(ValueError):
                toolkit.source_export("evaluation", existing)
            docker.assert_not_called()
            self.assertEqual(marker.read_bytes(), b"keep-existing-data")
            self.assertFalse((existing / "corporate").exists())

    def test_unavailable_docker_does_not_create_an_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new-export"
            with patch.object(toolkit, "require_compose", side_effect=RuntimeError("Docker unavailable")):
                with self.assertRaisesRegex(RuntimeError, "Docker unavailable"):
                    toolkit.source_export("core", target)
            self.assertFalse(target.exists())

    def test_export_copies_all_signals_without_printing_or_rewriting_contents(self) -> None:
        content = b'{"synthetic":"source-export-content-sentinel","values":[1,2.5]}\n{"incomplete":'
        recovered = b'{"synthetic":"recovery-export-content-sentinel"'
        commands = []

        def copy_archive(command, **kwargs):
            commands.append(command)
            self.assertEqual(command[0:2], ["docker", "compose"])
            self.assertEqual(command[-3], "cp")
            self.assertTrue(kwargs["capture_output"])
            for signal in ("logs", "metrics", "traces"):
                (Path(command[-1]) / f"{signal}.jsonl").write_bytes(content)
            (Path(command[-1]) / "recovered-logs-fixture.partial").write_bytes(recovered)
            return subprocess.CompletedProcess(command, 0, "source-export-content-sentinel", "")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new-export"
            output = io.StringIO()
            with (
                patch.object(toolkit, "require_compose", return_value=["docker", "compose"]),
                patch.object(toolkit, "load_env_file"),
                patch.object(toolkit, "compose_args", return_value=["-f", "fixture-compose.yaml"]),
                patch.object(toolkit.subprocess, "run", side_effect=copy_archive),
                redirect_stdout(output),
            ):
                self.assertEqual(toolkit.source_export("evaluation", target), target)
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][-2], "source-archive:/var/lib/otelcol/source/.")
            for signal in ("logs", "metrics", "traces"):
                self.assertEqual((target / f"{signal}.jsonl").read_bytes(), content)
            self.assertEqual((target / "recovered-logs-fixture.partial").read_bytes(), recovered)
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], "evaluation")
            self.assertEqual(
                {item["file"]: item["bytes"] for item in manifest["files"]},
                {"logs.jsonl": len(content), "metrics.jsonl": len(content), "traces.jsonl": len(content),
                 "recovered-logs-fixture.partial": len(recovered)},
            )
            self.assertIn("not atomic", manifest["snapshot"])
            self.assertNotIn("source-export-content-sentinel", output.getvalue())
            self.assertNotIn("source-export-content-sentinel", json.dumps(manifest))
            self.assertNotIn("recovery-export-content-sentinel", output.getvalue())
            self.assertNotIn("recovery-export-content-sentinel", json.dumps(manifest))

    def test_failed_copy_keeps_partial_export_without_a_success_manifest(self) -> None:
        def copy_archive(command, **kwargs):
            (Path(command[-1]) / "logs.jsonl").write_bytes(b"retained-partial-copy")
            return subprocess.CompletedProcess(command, 1, "", "private-provider-error")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "partial-export"
            with (
                patch.object(toolkit, "require_compose", return_value=["docker", "compose"]),
                patch.object(toolkit, "load_env_file"),
                patch.object(toolkit, "compose_args", return_value=[]),
                patch.object(toolkit.subprocess, "run", side_effect=copy_archive),
            ):
                with self.assertRaisesRegex(RuntimeError, "partial export retained") as failure:
                    toolkit.source_export("core", target)
            self.assertNotIn("private-provider-error", str(failure.exception))
            self.assertEqual((target / "logs.jsonl").read_bytes(), b"retained-partial-copy")
            self.assertFalse((target / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
