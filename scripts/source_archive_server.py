#!/usr/bin/env python3
"""Private OTLP JSON archive backend; sanitize before any persistent write."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


RESOURCE_KEYS = {"logs": "resourceLogs", "metrics": "resourceMetrics", "traces": "resourceSpans"}
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 64
REDACTED = "[REDACTED]"
LOG_BODY = {"stringValue": "AI telemetry metadata event"}

SENSITIVE_KEY = re.compile(
    r"(?i)(^|[._-])(?:input|output|response|body|prompt|completion)(?:$|[.])|"
    r"(^|[._-])(arguments?|args|result|payload|prompt[._-](?:content|text|length)|"
    r"completion[._-](?:content|text)|messages?|content|"
    r"input[._-](?:value|body|content|text|messages?)|"
    r"output[._-](?:value|body|content|text|messages?)|"
    r"response[._-](?:body|content|text|messages?|headers?)|reasoning[._-]summary|"
    r"tool[._-](?:arguments?|args|result|output|input)|mcp[._-](?:arguments?|result|payload)|"
    r"request[._-](?:body|headers?|id)|file[._-](?:path|content|name)|"
    r"repository[._-](?:url|path|name)|code[._-](?:content|diff|filepath|file[._-]path)|"
    r"process[._-](?:command(?:[._-]line)?|command[._-]args|executable[._-]path)|"
    r"command[._-](?:line|output)|shell[._-]command|db[._-](?:statement|query[._-]text)|"
    r"exception[._-](?:message|stacktrace)|error[._-]message|url[._-](?:full|path|query)|"
    r"http[._-](?:url|target)|user[._-](?:email|name|id|account[._-]id)|email|"
    r"account[._-]id|organization[._-]id|session[._-]id|conversation[._-]id|task[._-]id|"
    r"call[._-]id|trace[._-]id|span[._-]id|endpoint|host[._-]name|auth(?:orization)?|"
    r"cookie|api[._-]?key|access[._-]?token|refresh[._-]?token|password|secret|"
    r"absolute[._-]?path|path|cwd|transcript[._-]path)([._-]|$)"
)
# Numeric/content-container exceptions apply only to content-name aliases. They
# must never override a credential, identity, path, or payload ancestor.
PROTECTED_KEY = re.compile(
    r"(?i)(^|[._-])(arguments?|args|result|payload|messages?|content|reasoning[._-]summary|"
    r"tool[._-](?:arguments?|args|result|output|input)|mcp[._-](?:arguments?|result|payload)|"
    r"request[._-](?:body|headers?|id)|file[._-](?:path|content|name)|"
    r"repository[._-](?:url|path|name)|code[._-](?:content|diff|filepath|file[._-]path)|"
    r"process[._-](?:command(?:[._-]line)?|command[._-]args|executable[._-]path)|"
    r"command[._-](?:line|output)|shell[._-]command|db[._-](?:statement|query[._-]text)|"
    r"exception[._-](?:message|stacktrace)|error[._-]message|url[._-](?:full|path|query)|"
    r"http[._-](?:url|target)|user[._-](?:email|name|id|account[._-]id)|email|"
    r"account[._-]id|organization[._-]id|session[._-]id|conversation[._-]id|task[._-]id|"
    r"call[._-]id|trace[._-]id|span[._-]id|endpoint|host[._-]name|auth(?:orization)?|"
    r"cookie|api[._-]?key|access[._-]?token|refresh[._-]?token|password|secret|"
    r"absolute[._-]?path|path|cwd|transcript[._-]path)([._-]|$)"
)
SENSITIVE_VALUE = re.compile(
    r'''(?i)([a-z]:[\\/][^\s"'<>]*|\\\\[^\s"'<>]+|'''
    r'''(?:^|[\s="'])(?:/(?:[^/\s]+/)*[^/\s]+)|'''
    r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|"
    r"(?:bearer|basic)\s+[a-z0-9._~+/=-]+|"
    r"(?:sk|ghp|github_pat|xox[baprs])[-_][a-z0-9_-]{8,}|"
    r"(?:api[._-]?key|access[._-]?token|refresh[._-]?token|password|secret)\s*[:=]\s*[^\s,;]+)"
)
NUMERIC_CONTENT_METADATA = re.compile(
    r"(?i)(^|[._-])(?:prompt|completion|input|output)[._-]"
    r"(?:length|size|bytes|tokens|token[._-]count)$|"
    r"(^|[._-])(?:token[._-](?:count|usage)|usage)[._-]"
    r"(?:prompt|completion|input|output)(?:[._-](?:tokens|count))?$"
)
CONTENT_CONTAINER = re.compile(r"(?i)(^|[._-])(?:input|output|response|body|prompt|completion)$")
ANY_VALUE_TYPES = {
    "stringValue", "boolValue", "intValue", "doubleValue", "arrayValue", "kvlistValue", "bytesValue"
}


def _depth(depth: int) -> None:
    if depth > MAX_DEPTH:
        raise ValueError("OTLP structure exceeds supported nesting depth")


def _numeric(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) == {"intValue"}:
        item = value["intValue"]
        return isinstance(item, int) and not isinstance(item, bool) or (
            isinstance(item, str) and re.fullmatch(r"-?[0-9]+", item) is not None
        )
    if set(value) == {"doubleValue"}:
        return isinstance(value["doubleValue"], (int, float)) and not isinstance(value["doubleValue"], bool)
    return False


def _sanitize_attributes(items: Any, depth: int, prefix: str = "") -> tuple[list[dict[str, Any]], int]:
    _depth(depth)
    if not isinstance(items, list):
        raise ValueError("OTLP attributes must be an array")
    output: list[dict[str, Any]] = []
    removed = 0
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or "value" not in item:
            raise ValueError("Invalid OTLP attribute")
        key, value = item["key"], item["value"]
        full_key = f"{prefix}.{key}" if prefix else key
        numeric_size = bool(NUMERIC_CONTENT_METADATA.search(full_key)) and _numeric(value)
        structured_content = bool(CONTENT_CONTAINER.search(full_key)) and isinstance(value, dict) and set(value) == {"kvlistValue"}
        if (SENSITIVE_VALUE.search(full_key) or PROTECTED_KEY.search(full_key)
                or (SENSITIVE_KEY.search(full_key) and not numeric_size and not structured_content)):
            removed += 1
            continue
        safe_value, nested_removed = _sanitize_any(value, depth + 1, full_key)
        output.append({"key": key, "value": safe_value})
        removed += nested_removed
    return output, removed


def _sanitize_any(value: Any, depth: int, prefix: str = "") -> tuple[dict[str, Any], int]:
    _depth(depth)
    if not isinstance(value, dict) or len(value) > 1 or set(value) - ANY_VALUE_TYPES:
        raise ValueError("Invalid OTLP AnyValue")
    if not value:
        return {}, 0
    kind, item = next(iter(value.items()))
    if kind == "kvlistValue":
        if not isinstance(item, dict):
            raise ValueError("Invalid OTLP key/value list")
        attributes, removed = _sanitize_attributes(item.get("values", []), depth + 1, prefix)
        return {kind: {"values": attributes}}, removed
    if kind == "arrayValue":
        if not isinstance(item, dict) or not isinstance(item.get("values", []), list):
            raise ValueError("Invalid OTLP array")
        safe_items = [_sanitize_any(entry, depth + 1, prefix) for entry in item.get("values", [])]
        return {kind: {"values": [entry for entry, _ in safe_items]}}, sum(count for _, count in safe_items)
    if kind == "stringValue":
        if not isinstance(item, str):
            raise ValueError("Invalid OTLP string")
        return {kind: SENSITIVE_VALUE.sub(REDACTED, item)}, 0
    if kind == "bytesValue":
        # Unstructured binary values can conceal content that key/value redaction cannot inspect.
        return {"stringValue": REDACTED}, 1
    if kind == "boolValue" and not isinstance(item, bool):
        raise ValueError("Invalid OTLP boolean")
    if kind == "intValue" and not _numeric(value):
        raise ValueError("Invalid OTLP integer")
    if kind == "doubleValue" and not _numeric(value) and item not in ("NaN", "Infinity", "-Infinity"):
        raise ValueError("Invalid OTLP double")
    return {kind: item}, 0


def _sanitize_node(node: Any, signal: str, depth: int = 0) -> Any:
    _depth(depth)
    if isinstance(node, list):
        return [_sanitize_node(item, signal, depth + 1) for item in node]
    if isinstance(node, dict):
        output: dict[str, Any] = {}
        removed = 0
        for key, value in node.items():
            if SENSITIVE_VALUE.search(key):
                continue
            if key in ("attributes", "filteredAttributes"):
                output[key], count = _sanitize_attributes(value, depth + 1)
                removed += count
            elif key == "body" and signal == "logs":
                output[key] = dict(LOG_BODY)
            elif key == "traceState":
                output[key] = ""
            elif key == "description" and signal == "metrics":
                output[key] = ""
            elif key == "status" and isinstance(value, dict):
                output[key] = _sanitize_node(value, signal, depth + 1)
                if "message" in value:
                    output[key]["message"] = ""
            elif key in ("unit", "traceId", "spanId", "parentSpanId"):
                # Instrument units and structural correlation IDs are not indexing labels.
                if not isinstance(value, str):
                    raise ValueError("Invalid OTLP instrument or correlation identifier")
                output[key] = value
            else:
                output[key] = _sanitize_node(value, signal, depth + 1)
        if removed:
            # Keep producer counts intact; report archive removals in a separate metadata attribute.
            if "attributes" in output:
                count_key = "ai_observability.source_redacted_attribute_count"
                if not any(item["key"] == count_key for item in output["attributes"]):
                    output["attributes"].append({"key": count_key, "value": {"intValue": str(removed)}})
        return output
    if isinstance(node, str):
        return SENSITIVE_VALUE.sub(REDACTED, node)
    return node


def sanitize_document(signal: str, payload: Any) -> dict[str, Any]:
    """Return a sanitized independent OTLP document, retaining safe source structure."""
    key = RESOURCE_KEYS.get(signal)
    if key is None or not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ValueError("Invalid OTLP signal envelope")
    return _sanitize_node(payload, signal)


class ArchiveStore:
    """Serialize per-signal appends and acknowledge only after durable flush."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.locks = {signal: threading.Lock() for signal in RESOURCE_KEYS}
        for signal in RESOURCE_KEYS:
            fd = os.open(self.directory / f"{signal}.jsonl", os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                self._recover_incomplete_tail(signal, fd)
                os.fsync(fd)
            finally:
                os.close(fd)
        self._fsync_directory()

    def _fsync_directory(self) -> None:
        if os.name == "posix":
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def _recover_incomplete_tail(self, signal: str, fd: int) -> None:
        end = os.lseek(fd, 0, os.SEEK_END)
        if end == 0:
            return
        os.lseek(fd, end - 1, os.SEEK_SET)
        if os.read(fd, 1) == b"\n":
            return

        complete_end = 0
        position = end
        while position:
            start = max(0, position - 65536)
            os.lseek(fd, start, os.SEEK_SET)
            block = os.read(fd, position - start)
            if len(block) != position - start:
                raise OSError("Archive recovery read was incomplete")
            newline = block.rfind(b"\n")
            if newline >= 0:
                complete_end = start + newline + 1
                break
            position = start

        recovery_path = self.directory / f"recovered-{signal}-{uuid.uuid4().hex}.partial"
        recovery_fd = os.open(recovery_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.lseek(fd, complete_end, os.SEEK_SET)
            remaining = end - complete_end
            while remaining:
                block = os.read(fd, min(remaining, 65536))
                if not block:
                    raise OSError("Archive recovery read made no progress")
                pending = memoryview(block)
                while pending:
                    written = os.write(recovery_fd, pending)
                    if written == 0:
                        raise OSError("Archive recovery write made no progress")
                    pending = pending[written:]
                remaining -= len(block)
            os.fsync(recovery_fd)
        finally:
            os.close(recovery_fd)

        # Persist both the tail and its directory entry before changing the main
        # file. Any earlier failure leaves all original source bytes in place.
        self._fsync_directory()
        os.ftruncate(fd, complete_end)
        os.fsync(fd)

    def append(self, signal: str, document: dict[str, Any]) -> None:
        if signal not in RESOURCE_KEYS:
            raise ValueError("Unsupported signal")
        line = (json.dumps(document, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        with self.locks[signal]:
            fd = os.open(self.directory / f"{signal}.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            start = os.lseek(fd, 0, os.SEEK_END)
            try:
                remaining = memoryview(line)
                while remaining:
                    written = os.write(fd, remaining)
                    if written == 0:
                        raise OSError("Archive write made no progress")
                    remaining = remaining[written:]
                os.fsync(fd)
            except OSError:
                # Roll back only this unacknowledged append, never existing records.
                os.ftruncate(fd, start)
                raise
            finally:
                os.close(fd)


class ArchiveHandler(BaseHTTPRequestHandler):
    store: ArchiveStore
    concurrency = threading.BoundedSemaphore(8)

    def log_message(self, format: str, *args: Any) -> None:
        # BaseHTTPRequestHandler includes request paths and errors: never log those.
        return

    def _reply(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def do_GET(self) -> None:
        self._reply(200 if self.path == "/healthz" else 404)

    def do_POST(self) -> None:
        signal = next((value for value in RESOURCE_KEYS if self.path == f"/v1/{value}"), None)
        if signal is None:
            self._reply(404)
            return
        if self.headers.get("Content-Encoding", "identity") not in ("identity", ""):
            self._reply(415)
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self._reply(415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._reply(400)
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._reply(413)
            return
        if not self.concurrency.acquire(blocking=False):
            self._reply(503)
            return
        try:
            self.connection.settimeout(15)
            content = self.rfile.read(length)
            if len(content) != length:
                raise ValueError("Incomplete request")
            payload = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid number")))
            sanitized = sanitize_document(signal, payload)
            self.store.append(signal, sanitized)
        except (ValueError, UnicodeError, RecursionError):
            self._reply(400)
        except OSError:
            self._reply(503)
        else:
            self._reply(200)
        finally:
            self.concurrency.release()


class ArchiveHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        # Never include arbitrary request content or exception details in server logs.
        return


def main() -> None:
    ArchiveHandler.store = ArchiveStore(Path(os.environ.get("SOURCE_ARCHIVE_DIR", "/var/lib/otelcol/source")))
    server = ArchiveHTTPServer(("0.0.0.0", 4320), ArchiveHandler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
