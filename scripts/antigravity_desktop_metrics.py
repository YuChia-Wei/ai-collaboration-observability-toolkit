"""Pure OTLP contract for bounded desktop metadata, without local reads or I/O.

Generation totals describe deduplicated metadata accepted since the caller's
persistent ledger started. Thinking and response output are subsets of total
output and must never be added to it. Context values are observations of the
last persisted, verified generation snapshot, not the UI active conversation.
Their point timestamp is the read time. The native generation source time is
reported separately, so an idle conversation does not imply a failed producer.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


SOURCE = "desktop-local-metadata"
VERSION = "0.1.0"
PROFILES = frozenset({"personal-local", "corporate-local-redacted"})
TOKEN_TYPES = frozenset({
    "uncached_input_tokens", "total_output_tokens", "cache_write_input_tokens",
    "cache_read_input_tokens", "thinking_output_tokens", "response_output_tokens",
})
METRIC_NAMES = frozenset({
    "antigravity_desktop_generation_observed_tokens_total",
    "antigravity_desktop_generation_records_total",
    "antigravity_desktop_generation_read_limited",
    "antigravity_desktop_generation_latest_source_timestamp_seconds",
    "antigravity_desktop_read_success",
    "antigravity_desktop_read_timestamp_seconds",
    "antigravity_desktop_latest_generation_verified",
    "antigravity_desktop_latest_context_available",
    "antigravity_desktop_latest_context_source_timestamp_seconds",
    "antigravity_desktop_latest_context_estimated_tokens",
    "antigravity_desktop_latest_context_capacity_tokens",
    "antigravity_desktop_latest_context_used_ratio",
})
MAX_INTEGER = (1 << 53) - 1
_NAMESPACE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)


class DesktopMetricsError(ValueError):
    """Fixed diagnostic codes only; never echo metadata or local identifiers."""


def _datetime(value: Any) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        parsed = parsed.astimezone(timezone.utc)
        if not math.isfinite(parsed.timestamp()) or parsed.timestamp() <= 0:
            raise ValueError
        return parsed
    except (AttributeError, TypeError, ValueError, OverflowError, OSError):
        raise DesktopMetricsError("invalid_timestamp") from None


def _number(value: Any, *, positive: bool = False) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        return None
    return number


def _integer(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_INTEGER


def _time_ns(value: datetime) -> int:
    return int(value.timestamp()) * 1_000_000_000 + value.microsecond * 1_000


def _attributes(extra: dict[str, str] | None = None) -> list[dict[str, Any]]:
    values = {"tool": "antigravity", "source": SOURCE, "evidence_class": "observed", **(extra or {})}
    return [{"key": key, "value": {"stringValue": value}} for key, value in values.items()]


def _point(value: float | int, timestamp_ns: int, attributes: dict[str, str] | None = None) -> dict[str, Any]:
    return {"timeUnixNano": str(timestamp_ns), "asDouble": float(value), "attributes": _attributes(attributes)}


def _gauge(name: str, unit: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "unit": unit, "gauge": {"dataPoints": points}}


def _counter(name: str, unit: str, points: list[dict[str, Any]], start_ns: int) -> dict[str, Any]:
    for point in points:
        point["startTimeUnixNano"] = str(start_ns)
    return {"name": name, "unit": unit, "sum": {
        "aggregationTemporality": 2, "isMonotonic": True, "dataPoints": points,
    }}


def build_metrics_payload(
    *, observed_at: datetime | str, tokens: dict[str, Any], context: dict[str, Any],
    service_namespace: str = "ai-collaboration", profile: str = "personal-local",
) -> dict[str, Any]:
    """Build telemetry from a private ledger and a verified latest observed generation.

    ``tokens`` has read_success, optional ledger_start_at/totals/generation_count,
    read_limited, and optional latest_source_timestamp_seconds. Totals contain
    only genuinely observed TOKEN_TYPES; the caller owns durable deduplication.
    A failed read never republishes persisted totals or generation counters;
    read-health, read-time and available diagnostic metadata remain exportable.

    ``context`` has read_success, generation_verified, is_latest_generation, and
    optional source_timestamp_seconds/estimated_tokens_used/max_context_tokens.
    Only known source values for the verified latest observed generation are sent.
    A historical generation can be a valid latest-known snapshot. Values use
    the observation timestamp, while source_timestamp_seconds retains the
    native generation time independently; producer freshness uses read time.
    Availability is explicit for estimate/capacity/ratio, so omitted fields do
    not revive retained gauges, even within the same source generation.
    """
    observed = _datetime(observed_at)
    poll_ns = _time_ns(observed)
    if not isinstance(tokens, dict) or not isinstance(context, dict):
        raise DesktopMetricsError("invalid_snapshot")
    if not isinstance(service_namespace, str) or not _NAMESPACE.fullmatch(service_namespace):
        raise DesktopMetricsError("invalid_service_namespace")
    if not isinstance(profile, str) or profile not in PROFILES:
        raise DesktopMetricsError("invalid_profile")

    metrics: list[dict[str, Any]] = []
    components = (("tokens", tokens), ("context", context))
    metrics.append(_gauge("antigravity_desktop_read_success", "1", [
        _point(int(report.get("read_success") is True), poll_ns, {"component": component})
        for component, report in components
    ]))
    metrics.append(_gauge("antigravity_desktop_read_timestamp_seconds", "s", [
        _point(observed.timestamp(), poll_ns, {"component": component})
        for component, _report in components
    ]))

    if tokens.get("read_success") is True and ("totals" in tokens or "generation_count" in tokens):
        start = _datetime(tokens.get("ledger_start_at"))
        if start > observed:
            raise DesktopMetricsError("invalid_ledger_timestamp")
        totals = tokens.get("totals", {})
        if not isinstance(totals, dict) or set(totals) - TOKEN_TYPES or any(not _integer(value) for value in totals.values()):
            raise DesktopMetricsError("invalid_token_totals")
        if totals:
            metrics.append(_counter("antigravity_desktop_generation_observed_tokens_total", "{token}", [
                _point(value, poll_ns, {"token_type": token_type})
                for token_type, value in sorted(totals.items())
            ], _time_ns(start)))
        if "generation_count" in tokens:
            if not _integer(tokens["generation_count"]):
                raise DesktopMetricsError("invalid_generation_count")
            metrics.append(_counter("antigravity_desktop_generation_records_total", "{record}", [
                _point(tokens["generation_count"], poll_ns),
            ], _time_ns(start)))
    if type(tokens.get("read_limited")) is bool:
        metrics.append(_gauge("antigravity_desktop_generation_read_limited", "1", [
            _point(int(tokens["read_limited"]), poll_ns),
        ]))
    latest = _number(tokens.get("latest_source_timestamp_seconds"), positive=True)
    if latest is not None and latest <= observed.timestamp():
        metrics.append(_gauge("antigravity_desktop_generation_latest_source_timestamp_seconds", "s", [
            _point(latest, poll_ns),
        ]))

    selected = context.get("read_success") is True and context.get("generation_verified") is True
    metrics.append(_gauge("antigravity_desktop_latest_generation_verified", "1", [_point(int(selected), poll_ns)]))
    source_time = _number(context.get("source_timestamp_seconds"), positive=True)
    valid_source = source_time is not None and source_time <= observed.timestamp()
    if selected and valid_source:
        metrics.append(_gauge("antigravity_desktop_latest_context_source_timestamp_seconds", "s", [
            _point(source_time, poll_ns),
        ]))
    snapshot_verified = (selected and valid_source
                         and context.get("is_latest_generation") is True)
    estimate = context.get("estimated_tokens_used")
    capacity = context.get("max_context_tokens")
    estimate_available = snapshot_verified and _integer(estimate)
    capacity_available = estimate_available and _integer(capacity) and capacity > 0
    ratio_available = capacity_available and estimate <= capacity
    availability = {
        "estimate": estimate_available, "capacity": capacity_available, "ratio": ratio_available,
    }
    metrics.append(_gauge("antigravity_desktop_latest_context_available", "1", [
        _point(int(available), poll_ns, {"component": component})
        for component, available in availability.items()
    ]))
    if estimate_available:
        metrics.append(_gauge("antigravity_desktop_latest_context_estimated_tokens", "{token}", [_point(estimate, poll_ns)]))
        if capacity_available:
            metrics.append(_gauge("antigravity_desktop_latest_context_capacity_tokens", "{token}", [_point(capacity, poll_ns)]))
        if ratio_available:
            metrics.append(_gauge("antigravity_desktop_latest_context_used_ratio", "1", [_point(estimate / capacity, poll_ns)]))

    resource = {
        "service.name": "antigravity-desktop-metadata", "service.namespace": service_namespace,
        "service.version": VERSION, "deployment.environment.name": profile,
        "ai_observability.profile": profile, "ai_agent.provider": "google",
        "ai_agent.product": "antigravity", "ai_agent.surface": "desktop",
        "ai_context.environment.profile": profile,
    }
    return {"resourceMetrics": [{
        "resource": {"attributes": [{"key": key, "value": {"stringValue": value}} for key, value in resource.items()]},
        "scopeMetrics": [{"scope": {"name": "ai-collaboration-observability.antigravity-desktop", "version": VERSION}, "metrics": metrics}],
    }]}
