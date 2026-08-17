#!/usr/bin/env python3
"""Privacy-first Codex lifecycle Hook exporter for local OTLP/HTTP.

The default ``metadata-only`` mode reads only the documented lifecycle metadata
needed to correlate a turn and its tool calls. The explicit ``size-only`` mode
may read a submitted user prompt in memory solely to calculate its UTF-8 byte
length. It never stores prompt text, assistant messages, tool input/output,
transcripts, or working-directory paths.

Only OpenInference AGENT and TOOL spans are produced. Codex Hooks do not expose
the model-call boundary or token accounting needed for a truthful LLM span.
"""
from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_CAPTURE_MODE = "metadata-only"
SCOPE_NAME = "ai-collaboration-observability.codex-hooks-example"
SCOPE_VERSION = "0.1.0"
CAPTURE_MODES = ("metadata-only", "size-only")
PROMPT_SIZE_BUCKETS = (256, 1024, 4096, 16384, 65536, 262144)
SUPPORTED_EVENTS = {
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
}
SAFE_TEXT = re.compile(r"[^A-Za-z0-9_.:/+\-]", re.ASCII)
HEX_16 = re.compile(r"^[0-9a-f]{16}$")
HEX_32 = re.compile(r"^[0-9a-f]{32}$")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_capture_mode() -> str:
    value = os.getenv("AI_OBSERVABILITY_CAPTURE_MODE", DEFAULT_CAPTURE_MODE)
    return value if value in CAPTURE_MODES else DEFAULT_CAPTURE_MODE


def _safe_text(value: Any, *, fallback: str = "unknown", limit: int = 80) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    return SAFE_TEXT.sub("_", text)[:limit]


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_stdin_json() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _event_name(payload: dict[str, Any]) -> str:
    event = str(payload.get("hook_event_name") or "")
    return event if event in SUPPORTED_EVENTS else ""


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def _default_state_dir() -> Path:
    explicit = os.getenv("AI_OBSERVABILITY_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return root / "ai-collaboration-observability" / "codex-hooks"
    root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "ai-collaboration-observability" / "codex-hooks"


def _session_dir(state_root: Path, session_id: str) -> Path:
    return state_root / _hash_identifier(session_id)


def _state_path(session_dir: Path, kind: str, identifier: str) -> Path:
    return session_dir / f"{kind}-{_hash_identifier(identifier)}.json"


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
        json.dump(value, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _delete_state(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _clean_finished_tools(session_dir: Path) -> None:
    if not session_dir.is_dir():
        return
    for path in session_dir.glob("tool-*.json"):
        _delete_state(path)
    try:
        session_dir.rmdir()
    except OSError:
        pass


def _random_trace_id() -> str:
    return secrets.token_hex(16)


def _random_span_id() -> str:
    return secrets.token_hex(8)


def _valid_trace_id(value: Any) -> str | None:
    text = str(value or "")
    return text if HEX_32.fullmatch(text) else None


def _valid_span_id(value: Any) -> str | None:
    text = str(value or "")
    return text if HEX_16.fullmatch(text) else None


def _otlp_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    return {"stringValue": _safe_text(value)}


def _otlp_attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"key": key, "value": _otlp_value(value)}
        for key, value in values.items()
        if value is not None
    ]


def _resource_attributes(profile: str) -> dict[str, Any]:
    return {
        "service.name": "codex-hooks",
        "service.namespace": "ai-collaboration",
        "service.version": SCOPE_VERSION,
        "deployment.environment.name": _safe_text(profile),
        "ai_observability.profile": _safe_text(profile),
        "ai_agent.provider": "openai",
        "ai_agent.product": "codex",
        "ai_agent.surface": "hooks",
    }


def _trace_payload(
    *,
    profile: str,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    name: str,
    start_ns: int,
    end_ns: int,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(max(end_ns, start_ns + 1)),
        "attributes": _otlp_attributes(attributes),
        # Hooks establish lifecycle completion, not model/tool success.
        "status": {"code": 0},
    }
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _otlp_attributes(_resource_attributes(profile))},
                "scopeSpans": [
                    {
                        "scope": {"name": SCOPE_NAME, "version": SCOPE_VERSION},
                        "spans": [span],
                    }
                ],
            }
        ]
    }


