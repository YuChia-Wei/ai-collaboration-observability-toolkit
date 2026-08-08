#!/usr/bin/env python3
"""Privacy-first Antigravity hook/status-line exporter for local OTLP/HTTP.

This example deliberately consumes only documented Antigravity hook and status-line
fields. It never reads the transcript path, artifact directory, prompt text, tool
arguments, tool output, source files, e-mail address, workspace path, or VCS branch.

The script uses only the Python standard library. It is intended as an example to
copy into a workspace or user customization directory, not as a production agent
telemetry SDK.
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
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "http://127.0.0.1:4318"
DEFAULT_PROFILE = "personal-local"
DEFAULT_TIMEOUT_SECONDS = 0.35
DEFAULT_HEARTBEAT_SECONDS = 60.0
SCOPE_NAME = "ai-collaboration-observability.antigravity-example"
SCOPE_VERSION = "0.1.2"
SAFE_TEXT = re.compile(r"[^A-Za-z0-9_.:/() +\-]", re.ASCII)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_text(value: Any, *, fallback: str = "unknown", limit: int = 160) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    text = SAFE_TEXT.sub("_", text)
    return text[:limit]


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now_ns() -> int:
    return time.time_ns()


def _otlp_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": _safe_text(value)}


def _otlp_attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"key": key, "value": _otlp_value(value)}
        for key, value in values.items()
        if value is not None
    ]


def _base_endpoint(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OTLP HTTP endpoint must be an http(s) URL")
    path = parsed.path.rstrip("/")
    for suffix in ("/v1/logs", "/v1/metrics", "/v1/traces"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _default_state_dir() -> Path:
    explicit = os.getenv("AI_OBSERVABILITY_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return root / "ai-collaboration-observability" / "antigravity"
    root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "ai-collaboration-observability" / "antigravity"


def _session_key(conversation_id: str) -> str:
    return hashlib.sha256(conversation_id.encode("utf-8", errors="ignore")).hexdigest()


def _local_hmac_key(state_dir: Path) -> bytes:
    """Load or create a user-local key without exporting it or committing it."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "session-hmac.key"
    try:
        existing = path.read_bytes()
        if len(existing) >= 32:
            return existing
    except OSError:
        pass

    candidate = secrets.token_bytes(32)
    try:
        with path.open("xb") as handle:
            handle.write(candidate)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return candidate
    except FileExistsError:
        try:
            existing = path.read_bytes()
            if len(existing) >= 32:
                return existing
        except OSError:
            pass
    except OSError:
        pass

    # An ephemeral key preserves confidentiality if the local state directory is unavailable,
    # although correlation will not survive the process boundary.
    return candidate


