"""Publish deduplicated desktop metadata through the existing local Collector."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import time

from scripts import antigravity_desktop_context as context_reader
from scripts import antigravity_desktop_generations as generations
from scripts import antigravity_desktop_metrics as metrics
from scripts import antigravity_local as local
from scripts.antigravity_desktop_ledger import GenerationLedger
from scripts.antigravity_quota import export_metrics, _write_result


class ObservationError(ValueError):
    """Fixed, non-sensitive diagnostics."""


def default_state_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ai-collaboration-observability/antigravity-desktop"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "ai-collaboration-observability/antigravity-desktop"


@contextmanager
def publication_lock(directory: Path):
    """Serialize the complete collection/ingest/export operation across processes."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "publish.lock"
    if path.is_symlink():
        raise ObservationError("unsafe_publication_lock")
    handle = path.open("a+b")
    locked = False
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise ObservationError("desktop_observer_busy") from None
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _matches_generation(entry: dict, record: generations.GenerationRecord) -> bool:
    chat = entry.get("chatModel")
    usage = chat.get("usage") if isinstance(chat, dict) else None
    response_id = usage.get("responseId") if isinstance(usage, dict) else None
    if isinstance(response_id, str) and record.response_id is not None:
        return response_id.encode("utf-8") == record.response_id
    indices = entry.get("stepIndices")
    return (isinstance(indices, list) and bool(indices)
            and all(type(index) is int for index in indices)
            and tuple(indices) == record.step_indices)


def read_latest_context(read: generations.GenerationRead) -> dict:
    empty = {"read_success": False, "generation_verified": False,
             "is_latest_generation": False, "scope": "latest-observed-generation"}
    timed = [record for record in read.records if record.source_timestamp_seconds is not None]
    if not timed or len(timed) != len(read.records):
        return {**empty, "reason": "generation_source_time_unavailable"}
    newest_time = max(record.source_timestamp_seconds for record in timed)
    candidates = [record for record in timed if record.source_timestamp_seconds == newest_time]
    identities = {(record.selector, record.response_id, record.row_index) for record in candidates}
    if len(identities) != 1:
        return {**empty, "reason": "latest_generation_ambiguous"}
    latest = candidates[0]
    try:
        with local.DesktopClient() as client:
            response = client.request("GetCascadeTrajectoryGeneratorMetadata", {
                "cascadeId": latest.selector,
                "generatorMetadataOffset": latest.row_index,
                "includeMessages": False,
            })
        entries = response.get("generatorMetadata")
        if (not isinstance(entries, list) or not entries or not isinstance(entries[-1], dict)
                or not _matches_generation(entries[-1], latest)):
            return {**empty, "reason": "generation_changed_or_unmatched"}
        observed = datetime.now(timezone.utc)
        parsed = context_reader.parse_context_response(response, observed)
        if parsed.get("generation_distance_from_response_end") != 0:
            return {**empty, "reason": "latest_context_missing"}
        # Source time comes from the same native generation, never the poll or
        # file mtime. The fallback is explicitly a referenced step's creation.
        source_time = latest.source_timestamp_seconds
        native_created = parsed.get("generation_started_at")
        if native_created:
            actual = datetime.fromisoformat(native_created.replace("Z", "+00:00")).timestamp()
            if abs(actual - source_time) > 0.001:
                return {**empty, "reason": "context_source_time_conflict"}
        return {
            "read_success": True, "generation_verified": True,
            "is_latest_generation": True, "scope": "latest-observed-generation",
            "source_timestamp_seconds": source_time,
            "source_time_kind": latest.source_time_kind,
            "source_age_seconds": observed.timestamp() - source_time,
            "estimated_tokens_used": parsed.get("estimated_tokens_used"),
            "max_context_tokens": parsed.get("max_context_tokens"),
            "token_breakdown_total_tokens": parsed.get("token_breakdown_total_tokens"),
        }
    except Exception:
        return {**empty, "reason": "latest_context_read_unavailable"}


