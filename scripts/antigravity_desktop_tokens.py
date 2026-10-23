"""Bounded, read-only numeric Antigravity desktop generation metadata inspection.

Only ``gen_metadata`` is queried. Unknown protobuf fields and every string are
skipped without decoding; steps, prompts, model names, IDs and tool content are
never inspected. These are sampled historical generation records, not current
context occupancy, complete provider usage, or a billing ledger.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts import antigravity_local as local


SOURCE = "desktop-local-gen-metadata"
REFERENCE_BLOB = "1088dd4fe27d79a2242b1cca54397996271985d6"
SCHEMA_VERSION = 1
MAX_RECORD_BYTES = 1024 * 1024
MAX_DATABASE_BYTES_READ = 8 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 4096
MAX_TOKEN_VALUE = (1 << 53) - 1
TOKEN_FIELDS = {
    2: "uncached_input_tokens",
    3: "total_output_tokens",
    4: "cache_write_input_tokens",
    5: "cache_read_input_tokens",
    9: "thinking_output_tokens",
    10: "response_output_tokens",
}


class DesktopTokenError(ValueError):
    """Fixed diagnostics only; never include source bytes, paths or identifiers."""


def _varint(data: memoryview, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise DesktopTokenError("malformed_protobuf")
        byte = data[offset]
        offset += 1
        if shift == 63 and byte > 1:
            raise DesktopTokenError("malformed_protobuf")
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise DesktopTokenError("malformed_protobuf")


def _selected_fields(data: memoryview, selected: dict[int, int]) -> dict[int, Any]:
    """Read selected numeric/submessage fields; skip all other bytes in place."""
    result: dict[int, Any] = {}
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number == 0 or number > (1 << 29) - 1:
            raise DesktopTokenError("malformed_protobuf")
        value: int | memoryview | None = None
        if wire == 0:
            scalar, offset = _varint(data, offset)
            if number in selected:
                value = scalar
        elif wire in (1, 5):
            offset += 8 if wire == 1 else 4
            if offset > len(data):
                raise DesktopTokenError("malformed_protobuf")
        elif wire == 2:
            length, offset = _varint(data, offset)
            end = offset + length
            if end > len(data):
                raise DesktopTokenError("malformed_protobuf")
            if number in selected:
                value = data[offset:end]
            offset = end
        else:
            raise DesktopTokenError("unsupported_protobuf_wire")
        if number in selected:
            if wire != selected[number] or number in result:
                raise DesktopTokenError("unexpected_numeric_schema")
            result[number] = value
    return result


def _source_time(chat: dict[int, Any]) -> float | None:
    """Use numeric ChatStartMetadata.created_at only; never decode ISO strings."""
    if 9 not in chat:
        return None
    try:
        metadata = _selected_fields(chat[9], {4: 2})
        if 4 not in metadata:
            return None
        timestamp = _selected_fields(metadata[4], {1: 0, 2: 0})
        seconds = timestamp.get(1)
        nanos = timestamp.get(2, 0)
        if (seconds is None or not 946684800 <= seconds <= 4102444800
                or not 0 <= nanos < 1_000_000_000):
            return None
        return seconds + nanos / 1_000_000_000
    except DesktopTokenError:
        return None


def parse_generation_numeric_metadata(data: bytes) -> dict[str, Any]:
    """Return only reviewed numeric usage and an optional numeric event time.

    Absent proto fields stay absent: protobuf default-zero behavior is not used
    as evidence of an observed zero. Output field 3 already includes thinking;
    fields 9/10 are diagnostic subsets and are never added to it.
    """
    if not isinstance(data, bytes) or len(data) > MAX_RECORD_BYTES:
        raise DesktopTokenError("invalid_metadata_blob")
    root = _selected_fields(memoryview(data), {1: 2})
    if 1 not in root:
        return {"tokens": {}, "source_event_timestamp_seconds": None}
    chat = _selected_fields(root[1], {4: 2, 9: 2})
    usage = _selected_fields(chat[4], {number: 0 for number in TOKEN_FIELDS}) if 4 in chat else {}
    tokens = {}
    for number, value in usage.items():
        if not isinstance(value, int) or not 0 <= value <= MAX_TOKEN_VALUE:
            raise DesktopTokenError("invalid_token_number")
        tokens[TOKEN_FIELDS[number]] = value
    return {"tokens": tokens, "source_event_timestamp_seconds": _source_time(chat)}


def _utc_timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def _storage_state(path: Path) -> tuple[int, int, int, int]:
    main = path.stat()
    wal_path = path.with_name(path.name + "-wal")
    try:
        wal = None if wal_path.is_symlink() else wal_path.stat()
    except FileNotFoundError:
        wal = None
    return (main.st_mtime_ns, main.st_size,
            wal.st_mtime_ns if wal is not None else 0,
            wal.st_size if wal is not None else 0)


def _storage_recency(path: Path) -> int:
    state = _storage_state(path)
    return max(state[0], state[2])


def _read_database(path: Path, max_rows: int) -> dict[str, Any]:
    """Open a WAL-aware read transaction; query no conversation-content table."""
    totals = {name: 0 for name in TOKEN_FIELDS.values()}
    present = {name: 0 for name in TOKEN_FIELDS.values()}
    result: dict[str, Any] = {
        "status": "available", "rows_selected": 0, "records_with_usage": 0,
        "records_without_usage": 0, "invalid_records": 0,
        "limited": False, "bytes_inspected": 0, "event_times": [],
        "totals": totals, "present": present,
        "record_diagnostics": {},
        "storage_modified_at_unix_seconds": None,
        "storage_changed_during_read": False,
    }
    connection = None
    try:
        before = _storage_state(path)
        result["storage_modified_at_unix_seconds"] = max(before[0], before[2]) / 1_000_000_000
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA cache_size = -1024")
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.execute("BEGIN")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(gen_metadata)")}
        if not {"idx", "data"}.issubset(columns):
            raise DesktopTokenError("unsupported_metadata_schema")
        # CASE caps source BLOB transfer even for malformed/oversized rows. The
        # extra row detects truncation; every transferred BLOB remains capped.
        cursor = connection.execute(
            "SELECT idx, CASE WHEN typeof(data) != 'blob' THEN 0 "
            "WHEN length(data) > ? THEN 1 ELSE 2 END, "
            "CASE WHEN typeof(data) = 'blob' AND length(data) <= ? THEN data ELSE NULL END "
            "FROM gen_metadata ORDER BY idx DESC LIMIT ?",
            (MAX_RECORD_BYTES, MAX_RECORD_BYTES, max_rows + 1),
        )
        seen_indices = set()
        for offset, (index, metadata_kind, blob) in enumerate(cursor):
            if offset == max_rows:
                result["limited"] = True
                break
            if type(index) is not int or index in seen_indices:
                raise DesktopTokenError("invalid_metadata_index")
            seen_indices.add(index)
            result["rows_selected"] += 1
            if not isinstance(blob, bytes):
                result["invalid_records"] += 1
                code = "oversized_metadata" if metadata_kind == 1 else "non_blob_metadata"
                result["record_diagnostics"][code] = result["record_diagnostics"].get(code, 0) + 1
                continue
            if result["bytes_inspected"] + len(blob) > MAX_DATABASE_BYTES_READ:
                result["limited"] = True
                break
            result["bytes_inspected"] += len(blob)
            try:
                parsed = parse_generation_numeric_metadata(blob)
            except DesktopTokenError as error:
                result["invalid_records"] += 1
                code = str(error)
                result["record_diagnostics"][code] = result["record_diagnostics"].get(code, 0) + 1
                continue
            if not parsed["tokens"]:
                result["records_without_usage"] += 1
                continue
            result["records_with_usage"] += 1
            for name, value in parsed["tokens"].items():
                totals[name] += value
                present[name] += 1
            if parsed["source_event_timestamp_seconds"] is not None:
                result["event_times"].append(parsed["source_event_timestamp_seconds"])
        connection.rollback()
        result["storage_changed_during_read"] = before != _storage_state(path)
    except (OSError, sqlite3.Error, DesktopTokenError) as error:
        reason = str(error) if isinstance(error, DesktopTokenError) else "metadata_read_unavailable"
        return {"status": "unavailable", "reason": reason}
    finally:
        if connection is not None:
            connection.close()
    return result


def collect_desktop_tokens(*, source_root: Path | None = None,
                           max_databases: int = 3, max_rows: int = 512) -> dict[str, Any]:
    """Inspect bounded historical generation metadata, returning safe JSON only.

    No telemetry, model calls, credentials, RPCs, content-table reads or PB file
    reads occur. The caller may combine this historical sample with independent
    current-state metadata, but must retain its coverage and unknown freshness.
    """
    if (type(max_databases) is not int or not 1 <= max_databases <= 3
            or type(max_rows) is not int or not 1 <= max_rows <= 4096):
        raise DesktopTokenError("invalid_read_limit")
    root = source_root if source_root is not None else Path.home() / ".gemini/antigravity/conversations"
    observed = time.time()
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "source": SOURCE, "surface": "desktop",
        "evidence_class": "observed", "observed_at": _utc_timestamp(observed),
        "status": "unavailable", "reason": "metadata_source_unavailable",
        "source_event_timestamp_seconds": None, "source_freshness": "unknown",
        "storage_modified_at_unix_seconds": None,
        "storage_timestamp_scope": "main_db_or_existing_wal_mtime_not_event_time",
        "snapshot_consistency": "per_database_read_transaction_not_cross_database_atomic",
        "actual_desktop_version": None,
        "reference_blob_sha": REFERENCE_BLOB,
        "validated_schema_version": "2.25.0",
        "schema_evidence": "installed_product_protobuf_descriptors",
        "semantics": "sampled_historical_generation_records",
        "sum_scope": "latest_bounded_persisted_generations_per_database",
        "model_attribution": "unknown", "response_deduplication": "unverified",
        "context_occupancy": "not_measured", "billing_usage": "not_established",
        "limits": {"max_databases": max_databases, "max_rows_per_database": max_rows,
                   "max_record_bytes": MAX_RECORD_BYTES,
                   "max_bytes_per_database": MAX_DATABASE_BYTES_READ},
        "coverage": {"databases_discovered": 0, "databases_read": 0,
                     "databases_unavailable": 0, "legacy_pb_files_skipped": 0,
                     "rows_selected": 0, "records_with_usage": 0,
                     "records_without_usage": 0, "invalid_records": 0,
                     "bytes_inspected": 0, "record_diagnostics": {},
                     "event_timestamps_available": 0, "read_limited": False,
                     "storage_changed_during_read": False},
        "token_fields": {},
    }
    coverage = result["coverage"]
    try:
        version = local.get_desktop_version()
    except local.LocalVerificationError:
        result["reason"] = "desktop_version_unavailable"
        return result
    result["actual_desktop_version"] = version
    if version != local.REVIEWED_DESKTOP_VERSION:
        result["reason"] = "desktop_version_review_required"
        return result
    try:
        paths = []
        for count, path in enumerate(root.iterdir()):
            if count >= MAX_DIRECTORY_ENTRIES:
                coverage["read_limited"] = True
                break
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix.lower() == ".db":
                paths.append(path)
            elif path.suffix.lower() == ".pb":
                coverage["legacy_pb_files_skipped"] += 1
        # Most recent storage first, without exposing filenames/identifiers.
        paths.sort(key=_storage_recency, reverse=True)
    except OSError:
        return result
    coverage["databases_discovered"] = len(paths)
    if len(paths) > max_databases:
        coverage["read_limited"] = True
    totals = {name: 0 for name in TOKEN_FIELDS.values()}
    present = {name: 0 for name in TOKEN_FIELDS.values()}
    event_times = []
    storage_times = []
    for path in paths[:max_databases]:
        sample = _read_database(path, max_rows)
        if sample["status"] != "available":
            coverage["databases_unavailable"] += 1
            continue
        coverage["databases_read"] += 1
        for name in ("rows_selected", "records_with_usage", "records_without_usage", "invalid_records", "bytes_inspected"):
            coverage[name] += sample[name]
        for code, count in sample["record_diagnostics"].items():
            coverage["record_diagnostics"][code] = coverage["record_diagnostics"].get(code, 0) + count
        coverage["read_limited"] |= sample["limited"]
        coverage["storage_changed_during_read"] |= sample["storage_changed_during_read"]
        event_times.extend(sample["event_times"])
        storage_times.append(sample["storage_modified_at_unix_seconds"])
        for name in totals:
            totals[name] += sample["totals"][name]
            present[name] += sample["present"][name]
    records = coverage["records_with_usage"]
    coverage["event_timestamps_available"] = len(event_times)
    if storage_times:
        result["storage_modified_at_unix_seconds"] = max(storage_times)
    if event_times:
        result["source_event_timestamp_seconds"] = max(event_times)
        result["source_freshness"] = "historical_event_timestamp_observed"
    for name in totals:
        result["token_fields"][name] = {
            "sampled_sum": totals[name] if present[name] else None,
            "records_present": present[name], "records_absent": records - present[name],
            "coverage": "unavailable" if not present[name] else "complete" if present[name] == records else "partial",
        }
    if records:
        complete = (not coverage["read_limited"] and not coverage["databases_unavailable"]
                    and not coverage["invalid_records"] and not coverage["legacy_pb_files_skipped"]
                    and not coverage["records_without_usage"]
                    and all(value == records for value in present.values()))
        result["status"] = "observed" if complete else "partial"
        result["reason"] = "historical_metadata_sample"
    elif coverage["databases_read"]:
        result["reason"] = "no_numeric_usage_metadata"
    return result
