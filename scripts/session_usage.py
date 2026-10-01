"""Opt-in, local Codex usage accounting. Never export transcript content.

Only owned token_usage_record.usage deltas are accounted. Report identifiers
are domain-separated HMACs; no report fields become telemetry labels.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RATE_CARD = ROOT / "config/session-usage/codex-credit-rates.json"
TOKEN_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
)
MODELS = frozenset({
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-astra",
    "gpt-6-sol", "gpt-6-luna", "gpt-6.1-sol",
})
EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
DIAGNOSTIC_FIELDS = (
    "files_scanned", "invalid_json_lines", "invalid_usage_records",
    "inherited_usage_records_ignored", "duplicate_response_records",
    "unsupported_sessions", "missing_context_records", "unknown_model_records",
    "unknown_effort_records", "unknown_tier_records", "routing_ambiguous_records",
    "invalid_session_metadata", "orphan_parent_sessions", "unverified_thread_totals",
)


class ReportError(ValueError):
    """A bounded diagnostic code, never an input value or source path."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def _key_id(key: bytes) -> str:
    if not isinstance(key, bytes) or len(key) != 32:
        raise ReportError("invalid_hmac_key")
    return hashlib.sha256(key).hexdigest()[:16]


def _pseudonym(key: bytes, domain: str, *identities: str) -> str:
    return hmac.new(key, _canonical([domain, *identities]), hashlib.sha256).hexdigest()


