"""Durable local deduplication of numeric generation observations.

Only keyed hashes, reviewed numeric fields and timestamps are persisted. Native
response IDs and conversation selectors never reach SQLite or the public result.
The cumulative totals describe discovered metadata, not provider billing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable, Any

from scripts.antigravity_desktop_tokens import TOKEN_FIELDS

MAX_GENERATIONS = 100_000
MAX_EXACT_INTEGER = 2**53 - 1
FIELDS = frozenset(TOKEN_FIELDS.values())
TIME_KINDS = frozenset({"chat-start-created-at", "first-referenced-step-created-at"})


class LedgerError(ValueError):
    """Fixed diagnostic codes only."""


def _number(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_EXACT_INTEGER


def _time(value: Any, observed: float) -> bool:
    return (type(value) in {int, float} and math.isfinite(value)
            and 946684800 <= value <= observed + 1)


def _prepare_file(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise LedgerError("unsafe_ledger_path")
        if not path.exists():
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            except FileExistsError:
                if path.is_symlink():
                    raise LedgerError("unsafe_ledger_path") from None
    except LedgerError:
        raise
    except OSError:
        raise LedgerError("ledger_unavailable") from None


class GenerationLedger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def ingest(self, records: Iterable[Any], *, observed_at_seconds: float) -> dict:
        """Commit an idempotent batch before publishing cumulative totals.

        A retry after an OTLP transport failure resends the same cumulative
        values. Positive refinements of an existing generation add only their
        delta. Decreases or conflicting source times are rejected, never summed.
        """
        if not _time(observed_at_seconds, observed_at_seconds):
            raise LedgerError("invalid_observation_time")
        _prepare_file(self.path)
        try:
            with closing(sqlite3.connect(self.path, timeout=2)) as db:
                db.execute("PRAGMA busy_timeout=2000")
                db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS generations (digest BLOB PRIMARY KEY, source_time REAL NOT NULL, tokens TEXT NOT NULL)")
                db.commit()
                db.execute("BEGIN IMMEDIATE")
                meta = dict(db.execute("SELECT key,value FROM meta"))
                count = db.execute("SELECT COUNT(*) FROM generations").fetchone()[0]
                if not meta:
                    if count:
                        raise LedgerError("invalid_ledger_state")
                    meta = {"version": "1", "secret": os.urandom(32).hex(),
                            "started_at": str(observed_at_seconds), "totals": "{}"}
                    db.executemany("INSERT INTO meta(key,value) VALUES (?,?)", meta.items())
                if meta.get("version") != "1":
                    raise LedgerError("unsupported_ledger_version")
                try:
                    secret = bytes.fromhex(meta["secret"])
                    totals = json.loads(meta["totals"])
                    started_at = float(meta["started_at"])
                except (KeyError, ValueError, TypeError):
                    raise LedgerError("invalid_ledger_state") from None
                if (len(secret) != 32 or not isinstance(totals, dict)
                        or not set(totals) <= FIELDS or not all(_number(v) for v in totals.values())
                        or not _time(started_at, observed_at_seconds)):
                    raise LedgerError("invalid_ledger_state")
                result = {"new_generations": 0, "duplicate_generations": 0,
                          "refined_generations": 0, "missing_identity": 0,
                          "missing_source_time": 0, "invalid_records": 0,
                          "conflicting_records": 0, "capacity_reached": False}
                for record in records:
                    identity = record.response_id
                    if not isinstance(identity, bytes) or not 1 <= len(identity) <= 512:
                        result["missing_identity"] += 1
                        continue
                    source_time = record.source_timestamp_seconds
                    if not _time(source_time, observed_at_seconds) or record.source_time_kind not in TIME_KINDS:
                        result["missing_source_time"] += 1
                        continue
                    values = record.tokens
                    if (not isinstance(values, dict) or not values or not set(values) <= FIELDS
                            or not all(_number(v) for v in values.values())):
                        result["invalid_records"] += 1
                        continue
                    digest = hmac.digest(secret, b"antigravity-response-v1\0" + identity, hashlib.sha256)
                    old = db.execute("SELECT source_time,tokens FROM generations WHERE digest=?", (digest,)).fetchone()
                    previous = json.loads(old[1]) if old else {}
                    if (not isinstance(previous, dict) or not set(previous) <= FIELDS
                            or not all(_number(v) for v in previous.values())):
                        raise LedgerError("invalid_ledger_state")
                    if old and (abs(old[0] - source_time) > 0.001
                                or any(k in values and values[k] < v for k, v in previous.items())):
                        result["conflicting_records"] += 1
                        continue
                    if old is None and count >= MAX_GENERATIONS:
                        result["capacity_reached"] = True
                        continue
                    combined = {**previous, **values}
                    if old is not None and combined == previous:
                        result["duplicate_generations"] += 1
                        continue
                    for field, value in values.items():
                        updated = totals.get(field, 0) + value - previous.get(field, 0)
                        if not _number(updated):
                            raise LedgerError("ledger_numeric_capacity_reached")
                        totals[field] = updated
                    db.execute("INSERT OR REPLACE INTO generations(digest,source_time,tokens) VALUES (?,?,?)",
                               (digest, source_time, json.dumps(combined, separators=(",", ":"))))
                    if old is None:
                        count += 1
                        result["new_generations"] += 1
                    else:
                        result["refined_generations"] += 1
                db.execute("UPDATE meta SET value=? WHERE key='totals'", (json.dumps(totals, separators=(",", ":")),))
                latest = db.execute("SELECT MAX(source_time) FROM generations").fetchone()[0]
                db.commit()
                return {**result, "ledger_start_at_unix_seconds": started_at,
                        "totals": totals, "generation_count": count,
                        "latest_source_timestamp_seconds": latest}
        except LedgerError:
            raise
        except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
            raise LedgerError("ledger_unavailable") from None