def _prompt_size_bucket_counts(byte_count: int) -> list[str]:
    for index, bound in enumerate(PROMPT_SIZE_BUCKETS):
        if byte_count <= bound:
            return ["1" if position == index else "0" for position in range(len(PROMPT_SIZE_BUCKETS) + 1)]
    return ["0"] * len(PROMPT_SIZE_BUCKETS) + ["1"]


def _prompt_size_metric_payload(
    *,
    profile: str,
    timestamp_ns: int,
    byte_count: int,
) -> dict[str, Any]:
    """Build the opt-in metric without retaining the source prompt.

    The histogram is Delta so Prometheus can expose range-safe _sum and _count
    series. Its labels are fixed reviewed dimensions; no correlation or content
    identifier is emitted.
    """
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": _otlp_attributes(_resource_attributes(profile))},
                "scopeMetrics": [
                    {
                        "scope": {"name": SCOPE_NAME, "version": SCOPE_VERSION},
                        "metrics": [
                            {
                                "name": "ai_agent.observed.user_prompt.bytes",
                                "description": "Opt-in UTF-8 byte length of a Codex user prompt.",
                                "unit": "By",
                                "histogram": {
                                    "aggregationTemporality": 1,
                                    "dataPoints": [
                                        {
                                            "startTimeUnixNano": str(timestamp_ns),
                                            "timeUnixNano": str(timestamp_ns),
                                            "attributes": _otlp_attributes(
                                                {
                                                    "operation": "turn",
                                                    "evidence_class": "observed",
                                                    "content_scope": "user_prompt",
                                                    "measurement_method": "utf8_bytes",
                                                }
                                            ),
                                            "count": "1",
                                            "sum": byte_count,
                                            "bucketCounts": _prompt_size_bucket_counts(byte_count),
                                            "explicitBounds": list(PROMPT_SIZE_BUCKETS),
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _base_endpoint(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OTLP HTTP endpoint must be an http(s) URL")
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Codex Hook telemetry endpoint must be loopback")
    path = parsed.path.rstrip("/")
    for signal in ("traces", "metrics", "logs"):
        suffix = f"/v1/{signal}"
        if path.endswith(suffix):
            path = path[: -len(suffix)]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _capture_payload(
    capture_dir: Path, signal: str, label: str, payload: dict[str, Any]
) -> None:
    capture_dir.mkdir(parents=True, exist_ok=True)
    path = capture_dir / f"{time.time_ns()}-{signal}-{label}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _emit_trace(
    *,
    label: str,
    payload: dict[str, Any],
    endpoint: str,
    timeout: float,
    phoenix: bool | None,
    dry_run: bool,
    capture_dir: Path | None,
    debug: bool,
) -> None:
    if capture_dir:
        _capture_payload(capture_dir, "traces", label, payload)
    if dry_run:
        return
    headers = {"Content-Type": "application/json"}
    if phoenix is not None:
        headers["x-ai-observability-phoenix"] = "true" if phoenix else "false"
    try:
        request = urllib.request.Request(
            f"{_base_endpoint(endpoint)}/v1/traces",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=max(0.05, timeout)) as response:
            response.read(1024)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        if debug:
            print(f"Codex Hooks OTLP export skipped: {type(exc).__name__}", file=sys.stderr)


def _emit_metric(
    *,
    label: str,
    payload: dict[str, Any],
    endpoint: str,
    timeout: float,
    dry_run: bool,
    capture_dir: Path | None,
    debug: bool,
) -> None:
    if capture_dir:
        _capture_payload(capture_dir, "metrics", label, payload)
    if dry_run:
        return
    try:
        request = urllib.request.Request(
            f"{_base_endpoint(endpoint)}/v1/metrics",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=max(0.05, timeout)) as response:
            response.read(1024)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        if debug:
            print(
                f"Codex Hooks OTLP metric export skipped: {type(exc).__name__}",
                file=sys.stderr,
            )


def _tool_category(value: Any) -> str:
    name = str(value or "")
    if name == "Bash":
        return "execution"
    if name == "apply_patch":
        return "editor"
    if name in {"Agent", "spawn_agent", "send_message", "wait_agent"}:
        return "agent-collaboration"
    if name.startswith("mcp__"):
        return "connector"
    return "other"


def _model(payload: dict[str, Any], fallback: Any = None) -> str:
    return _safe_text(payload.get("model") or fallback, fallback="unknown")


def _base_span_attributes(model: str) -> dict[str, Any]:
    return {
        "gen_ai.provider.name": "openai",
        "gen_ai.request.model": model,
        "ai_agent.evidence.class": "observed",
        "ai_agent.coverage": "partial",
    }


def _turn_state(payload: dict[str, Any], state_root: Path) -> tuple[Path, Path]:
    session_id = str(payload.get("session_id") or "unknown-session")
    turn_id = str(payload.get("turn_id") or "unknown-turn")
    session = _session_dir(state_root, session_id)
    return session, _state_path(session, "turn", turn_id)


def _size_only_enabled(args: argparse.Namespace) -> bool:
    # Corporate mode stays fail-closed even when a hook command is misconfigured.
    profile = _safe_text(getattr(args, "profile", DEFAULT_PROFILE), fallback=DEFAULT_PROFILE)
    return (
        getattr(args, "capture_mode", DEFAULT_CAPTURE_MODE) == "size-only"
        and not profile.lower().startswith("corporate")
    )


def _utf8_byte_count(value: str) -> int:
    return len(value.encode("utf-8", errors="surrogatepass"))


def _handle_event(payload: dict[str, Any], args: argparse.Namespace) -> None:
    event = _event_name(payload)
    if not event:
        return

    now_ns = time.time_ns()
    state_root = Path(args.state_dir).expanduser()
    session, turn_path = _turn_state(payload, state_root)

    if event == "UserPromptSubmit":
        _save_state(
            turn_path,
            {
                "trace_id": _random_trace_id(),
                "span_id": _random_span_id(),
                "start_ns": now_ns,
                "model": _model(payload),
            },
        )
        if _size_only_enabled(args):
            # Do not access this field unless the user explicitly selected the
            # limited measurement mode. The string remains local and ephemeral.
            prompt = payload.get("prompt")
            if isinstance(prompt, str):
                _emit_metric(
                    label="user-prompt-bytes",
                    payload=_prompt_size_metric_payload(
                        profile=args.profile,
                        timestamp_ns=now_ns,
                        byte_count=_utf8_byte_count(prompt),
                    ),
                    endpoint=args.endpoint,
                    timeout=args.timeout,
                    dry_run=args.dry_run,
                    capture_dir=args.capture_dir,
                    debug=args.debug,
                )
        return

    turn = _load_state(turn_path)
    trace_id = _valid_trace_id(turn.get("trace_id")) or _random_trace_id()
    parent_span_id = _valid_span_id(turn.get("span_id"))
    model = _model(payload, turn.get("model"))

    if event == "PreToolUse":
        tool_use_id = str(payload.get("tool_use_id") or "unknown-tool")
        tool_path = _state_path(session, "tool", tool_use_id)
        _save_state(
            tool_path,
            {
                "trace_id": trace_id,
                "span_id": _random_span_id(),
                "parent_span_id": parent_span_id,
                "start_ns": now_ns,
                "model": model,
                "category": _tool_category(payload.get("tool_name")),
            },
        )
        return

    if event == "PostToolUse":
        tool_use_id = str(payload.get("tool_use_id") or "unknown-tool")
        tool_path = _state_path(session, "tool", tool_use_id)
        tool = _load_state(tool_path)
        tool_trace_id = _valid_trace_id(tool.get("trace_id")) or trace_id
        tool_span_id = _valid_span_id(tool.get("span_id")) or _random_span_id()
        tool_parent_id = _valid_span_id(tool.get("parent_span_id")) or parent_span_id
        start_ns = _safe_int(tool.get("start_ns"), now_ns - 1)
        category = _safe_text(
            tool.get("category"),
            fallback=_tool_category(payload.get("tool_name")),
            limit=32,
        )
        attributes = {
            **_base_span_attributes(_model(payload, tool.get("model") or model)),
            "openinference.span.kind": "TOOL",
            "tool.name": category,
            "ai_agent.operation": "tool",
            "ai_agent.tool.category": category,
            "ai_agent.lifecycle.state": "completed",
        }
        _emit_trace(
            label="tool",
            payload=_trace_payload(
                profile=args.profile,
                trace_id=tool_trace_id,
                span_id=tool_span_id,
                parent_span_id=tool_parent_id,
                name=f"codex.tool.{category}",
                start_ns=start_ns,
                end_ns=now_ns,
                attributes=attributes,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            phoenix=args.phoenix,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )
        _delete_state(tool_path)
        return

    if event == "Stop":
        span_id = parent_span_id or _random_span_id()
        start_ns = _safe_int(turn.get("start_ns"), now_ns - 1)
        attributes = {
            **_base_span_attributes(model),
            "openinference.span.kind": "AGENT",
            "agent.name": "codex",
            "ai_agent.operation": "turn",
            "ai_agent.lifecycle.state": "completed",
        }
        _emit_trace(
            label="turn",
            payload=_trace_payload(
                profile=args.profile,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                name="codex.agent.turn",
                start_ns=start_ns,
                end_ns=now_ns,
                attributes=attributes,
            ),
            endpoint=args.endpoint,
            timeout=args.timeout,
            phoenix=args.phoenix,
            dry_run=args.dry_run,
            capture_dir=args.capture_dir,
            debug=args.debug,
        )
        _delete_state(turn_path)
        _clean_finished_tools(session)


def _hook_response(event: str) -> None:
    # Stop requires JSON stdout on successful exit. Other events should stay silent
    # so they do not inject developer context or tool feedback.
    if event == "Stop":
        print("{}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default=os.getenv("AI_OBSERVABILITY_OTLP_HTTP_ENDPOINT", DEFAULT_ENDPOINT),
        help="Loopback Collector OTLP/HTTP base endpoint.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("AI_OBSERVABILITY_PROFILE", DEFAULT_PROFILE),
        help="Bounded environment profile recorded on the resource.",
    )
    parser.add_argument(
        "--capture-mode",
        choices=CAPTURE_MODES,
        default=_default_capture_mode(),
        help=(
            "metadata-only never reads prompt content; size-only exports only its "
            "UTF-8 byte count outside Corporate profiles."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(
            os.getenv("AI_OBSERVABILITY_HTTP_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        ),
        help="Local OTLP request timeout in seconds.",
    )
    parser.add_argument(
        "--state-dir",
        default=str(_default_state_dir()),
        help="Local metadata-only correlation state directory.",
    )
    parser.add_argument(
        "--phoenix",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Explicitly include or exclude compatible traces from Evaluation Phoenix.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=_bool_env("AI_OBSERVABILITY_DRY_RUN", False),
        help="Build state and optional captures without network requests.",
    )
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=(
            Path(os.environ["AI_OBSERVABILITY_CAPTURE_DIR"])
            if os.getenv("AI_OBSERVABILITY_CAPTURE_DIR")
            else None
        ),
        help="Write sanitized OTLP traces for inspection or tests.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=_bool_env("AI_OBSERVABILITY_DEBUG", False),
        help="Write exception classes only; payload content is never logged.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = _read_stdin_json()
    event = _event_name(payload)
    try:
        _handle_event(payload, args)
    except Exception as exc:  # Lifecycle telemetry must not alter Codex behavior.
        if args.debug:
            print(f"Codex Hooks observability failed: {type(exc).__name__}", file=sys.stderr)
    _hook_response(event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
