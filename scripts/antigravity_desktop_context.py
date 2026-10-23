"""Bounded, read-only validation of desktop generation context metadata.

This is a version-reviewed internal adapter, not a documented Google API.
It does not export telemetry. Conversation selectors, RPC responses, identity
and message fields remain in process memory and never enter the safe result.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import sqlite3
from typing import Any

from scripts import antigravity_local as local


SOURCE = "desktop-local-generation-context-metadata"
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z", re.ASCII)
_MAX_SQLITE_INDEX = 2**32 - 1

# Field numbers were read from the installed 2.25.0 language_server.exe
# DescriptorProto; names below are schema identifiers, never runtime content.
SCHEMA_EVIDENCE = {
    "source": "installed-language-server-descriptor-proto",
    "reviewed_desktop_version": local.REVIEWED_DESKTOP_VERSION,
    "request_fields": {"cascade_id": 1, "generator_metadata_offset": 2,
                       "include_messages": 3},
    "response_generator_metadata_field": 1,
    "context_parent_fields": {"CortexStepGeneratorMetadata.chat_model": 1,
                              "ChatModelMetadata.chat_start_metadata": 9,
                              "ChatStartMetadata.context_window_metadata": 10},
    "context_fields": {"estimated_tokens_used": 1, "truncation_reason": 2,
                       "token_breakdown": 3, "max_context_tokens": 4},
    "generation_timestamp_field": 4,
    "breakdown_total_tokens_field": 2,
    "contract_stability": "internal-version-reviewed",
}


def _number(value: Any, *, positive: bool = False) -> int | None:
    # ContextWindowMetadata fields are int32, unlike uint64 usage fields.
    if type(value) is not int or value < (1 if positive else 0) or value > 2**31 - 1:
        return None
    return value


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, dict):
        seconds, nanos = value.get("seconds"), value.get("nanos", 0)
        if isinstance(seconds, str) and re.fullmatch(r"[0-9]{1,12}", seconds):
            seconds = int(seconds)
        if (type(seconds) is not int or not 0 <= seconds <= 253402300799
                or type(nanos) is not int or not 0 <= nanos < 1_000_000_000):
            return None
        try:
            return datetime.fromtimestamp(seconds + nanos / 1_000_000_000, timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            return None
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _usage_cross_check(entries: list) -> dict:
    """Summarize only numeric usage in the same bounded RPC response suffix."""
    fields = ("inputTokens", "outputTokens", "cacheWriteTokens", "cacheReadTokens",
              "thinkingOutputTokens", "responseOutputTokens")
    sums, present = {field: 0 for field in fields}, set()
    count = 0
    for entry in entries:
        chat = entry.get("chatModel") if isinstance(entry, dict) else None
        usage = chat.get("usage") if isinstance(chat, dict) else None
        if not isinstance(usage, dict):
            continue
        found = False
        for field in fields:
            value = usage.get(field)
            if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value):
                value = int(value)
            if type(value) is int and 0 <= value < 2**64:
                sums[field] += value
                present.add(field)
                found = True
        count += found
    return {"scope": "requested-generation-suffix", "records_with_numeric_usage": count,
            "sums": {field: sums[field] for field in fields if field in present}}


def parse_context_response(response: Any, observed_at: datetime) -> dict:
    """Extract the newest context block; never infer it from historical usage."""
    empty = {
        "status": "unavailable", "reason": "context_metadata_missing",
        "estimated_tokens_used": None, "max_context_tokens": None,
        "used_ratio": None, "token_breakdown_total_tokens": None,
        "measurement_kind": "unknown", "generation_started_at": None,
        "source_age_seconds": None,
    }
    if observed_at.tzinfo is None:
        raise ValueError("observation_time_requires_timezone")
    if not isinstance(response, dict) or not isinstance(response.get("generatorMetadata"), list):
        return {**empty, "reason": "context_response_invalid"}
    entries = response["generatorMetadata"]
    if len(entries) > 1000:
        return {**empty, "reason": "context_response_invalid"}
    empty["rpc_usage_cross_check"] = _usage_cross_check(entries)
    # Returned generator metadata is an ordered suffix from the requested
    # offset. A later entry without context must not be treated as an update
    # to an earlier estimate: distance_from_end makes that limitation explicit.
    for reverse_index, entry in enumerate(reversed(entries)):
        if not isinstance(entry, dict):
            continue
        chat = entry.get("chatModel")
        if not isinstance(chat, dict):
            continue
        start = chat.get("chatStartMetadata")
        if not isinstance(start, dict):
            continue
        context = start.get("contextWindowMetadata")
        if not isinstance(context, dict):
            continue
        estimate = _number(context.get("estimatedTokensUsed"))
        capacity = _number(context.get("maxContextTokens"), positive=True)
        breakdown = context.get("tokenBreakdown")
        total = _number(breakdown.get("totalTokens")) if isinstance(breakdown, dict) else None
        created = _timestamp(start.get("createdAt"))
        age = (observed_at - created).total_seconds() if created else None
        if age is not None and (not math.isfinite(age) or age < 0):
            created, age = None, None
        result = {
            **empty,
            "estimated_tokens_used": estimate,
            "max_context_tokens": capacity,
            "used_ratio": estimate / capacity if estimate is not None and capacity is not None else None,
            "token_breakdown_total_tokens": total,
            "measurement_kind": "server-estimate" if estimate is not None else "unknown",
            "generation_started_at": created.isoformat().replace("+00:00", "Z") if created else None,
            "source_age_seconds": age,
            "generation_distance_from_response_end": reverse_index,
            "generation_timestamp_present": "createdAt" in start,
        }
        if estimate is not None:
            result["status"] = "observed" if capacity is not None and created is not None and reverse_index == 0 else "partial"
            result.pop("reason", None)
        return result
    return empty


def _recent_databases(root: Path, limit: int) -> list[tuple[Path, float]]:
    candidates = []
    try:
        for path in root.iterdir():
            if path.suffix != ".db" or not _UUID.fullmatch(path.stem) or not path.is_file() or path.is_symlink():
                continue
            modified = path.stat().st_mtime
            wal = path.with_name(path.name + "-wal")
            if wal.is_file() and not wal.is_symlink():
                modified = max(modified, wal.stat().st_mtime)
            candidates.append((path, modified))
    except OSError:
        raise local.LocalVerificationError("desktop_context_store_unavailable") from None
    return sorted(candidates, key=lambda item: item[1], reverse=True)[:limit]


def _metadata_offset(path: Path) -> int:
    """Read only the numeric metadata index; no trajectory rows are opened."""
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as connection:
            connection.execute("PRAGMA query_only=ON")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(gen_metadata)")}
            if "idx" not in columns:
                raise ValueError
            highest = connection.execute("SELECT MAX(idx) FROM gen_metadata").fetchone()[0]
        if type(highest) is not int or not 0 <= highest <= _MAX_SQLITE_INDEX:
            raise ValueError
        # Request at most the newest three persisted generator records. SQLite
        # and RPC indexes were verified against this installed desktop version.
        return max(0, highest - 2)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        raise local.LocalVerificationError("desktop_context_index_unavailable") from None


def collect_desktop_context(max_conversations: int = 3, source_root: Path | None = None) -> dict:
    """Return a sanitized snapshot of recent persisted generation estimates.

    A recent database is not proof of the UI's active conversation. Missing
    capacity stays unknown. No usage totals, model limit tables, or token
    arithmetic are substituted for a server-provided context field.
    """
    observed = datetime.now(timezone.utc)
    result = {
        "source": SOURCE, "status": "unavailable",
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "selection": "recent-local-conversations",
        "current_active_conversation": "unknown",
        "observation_scope": "latest-persisted-generation",
        "telemetry_exported": False, "schema_evidence": SCHEMA_EVIDENCE,
        "conversations": [],
    }
    if type(max_conversations) is not int or not 1 <= max_conversations <= 3:
        return {**result, "reason": "invalid_conversation_limit"}
    try:
        version = local.get_desktop_version()
        result["desktop_version"] = version
        if version != local.REVIEWED_DESKTOP_VERSION:
            raise local.LocalVerificationError("desktop_version_review_required")
        root = Path(source_root) if source_root is not None else Path.home() / ".gemini/antigravity/conversations"
        candidates = _recent_databases(root, max_conversations)
        if not candidates:
            raise local.LocalVerificationError("desktop_context_store_unavailable")

        def read() -> dict:
            records = []
            with local.DesktopClient() as client:
                for rank, (path, modified) in enumerate(candidates, 1):
                    safe = {"selection_rank": rank,
                            "local_file_age_seconds": max(0, observed.timestamp() - modified)}
                    try:
                        offset = _metadata_offset(path)
                        response = client.request("GetCascadeTrajectoryGeneratorMetadata", {
                            "cascadeId": path.stem, "generatorMetadataOffset": offset,
                            "includeMessages": False,
                        })
                        safe.update(parse_context_response(response, observed))
                    except local.LocalVerificationError as error:
                        safe.update({"status": "unavailable", "reason": error.code})
                    records.append(safe)
            return {"conversations": records}

        safe_read, proof = local.collect_verified(read)
        result["identity_verification"] = proof
        result["conversations"] = safe_read["conversations"]
        statuses = [item["status"] for item in result["conversations"]]
        if statuses and all(status == "observed" for status in statuses):
            result["status"] = "observed"
        elif any(status in {"observed", "partial"} for status in statuses):
            result["status"] = "partial"
        else:
            result["reason"] = "context_metadata_unavailable"
    except local.LocalVerificationError as error:
        result["reason"] = error.code
    except Exception:
        result["reason"] = "desktop_context_read_failed"
    return result