def _session_pseudonym(conversation_id: str, salt: str, state_dir: Path) -> str:
    key = salt.encode("utf-8") if salt else _local_hmac_key(state_dir)
    digest = hmac.new(
        key,
        conversation_id.encode("utf-8", errors="ignore"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:24]


def _state_path(state_dir: Path, conversation_id: str) -> Path:
    return state_dir / f"{_session_key(conversation_id)}.json"


def _load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name,
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _read_stdin_json() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _detect_product(payload: dict[str, Any], configured: str) -> str:
    """Select a bounded product name without inspecting path-bearing hook fields."""
    if configured and configured != "auto":
        return _safe_text(configured, fallback="antigravity")
    product = payload.get("product")
    if product:
        return _safe_text(product, fallback="antigravity")
    return "antigravity"


def _resource_attributes(
    *,
    product: str,
    version: str,
    profile: str,
    model: str,
    session_id: str | None,
    phoenix: bool,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "service.name": product,
        "service.namespace": "ai-collaboration",
        "service.version": version,
        "deployment.environment.name": profile,
        "ai_context.environment.profile": profile,
        "ai_context.tool.category": "coding-agent",
        "ai_context.model.family": model,
        "ai_context.evidence.class": "antigravity-local-extension",
        "ai_context.export.phoenix": phoenix,
    }
    if session_id:
        values["ai_context.session.id"] = session_id
    return values


def _log_payload(
    *,
    timestamp_ns: int,
    resource: dict[str, Any],
    event_name: str,
    severity: str,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    body = "Antigravity telemetry metadata event"
    return {
        "resourceLogs": [
            {
                "resource": {"attributes": _otlp_attributes(resource)},
                "scopeLogs": [
                    {
                        "scope": {"name": SCOPE_NAME, "version": SCOPE_VERSION},
                        "logRecords": [
                            {
                                "timeUnixNano": str(timestamp_ns),
                                "observedTimeUnixNano": str(timestamp_ns),
                                "severityText": severity,
                                "body": {"stringValue": body},
                                "attributes": _otlp_attributes(
                                    {"event.name": event_name, **attributes}
                                ),
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _gauge_metric(
    name: str,
    unit: str,
    timestamp_ns: int,
    points: list[tuple[int | float, dict[str, Any]]],
) -> dict[str, Any]:
    data_points: list[dict[str, Any]] = []
    for value, attributes in points:
        point: dict[str, Any] = {
            "timeUnixNano": str(timestamp_ns),
            "attributes": _otlp_attributes(attributes),
        }
        if isinstance(value, int):
            point["asInt"] = str(value)
        else:
            point["asDouble"] = float(value)
        data_points.append(point)
    return {"name": name, "unit": unit, "gauge": {"dataPoints": data_points}}


def _metrics_payload(
    *,
    timestamp_ns: int,
    resource: dict[str, Any],
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": _otlp_attributes(resource)},
                "scopeMetrics": [
                    {
                        "scope": {"name": SCOPE_NAME, "version": SCOPE_VERSION},
                        "metrics": metrics,
                    }
                ],
            }
        ]
    }


def _trace_payload(
    *,
    resource: dict[str, Any],
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    name: str,
    start_ns: int,
    end_ns: int,
    attributes: dict[str, Any],
    success: bool,
) -> dict[str, Any]:
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(max(end_ns, start_ns + 1)),
        "attributes": _otlp_attributes(attributes),
        "status": {"code": 1 if success else 2},
    }
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _otlp_attributes(resource)},
                "scopeSpans": [
                    {
                        "scope": {"name": SCOPE_NAME, "version": SCOPE_VERSION},
                        "spans": [span],
                    }
                ],
            }
        ]
    }


def _deterministic_ids(session_key: str, suffix: str) -> tuple[str, str]:
    trace_id = hashlib.sha256(f"trace:{session_key}:{suffix}".encode()).hexdigest()[:32]
    span_id = hashlib.sha256(f"span:{session_key}:{suffix}".encode()).hexdigest()[:16]
    return trace_id, span_id


def _capture_payload(capture_dir: Path, signal: str, label: str, payload: dict[str, Any]) -> None:
    capture_dir.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^A-Za-z0-9_.-]", "_", label)[:80]
    path = capture_dir / f"{time.time_ns()}-{signal}-{safe_label}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _emit(
    *,
    signal: str,
    label: str,
    payload: dict[str, Any],
    endpoint: str,
    timeout: float,
    dry_run: bool,
    capture_dir: Path | None,
    debug: bool,
) -> None:
    if capture_dir:
        _capture_payload(capture_dir, signal, label, payload)
    if dry_run:
        return
    url = f"{_base_endpoint(endpoint)}/v1/{signal}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.05, timeout)) as response:
            response.read(1024)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        if debug:
            print(f"Antigravity OTLP export skipped: {type(exc).__name__}", file=sys.stderr)


def _model_from_payload(payload: dict[str, Any]) -> str:
    """Read documented model metadata without reading conversation content.

    Antigravity lifecycle Hooks expose ``modelName`` as a common field. The CLI
    custom status-line payload exposes a ``model`` object. Supporting both keeps
    lifecycle and usage signals consistent without opening transcripts.
    """
    hook_model = payload.get("modelName")
    if hook_model:
        return _safe_text(hook_model, fallback="unknown")
    model = payload.get("model")
    if isinstance(model, dict):
        return _safe_text(model.get("id") or model.get("display_name"), fallback="unknown")
    return "unknown"


TOOL_CATEGORIES = {
    "file-operation",
    "search-operation",
    "execution-operation",
    "agent-collaboration",
    "interaction-operation",
    "other-tool",
}


def _tool_category(value: Any) -> str:
    """Validate the low-cardinality category supplied by the Hook matcher.

    ``PostToolUse`` includes a ``toolCall`` object, but it may contain tool arguments,
    commands, paths, or other sensitive values. The Hook matcher already knows which
    tool family fired, so this exporter receives only a bounded category and never
    reads ``toolCall``.
    """
    candidate = _safe_text(value, fallback="other-tool", limit=64)
    return candidate if candidate in TOOL_CATEGORIES else "other-tool"