def _collect_locked(args: argparse.Namespace) -> dict:
    # The private read result is not serialized. Only summaries and aggregates
    # cross this boundary, after stable native account verification.
    def read():
        sample = generations.collect_desktop_generations(
            max_databases=args.max_conversations, max_rows=args.max_rows,
        )
        return {"sample": sample, "context": read_latest_context(sample)}

    private, proof = local.collect_verified(read)
    sample, context = private["sample"], private["context"]
    summary = sample.safe_summary()
    if not sample.records:
        raise ObservationError("generation_metadata_unavailable")
    observed = datetime.now(timezone.utc)
    ledger = GenerationLedger(args.state_dir / "generations.sqlite3").ingest(
        sample.records, observed_at_seconds=observed.timestamp(),
    )
    coverage = summary.get("coverage", {})
    token_success = not any((
        coverage.get("databases_unavailable", 0),
        coverage.get("invalid_generation_records", 0),
        coverage.get("invalid_step_metadata", 0),
        coverage.get("missing_step_metadata", 0),
        ledger["missing_identity"], ledger["missing_source_time"],
        ledger["invalid_records"], ledger["conflicting_records"], ledger["capacity_reached"],
    ))
    tokens = {
        "read_success": token_success,
        "ledger_start_at": datetime.fromtimestamp(ledger["ledger_start_at_unix_seconds"], timezone.utc),
        "totals": ledger["totals"], "generation_count": ledger["generation_count"],
        "read_limited": bool(coverage.get("read_limited", True)),
        "latest_source_timestamp_seconds": ledger["latest_source_timestamp_seconds"],
    }
    payload = metrics.build_metrics_payload(observed_at=observed, tokens=tokens, context=context,
                                           service_namespace=args.service_namespace, profile=args.profile)
    if args.export:
        export_metrics(payload, args.endpoint)
    return {
        "schema_version": 1, "source": "desktop-local-metadata",
        "status": "observed" if token_success and context["generation_verified"] else "partial",
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "active_conversation": "deferred",
        "context_scope": "latest-observed-generation",
        "identity_verification": proof, "generation_read": summary,
        "deduplication": ledger, "latest_context": context,
        "export_status": "otlp-accepted" if args.export else "not-requested",
    }


def collect_observation(args: argparse.Namespace) -> dict:
    with publication_lock(args.state_dir):
        try:
            return _collect_locked(args)
        except Exception:
            if args.export:
                try:
                    export_metrics(metrics.build_metrics_payload(
                        observed_at=datetime.now(timezone.utc), tokens={"read_success": False},
                        context={"read_success": False, "generation_verified": False, "is_latest_generation": False},
                        service_namespace=args.service_namespace, profile=args.profile,
                    ), args.endpoint)
                except Exception:
                    pass
            raise


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--state-dir", type=Path, default=default_state_dir(),
                        help="Durable private hash/numeric ledger; preserve across restarts.")
    parser.add_argument("--max-conversations", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--max-rows", type=int, default=512)
    parser.add_argument("--endpoint", default="http://127.0.0.1:4318")
    parser.add_argument("--service-namespace", default="ai-collaboration")
    parser.add_argument("--profile", choices=("personal-local", "corporate-local-redacted"), default="personal-local")
    parser.add_argument("--output", type=Path)


def run(args: argparse.Namespace) -> int:
    if (not 15 <= args.interval_seconds <= 3600 or not 1 <= args.max_rows <= 4096
            or not 1 <= args.max_conversations <= 3):
        raise ObservationError("invalid_observation_limits")
    while True:
        try:
            result = collect_observation(args)
        except Exception as error:
            busy = isinstance(error, ObservationError) and str(error) == "desktop_observer_busy"
            result = {"source": "desktop-local-metadata", "status": "unavailable",
                      "error": "desktop_observer_busy" if busy else "desktop_observation_unavailable"}
        _write_result(result, args.output)
        if not args.watch:
            return 0 if result["status"] in {"observed", "partial"} else 1
        time.sleep(args.interval_seconds)
