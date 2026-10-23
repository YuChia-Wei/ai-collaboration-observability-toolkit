"""Read bounded desktop usage metadata locally, without telemetry export."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Callable


def _read_component(reader: Callable[[], dict], failure_code: str) -> dict:
    try:
        result = reader()
        if not isinstance(result, dict) or result.get("status") not in {
            "observed", "partial", "unavailable",
        }:
            return {"status": "unavailable", "error": "unsupported_reader_report"}
        return result
    except Exception:
        # SQLite/RPC errors may contain paths, selectors, or provider output.
        return {"status": "unavailable", "error": failure_code}


def collect_desktop_usage(*, max_conversations: int = 3, max_rows: int = 512) -> dict:
    if (type(max_conversations) is not int or not 1 <= max_conversations <= 3
            or type(max_rows) is not int or not 1 <= max_rows <= 4096):
        raise ValueError("invalid_desktop_read_limits")
    from scripts.antigravity_desktop_tokens import collect_desktop_tokens
    from scripts.antigravity_desktop_context import collect_desktop_context

    started = dt.datetime.now(dt.timezone.utc)
    tokens = _read_component(lambda: collect_desktop_tokens(
        max_databases=max_conversations, max_rows=max_rows,
    ), "desktop_token_read_unavailable")
    context = _read_component(lambda: collect_desktop_context(
        max_conversations=max_conversations,
    ), "desktop_context_read_unavailable")
    states = {tokens["status"], context["status"]}
    status = ("observed" if states == {"observed"} else
              "unavailable" if states == {"unavailable"} else "partial")
    return {
        "schema_version": 1,
        "source": "local-desktop-metadata",
        "status": status,
        "read_started_at": started.isoformat().replace("+00:00", "Z"),
        "read_completed_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "selection": "recent-local-conversations",
        "current_active_conversation": "unknown",
        "export_status": "not-supported",
        "tokens": tokens,
        "context": context,
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-conversations", type=int, choices=range(1, 4), default=3,
                        help="Maximum recent local conversations per source (1-3).")
    parser.add_argument("--max-rows", type=int, default=512,
                        help="Maximum persisted token metadata rows per database (1-4096).")
    parser.add_argument("--output", type=Path, help="Write sanitized metadata to a local JSON file.")


def run(args: argparse.Namespace) -> int:
    try:
        result = collect_desktop_usage(max_conversations=args.max_conversations,
                                       max_rows=args.max_rows)
    except Exception:
        result = {"source": "local-desktop-metadata", "status": "unavailable",
                  "error": "desktop_read_unavailable"}
    rendered = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if args.output is None:
        print(rendered, end="", flush=True)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, args.output)
    return 0 if result["status"] == "observed" else 1
