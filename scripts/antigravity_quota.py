"""Collect official, zero-turn Antigravity quota after a local account check."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scripts import antigravity_quota_snapshot as contract

MAX_REPORT_BYTES = 1024 * 1024


class QuotaCollectionError(RuntimeError):
    """Only fixed diagnostic codes may cross the provider boundary."""


@contextmanager
def _report_workspace(root: Path | None):
    temporary = tempfile.TemporaryDirectory(
        prefix="antigravity-quota-", dir=root, ignore_cleanup_errors=True,
    )
    path = Path(temporary.name)
    parent = path.resolve().parent
    try:
        yield temporary.name
    finally:
        # agy can return its built-in report before a status-line child has
        # released the working directory on Windows. Cleanup is best effort
        # and bounded; a transient cwd lock must not invalidate a valid report.
        for _ in range(20):
            if path.resolve().parent != parent or path.is_symlink():
                break
            temporary.cleanup()
            if not path.exists():
                break
            time.sleep(0.1)


def read_official_report(
    *, agy_bin: str | None = None, timeout: float = 20,
    scratch_root: Path | None = None,
) -> dict[str, Any]:
    if not 1 <= timeout <= 60:
        raise QuotaCollectionError("invalid_timeout")
    executable = Path(agy_bin).expanduser() if agy_bin else Path(shutil.which("agy") or "")
    if not executable.is_file():
        raise QuotaCollectionError("cli_not_found")
    executable = executable.resolve()
    if not _is_native_cli_installation(str(executable)):
        raise QuotaCollectionError("unverified_cli_installation")
    try:
        version = subprocess.run(
            [str(executable), "--version"], capture_output=True, text=True,
            timeout=3, check=False,
        )
        match = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)\s*", version.stdout)
        if version.returncode or not match or tuple(map(int, match.groups())) < (1, 1, 11):
            raise QuotaCollectionError("unsupported_cli_version")
        if scratch_root is not None:
            scratch_root.mkdir(parents=True, exist_ok=True)
        with _report_workspace(scratch_root) as work:
            # Built-in reports need no exporter callback; suppress callback
            # side effects if a future client initializes its status line.
            environment = os.environ.copy()
            environment.update({
                "AI_OBSERVABILITY_DRY_RUN": "true",
                "AI_OBSERVABILITY_STATE_DIR": str(Path(work) / "state"),
                "AI_OBSERVABILITY_SESSION_SALT": "quota-report-no-session",
                "AI_OBSERVABILITY_SERVICE_NAMESPACE": "ai-collaboration-fixture",
            })
            environment.pop("AI_OBSERVABILITY_CAPTURE_DIR", None)
            result = subprocess.run(
                [str(executable), "--log-file", os.devnull, "-p", "/usage",
                 "--output-format", "json", "--print-timeout", f"{timeout:g}s"],
                cwd=work, env=environment, capture_output=True, text=True,
                timeout=timeout + 5, check=False,
            )
        if result.returncode:
            raise QuotaCollectionError("cli_report_failed")
        if len(result.stdout.encode("utf-8")) > MAX_REPORT_BYTES:
            raise QuotaCollectionError("cli_report_too_large")
        report = json.loads(result.stdout)
        if not isinstance(report, dict):
            raise QuotaCollectionError("invalid_cli_report")
        return report
    except QuotaCollectionError:
        raise
    except subprocess.TimeoutExpired:
        raise QuotaCollectionError("cli_report_timeout") from None
    except (OSError, ValueError):
        raise QuotaCollectionError("cli_report_unavailable") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise QuotaCollectionError("collector_redirect_refused")


def export_metrics(payload: dict[str, Any], endpoint: str, timeout: float = 3) -> None:
    parsed = urllib.parse.urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise QuotaCollectionError("collector_endpoint_must_be_loopback")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/metrics",
        data=json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(16385)
        if len(raw) > 16384:
            raise QuotaCollectionError("collector_response_too_large")
        result = json.loads(raw or b"{}")
        partial = result.get("partialSuccess", {})
        if partial.get("rejectedDataPoints") not in (None, 0, "0"):
            raise QuotaCollectionError("collector_rejected_metrics")
    except QuotaCollectionError:
        raise
    except (OSError, ValueError, AttributeError):
        raise QuotaCollectionError("collector_export_failed") from None


def _is_native_cli_installation(agy_bin: str | None) -> bool:
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        return False
    installed = Path(os.environ["LOCALAPPDATA"]) / "agy/bin/agy.exe"
    selected = Path(agy_bin) if agy_bin else Path(shutil.which("agy") or "")
    return (installed.is_file() and selected.is_file()
            and os.path.normcase(str(selected.resolve())) == os.path.normcase(str(installed.resolve())))


def collect_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    from scripts.antigravity_local import (
        LocalVerificationError, collect_verified, refresh_expired_cli_binding,
    )

    def read_report():
        return read_official_report(
            agy_bin=args.agy_bin, timeout=args.timeout, scratch_root=args.scratch_root,
        )

    try:
        report, _proof = collect_verified(read_report)
    except LocalVerificationError as error:
        if error.code != "cli_auth_expired":
            raise
        # Only the fixed native installation may refresh credentials. Explicit
        # --agy-bin paths must resolve to that same verified installation.
        if not _is_native_cli_installation(args.agy_bin):
            raise QuotaCollectionError("native_refresh_unavailable") from None
        refresh_expired_cli_binding(read_report)
        # The probe result is discarded. A separate report must pass the full
        # current, stable-account check before any quota can be exported.
        report, _proof = collect_verified(read_report)
    snapshot = contract.normalize_quota_report(report, dt.datetime.now(dt.timezone.utc))
    snapshot["identity_status"] = "matched"
    snapshot["identity_verification"] = {
        "method": "native-cli-keyring-and-desktop-rpc",
        "account_stable_during_report": True,
    }
    if args.export:
        export_metrics(contract.build_metrics_payload(
            snapshot, identity_match=True, service_namespace=args.service_namespace,
            profile=args.profile,
        ), args.endpoint)
    snapshot["export_status"] = "otlp-accepted" if args.export else "not-requested"
    return snapshot


def _write_result(result: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if output is None:
        print(rendered, end="", flush=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, output)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--export", action="store_true", help="Send verified account quota to the local Collector.")
    parser.add_argument("--agy-bin", help="Explicit path to the same native CLI installation under LOCALAPPDATA/agy/bin.")
    parser.add_argument("--timeout", type=float, default=20, help="Official report deadline, 1-60 seconds.")
    parser.add_argument("--scratch-root", type=Path, help="Disposable scratch parent, e.g. a verified RAM disk task directory.")
    parser.add_argument("--endpoint", default=os.getenv("AI_OBSERVABILITY_OTLP_HTTP_ENDPOINT", "http://127.0.0.1:4318"))
    parser.add_argument("--service-namespace", default="ai-collaboration")
    parser.add_argument("--profile", choices=sorted(contract.PROFILES), default="personal-local")
    parser.add_argument("--output", type=Path, help="Write only sanitized metadata to this local file.")
    parser.add_argument("--watch", action="store_true", help="Keep collecting while this process runs; no model requests.")
    parser.add_argument("--interval-seconds", type=float, default=120, help="Polling interval, 30-3600 seconds.")


def run(args: argparse.Namespace) -> int:
    if not 1 <= args.timeout <= 60 or not 30 <= args.interval_seconds <= 3600:
        raise QuotaCollectionError("invalid_collection_limits")
    while True:
        try:
            snapshot = collect_snapshot(args)
            _write_result(snapshot, args.output)
            success = True
        except Exception as exc:
            # Provider messages, process output and identity values never reach
            # diagnostics, even when a provider returns an unexpected exception.
            from scripts.antigravity_local import LocalVerificationError
            code = str(exc) if isinstance(exc, (QuotaCollectionError, contract.QuotaReportError, LocalVerificationError)) else "collection_unavailable"
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
                code = "collection_unavailable"
            if args.export:
                try:
                    export_metrics(contract.build_identity_status_payload(
                        False, dt.datetime.now(dt.timezone.utc),
                        service_namespace=args.service_namespace, profile=args.profile,
                    ), args.endpoint)
                except Exception:
                    pass
            _write_result({"source": contract.SOURCE, "status": "unavailable", "error": code}, args.output)
            success = False
        if not args.watch:
            return 0 if success else 1
        time.sleep(args.interval_seconds)