def _common_context(
    payload: dict[str, Any], args: argparse.Namespace
) -> tuple[str, str, str, str | None, Path, dict[str, Any]]:
    conversation_id = str(payload.get("conversationId") or payload.get("conversation_id") or payload.get("session_id") or "unknown-session")
    state_dir = Path(args.state_dir).expanduser()
    state_path = _state_path(state_dir, conversation_id)
    state = _load_state(state_path)
    product = _detect_product(payload, args.product)
    version = _safe_text(payload.get("version") or state.get("version"), fallback="unknown")
    model = _model_from_payload(payload)
    if model == "unknown":
        model = _safe_text(state.get("model"), fallback="unknown")
    state["model"] = model
    include_session = args.include_session_hash
    if include_session is None:
        include_session = "corporate" not in args.profile.lower()
    session_id = (
        _session_pseudonym(conversation_id, args.session_salt, state_dir) if include_session else None
    )
    return conversation_id, product, version, session_id, state_path, state


def _hook_response(event: str) -> dict[str, Any]:
    if event in {"PreInvocation", "PostInvocation"}:
        response: dict[str, Any] = {"injectSteps": []}
        if event == "PostInvocation":
            response["terminationBehavior"] = ""
        return response
    if event == "Stop":
        return {"decision": ""}
    return {}


