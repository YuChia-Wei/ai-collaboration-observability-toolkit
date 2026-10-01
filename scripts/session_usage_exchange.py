#!/usr/bin/env python3
"""Validate and merge signed, pseudonymous session reports; export summary CSV."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import hmac
import io
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from scripts import session_usage as usage


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas/session-usage-report.schema.json"
TOKEN_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
)
CSV_COLUMNS = (
    "rate_card_version", "session_key", "root_session_key", "session_status",
    "agent_role", "configured_model_id", "actual_model_id", "model_id",
    "model_basis", "reasoning_effort", "configured_service_tier", "tier_basis",
    "response_count", *TOKEN_FIELDS, "estimated_credits", "unpriced_tokens",
    "pricing_status",
)
_DESCRIPTOR_METADATA = ("parent_session_key", "agent_role")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise usage.ReportError("invalid_report_json")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise usage.ReportError("invalid_report_json")


def _load_json(path: Path, error_code: str) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except usage.ReportError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise usage.ReportError(error_code) from None


def _validator() -> Draft202012Validator:
    schema = _load_json(SCHEMA_PATH, "report_schema_unavailable")
    try:
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())
    except (SchemaError, ValueError, TypeError, RecursionError):
        # Schema diagnostics must not disclose local paths or input payloads.
        raise usage.ReportError("report_schema_unavailable") from None


def _validate_report(report: Any, validator: Draft202012Validator) -> None:
    try:
        valid = validator.is_valid(report)
    except (ValueError, TypeError, RecursionError):
        valid = False
    if not valid:
        raise usage.ReportError("invalid_report_schema")


def _merge_descriptor(current: dict[str, Any], incoming: dict[str, Any]) -> None:
    if any(current[field] != incoming[field] for field in _DESCRIPTOR_METADATA):
        raise usage.ReportError("conflicting_session_metadata")
    if current["status"] != incoming["status"]:
        current["status"] = "partial"
    for field, choose in (("first_seen", min), ("last_seen", max)):
        values = [value for value in (current.get(field), incoming.get(field)) if value]
        current[field] = choose(
            values, key=lambda value: dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        ) if values else None


def _validate_response(response: dict[str, Any], card: dict[str, Any]) -> None:
    if usage._tokens(response["tokens"]) is None:
        raise usage.ReportError("invalid_response_tokens")
    if (
        (response["model_basis"] == "configured" and (
            response["model_id"] == "unmapped"
            or response["model_id"] != response["configured_model_id"]
        ))
        or (response["model_basis"] != "configured" and response["model_id"] != "unmapped")
        or ((response["tier_basis"] == "configured")
            != (response["configured_service_tier"] != "unknown"))
    ):
        raise usage.ReportError("invalid_response_metadata")
    expected = dict(response)
    usage._price(expected, card)
    if any(response[field] != expected[field] for field in (
        "estimated_credits", "unpriced_tokens", "pricing_status", "credit_multiplier",
    )):
        raise usage.ReportError("invalid_response_pricing")


def merge_reports(
    paths: Iterable[Path], key: bytes, *, rate_card: dict | None = None,
) -> dict:
    """Merge authenticated response records, recalculating every aggregate.

    Response overlap is idempotent. Diagnostic counters are source-report maxima,
    so partial or invalid source observations survive overlap without becoming
    purported company-wide sums. CSV exports are deliberately not importable.
    """
    if not isinstance(key, bytes) or len(key) != 32:
        raise usage.ReportError("invalid_hmac_key")
    validator = _validator()
    card = rate_card if rate_card is not None else usage.load_rate_card()
    usage._validate_card(card)
    expected_key_id = usage._key_id(key)
    expected_digest = usage._card_digest(card)
    expected_version = card.get("rate_card_version", card.get("version"))
    responses: dict[str, dict[str, Any]] = {}
    descriptors: dict[str, dict[str, Any]] = {}
    diagnostics: dict[str, int] = {}
    includes_subagents = False
    report_count = 0

    for path in paths:
        report_path = Path(path)
        if report_path.is_symlink():
            raise usage.ReportError("symlink_report_rejected")
        report = _load_json(report_path, "invalid_report_json")
        _validate_report(report, validator)
        if report["key_id"] != expected_key_id:
            raise usage.ReportError("company_key_mismatch")
        unsigned = {name: value for name, value in report.items() if name != "signature"}
        signature = hmac.new(key, usage._canonical(unsigned), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, report["signature"]):
            raise usage.ReportError("invalid_report_signature")
        if (
            report["rate_card_version"] != expected_version
            or report["rate_card_sha256"] != expected_digest
        ):
            raise usage.ReportError("rate_card_mismatch")
        report_count += 1
        includes_subagents = includes_subagents or report["scope"]["includes_subagents"]
        for name, count in report["diagnostics"].items():
            diagnostics[name] = max(diagnostics.get(name, 0), count)
        for descriptor in report["sessions"]:
            session_key = descriptor["session_key"]
            if session_key in descriptors:
                _merge_descriptor(descriptors[session_key], descriptor)
            else:
                descriptors[session_key] = dict(descriptor)
        for response in report["responses"]:
            response_key = response["response_key"]
            previous = responses.get(response_key)
            if previous is not None and previous != response:
                raise usage.ReportError("conflicting_response_records")
            _validate_response(response, card)
            responses[response_key] = response

    if not report_count:
        raise usage.ReportError("no_reports_selected")
    if any(response["session_key"] not in descriptors for response in responses.values()):
        raise usage.ReportError("invalid_report_relationships")
    for response in responses.values():
        descriptor = descriptors[response["session_key"]]
        if (
            response["parent_session_key"] != descriptor["parent_session_key"]
            or (response["agent_role"] != descriptor["agent_role"]
                and response["agent_role"] != "approval_reviewer")
        ):
            raise usage.ReportError("invalid_report_relationships")
    result = usage._assemble_report(
        list(responses.values()), list(descriptors.values()), diagnostics, key, card,
        selection="merged_reports", includes_subagents=includes_subagents,
    )
    _validate_report(result, validator)
    return result


def render_csv(report: dict) -> str:
    """Render approved group columns only, retaining unsupported session rows."""
    _validate_report(report, _validator())
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    descriptors = {item["session_key"]: item for item in report["sessions"]}
    rows: list[dict[str, Any]] = []
    grouped_sessions: set[str] = set()
    for group in report["groups"]:
        session_key = group["session_key"]
        grouped_sessions.add(session_key)
        row = {column: group.get(column, "") for column in CSV_COLUMNS}
        row["rate_card_version"] = report["rate_card_version"]
        row["session_status"] = descriptors.get(session_key, {}).get("status", "partial")
        for field in TOKEN_FIELDS:
            row[field] = group["tokens"][field]
        rows.append(row)
    for descriptor in report["sessions"]:
        if descriptor["session_key"] in grouped_sessions:
            continue
        rows.append({
            "rate_card_version": report["rate_card_version"],
            "session_key": descriptor["session_key"],
            "session_status": descriptor["status"],
            "agent_role": descriptor["agent_role"],
        })
    for row in sorted(rows, key=lambda item: tuple(str(item.get(column) or "") for column in CSV_COLUMNS)):
        writer.writerow(row)
    return output.getvalue()