def create_key(path: Path) -> None:
    """Create an exclusive key file. The value is never printed."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii", newline="") as stream:
            stream.write(secrets.token_hex(32) + "\n")
    except OSError:
        raise ReportError("key_creation_failed") from None


def read_key(path: Path) -> bytes:
    try:
        if path.is_symlink():
            raise ReportError("symlink_key_rejected")
        with path.open("rb") as stream:
            encoded = stream.read(129)
        if not re.fullmatch(rb"[0-9a-fA-F]{64}(?:\r?\n)?", encoded):
            raise ReportError("invalid_hmac_key_file")
        return bytes.fromhex(encoded.strip().decode("ascii"))
    except OSError:
        raise ReportError("key_read_failed") from None


def _decimal(value: Any) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ReportError("invalid_rate_card")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ReportError("invalid_rate_card") from None
    if not result.is_finite() or result < 0 or result > 1_000_000:
        raise ReportError("invalid_rate_card")
    return result


def load_rate_card(path: Path = DEFAULT_RATE_CARD) -> dict[str, Any]:
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ReportError("rate_card_read_failed") from None
    return _validate_card(card)


def _validate_card(card: Any) -> dict[str, Any]:
    """Validate approved, versioned metadata before it can enter a report."""
    keys = {"schema_version", "version", "source", "verified_on", "scope", "models",
            "speed_multipliers", "ultrafast_models"}
    if not isinstance(card, dict) or set(card) != keys:
        raise ReportError("invalid_rate_card")
    if (card["schema_version"] != "codex-credit-rate-card/v1"
            or not isinstance(card["version"], str)
            or not re.fullmatch(r"openai-codex-credits-\d{4}-\d{2}-\d{2}", card["version"])
            or card["source"] != "https://learn.chatgpt.com/docs/pricing#token-rates"
            or card["scope"] != "published_token_classes"
            or not isinstance(card["models"], dict) or set(card["models"]) != MODELS
            or card["ultrafast_models"] != ["gpt-6-astra"]):
        raise ReportError("invalid_rate_card")
    try:
        dt.date.fromisoformat(card["verified_on"])
    except (TypeError, ValueError):
        raise ReportError("invalid_rate_card") from None
    for rates in card["models"].values():
        if not isinstance(rates, dict) or set(rates) != {"input_uncached", "input_cached", "output"}:
            raise ReportError("invalid_rate_card")
        for value in rates.values():
            _decimal(value)
    if card["speed_multipliers"] != {"standard": "1", "fast": "2", "ultrafast": "6"}:
        raise ReportError("invalid_rate_card")
    return card


def _card_digest(card: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(card)).hexdigest()


def _sign(report: dict[str, Any], key: bytes) -> dict[str, Any]:
    report = {name: value for name, value in report.items() if name != "signature"}
    report["signature"] = hmac.new(key, _canonical(report), hashlib.sha256).hexdigest()
    return report


def _identity(value: Any) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 512 else None


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def _tokens(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    result = {field: value.get(field) for field in TOKEN_FIELDS}
    if any(type(number) is not int or number < 0 or number > 2**63 - 1 for number in result.values()):
        return None
    if (result["cached_input_tokens"] + result["cache_write_input_tokens"] > result["input_tokens"]
            or result["reasoning_output_tokens"] > result["output_tokens"]
            or result["input_tokens"] + result["output_tokens"] != result["total_tokens"]):
        return None
    return result


def _tier(value: Any) -> str:
    if value in ("priority", "fast"):
        return "fast"
    if value in ("standard", "default"):
        return "standard"
    return "ultrafast" if value == "ultrafast" else "unknown"


def _model(value: Any) -> str:
    return value if isinstance(value, str) and value in MODELS else "unmapped"


def _effort(value: Any) -> str:
    return value if isinstance(value, str) and value in EFFORTS else "unknown"


def _number(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _price(response: dict[str, Any], card: dict[str, Any]) -> None:
    tokens = response["tokens"]
    model, tier = response["model_id"], response["configured_service_tier"]
    if model not in card["models"] or (tier == "ultrafast" and model not in card["ultrafast_models"]):
        response.update(estimated_credits=None, unpriced_tokens=tokens["total_tokens"],
                        pricing_status="unpriced", credit_multiplier=None)
        return
    multiplier = card["speed_multipliers"][tier if tier != "unknown" else "standard"]
    rates = card["models"][model]
    uncached = tokens["input_tokens"] - tokens["cached_input_tokens"] - tokens["cache_write_input_tokens"]
    credits = (Decimal(uncached) * _decimal(rates["input_uncached"])
               + Decimal(tokens["cached_input_tokens"]) * _decimal(rates["input_cached"])
               + Decimal(tokens["output_tokens"]) * _decimal(rates["output"]))
    response.update(
        estimated_credits=_number(credits * Decimal(multiplier) / Decimal(1_000_000)),
        unpriced_tokens=tokens["cache_write_input_tokens"],
        pricing_status="partial" if tokens["cache_write_input_tokens"] else "priced",
        credit_multiplier=multiplier,
    )


def _scan(path: Path, diagnostics: dict[str, int], *, include_account_usage: bool = False) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool]:
    """Retain only approved metadata, never complete input payloads."""
    events: list[dict[str, Any]] = []
    meta = None
    partial = False
    try:
        if path.is_symlink():
            raise ReportError("symlink_input_rejected")
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    diagnostics["invalid_json_lines"] += 1
                    partial = True
                    continue
                if not isinstance(record, dict):
                    diagnostics["invalid_json_lines"] += 1
                    partial = True
                    continue
                payload = record.get("payload")
                payload = payload if isinstance(payload, dict) else {}
                kind = record.get("type")
                if kind == "session_meta":
                    source = payload.get("source")
                    subagent = source.get("subagent") if isinstance(source, dict) else None
                    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
                    spawn = spawn if isinstance(spawn, dict) else {}
                    identity = _identity(payload.get("id"))
                    if not identity:
                        diagnostics["invalid_session_metadata"] += 1
                        partial = True
                        continue
                    meta = {"id": identity,
                            "parent": _identity(payload.get("parent_thread_id")) or _identity(spawn.get("parent_thread_id")),
                            "role": "subagent" if isinstance(subagent, dict) else "primary"}
                elif (include_account_usage and kind == "event_msg"
                      and payload.get("type") == "token_count" and payload.get("rate_limits") is not None):
                    from scripts.codex_account_usage import normalize_rate_limits
                    timestamp = _timestamp(record.get("timestamp"))
                    snapshot = normalize_rate_limits(payload["rate_limits"], timestamp) if timestamp else None
                    events.append({"kind": "account_snapshot", "owner": meta["id"] if meta else None,
                                   "snapshot": snapshot})
                elif kind == "turn_context":
                    mode = payload.get("collaboration_mode")
                    settings = mode.get("settings") if isinstance(mode, dict) else None
                    settings = settings if isinstance(settings, dict) else {}
                    events.append({"kind": kind, "turn": _identity(payload.get("turn_id")),
                                   "model": _model(payload.get("model", settings.get("model"))),
                                   "reviewer": payload.get("model") == "codex-auto-review",
                                   "effort": _effort(payload.get("effort", settings.get("reasoning_effort")))})
                elif kind == "token_usage_record":
                    events.append({"kind": kind,
                                   **{name: _identity(payload.get(name)) for name in
                                      ("thread_id", "turn_id", "session_id", "response_id")},
                                   "timestamp": _timestamp(record.get("timestamp")),
                                   "tokens": _tokens(payload.get("usage")),
                                   "thread_total": _tokens(payload.get("thread_token_usage"))})
                elif kind == "event_msg" and payload.get("type") == "thread_settings_applied":
                    settings = payload.get("thread_settings")
                    settings = settings if isinstance(settings, dict) else {}
                    events.append({"kind": "settings", "thread": _identity(payload.get("thread_id")),
                                   "tier": _tier(settings.get("service_tier"))})
                elif kind == "event_msg" and payload.get("type") == "task_started":
                    events.append({"kind": "start", "turn": _identity(payload.get("turn_id"))})
                elif record.get("method") == "model/rerouted":
                    params = record.get("params")
                    params = params if isinstance(params, dict) else {}
                    events.append({"kind": "reroute", "thread": _identity(params.get("threadId")),
                                   "turn": _identity(params.get("turnId"))})
    except (OSError, UnicodeError):
        raise ReportError("source_read_failed") from None
    if meta is None:
        diagnostics["invalid_session_metadata"] += 1
    return meta, events, partial


def _total(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    result = dict.fromkeys(TOKEN_FIELDS, 0)
    for record in records:
        for name in TOKEN_FIELDS:
            result[name] += record["tokens"][name]
    return result


def _credits(records: Iterable[dict[str, Any]]) -> str | None:
    values = [Decimal(record["estimated_credits"]) for record in records if record["estimated_credits"] is not None]
    return _number(sum(values, Decimal(0))) if values else None


def _pricing_status(records: list[dict[str, Any]]) -> str:
    if not records or all(record["estimated_credits"] is None for record in records):
        return "unpriced"
    return "partial" if any(record["unpriced_tokens"] or record["estimated_credits"] is None
                            for record in records) else "priced"


def _assemble_report(responses: list[dict[str, Any]], descriptors: list[dict[str, Any]],
                     diagnostics: dict[str, int], key: bytes, rate_card: dict[str, Any], *,
                     selection: str = "all_sessions", includes_subagents: bool = True) -> dict[str, Any]:
    responses = sorted(responses, key=lambda row: (row["session_key"], row["timestamp"], row["response_key"]))
    diagnostics = {field: diagnostics.get(field, 0) for field in DIAGNOSTIC_FIELDS}
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_keys = ("session_key", "root_session_key", "agent_role", "model_id", "configured_model_id",
                  "actual_model_id", "model_basis", "reasoning_effort", "configured_service_tier", "tier_basis")
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for response in responses:
        by_session[response["session_key"]].append(response)
        grouped[tuple(response[field] for field in group_keys)].append(response)
    groups = []
    for group_key, rows in sorted(grouped.items()):
        groups.append({**dict(zip(group_keys, group_key)), "response_count": len(rows),
                       "tokens": _total(rows), "estimated_credits": _credits(rows),
                       "unpriced_tokens": sum(row["unpriced_tokens"] for row in rows),
                       "pricing_status": _pricing_status(rows)})
    sessions = []
    for descriptor in sorted(descriptors, key=lambda row: row["session_key"]):
        rows = by_session[descriptor["session_key"]]
        status = descriptor["status"]
        if not rows and status == "observed":
            status = "unsupported_source"
        elif rows and (status == "unsupported_source" or any(row["model_basis"] != "configured"
                                                            or row["reasoning_effort"] == "unknown"
                                                            or row["configured_service_tier"] == "unknown" for row in rows)):
            status = "partial"
        sessions.append({"session_key": descriptor["session_key"],
                         "parent_session_key": descriptor["parent_session_key"],
                         "agent_role": descriptor["agent_role"], "status": status,
                         "response_count": len(rows), "tokens": _total(rows) if rows else None,
                         "estimated_credits": _credits(rows),
                         "unpriced_tokens": sum(row["unpriced_tokens"] for row in rows),
                         "first_seen": min((row["timestamp"] for row in rows), default=None),
                         "last_seen": max((row["timestamp"] for row in rows), default=None)})
    diagnostics["unsupported_sessions"] = sum(row["status"] == "unsupported_source" for row in sessions)
    incomplete = ("invalid_json_lines", "invalid_usage_records", "unsupported_sessions",
                  "missing_context_records", "unknown_model_records", "unknown_effort_records",
                  "unknown_tier_records",
                  "routing_ambiguous_records", "invalid_session_metadata", "orphan_parent_sessions",
                  "unverified_thread_totals")
    return _sign({
        "schema_version": "session-usage/v1", "key_id": _key_id(key),
        "rate_card_version": rate_card["version"], "rate_card_sha256": _card_digest(rate_card),
        "estimate_kind": "public_codex_credit_equivalent", "billing_status": "actual_debit_unavailable",
        "scope": {"selection": selection, "includes_subagents": includes_subagents},
        "sessions": sessions, "responses": responses, "groups": groups,
        "summary": {"session_count": len(sessions), "response_count": len(responses),
                    "tokens": _total(responses), "estimated_credits": _credits(responses),
                    "unpriced_tokens": sum(row["unpriced_tokens"] for row in responses),
                    "metadata_complete": not any(diagnostics[field] for field in incomplete)
                                         and all(row["status"] == "observed" for row in sessions),
                    "pricing_complete": bool(responses) and not any(row["unpriced_tokens"]
                                                                      or row["estimated_credits"] is None for row in responses)},
        "diagnostics": diagnostics,
    }, key)


def collect_report(source_root: Path, key: bytes, *, session_id: str | None = None,
                   include_subagents: bool = False, rate_card: dict[str, Any] | None = None,
                   include_account_usage: bool = False, official_usage: bool = False,
                   codex_bin: str | None = None, official_timeout: float = 20.0) -> dict[str, Any]:
    _key_id(key)
    card = _validate_card(rate_card) if rate_card is not None else load_rate_card()
    if not source_root.is_dir() or source_root.is_symlink():
        raise ReportError("invalid_source_root")
    paths = sorted(source_root.rglob("*.jsonl"))
    if not paths:
        raise ReportError("no_rollout_files")
    diagnostics = dict.fromkeys(DIAGNOSTIC_FIELDS, 0)
    metadata: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    routed: set[tuple[str, str]] = set()
    thread_totals: dict[str, tuple[str, dict[str, int]]] = {}
    include_account_usage = include_account_usage or official_usage
    account_events: list[dict[str, Any]] = []
    for path in paths:
        diagnostics["files_scanned"] += 1
        meta, events, partial = _scan(path, diagnostics, include_account_usage=include_account_usage)
        if meta is None:
            continue
        owner = meta["id"]
        descriptor = {**meta, "status": "partial" if partial else "observed"}
        existing = metadata.get(owner)
        if existing and any(existing[field] != meta[field] for field in ("parent", "role")):
            raise ReportError("conflicting_session_metadata")
        if existing and existing["status"] == "partial":
            descriptor["status"] = "partial"
        metadata[owner] = descriptor
        current_tier = "unknown"
        turns: dict[str, dict[str, Any]] = {}
        turn_tiers: dict[str, str] = {}
        for event in events:
            kind = event["kind"]
            if kind == "account_snapshot":
                account_events.append({**event, "file_owner": owner})
            elif kind == "settings" and event["thread"] == owner:
                current_tier = event["tier"]
            elif kind == "start" and event["turn"]:
                turn_tiers[event["turn"]] = current_tier
            elif kind == "turn_context" and event["turn"]:
                turns[event["turn"]] = event
                turn_tiers.setdefault(event["turn"], current_tier)
            elif kind == "reroute" and event["thread"] and event["turn"]:
                routed.add((event["thread"], event["turn"]))
            elif kind == "token_usage_record":
                if event["thread_id"] and event["thread_id"] != owner:
                    diagnostics["inherited_usage_records_ignored"] += 1
                    continue
                if (not all(event[field] for field in ("thread_id", "turn_id", "session_id", "response_id", "timestamp"))
                        or event["tokens"] is None):
                    diagnostics["invalid_usage_records"] += 1
                    metadata[owner]["status"] = "partial"
                    continue
                context = turns.get(event["turn_id"])
                tier = turn_tiers.get(event["turn_id"], "unknown")
                role = "approval_reviewer" if context and context["reviewer"] else meta["role"]
                response = {
                    "session_key": _pseudonym(key, "session", owner),
                    "root_session_key": _pseudonym(key, "session", event["session_id"]),
                    "parent_session_key": _pseudonym(key, "session", meta["parent"]) if meta["parent"] else None,
                    "turn_key": _pseudonym(key, "turn", owner, event["turn_id"]),
                    "response_key": _pseudonym(key, "response", owner, event["response_id"]),
                    "agent_role": role, "timestamp": event["timestamp"],
                    "configured_model_id": context["model"] if context else "unmapped",
                    "actual_model_id": "unmapped", "model_id": context["model"] if context else "unmapped",
                    "model_basis": "configured" if context and context["model"] != "unmapped" else "unknown",
                    "reasoning_effort": context["effort"] if context else "unknown",
                    "configured_service_tier": tier,
                    "tier_basis": "configured" if tier != "unknown" else "standard_assumption",
                    "tokens": event["tokens"],
                    "_owner": owner, "_root": event["session_id"], "_turn": event["turn_id"],
                    "_missing_context": context is None,
                }
                candidates.append(response)
                total = event["thread_total"]
                if total is not None and (owner not in thread_totals or event["timestamp"] >= thread_totals[owner][0]):
                    thread_totals[owner] = (event["timestamp"], total)
    if session_id is not None and session_id not in metadata:
        raise ReportError("session_not_found")
    selected = set(metadata) if session_id is None else {session_id}
    if session_id is not None and include_subagents:
        while True:
            children = {owner for owner, meta in metadata.items() if meta["role"] == "subagent"
                        and meta["parent"] in selected}
            children |= {row["_owner"] for row in candidates if row["_root"] in selected
                         and metadata[row["_owner"]]["role"] == "subagent"}
            expanded = selected | children
            if expanded == selected:
                break
            selected = expanded
    unique: dict[str, dict[str, Any]] = {}
    for row in candidates:
        if row["_owner"] not in selected:
            continue
        missing = row.pop("_missing_context")
        owner, turn = row.pop("_owner"), row.pop("_turn")
        row.pop("_root")
        if (owner, turn) in routed:
            row["model_id"] = "unmapped"
            row["model_basis"] = "routing_ambiguous"
        _price(row, card)
        previous = unique.get(row["response_key"])
        if previous is not None:
            if previous != row:
                raise ReportError("conflicting_response_records")
            diagnostics["duplicate_response_records"] += 1
            continue
        unique[row["response_key"]] = row
        diagnostics["missing_context_records"] += int(missing)
        diagnostics["unknown_model_records"] += int(row["model_id"] == "unmapped")
        diagnostics["unknown_effort_records"] += int(row["reasoning_effort"] == "unknown")
        diagnostics["unknown_tier_records"] += int(row["configured_service_tier"] == "unknown")
        diagnostics["routing_ambiguous_records"] += int(row["model_basis"] == "routing_ambiguous")
    descriptors = []
    responses = list(unique.values())
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in responses:
        by_session[row["session_key"]].append(row)
    for owner in sorted(selected):
        meta = metadata[owner]
        session_key = _pseudonym(key, "session", owner)
        rows = by_session[session_key]
        if meta["parent"] and meta["parent"] not in metadata:
            diagnostics["orphan_parent_sessions"] += 1
            meta["status"] = "partial"
        if rows and (owner not in thread_totals or _total(rows) != thread_totals[owner][1]):
            diagnostics["unverified_thread_totals"] += 1
            meta["status"] = "partial"
        descriptors.append({"session_key": session_key,
                            "parent_session_key": _pseudonym(key, "session", meta["parent"]) if meta["parent"] else None,
                            "agent_role": meta["role"], "status": meta["status"]})
    selection = "all_sessions" if session_id is None else "session_with_subagents" if include_subagents else "single_session"
    report = _assemble_report(responses, descriptors, diagnostics, key, card,
                              selection=selection, includes_subagents=session_id is None or include_subagents)
    if include_account_usage:
        from scripts.session_usage_metrics import collect_metrics, attach_metrics
        metrics = collect_metrics(account_events, selected, key, official_usage=official_usage,
                                  codex_bin=codex_bin, timeout=official_timeout)
        report = attach_metrics(report, metrics, key)
    return report


def merge_reports(paths: Iterable[Path], key: bytes, *, rate_card: dict[str, Any] | None = None) -> dict[str, Any]:
    from scripts.session_usage_exchange import merge_reports as merge
    return merge(paths, key, rate_card=rate_card)


def render_csv(report: dict[str, Any]) -> str:
    from scripts.session_usage_exchange import render_csv as render
    return render(report)


def write_report(report: dict[str, Any], path: Path | None, *, format: str = "json") -> str:
    if format not in ("json", "csv"):
        raise ReportError("invalid_report_format")
    rendered = json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n" if format == "json" else render_csv(report)
    if path is not None:
        # Atomic replacement; partial output never masquerades as a valid signed report.
        temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(rendered)
            os.replace(temporary, path)
        except OSError:
            raise ReportError("report_write_failed") from None
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return rendered
