#!/usr/bin/env python3
"""Prove source retention and privacy through a running Collector, without printing data."""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import toolkit


SENTINEL = "SOURCE_PRIVATE_SENTINEL_93F2"


def attr(key: str, value: Any) -> dict[str, Any]:
    def encoded(item: Any) -> dict[str, Any]:
        if isinstance(item, bool):
            return {"boolValue": item}
        if isinstance(item, int):
            return {"intValue": str(item)}
        if isinstance(item, dict):
            return {"kvlistValue": {"values": [attr(k, v) for k, v in item.items()]}}
        if isinstance(item, list):
            return {"arrayValue": {"values": [encoded(v) for v in item]}}
        return {"stringValue": item}
    return {"key": key, "value": encoded(value)}


def fixtures(marker: str) -> dict[str, dict[str, Any]]:
    now = time.time_ns()
    attributes = [
        attr("source.test.case", marker), attr("safe.phase", "discovery"),
        attr("safe.number", 42), attr("safe.enabled", True),
        attr("model", "future-safe-model"),
        attr("gen_ai.usage.prompt_tokens", 123), attr("gen_ai.usage.completion_tokens", 45),
        attr("prompt.length", 789), attr("input_tokens", 123),
        attr("llm.token_count.prompt", 123),
        attr("prompt", SENTINEL), attr("secret", SENTINEL),
        attr("account.id", SENTINEL), attr("file.path", "C:\\private\\" + SENTINEL),
        attr("nested", {"safe_count": 7, "password": SENTINEL}),
        attr("nested_items", [{"safe_count": 9, "api_key": SENTINEL}]),
        attr("account", {"id": SENTINEL, "safe_count": 3}),
        attr("user", {"id": SENTINEL, "name": SENTINEL}),
        attr("process", {"command": SENTINEL}),
        attr("operator@example.invalid", SENTINEL),
    ]
    resource = {"attributes": [
        attr("service.name", "codex-app-server"),
        attr("service.namespace", "ai-collaboration-source-fixture"),
        attr("deployment.environment.name", "sender-environment"), *attributes,
    ]}
    scope = {"name": "source.retention.fixture", "version": "1", "attributes": attributes}
    # These distinct streams would lose their dimensions in the bounded projection.
    points = [
        {"attributes": [*attributes, attr("source.bucket.variant", variant)],
         "startTimeUnixNano": str(now - 1_000_000_000), "timeUnixNano": str(now),
         "count": "2", "sum": 12, "min": 2, "max": 10,
         "bucketCounts": ["1", "1", "0"], "explicitBounds": bounds,
         "exemplars": [{"timeUnixNano": str(now), "asDouble": 10,
                        "filteredAttributes": attributes}]}
        for variant, bounds in [("a", [5, 20]), ("b", [8, 30])]
    ]
    metric = {"name": "source.fixture.future_histogram", "unit": "ms",
              "description": SENTINEL,
              "histogram": {"aggregationTemporality": 1, "dataPoints": points}}
    log = {"timeUnixNano": str(now), "severityNumber": 9, "severityText": "INFO",
           "body": {"stringValue": SENTINEL}, "attributes": attributes}
    span = {"traceId": uuid.uuid4().hex, "spanId": uuid.uuid4().hex[:16],
            "name": "source.fixture.operation", "kind": 1,
            "startTimeUnixNano": str(now - 1000000), "endTimeUnixNano": str(now),
            "status": {"code": 2, "message": SENTINEL}, "traceState": SENTINEL,
            "attributes": attributes,
            "events": [{"name": "source.fixture.event", "timeUnixNano": str(now),
                        "attributes": attributes}],
            "links": [{"traceId": uuid.uuid4().hex, "spanId": uuid.uuid4().hex[:16],
                       "traceState": SENTINEL, "attributes": attributes}]}
    return {
        "metrics": {"resourceMetrics": [{"resource": resource, "scopeMetrics": [{"scope": scope, "metrics": [metric]}]}]},
        "logs": {"resourceLogs": [{"resource": resource, "scopeLogs": [{"scope": scope, "logRecords": [log]}]}]},
        "traces": {"resourceSpans": [{"resource": resource, "scopeSpans": [{"scope": scope, "spans": [span]}]}]},
    }


def values(attributes: list[dict[str, Any]]) -> dict[str, Any]:
    return {item["key"]: next(iter(item["value"].values())) for item in attributes}


def matching_resources(path: Path, field: str, marker: str) -> list[dict[str, Any]]:
    found = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                document = json.loads(line)
            except json.JSONDecodeError:
                # A live copy may end in one incomplete write; never ignore middle corruption.
                if line.endswith("\n") or stream.read(1):
                    raise RuntimeError("Source archive contains an invalid complete or interior JSON line") from None
                break
            for resource in document.get(field, []):
                attrs = values(resource.get("resource", {}).get("attributes", []))
                if attrs.get("source.test.case") == marker:
                    found.append(resource)
    return found