def handle_hook(args: argparse.Namespace) -> int:
    payload = _read_stdin_json()
    event = args.event
    now_ns = _now_ns()
    conversation_id, product, version, session_id, state_path, state = _common_context(
        payload, args
    )
    session_key = _session_key(conversation_id)
    state.setdefault("first_seen_ns", now_ns)
    state["version"] = version
    state["product"] = product
    invocations = state.setdefault("invocations", {})
    if not isinstance(invocations, dict):
        invocations = {}
        state["invocations"] = invocations
    model = _model_from_payload(payload)
    if model == "unknown":
        model = _safe_text(state.get("model"), fallback="unknown")
    state["model"] = model
    resource = _resource_attributes(
        product=product,
        version=version,
        profile=args.profile,
        model=model,
        session_id=session_id,
        phoenix=args.phoenix,
    )
    base_attributes: dict[str, Any] = {
        "gen_ai.provider.name": "google",
        "ai_context.tool.category": "coding-agent",
        "ai_context.model.family": model,
        "ai_context.evidence.class": "antigravity-hook",
    }

    if event == "PreInvocation":
        invocation_num = _safe_int(payload.get("invocationNum"))
        invocations[str(invocation_num)] = now_ns
        attributes = {
            **base_attributes,
            "gen_ai.operation.name": "agent_invocation",
            "ai_context.operation.type": "model_invocation",
            "ai_context.workflow.stage": "pre_invocation",
            "ai_context.state": "started",
            "antigravity.invocation.number": invocation_num,
            "antigravity.initial_steps": _safe_int(payload.get("initialNumSteps")),
        }
        _emit(
            signal="logs",
            label="pre-invocation",
            payload=_log_payload(
                timestamp_ns=now_ns,
                resource=resource,
                event_name="antigravity.invocation.started",
                severity="INFO",
                attributes=attributes,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )

    elif event == "PostInvocation":
        invocation_num = _safe_int(payload.get("invocationNum"))
        start_ns = _safe_int(invocations.pop(str(invocation_num), now_ns), now_ns)
        duration_ms = max(0, (now_ns - start_ns) // 1_000_000)
        trace_id, span_id = _deterministic_ids(
            session_key, f"invocation:{invocation_num}:{start_ns}"
        )
        attributes = {
            **base_attributes,
            "gen_ai.operation.name": "agent_invocation",
            "ai_context.operation.type": "model_invocation",
            "ai_context.workflow.stage": "post_invocation",
            "ai_context.state": "completed",
            "ai_context.outcome": "success",
            "duration_ms": duration_ms,
            "success": True,
            "antigravity.invocation.number": invocation_num,
            "antigravity.initial_steps": _safe_int(payload.get("initialNumSteps")),
        }
        _emit(
            signal="traces",
            label="invocation",
            payload=_trace_payload(
                resource=resource,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                name="antigravity.agent.invocation",
                start_ns=start_ns,
                end_ns=now_ns,
                attributes=attributes,
                success=True,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )
        _emit(
            signal="logs",
            label="post-invocation",
            payload=_log_payload(
                timestamp_ns=now_ns,
                resource=resource,
                event_name="antigravity.invocation.completed",
                severity="INFO",
                attributes=attributes,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )

    elif event == "PostToolUse":
        # The raw error is used only as a boolean outcome and is never serialized.
        failed = bool(str(payload.get("error") or "").strip())
        tool_category = _tool_category(args.operation)
        attributes = {
            **base_attributes,
            "ai_context.operation.type": "tool_use",
            "ai_context.workflow.stage": "post_tool_use",
            "ai_context.tool.category": tool_category,
            "ai_context.state": "completed",
            "ai_context.outcome": "error" if failed else "success",
            "ai_context.error.category": "tool_error" if failed else "none",
            "success": not failed,
            "antigravity.tool.category": tool_category,
            "antigravity.step.index": _safe_int(payload.get("stepIdx")),
        }
        _emit(
            signal="logs",
            label="post-tool-use",
            payload=_log_payload(
                timestamp_ns=now_ns,
                resource=resource,
                event_name="antigravity.tool.completed",
                severity="ERROR" if failed else "INFO",
                attributes=attributes,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )

    elif event == "Stop":
        start_ns = _safe_int(state.get("first_seen_ns"), now_ns)
        reason = _safe_text(payload.get("terminationReason"), fallback="unknown")
        failed = reason == "error" or bool(str(payload.get("error") or "").strip())
        duration_ms = max(0, (now_ns - start_ns) // 1_000_000)
        execution_num = _safe_int(payload.get("executionNum"))
        trace_id, span_id = _deterministic_ids(
            session_key, f"execution:{execution_num}:{start_ns}"
        )
        attributes = {
            **base_attributes,
            "ai_context.operation.type": "agent_execution",
            "ai_context.workflow.stage": "stop",
            "ai_context.state": "idle" if payload.get("fullyIdle") else "background_active",
            "ai_context.outcome": reason,
            "ai_context.error.category": "system_error" if failed else "none",
            "duration_ms": duration_ms,
            "success": not failed,
            "antigravity.execution.number": execution_num,
            "antigravity.fully_idle": bool(payload.get("fullyIdle")),
        }
        _emit(
            signal="traces",
            label="execution",
            payload=_trace_payload(
                resource=resource,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                name="antigravity.agent.execution",
                start_ns=start_ns,
                end_ns=now_ns,
                attributes=attributes,
                success=not failed,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )
        _emit(
            signal="logs",
            label="stop",
            payload=_log_payload(
                timestamp_ns=now_ns,
                resource=resource,
                event_name="antigravity.execution.stopped",
                severity="ERROR" if failed else "INFO",
                attributes=attributes,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )
        state.pop("first_seen_ns", None)
        state["invocations"] = {}

    _save_state(state_path, state)
    print(json.dumps(_hook_response(event), separators=(",", ":")))
    return 0


def _statusline_text(payload: dict[str, Any]) -> str:
    model = _model_from_payload(payload)
    state = _safe_text(payload.get("agent_state"), fallback="unknown")
    context = payload.get("context_window") if isinstance(payload.get("context_window"), dict) else {}
    used = _safe_float(context.get("used_percentage"), 0.0)
    total_input = _safe_int(context.get("total_input_tokens"))
    total_output = _safe_int(context.get("total_output_tokens"))
    text = f"AGY {model} | {state} | ctx {used:.1f}% | in {total_input} out {total_output}"
    width = _safe_int(payload.get("terminal_width"), 0)
    if width > 8 and len(text) >= width:
        text = text[: max(1, width - 2)] + "…"
    return text


def handle_statusline(args: argparse.Namespace) -> int:
    payload = _read_stdin_json()
    now_ns = _now_ns()
    conversation_id, product, version, session_id, state_path, state = _common_context(
        payload, args
    )
    model = _model_from_payload(payload)
    agent_state = _safe_text(payload.get("agent_state"), fallback="unknown")
    execution_mode = _safe_text(payload.get("execution_mode"), fallback="unknown")
    context = payload.get("context_window") if isinstance(payload.get("context_window"), dict) else {}
    current = context.get("current_usage") if isinstance(context.get("current_usage"), dict) else {}
    total_input = max(0, _safe_int(context.get("total_input_tokens")))
    total_output = max(0, _safe_int(context.get("total_output_tokens")))
    used_percentage = min(100.0, max(0.0, _safe_float(context.get("used_percentage"))))
    current_values = {
        "input": max(0, _safe_int(current.get("input_tokens"))),
        "output": max(0, _safe_int(current.get("output_tokens"))),
        "cache_creation": max(0, _safe_int(current.get("cache_creation_input_tokens"))),
        "cache_read": max(0, _safe_int(current.get("cache_read_input_tokens"))),
    }
    task_count = max(0, _safe_int(payload.get("task_count")))
    artifact_count = max(0, _safe_int(payload.get("artifact_count")))
    exceeds_200k = bool(payload.get("exceeds_200k_tokens"))
    quota = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}

    safe_snapshot = {
        "model": model,
        "agent_state": agent_state,
        "execution_mode": execution_mode,
        "total_input": total_input,
        "total_output": total_output,
        "used_percentage": round(used_percentage, 4),
        "current": current_values,
        "task_count": task_count,
        "artifact_count": artifact_count,
        "exceeds_200k_tokens": exceeds_200k,
        "pending_input_count": max(0, _safe_int(payload.get("pending_input_count"))),
        "tool_confirmation_pending": bool(payload.get("tool_confirmation_pending")),
        "quota": {
            _safe_text(name): round(_safe_float(value.get("remaining_fraction")), 6)
            for name, value in quota.items()
            if isinstance(value, dict) and value.get("remaining_fraction") is not None
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(safe_snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    last_fingerprint = str(state.get("status_fingerprint") or "")
    last_emit_ns = _safe_int(state.get("status_emit_ns"), 0)
    heartbeat_ns = int(max(1.0, args.heartbeat_seconds) * 1_000_000_000)
    should_emit = fingerprint != last_fingerprint or now_ns - last_emit_ns >= heartbeat_ns

    state.update(
        {
            "first_seen_ns": _safe_int(state.get("first_seen_ns"), now_ns),
            "version": version,
            "product": product,
            "model": model,
            "status_fingerprint": fingerprint,
        }
    )

    if should_emit:
        resource = _resource_attributes(
            product=product,
            version=version,
            profile=args.profile,
            model=model,
            session_id=session_id,
            phoenix=args.phoenix,
        )
        log_attributes: dict[str, Any] = {
            "gen_ai.provider.name": "google",
            "gen_ai.request.model": model,
            "gen_ai.usage.input_tokens": total_input,
            "gen_ai.usage.output_tokens": total_output,
            "gen_ai.usage.cached_input_tokens": current_values["cache_read"],
            "ai_context.operation.type": "status_update",
            "ai_context.workflow.stage": execution_mode,
            "ai_context.state": agent_state,
            "ai_context.tool.category": "coding-agent",
            "ai_context.model.family": model,
            "ai_context.evidence.class": "antigravity-statusline",
        }
        _emit(
            signal="logs",
            label="statusline",
            payload=_log_payload(
                timestamp_ns=now_ns,
                resource=resource,
                event_name="antigravity.status.changed",
                severity="INFO",
                attributes=log_attributes,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )

        common_metric_attributes = {
            "tool": "antigravity",
            "model_family": model,
        }
        metrics: list[dict[str, Any]] = [
            _gauge_metric(
                "antigravity_session_tokens",
                "{token}",
                now_ns,
                [
                    (total_input, {**common_metric_attributes, "token_type": "input"}),
                    (total_output, {**common_metric_attributes, "token_type": "output"}),
                ],
            ),
            _gauge_metric(
                "antigravity_context_tokens",
                "{token}",
                now_ns,
                [
                    (value, {**common_metric_attributes, "token_type": token_type})
                    for token_type, value in current_values.items()
                ],
            ),
            _gauge_metric(
                "antigravity_context_used_ratio",
                "1",
                now_ns,
                [(used_percentage / 100.0, common_metric_attributes)],
            ),
            _gauge_metric(
                "antigravity_background_task_count",
                "{task}",
                now_ns,
                [
                    (
                        task_count,
                        {**common_metric_attributes, "state": agent_state},
                    )
                ],
            ),
            _gauge_metric(
                "antigravity_artifact_count",
                "{artifact}",
                now_ns,
                [(artifact_count, common_metric_attributes)],
            ),
            _gauge_metric(
                "antigravity_context_exceeds_200k",
                "1",
                now_ns,
                [(1 if exceeds_200k else 0, common_metric_attributes)],
            ),
            _gauge_metric(
                "antigravity_pending_input_count",
                "{message}",
                now_ns,
                [
                    (
                        safe_snapshot["pending_input_count"],
                        common_metric_attributes,
                    )
                ],
            ),
            _gauge_metric(
                "antigravity_tool_confirmation_pending",
                "1",
                now_ns,
                [
                    (
                        1 if safe_snapshot["tool_confirmation_pending"] else 0,
                        common_metric_attributes,
                    )
                ],
            ),
        ]
        quota_points = [
            (
                max(0.0, min(1.0, remaining)),
                {**common_metric_attributes, "type": quota_name},
            )
            for quota_name, remaining in safe_snapshot["quota"].items()
        ]
        if quota_points:
            metrics.append(
                _gauge_metric(
                    "antigravity_quota_remaining_ratio",
                    "1",
                    now_ns,
                    quota_points,
                )
            )
        _emit(
            signal="metrics",
            label="statusline",
            payload=_metrics_payload(
                timestamp_ns=now_ns,
                resource=resource,
                metrics=metrics,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )
        state["status_emit_ns"] = now_ns

    _save_state(state_path, state)
    print(_statusline_text(payload))
    return 0


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--endpoint",
        default=os.getenv("AI_OBSERVABILITY_OTLP_HTTP_ENDPOINT", DEFAULT_ENDPOINT),
        help="Base OTLP/HTTP endpoint; /v1/<signal> is appended automatically.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("AI_OBSERVABILITY_PROFILE", DEFAULT_PROFILE),
        help="Telemetry environment profile recorded before Collector normalization.",
    )
    parser.add_argument(
        "--product",
        default=os.getenv("AI_OBSERVABILITY_PRODUCT", "auto"),
        help="Bounded product name. 'auto' uses the documented status-line product field; hooks fall back to antigravity.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("AI_OBSERVABILITY_HTTP_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        help="Local OTLP HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--state-dir",
        default=str(_default_state_dir()),
        help="Local state directory. Raw prompts and paths are never stored.",
    )
    parser.add_argument(
        "--session-salt",
        default=os.getenv("AI_OBSERVABILITY_SESSION_SALT", ""),
        help="Optional HMAC salt for a stable pseudonymous session identifier.",
    )
    parser.add_argument(
        "--include-session-hash",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include a pseudonymous session ID. Defaults off for corporate profiles.",
    )
    parser.add_argument(
        "--phoenix",
        action=argparse.BooleanOptionalAction,
        default=_bool_env("AI_OBSERVABILITY_PHOENIX", False),
        help="Opt curated spans into the evaluation-mode Phoenix route.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=_bool_env("AI_OBSERVABILITY_DRY_RUN", False),
        help="Do not send network requests.",
    )
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=(
            Path(os.environ["AI_OBSERVABILITY_CAPTURE_DIR"])
            if os.getenv("AI_OBSERVABILITY_CAPTURE_DIR")
            else None
        ),
        help="Write sanitized OTLP payloads to this directory for inspection/tests.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=_bool_env("AI_OBSERVABILITY_DEBUG", False),
        help="Write exporter failure categories to stderr. Never writes payload content.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    hook = subparsers.add_parser("hook", help="Handle one Antigravity lifecycle hook.")
    hook.add_argument(
        "event",
        choices=["PreInvocation", "PostInvocation", "PostToolUse", "Stop"],
    )
    hook.add_argument(
        "--operation",
        choices=sorted(TOOL_CATEGORIES),
        default="other-tool",
        help="Low-cardinality tool category supplied by the PostToolUse matcher.",
    )
    _add_common_arguments(hook)
    hook.set_defaults(handler=handle_hook)

    statusline = subparsers.add_parser(
        "statusline", help="Render the CLI status line and export safe usage metadata."
    )
    _add_common_arguments(statusline)
    statusline.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=float(
            os.getenv(
                "AI_OBSERVABILITY_STATUS_HEARTBEAT_SECONDS",
                DEFAULT_HEARTBEAT_SECONDS,
            )
        ),
        help="Re-emit unchanged safe status metadata at this interval.",
    )
    statusline.set_defaults(handler=handle_statusline)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:  # Hook/status-line extensions must not block agent execution.
        if getattr(args, "debug", False):
            print(f"Antigravity observability extension failed: {type(exc).__name__}", file=sys.stderr)
        if args.command == "statusline":
            print("AGY telemetry unavailable")
        else:
            print(json.dumps(_hook_response(getattr(args, "event", ""))))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
