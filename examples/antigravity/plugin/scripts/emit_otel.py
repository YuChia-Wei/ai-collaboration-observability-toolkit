#!/usr/bin/env python3
"""Metadata-only Antigravity JSON Hooks to OTLP/HTTP bridge.

The bridge intentionally does not read transcriptPath, artifactDirectoryPath,
workspacePaths, prompt text, model output, tool arguments, or raw error text.
It uses only Python's standard library and fails open: observability delivery
errors never block or alter the Antigravity execution loop.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_VERSION = "0.1.1"
SCOPE_NAME = "ai-collaboration-observability.antigravity-hook"
DEFAULT_ENDPOINT = "http://127.0.0.1:4318"
SAFE_TOKEN = re.compile(r"[^A-Za-z0-9._:/-]+")
_KEY_CACHE: bytes | None = None

KNOWN_TERMINATION_REASONS = {
    "model_stop",
    "max_steps_exceeded",
    "error",
    "cancelled",
    "interrupted",
    "completed",
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_token(value: Any, fallback: str = "unknown", maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    sanitized = SAFE_TOKEN.sub("-", value.strip()).strip("-.")
    return (sanitized or fallback)[:maximum]


def _now_ns() -> int:
    return time.time_ns()


def _state_root() -> Path:
    override = os.getenv("ANTIGRAVITY_OBSERVABILITY_STATE_DIR")
    if override:
        root = Path(override).expanduser()
    elif os.name == "nt" and os.getenv("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "ai-collaboration-observability-toolkit" / "antigravity"
    else:
        state_home = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        root = state_home / "ai-collaboration-observability-toolkit" / "antigravity"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _key() -> bytes:
    global _KEY_CACHE
    if _KEY_CACHE is not None:
        return _KEY_CACHE
    path = _state_root() / "pseudonym.key"
    try:
        if path.exists():
            for _ in range(5):
                value = path.read_bytes()
                if len(value) >= 32:
                    _KEY_CACHE = value
                    return _KEY_CACHE
                time.sleep(0.01)
        value = secrets.token_bytes(32)
        try:
            with path.open("xb") as stream:
                stream.write(value)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            _KEY_CACHE = value
            return _KEY_CACHE
        except FileExistsError:
            for _ in range(5):
                existing = path.read_bytes()
                if len(existing) >= 32:
                    _KEY_CACHE = existing
                    return _KEY_CACHE
                time.sleep(0.01)
            raise OSError("pseudonym key was not fully initialized")
    except OSError:
        # Ephemeral fallback still prevents the raw identifier from leaving the process.
        _KEY_CACHE = secrets.token_bytes(32)
        return _KEY_CACHE


def _digest(value: str, size: int) -> str:
    return hmac.new(_key(), value.encode("utf-8", errors="replace"), hashlib.sha256).digest()[:size].hex()


def _conversation(payload: dict[str, Any]) -> str:
    raw = payload.get("conversationId")
    return raw if isinstance(raw, str) and raw else "missing-conversation-id"


def _trace_id(payload: dict[str, Any]) -> str:
    return _digest(f"trace:{_conversation(payload)}", 16)


def _session_span_id(payload: dict[str, Any]) -> str:
    return _digest(f"session:{_conversation(payload)}", 8)


def _invocation_span_id(payload: dict[str, Any]) -> str:
    invocation = payload.get("invocationNum", 0)
    return _digest(f"invocation:{_conversation(payload)}:{invocation}", 8)


def _state_path(payload: dict[str, Any]) -> Path:
    return _state_root() / f"session-{_digest(_conversation(payload), 12)}.json"


def _read_state(payload: dict[str, Any]) -> dict[str, Any]:
    path = _state_path(payload)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(payload: dict[str, Any], state: dict[str, Any]) -> None:
    path = _state_path(payload)
    try:
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return


def _delete_state(payload: dict[str, Any]) -> None:
    try:
        _state_path(payload).unlink(missing_ok=True)
    except OSError:
        return


def _cleanup_stale_state() -> None:
    cutoff = time.time() - 7 * 24 * 60 * 60
    try:
        for path in _state_root().glob("session-*.json"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        return


def _surface(payload: dict[str, Any]) -> str:
    override = os.getenv("ANTIGRAVITY_OBSERVABILITY_SERVICE_NAME")
    if override:
        return _safe_token(override, "antigravity")
    transcript = payload.get("transcriptPath")
    if isinstance(transcript, str) and "antigravity-cli" in transcript.replace("\\", "/").lower():
        return "antigravity-cli"
    return "antigravity-2"


def _model(payload: dict[str, Any]) -> str:
    return _safe_token(payload.get("modelName"), "unknown-model")


def _resource_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "service.name": _surface(payload),
        "service.namespace": "ai-collaboration",
        "service.version": _safe_token(os.getenv("ANTIGRAVITY_VERSION"), "unknown"),
        "telemetry.sdk.name": "antigravity-json-hooks-bridge",
        "telemetry.sdk.language": "python",
        "telemetry.sdk.version": SCRIPT_VERSION,
        "ai_context.framework.name": _safe_token(
            os.getenv("AI_CONTEXT_FRAMEWORK_NAME"), "ai-collaboration-framework"
        ),
        "ai_context.framework.version": _safe_token(
            os.getenv("AI_CONTEXT_FRAMEWORK_VERSION"), "unknown"
        ),
        "ai_context.tool.category": _surface(payload),
        "ai_context.model.family": _model(payload),
        "ai_context.evidence.class": "hook-observation",
    }


def _any_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"key": key, "value": _any_value(value)}
        for key, value in values.items()
        if value is not None
    ]


def _endpoint() -> str:
    endpoint = (
        os.getenv("AI_OBSERVABILITY_OTLP_HTTP_ENDPOINT")
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or DEFAULT_ENDPOINT
    ).rstrip("/")
    for suffix in ("/v1/logs", "/v1/traces", "/v1/metrics"):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)]
            break
    if not endpoint.startswith(("http://", "https://")):
        return DEFAULT_ENDPOINT
    return endpoint


def _post(signal_path: str, document: dict[str, Any]) -> None:
    if not _env_bool("AI_OBSERVABILITY_ENABLED", True):
        return
    request = urllib.request.Request(
        f"{_endpoint()}{signal_path}",
        data=json.dumps(document, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = float(os.getenv("AI_OBSERVABILITY_TIMEOUT_SECONDS", "0.75"))
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, min(timeout, 3.0))) as response:
            response.read(1)
    except (OSError, ValueError, urllib.error.URLError):
        # Observability must never block or change the agent's execution outcome.
        return


def _emit_log(
    payload: dict[str, Any],
    event_name: str,
    operation: str,
    outcome: str,
    *,
    duration_ms: int | None = None,
    success: bool = True,
    error_category: str | None = None,
    state: str = "completed",
    span_id: str | None = None,
) -> None:
    timestamp = _now_ns()
    attributes = {
        "event.name": event_name,
        "gen_ai.provider.name": "google",
        "gen_ai.operation.name": operation,
        "gen_ai.request.model": _model(payload),
        "ai_context.operation.type": operation,
        "ai_context.workflow.stage": operation,
        "ai_context.tool.category": _surface(payload),
        "ai_context.model.family": _model(payload),
        "ai_context.state": state,
        "ai_context.outcome": outcome,
        "ai_context.evidence.class": "hook-observation",
        "ai_context.error.category": error_category,
        "duration_ms": duration_ms,
        "success": success,
    }
    record: dict[str, Any] = {
        "timeUnixNano": str(timestamp),
        "observedTimeUnixNano": str(timestamp),
        "severityNumber": 9 if success else 17,
        "severityText": "INFO" if success else "ERROR",
        "body": {"stringValue": "AI telemetry metadata event"},
        "attributes": _attributes(attributes),
        "traceId": _trace_id(payload),
        "spanId": span_id or _session_span_id(payload),
    }
    document = {
        "resourceLogs": [
            {
                "resource": {"attributes": _attributes(_resource_attributes(payload))},
                "scopeLogs": [
                    {
                        "scope": {"name": SCOPE_NAME, "version": SCRIPT_VERSION},
                        "logRecords": [record],
                    }
                ],
            }
        ]
    }
    _post("/v1/logs", document)


def _emit_span(
    payload: dict[str, Any],
    name: str,
    operation: str,
    start_ns: int,
    end_ns: int,
    span_id: str,
    *,
    parent_span_id: str | None = None,
    outcome: str = "success",
    success: bool = True,
    error_category: str | None = None,
    state: str = "completed",
) -> None:
    attributes = {
        "event.name": name,
        "gen_ai.provider.name": "google",
        "gen_ai.operation.name": operation,
        "gen_ai.request.model": _model(payload),
        "ai_context.operation.type": operation,
        "ai_context.workflow.stage": operation,
        "ai_context.tool.category": _surface(payload),
        "ai_context.model.family": _model(payload),
        "ai_context.state": state,
        "ai_context.outcome": outcome,
        "ai_context.evidence.class": "hook-observation",
        "ai_context.error.category": error_category,
        "duration_ms": max(0, (end_ns - start_ns) // 1_000_000),
        "success": success,
    }
    span: dict[str, Any] = {
        "traceId": _trace_id(payload),
        "spanId": span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(max(start_ns, end_ns)),
        "attributes": _attributes(attributes),
        "status": {"code": 1 if success else 2, "message": ""},
    }
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    document = {
        "resourceSpans": [
            {
                "resource": {"attributes": _attributes(_resource_attributes(payload))},
                "scopeSpans": [
                    {
                        "scope": {"name": SCOPE_NAME, "version": SCRIPT_VERSION},
                        "spans": [span],
                    }
                ],
            }
        ]
    }
    _post("/v1/traces", document)


def _pre_invocation(payload: dict[str, Any]) -> None:
    now = _now_ns()
    state = _read_state(payload)
    state.setdefault("firstSeenNs", now)
    invocations = state.setdefault("invocations", {})
    if isinstance(invocations, dict):
        invocations[str(payload.get("invocationNum", 0))] = now
    _write_state(payload, state)


def _post_invocation(payload: dict[str, Any]) -> None:
    now = _now_ns()
    state = _read_state(payload)
    invocations = state.setdefault("invocations", {})
    start = now
    if isinstance(invocations, dict):
        candidate = invocations.pop(str(payload.get("invocationNum", 0)), None)
        if isinstance(candidate, int):
            start = candidate
    state.setdefault("firstSeenNs", start)
    _write_state(payload, state)
    span_id = _invocation_span_id(payload)
    duration = max(0, (now - start) // 1_000_000)
    _emit_span(
        payload,
        "antigravity.model.invocation",
        "model-invocation",
        start,
        now,
        span_id,
        parent_span_id=_session_span_id(payload),
    )
    _emit_log(
        payload,
        "antigravity.model.invocation.completed",
        "model-invocation",
        "success",
        duration_ms=duration,
        span_id=span_id,
    )


def _post_tool_use(payload: dict[str, Any], operation: str) -> None:
    has_error = bool(payload.get("error"))
    _emit_log(
        payload,
        "antigravity.tool.completed",
        _safe_token(operation, "tool-operation"),
        "error" if has_error else "success",
        success=not has_error,
        error_category="tool-error" if has_error else None,
    )


def _stop(payload: dict[str, Any]) -> None:
    now = _now_ns()
    state = _read_state(payload)
    first_seen = state.get("firstSeenNs")
    start = first_seen if isinstance(first_seen, int) else now
    raw_reason = payload.get("terminationReason")
    reason = raw_reason if raw_reason in KNOWN_TERMINATION_REASONS else "other"
    has_error = bool(payload.get("error")) or reason == "error"
    fully_idle = bool(payload.get("fullyIdle"))
    state_name = "idle" if fully_idle else "background-active"
    _emit_span(
        payload,
        "antigravity.agent.session",
        "agent-workflow",
        start,
        now,
        _session_span_id(payload),
        outcome=reason,
        success=not has_error,
        error_category="agent-error" if has_error else None,
        state=state_name,
    )
    _emit_log(
        payload,
        "antigravity.agent.stopped",
        "agent-workflow",
        reason,
        duration_ms=max(0, (now - start) // 1_000_000),
        success=not has_error,
        error_category="agent-error" if has_error else None,
        state=state_name,
    )
    _delete_state(payload)


def _response(event: str) -> dict[str, Any]:
    if event == "stop":
        # Any value other than "continue" permits the normal stop.
        return {"decision": ""}
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "event",
        choices=("pre-invocation", "post-invocation", "post-tool-use", "stop"),
    )
    parser.add_argument("--operation", default="tool-operation")
    args = parser.parse_args(argv)

    response = _response(args.event)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            payload = {}
        _cleanup_stale_state()
        if args.event == "pre-invocation":
            _pre_invocation(payload)
        elif args.event == "post-invocation":
            _post_invocation(payload)
        elif args.event == "post-tool-use":
            _post_tool_use(payload, args.operation)
        else:
            _stop(payload)
    except Exception:  # noqa: BLE001
        # Hook failures must not change the agent's permissions or completion state.
        pass

    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