def verify(path: Path, marker: str, sent: dict[str, dict[str, Any]]) -> None:
    for signal, field, scope_key, records_key in [
        ("metrics", "resourceMetrics", "scopeMetrics", "metrics"),
        ("logs", "resourceLogs", "scopeLogs", "logRecords"),
        ("traces", "resourceSpans", "scopeSpans", "spans"),
    ]:
        resources = matching_resources(path / f"{signal}.jsonl", field, marker)
        assert resources, f"{signal}: source fixture missing"
        assert SENTINEL not in json.dumps(resources), f"{signal}: privacy sentinel persisted"
        resource = resources[-1]
        attrs = values(resource["resource"]["attributes"])
        assert attrs["deployment.environment.name"] == "sender-environment"
        assert attrs["safe.phase"] == "discovery"
        assert attrs["ai_observability.collection"] == "source-preserving"
        assert attrs["ai_observability.source_schema_version"] == "2"
        scopes = resource[scope_key]
        assert values(scopes[0]["scope"]["attributes"])["safe.number"] == "42"
        records = [record for scope in scopes for record in scope[records_key]]
        assert len(records) == 1, f"{signal}: source was replaced or copied by canonical mapping"
        record = records[0]
        if signal == "metrics":
            original = sent[signal][field][0][scope_key][0][records_key][0]
            assert record["name"] == original["name"]
            assert record["unit"] == "ms"
            assert record["histogram"]["aggregationTemporality"] == 1
            points = record["histogram"]["dataPoints"]
            assert len(points) == 2, "distinct source histogram streams were collapsed"
            for actual, expected in zip(points, original["histogram"]["dataPoints"]):
                for key in ("startTimeUnixNano", "timeUnixNano", "count", "sum", "min", "max", "bucketCounts", "explicitBounds"):
                    assert actual[key] == expected[key], f"source histogram changed: {key}"
                labels = values(actual["attributes"])
                assert labels["model"] == "future-safe-model"
                assert values(labels["nested"]["values"])["safe_count"] == "7"
                assert labels["gen_ai.usage.prompt_tokens"] == "123"
                assert labels["gen_ai.usage.completion_tokens"] == "45"
                assert labels["prompt.length"] == "789"
                assert labels["llm.token_count.prompt"] == "123"
                assert labels["source.bucket.variant"] in {"a", "b"}
                assert actual["exemplars"][0]["asDouble"] == 10
        elif signal == "logs":
            assert record["body"] == {"stringValue": "AI telemetry metadata event"}
        else:
            assert record["name"] == "source.fixture.operation"
            assert record["status"]["code"] == 2
            assert record["events"][0]["name"] == "source.fixture.event"
            original = sent[signal][field][0][scope_key][0][records_key][0]
            assert record["links"][0]["traceId"] == original["links"][0]["traceId"]
            assert record["links"][0]["spanId"] == original["links"][0]["spanId"]
            assert values(record["links"][0]["attributes"])["safe.number"] == "42"


def send(payloads: dict[str, dict[str, Any]]) -> None:
    for signal, payload in payloads.items():
        status, body = toolkit.http(
            "POST", f"http://127.0.0.1:{os.getenv('OTLP_HTTP_PORT', '4318')}/v1/{signal}",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
        )
        if status not in (200, 202) or json.loads(body or b"{}").get("partialSuccess"):
            raise RuntimeError(f"Collector did not fully accept {signal} fixture")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["core", "evaluation"], default="evaluation")
    parser.add_argument("--persistence-check", action="store_true")
    args = parser.parse_args()
    toolkit.load_env_file()
    marker = uuid.uuid4().hex
    sent = fixtures(marker)
    report = toolkit.SmokeReport(args.mode)
    try:
        toolkit.wait_stack(args.mode)
        send(sent)
        time.sleep(2)
        target = toolkit.ROOT / "artifacts" / f"source-smoke-{marker}"
        snapshot = toolkit.source_export(args.mode, target / "before")
        verify(snapshot, marker, sent)
        report.pass_("source OTLP retention and privacy", "all signals; unknown dimensions; histogram variants; nested privacy; exemplars")
        if args.persistence_check:
            toolkit.compose_command(args.mode, ["restart", "source-archive", "otel-collector"])
            toolkit.wait_stack(args.mode)
            next_marker = uuid.uuid4().hex
            next_sent = fixtures(next_marker)
            send(next_sent)
            after = toolkit.source_export(args.mode, target / "after")
            verify(after, marker, sent)
            verify(after, next_marker, next_sent)
            for signal in toolkit.SOURCE_SIGNALS:
                before_file = snapshot / f"{signal}.jsonl"
                with before_file.open("rb") as before, (after / before_file.name).open("rb") as restored:
                    while chunk := before.read(1024 * 1024):
                        assert restored.read(len(chunk)) == chunk, "source archive was truncated during restart"
            report.pass_("source archive append persistence after archive and Collector restart")
        else:
            report.skip("source archive restart persistence", "--persistence-check was not selected")
    except Exception as exc:
        report.fail("source archive runtime", f"{type(exc).__name__}: {exc}")
    report.write(toolkit.ROOT / "artifacts" / f"source-smoke-{marker}" / "report.json")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
