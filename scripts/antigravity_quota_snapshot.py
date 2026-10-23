"""Pure, privacy-safe normalization of the official Antigravity ``/usage`` report.

This module never invokes Antigravity, opens account stores, or sends telemetry.
The caller must compare the CLI and desktop accounts locally and explicitly mark
the normalized snapshot as matched before building an OTLP metrics payload.
Only known product quota categories and numeric measurements survive parsing.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

SOURCE = "official-cli-report"
SCOPE_NAME = "ai-collaboration-observability.antigravity-quota"
SCOPE_VERSION = "0.1.0"
SCHEMA_VERSION = 1

# These are product categories, never account- or conversation-derived labels.
QUOTA_GROUPS = {
    "Gemini Models": "gemini",
    "Claude and GPT models": "claude-gpt",
    "Gemini 4 Argon": "gemini-argon",
}
QUOTA_BUCKETS = {
    "gemini-weekly": ("gemini", "weekly"),
    "gemini-5h": ("gemini", "5h"),
    "3p-weekly": ("claude-gpt", "weekly"),
    "3p-5h": ("claude-gpt", "5h"),
    "gemini-argon-wtu-weekly": ("gemini-argon", "weekly"),
}
PROFILES = frozenset({"personal-local", "corporate-local-redacted"})
_NAMESPACE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)


class QuotaReportError(ValueError):
    """A fixed diagnostic code that cannot echo private report content."""


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _utc_datetime(value: Any) -> datetime:
    """Parse an explicit timestamp; a missing timezone is never guessed."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise QuotaReportError("invalid_timestamp") from None
    else:
        raise QuotaReportError("invalid_timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QuotaReportError("invalid_timestamp")
    try:
        parsed = parsed.astimezone(timezone.utc)
        seconds = parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        raise QuotaReportError("invalid_timestamp") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise QuotaReportError("invalid_timestamp")
    return parsed


def normalize_quota_report(report: Any, observed_at: datetime | str) -> dict[str, Any]:
    """Keep only allowlisted account quota measurements from a passive report.

    Invalid or unknown bucket measurements are omitted, never replaced with 0.
    The official report must be a successful, zero-turn ``usage`` command. This
    distinguishes a passive account snapshot from a model conversation response.
    Raw identity fields, usage counters, descriptions and bucket display names
    are deliberately ignored. Errors contain fixed codes only.
    """
    observed = _utc_datetime(observed_at)
    if not isinstance(report, dict):
        raise QuotaReportError("invalid_report")
    if report.get("status") != "SUCCESS":
        raise QuotaReportError("report_not_successful")
    turns = report.get("num_turns")
    if isinstance(turns, bool) or not isinstance(turns, int) or turns != 0:
        raise QuotaReportError("report_not_passive")
    command = report.get("command")
    if not isinstance(command, dict) or command.get("name") != "usage":
        raise QuotaReportError("unexpected_command")
    data = command.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        raise QuotaReportError("invalid_quota_groups")

    buckets: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    unknown = 0
    invalid = 0
    for group in data["groups"]:
        if not isinstance(group, dict) or not isinstance(group.get("buckets"), list):
            invalid += 1
            continue
        raw_name = group.get("name")
        quota_group = QUOTA_GROUPS.get(raw_name) if isinstance(raw_name, str) else None
        for raw_bucket in group["buckets"]:
            if not isinstance(raw_bucket, dict):
                invalid += 1
                continue
            bucket_id = raw_bucket.get("id")
            allowed = QUOTA_BUCKETS.get(bucket_id) if isinstance(bucket_id, str) else None
            if quota_group is None or allowed is None:
                unknown += 1
                continue
            if allowed != (quota_group, raw_bucket.get("window")):
                invalid += 1
                continue
            ratio = _finite_number(raw_bucket.get("remaining_fraction"))
            if ratio is None or not 0 <= ratio <= 1:
                invalid += 1
                continue
            key = (quota_group, bucket_id, allowed[1])
            if key in seen:
                raise QuotaReportError("duplicate_quota_bucket")
            seen.add(key)
            bucket: dict[str, Any] = {
                "quota_group": quota_group,
                "bucket": bucket_id,
                "window": allowed[1],
                "remaining_ratio": ratio,
            }
            try:
                reset = _utc_datetime(raw_bucket.get("reset_time"))
            except QuotaReportError:
                pass
            else:
                bucket["reset_at_unix_seconds"] = reset.timestamp()
            buckets.append(bucket)
    if not buckets:
        raise QuotaReportError("no_supported_quota_buckets")
    buckets.sort(key=lambda item: (item["quota_group"], item["bucket"], item["window"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "identity_status": "unverified",
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "observed_at_unix_seconds": observed.timestamp(),
        "buckets": buckets,
        "skipped_unknown_buckets": unknown,
        "skipped_invalid_buckets": invalid,
    }


def _attributes(values: dict[str, str]) -> list[dict[str, Any]]:
    return [{"key": key, "value": {"stringValue": value}} for key, value in values.items()]


def _gauge(name: str, unit: str, timestamp_ns: int, points: list[tuple[float, dict[str, str]]]) -> dict[str, Any]:
    return {
        "name": name,
        "unit": unit,
        "gauge": {
            "dataPoints": [
                {
                    "timeUnixNano": str(timestamp_ns),
                    "asDouble": value,
                    "attributes": _attributes(attributes),
                }
                for value, attributes in points
            ]
        },
    }


def _common_attributes() -> dict[str, str]:
    return {
        "tool": "antigravity",
        "source": SOURCE,
        "scope": "account",
        "evidence_class": "observed",
    }


def _resource_attributes(service_namespace: str, profile: str) -> dict[str, str]:
    if not isinstance(service_namespace, str) or not _NAMESPACE.fullmatch(service_namespace):
        raise QuotaReportError("invalid_service_namespace")
    if not isinstance(profile, str) or profile not in PROFILES:
        raise QuotaReportError("invalid_profile")
    return {
        "service.name": "antigravity-quota",
        "service.namespace": service_namespace,
        "service.version": SCOPE_VERSION,
        "deployment.environment.name": profile,
        "ai_observability.profile": profile,
        "ai_agent.provider": "google",
        "ai_agent.product": "antigravity",
        "ai_agent.surface": "account",
        "ai_context.environment.profile": profile,
        "ai_context.evidence.class": "observed",
    }


def _metrics_envelope(resource: dict[str, str], metrics: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceMetrics": [{
            "resource": {"attributes": _attributes(resource)},
            "scopeMetrics": [{"scope": {"name": SCOPE_NAME, "version": SCOPE_VERSION}, "metrics": metrics}],
        }]
    }


def build_identity_status_payload(
    matched: bool,
    observed_at: datetime | str,
    service_namespace: str = "ai-collaboration",
    profile: str = "personal-local",
) -> dict[str, Any]:
    """Update only the same-account gate without refreshing quota snapshots.

    Callers use False when identity matching fails or cannot be established.
    No identity values, quota measurements, or quota observation timestamp
    gauges are included. Existing quota measurements therefore keep their age.
    """
    if type(matched) is not bool:
        raise QuotaReportError("invalid_identity_status")
    observed = _utc_datetime(observed_at)
    timestamp_ns = int(observed.timestamp()) * 1_000_000_000 + observed.microsecond * 1_000
    resource = _resource_attributes(service_namespace, profile)
    metric = _gauge(
        "antigravity_account_quota_identity_match",
        "1",
        timestamp_ns,
        [(1.0 if matched else 0.0, _common_attributes())],
    )
    return _metrics_envelope(resource, [metric])


def build_metrics_payload(
    snapshot: Any,
    identity_match: bool = False,
    service_namespace: str = "ai-collaboration",
    profile: str = "personal-local",
) -> dict[str, Any]:
    """Build independent quota gauges only after a local same-account check.

    ``identity_match`` must be literally True, and the caller must explicitly
    set ``snapshot['identity_status']`` to ``matched`` after that check. No
    account values or account hashes appear in the payload. The observation
    timestamp is preserved so dashboards can distinguish an old snapshot from
    an updated one; this function never refreshes stale data with the current
    wall clock. An old observation is valid history, not a fresh observation.
    """
    if identity_match is not True or not isinstance(snapshot, dict) or snapshot.get("identity_status") != "matched":
        raise QuotaReportError("identity_not_matched")
    if type(snapshot.get("schema_version")) is not int or snapshot.get("schema_version") != SCHEMA_VERSION or snapshot.get("source") != SOURCE:
        raise QuotaReportError("invalid_snapshot")
    resource = _resource_attributes(service_namespace, profile)
    observed = _utc_datetime(snapshot.get("observed_at"))
    seconds = _finite_number(snapshot.get("observed_at_unix_seconds"))
    if seconds is None or seconds != observed.timestamp():
        raise QuotaReportError("invalid_snapshot_timestamp")
    # Keep the supplied datetime's microseconds exact instead of rounding them
    # through an epoch-sized binary float when producing the OTLP timestamp.
    timestamp_ns = int(seconds) * 1_000_000_000 + observed.microsecond * 1_000
    raw_buckets = snapshot.get("buckets")
    if not isinstance(raw_buckets, list) or not raw_buckets:
        raise QuotaReportError("invalid_snapshot_buckets")

    common = _common_attributes()
    ratio_points: list[tuple[float, dict[str, str]]] = []
    reset_points: list[tuple[float, dict[str, str]]] = []
    seen: set[str] = set()
    for bucket in raw_buckets:
        if not isinstance(bucket, dict):
            raise QuotaReportError("invalid_snapshot_bucket")
        bucket_id = bucket.get("bucket")
        allowed = QUOTA_BUCKETS.get(bucket_id) if isinstance(bucket_id, str) else None
        if allowed is None or allowed != (bucket.get("quota_group"), bucket.get("window")) or bucket_id in seen:
            raise QuotaReportError("invalid_snapshot_bucket")
        ratio = _finite_number(bucket.get("remaining_ratio"))
        if ratio is None or not 0 <= ratio <= 1:
            raise QuotaReportError("invalid_snapshot_bucket")
        seen.add(bucket_id)
        attributes = {**common, "quota_group": allowed[0], "bucket": bucket_id, "window": allowed[1]}
        ratio_points.append((ratio, attributes))
        if "reset_at_unix_seconds" in bucket:
            reset = _finite_number(bucket["reset_at_unix_seconds"])
            if reset is None or reset <= 0:
                raise QuotaReportError("invalid_snapshot_reset")
            reset_points.append((reset, attributes))

    metrics = [
        _gauge("antigravity_account_quota_remaining_ratio", "1", timestamp_ns, ratio_points),
        _gauge("antigravity_account_quota_snapshot_timestamp_seconds", "s", timestamp_ns, [(seconds, common)]),
        _gauge("antigravity_account_quota_identity_match", "1", timestamp_ns, [(1.0, common)]),
    ]
    if reset_points:
        metrics.append(_gauge("antigravity_account_quota_reset_timestamp_seconds", "s", timestamp_ns, reset_points))
    return _metrics_envelope(resource, metrics)
