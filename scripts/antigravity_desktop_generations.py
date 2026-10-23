"""Private generation identities and numeric timestamps for desktop publishing.

This version-reviewed adapter reads only gen_metadata and referenced
steps.metadata. Only native response_id is retained as a private byte key;
all other strings, tool fields and step bodies are skipped without decoding.
Raw records must stay in memory. Publishers persist keyed hashes and numbers,
and expose only safe_summary(), never dataclasses.asdict() on these records.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterator

from scripts import antigravity_desktop_tokens as numeric
from scripts import antigravity_local as local


MAX_STEP_INDICES = 4096
MAX_STEP_RECORD_BYTES = 1024 * 1024
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z", re.ASCII)
_TIME_FIELDS = {1: "created_at", 6: "viewable_at", 7: "finished_generating_at",
                8: "completed_at", 22: "last_completed_chunk_at", 32: "started_at"}
SCHEMA_EVIDENCE = {
    "source": "installed-language-server-descriptor-proto",
    "reviewed_desktop_version": "2.25.0",
    "generation_step_indices": {"field": 2, "type": "repeated-uint32"},
    "generation_chat_model_field": 1, "chat_model_usage_field": 4,
    "native_response_id_field": 11,
    "chat_start_metadata_field": 9, "chat_start_created_at_field": 4,
    "step_timestamp_fields": {name: number for number, name in _TIME_FIELDS.items()},
    "timestamp_type": "google.protobuf.Timestamp",
}


@dataclass(repr=False, frozen=True)
class GenerationRecord:
    response_id: bytes | None
    selector: str
    row_index: int
    tokens: dict[str, int]
    source_timestamp_seconds: float | None
    source_time_kind: str
    linked_step_count: int
    timestamped_step_count: int
    step_indices: tuple[int, ...] = ()
    latest_referenced_step_completed_timestamp_seconds: float | None = None
    latest_referenced_step_finished_generating_timestamp_seconds: float | None = None


@dataclass(repr=False, frozen=True)
class GenerationRead:
    records: tuple[GenerationRecord, ...] = field(default_factory=tuple)
    report: dict[str, Any] = field(default_factory=dict)

    def safe_summary(self) -> dict[str, Any]:
        return deepcopy(self.report)


def _fields(data: memoryview, selected: set[int]) -> Iterator[tuple[int, int, Any]]:
    """Yield only explicitly selected fields; unknown bytes are skipped in place."""
    offset = 0
    while offset < len(data):
        tag, offset = numeric._varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not 0 < number < (1 << 29):
            raise numeric.DesktopTokenError("malformed_protobuf")
        value = None
        if wire == 0:
            scalar, offset = numeric._varint(data, offset)
            if number in selected:
                value = scalar
        elif wire in (1, 5):
            offset += 8 if wire == 1 else 4
        elif wire == 2:
            length, offset = numeric._varint(data, offset)
            end = offset + length
            if number in selected:
                value = data[offset:end]
            offset = end
        else:
            raise numeric.DesktopTokenError("unsupported_protobuf_wire")
        if offset > len(data):
            raise numeric.DesktopTokenError("malformed_protobuf")
        if number in selected:
            yield number, wire, value


def _timestamp(data: memoryview) -> float | None:
    try:
        fields = numeric._selected_fields(data, {1: 0, 2: 0})
        seconds, nanos = fields.get(1), fields.get(2, 0)
        if (seconds is None or not 946684800 <= seconds <= 4102444800
                or not 0 <= nanos < 1_000_000_000):
            return None
        return seconds + nanos / 1_000_000_000
    except numeric.DesktopTokenError:
        return None


def parse_step_numeric_timestamps(data: bytes) -> dict[str, float]:
    """Read only reviewed Timestamp fields, never step arguments or tool calls."""
    if not isinstance(data, bytes) or len(data) > MAX_STEP_RECORD_BYTES:
        raise numeric.DesktopTokenError("invalid_step_metadata_blob")
    fields = numeric._selected_fields(memoryview(data), {number: 2 for number in _TIME_FIELDS})
    result = {}
    for number, value in fields.items():
        timestamp = _timestamp(value)
        if timestamp is not None:
            result[_TIME_FIELDS[number]] = timestamp
    return result


def _generation_parts(data: bytes) -> tuple[dict[str, Any], bytes | None, tuple[int, ...]]:
    parsed = numeric.parse_generation_numeric_metadata(data)
    indices = []
    for number, wire, value in _fields(memoryview(data), {2}):
        if wire == 0:
            values = [value]
        elif wire == 2:
            values, offset = [], 0
            while offset < len(value):
                index, offset = numeric._varint(value, offset)
                values.append(index)
                if len(values) > MAX_STEP_INDICES:
                    raise numeric.DesktopTokenError("generation_step_limit")
        else:
            raise numeric.DesktopTokenError("invalid_generation_step_indices")
        for index in values:
            if not 0 <= index < (1 << 32) or len(indices) >= MAX_STEP_INDICES:
                raise numeric.DesktopTokenError("generation_step_limit")
            indices.append(index)
    # Do not process the same referenced step twice if the source repeats it.
    indices = list(dict.fromkeys(indices))
    root = numeric._selected_fields(memoryview(data), {1: 2})
    response_id = None
    if 1 in root:
        chat = numeric._selected_fields(root[1], {4: 2})
        if 4 in chat:
            try:
                identity = numeric._selected_fields(chat[4], {11: 2}).get(11)
                # An opaque native identity is never text-decoded. Reject free
                # text/control characters rather than retaining arbitrary data.
                if identity is not None and 1 <= len(identity) <= 512 and all(32 < byte < 127 for byte in identity):
                    response_id = bytes(identity)
            except numeric.DesktopTokenError:
                pass
    return parsed, response_id, tuple(indices)


def _increment(diagnostics: dict, code: str) -> None:
    diagnostics[code] = diagnostics.get(code, 0) + 1


def _read_database(path: Path, max_rows: int) -> tuple[list[GenerationRecord], dict]:
    records: list[GenerationRecord] = []
    report = {"status": "available", "rows_selected": 0, "invalid_generation_records": 0,
              "generations_without_usage": 0, "linked_step_metadata_read": 0,
              "invalid_step_metadata": 0, "missing_step_metadata": 0,
              "bytes_inspected": 0, "read_limited": False, "diagnostics": {},
              "storage_changed_during_read": False}
    connection = None
    try:
        before = numeric._storage_state(path)
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA cache_size=-1024")
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.execute("BEGIN")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(gen_metadata)")}
        if not {"idx", "data"}.issubset(columns):
            raise numeric.DesktopTokenError("unsupported_generation_schema")
        pending = []
        seen = set()
        rows = connection.execute(
            "SELECT idx, CASE WHEN typeof(data)='blob' AND length(data)<=? THEN data ELSE NULL END "
            "FROM gen_metadata ORDER BY idx DESC LIMIT ?", (numeric.MAX_RECORD_BYTES, max_rows + 1))
        for offset, (index, blob) in enumerate(rows):
            if offset == max_rows:
                report["read_limited"] = True
                break
            if type(index) is not int or not 0 <= index < (1 << 32) or index in seen:
                raise numeric.DesktopTokenError("invalid_generation_index")
            seen.add(index)
            report["rows_selected"] += 1
            if not isinstance(blob, bytes):
                report["invalid_generation_records"] += 1
                _increment(report["diagnostics"], "unavailable_generation_blob")
                continue
            if report["bytes_inspected"] + len(blob) > numeric.MAX_DATABASE_BYTES_READ:
                report["read_limited"] = True
                break
            report["bytes_inspected"] += len(blob)
            try:
                parsed, response_id, indices = _generation_parts(blob)
            except numeric.DesktopTokenError as error:
                report["invalid_generation_records"] += 1
                _increment(report["diagnostics"], str(error))
                continue
            if not parsed["tokens"]:
                report["generations_without_usage"] += 1
                continue
            pending.append((index, parsed, response_id, indices))
        referenced = sorted({index for _, _, _, indices in pending for index in indices})
        if len(referenced) > MAX_STEP_INDICES:
            report["read_limited"] = True
            referenced = referenced[-MAX_STEP_INDICES:]
        step_times: dict[int, dict[str, float]] = {}
        step_columns = {row[1] for row in connection.execute("PRAGMA table_info(steps)")}
        if referenced and {"idx", "metadata"}.issubset(step_columns):
            for start in range(0, len(referenced), 200):
                selected = referenced[start:start + 200]
                placeholders = ",".join("?" for _ in selected)
                step_rows = connection.execute(
                    "SELECT idx, CASE WHEN typeof(metadata)='blob' AND length(metadata)<=? "
                    "THEN metadata ELSE NULL END FROM steps WHERE idx IN (" + placeholders + ")",
                    (MAX_STEP_RECORD_BYTES, *selected),
                )
                for index, blob in step_rows:
                    if index in step_times:
                        raise numeric.DesktopTokenError("duplicate_step_metadata_index")
                    if not isinstance(blob, bytes):
                        report["invalid_step_metadata"] += 1
                        continue
                    if report["bytes_inspected"] + len(blob) > numeric.MAX_DATABASE_BYTES_READ:
                        report["read_limited"] = True
                        break
                    report["bytes_inspected"] += len(blob)
                    report["linked_step_metadata_read"] += 1
                    try:
                        step_times[index] = parse_step_numeric_timestamps(blob)
                    except numeric.DesktopTokenError:
                        report["invalid_step_metadata"] += 1
                if report["read_limited"] and report["bytes_inspected"] >= numeric.MAX_DATABASE_BYTES_READ:
                    break
        report["missing_step_metadata"] = len(referenced) - len(step_times)
        for index, parsed, response_id, indices in pending:
            times = [step_times.get(step, {}) for step in indices]
            created = [value["created_at"] for value in times if "created_at" in value]
            completed = [value["completed_at"] for value in times if "completed_at" in value]
            finished = [value["finished_generating_at"] for value in times if "finished_generating_at" in value]
            source_time = parsed["source_event_timestamp_seconds"]
            kind = "chat-start-created-at" if source_time is not None else "unknown"
            first_created = step_times.get(indices[0], {}).get("created_at") if indices else None
            if source_time is None and first_created is not None:
                source_time, kind = first_created, "first-referenced-step-created-at"
            records.append(GenerationRecord(
                response_id, path.stem, index, parsed["tokens"], source_time, kind,
                len(indices), len(created), indices,
                max(completed) if completed else None,
                max(finished) if finished else None,
            ))
        connection.rollback()
        report["storage_changed_during_read"] = before != numeric._storage_state(path)
    except (OSError, sqlite3.Error, numeric.DesktopTokenError) as error:
        report["status"] = "unavailable"
        report["reason"] = str(error) if isinstance(error, numeric.DesktopTokenError) else "generation_metadata_read_unavailable"
        records = []
    finally:
        if connection is not None:
            connection.close()
    return records, report


def collect_desktop_generations(*, source_root: Path | None = None, max_databases: int = 3,
                                max_rows: int = 512, selector: str | None = None) -> GenerationRead:
    """Collect private records plus an independently safe aggregate report.

    ``selector`` is a validated private UUID from independent active-selection
    evidence. It selects only that fixed-root database; it is never reported.
    A missing native response ID remains in the sample for coverage only and
    must not become a trusted cumulative token counter.
    """
    if (type(max_databases) is not int or not 1 <= max_databases <= 3
            or type(max_rows) is not int or not 1 <= max_rows <= 4096):
        raise numeric.DesktopTokenError("invalid_read_limit")
    observed = time.time()
    report: dict[str, Any] = {
        "status": "unavailable", "reason": "generation_source_unavailable",
        "source": "desktop-local-generation-metadata", "surface": "desktop",
        "evidence_class": "observed", "observed_at": numeric._utc_timestamp(observed),
        "actual_desktop_version": None, "schema_evidence": deepcopy(SCHEMA_EVIDENCE),
        "selection": "private-selector" if selector is not None else "recent-persisted-conversations",
        "semantics": "bounded_persisted_generation_records_not_billing",
        "coverage": {"databases_discovered": 0, "databases_read": 0, "databases_unavailable": 0,
                     "legacy_pb_files_skipped": 0, "rows_selected": 0,
                     "invalid_generation_records": 0, "generations_without_usage": 0,
                     "linked_step_metadata_read": 0, "invalid_step_metadata": 0,
                     "missing_step_metadata": 0, "bytes_inspected": 0,
                     "read_limited": False, "storage_changed_during_read": False,
                     "diagnostics": {}},
        "limits": {"max_databases": max_databases, "max_rows_per_database": max_rows,
                   "max_generation_bytes": numeric.MAX_RECORD_BYTES,
                   "max_step_metadata_bytes": MAX_STEP_RECORD_BYTES,
                   "max_combined_bytes_per_database": numeric.MAX_DATABASE_BYTES_READ,
                   "max_step_indices_per_database": MAX_STEP_INDICES},
        "generations": 0, "native_response_ids_available": 0,
        "native_response_ids_missing": 0, "distinct_native_response_ids": 0,
        "generation_source_times_available": 0, "generation_source_times_missing": 0,
        "source_time_kinds": {}, "latest_source_timestamp_seconds": None,
        "oldest_source_timestamp_seconds": None, "latest_source_age_seconds": None,
        "token_fields": {},
    }
    if selector is not None and (not isinstance(selector, str) or not _UUID.fullmatch(selector)):
        report["reason"] = "invalid_private_selector"
        return GenerationRead(report=report)
    try:
        version = local.get_desktop_version()
        report["actual_desktop_version"] = version
        if version != local.REVIEWED_DESKTOP_VERSION:
            report["reason"] = "desktop_version_review_required"
            return GenerationRead(report=report)
    except local.LocalVerificationError:
        report["reason"] = "desktop_version_unavailable"
        return GenerationRead(report=report)
    root = source_root if source_root is not None else Path.home() / ".gemini/antigravity/conversations"
    coverage = report["coverage"]
    try:
        if selector is not None:
            path = root / (selector + ".db")
            paths = [path] if path.is_file() and not path.is_symlink() else []
        else:
            paths = []
            for offset, path in enumerate(root.iterdir()):
                if offset >= numeric.MAX_DIRECTORY_ENTRIES:
                    coverage["read_limited"] = True
                    break
                if path.is_symlink() or not path.is_file():
                    continue
                if path.suffix.lower() == ".db":
                    paths.append(path)
                elif path.suffix.lower() == ".pb":
                    coverage["legacy_pb_files_skipped"] += 1
            paths.sort(key=numeric._storage_recency, reverse=True)
    except OSError:
        return GenerationRead(report=report)
    coverage["databases_discovered"] = len(paths)
    coverage["read_limited"] |= len(paths) > max_databases
    records = []
    for path in paths[:max_databases]:
        current, sample = _read_database(path, max_rows)
        if sample["status"] != "available":
            coverage["databases_unavailable"] += 1
            _increment(coverage["diagnostics"], sample["reason"])
            continue
        records.extend(current)
        coverage["databases_read"] += 1
        for name in ("rows_selected", "invalid_generation_records", "generations_without_usage",
                     "linked_step_metadata_read", "invalid_step_metadata", "missing_step_metadata", "bytes_inspected"):
            coverage[name] += sample[name]
        for name in ("read_limited", "storage_changed_during_read"):
            coverage[name] |= sample[name]
        for code, count in sample["diagnostics"].items():
            coverage["diagnostics"][code] = coverage["diagnostics"].get(code, 0) + count
    report["generations"] = len(records)
    ids = [record.response_id for record in records if record.response_id is not None]
    report["native_response_ids_available"] = len(ids)
    report["native_response_ids_missing"] = len(records) - len(ids)
    report["distinct_native_response_ids"] = len(set(ids))
    source_times = [record.source_timestamp_seconds for record in records if record.source_timestamp_seconds is not None]
    report["generation_source_times_available"] = len(source_times)
    report["generation_source_times_missing"] = len(records) - len(source_times)
    for record in records:
        _increment(report["source_time_kinds"], record.source_time_kind)
    if source_times:
        report["latest_source_timestamp_seconds"] = max(source_times)
        report["oldest_source_timestamp_seconds"] = min(source_times)
        report["latest_source_age_seconds"] = observed - max(source_times)
    for name in numeric.TOKEN_FIELDS.values():
        values = [record.tokens[name] for record in records if name in record.tokens]
        report["token_fields"][name] = {"sampled_sum": sum(values) if values else None,
                                      "records_present": len(values), "records_absent": len(records) - len(values)}
    if records:
        report["status"] = "partial" if (coverage["read_limited"] or coverage["databases_unavailable"]
            or coverage["legacy_pb_files_skipped"] or coverage["invalid_generation_records"]
            or len(ids) != len(records) or len(source_times) != len(records)
            or coverage["missing_step_metadata"] or coverage["invalid_step_metadata"]) else "observed"
        report["reason"] = "bounded_generation_metadata_sample"
    return GenerationRead(tuple(records), report)
