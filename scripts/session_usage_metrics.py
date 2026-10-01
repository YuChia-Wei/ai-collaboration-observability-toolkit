"""Separate account observations and provider estimates from the local ledger."""
from __future__ import annotations

import datetime as dt
import hmac
from typing import Any

from scripts import session_usage as usage

DIAGNOSTICS = (
    "invalid_snapshot_records", "inherited_snapshot_records_ignored",
    "duplicate_snapshot_records", "sessions_without_snapshots", "official_requests",
    "official_unavailable", "official_thread_usage_missing", "official_invalid_records",
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _record_key(row: dict, key: bytes, domain: str) -> str:
    return usage._pseudonym(key, domain, usage._canonical(row).decode("ascii"))


def _seal(row: dict, key: bytes, domain: str) -> dict:
    return {**row, "observation_key": _record_key(row, key, domain)}


def attach_metrics(report: dict, metrics: dict, key: bytes) -> dict:
    return usage._sign({**report, "schema_version": "session-usage/v2", "usage_metrics": metrics}, key)


def collect_metrics(events: list[dict], selected: set[str], key: bytes, *,
                    official_usage: bool = False, codex_bin: str | None = None,
                    timeout: float = 20.0) -> dict:
    diagnostics = dict.fromkeys(DIAGNOSTICS, 0)
    snapshots: dict[str, dict] = {}
    observed: set[str] = set()
    for event in events:
        if event["file_owner"] not in selected:
            continue
        if event["owner"] != event["file_owner"]:
            diagnostics["inherited_snapshot_records_ignored"] += 1
            continue
        snapshot = event["snapshot"]
        if snapshot is None:
            diagnostics["invalid_snapshot_records"] += 1
            continue
        owner = event["file_owner"]
        row = _seal({**snapshot, "source": "rollout", "scope": "account_quota",
                     "observed_in_session_key": usage._pseudonym(key, "session", owner)},
                    key, "account_snapshot")
        observed.add(owner)
        if row["observation_key"] in snapshots:
            diagnostics["duplicate_snapshot_records"] += 1
        snapshots[row["observation_key"]] = row
    diagnostics["sessions_without_snapshots"] = len(selected - observed)
    estimates = []
    if official_usage:
        from scripts.codex_account_usage import collect_account_usage
        collected = collect_account_usage(sorted(selected), codex_bin=codex_bin, timeout=timeout)
        for name, count in collected["diagnostics"].items():
            diagnostics[name] = count
        timestamp = _now()
        snapshot = collected["account_snapshot"]
        if snapshot is not None:
            row = _seal({**snapshot, "source": "app_server", "scope": "account_quota",
                         "observed_in_session_key": None}, key, "account_snapshot")
            snapshots[row["observation_key"]] = row
        available = {item["thread_id"]: item for item in collected["thread_estimates"]}
        for owner in sorted(selected):
            item = available.get(owner)
            row = {"session_key": usage._pseudonym(key, "session", owner),
                   "source": "app_server", "scope": "thread_scope_unverified",
                   "estimate_kind": "provider_estimated_usage",
                   "observed_at": (item.get("observed_at", timestamp) if item is not None
                                   else collected.get("thread_observations", {}).get(owner, timestamp)),
                   "status": "available" if item is not None else "unavailable",
                   "estimated_usage_credits_micros": item["estimated_usage_credits_micros"] if item else None,
                   "estimated_usage_usd_micros": item["estimated_usage_usd_micros"] if item else None,
                   "groups": item["groups"] if item else []}
            estimates.append(_seal(row, key, "thread_estimate"))
    return {"account_snapshots": sorted(snapshots.values(), key=lambda row: (row["observed_at"], row["observation_key"])),
            "thread_estimates": estimates, "diagnostics": diagnostics}


def validate_metrics(metrics: dict, session_keys: set[str], key: bytes) -> None:
    """Schema is checked by the caller; verify identity binding and row integrity."""
    for field, domain in (("account_snapshots", "account_snapshot"), ("thread_estimates", "thread_estimate")):
        seen = set()
        for row in metrics[field]:
            observation = row["observation_key"]
            if observation in seen:
                raise usage.ReportError("duplicate_metric_observations")
            seen.add(observation)
            unsigned = {name: value for name, value in row.items() if name != "observation_key"}
            if not hmac.compare_digest(observation, _record_key(unsigned, key, domain)):
                raise usage.ReportError("invalid_metric_observation_key")
            session = row.get("session_key", row.get("observed_in_session_key"))
            if session is not None and session not in session_keys:
                raise usage.ReportError("invalid_metric_relationships")
            if field == "account_snapshots":
                if ((row["source"] == "rollout") != (session is not None)):
                    raise usage.ReportError("invalid_metric_relationships")
            else:
                if ((row["status"] == "available") != (row["estimated_usage_credits_micros"] is not None)
                        or (row["status"] == "unavailable" and (row["groups"] or row["estimated_usage_usd_micros"] is not None))):
                    raise usage.ReportError("invalid_metric_estimate")
                for group in row["groups"]:
                    tokens = [group[name] for name in ("input_tokens", "output_tokens", "total_tokens")]
                    if all(value is not None for value in tokens) and tokens[0] + tokens[1] != tokens[2]:
                        raise usage.ReportError("invalid_metric_tokens")
                    if (group["input_tokens"] is not None and group["cached_input_tokens"] is not None
                            and group["cached_input_tokens"] > group["input_tokens"]):
                        raise usage.ReportError("invalid_metric_tokens")


def merge_metrics(sources: list[dict], key: bytes) -> dict:
    snapshots: dict[str, dict] = {}
    estimates: dict[str, dict] = {}
    observations: dict[tuple[str, str], dict] = {}
    diagnostics = dict.fromkeys(DIAGNOSTICS, 0)
    for source in sources:
        for name, count in source["diagnostics"].items():
            diagnostics[name] = max(diagnostics[name], count)
        for row in source["account_snapshots"]:
            snapshots[row["observation_key"]] = row
        for row in source["thread_estimates"]:
            identity = (row["session_key"], row["observed_at"])
            if identity in observations and observations[identity] != row:
                raise usage.ReportError("conflicting_thread_estimates")
            observations[identity] = row
            previous = estimates.get(row["session_key"])
            if previous is None or row["observed_at"] > previous["observed_at"]:
                estimates[row["session_key"]] = row
    return {"account_snapshots": sorted(snapshots.values(), key=lambda row: (row["observed_at"], row["observation_key"])),
            "thread_estimates": sorted(estimates.values(), key=lambda row: row["session_key"]),
            "diagnostics": diagnostics}
