"""Opt-in official Codex usage reads with a fixed, content-free output contract.

Native thread identifiers are internal lookup keys. The report layer must HMAC
them before export; neither this module nor its transport writes telemetry.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from scripts.session_usage import EFFORTS, MODELS

PLANS = frozenset({
    "free", "go", "plus", "pro", "prolite", "team",
    "self_serve_business_prolite", "self_serve_business_usage_based", "business",
    "ent26", "enterprise_cbp_automation", "enterprise_cbp_usage_based",
    "enterprise", "edu", "edu_plus", "edu_pro", "unknown",
})
DIAGNOSTIC_FIELDS = (
    "official_requests", "official_unavailable", "official_thread_usage_missing",
    "official_invalid_records",
)
MAX_INT64 = 2**63 - 1
MAX_LINE = 2 * 1024 * 1024


class _Unavailable(RuntimeError):
    """A transport failed; never retain the provider's message or stderr."""


class _Invalid(ValueError):
    """A provider value is outside the reviewed metadata contract."""


def _integer(value: Any, *, nullable: bool = False, signed: bool = False) -> int | None:
    if value is None and nullable:
        return None
    minimum = -2**63 if signed else 0
    if type(value) is not int or not minimum <= value <= MAX_INT64:
        raise _Invalid()
    return value


def _field(value: dict[str, Any], camel: str, snake: str) -> Any:
    return value.get(camel) if camel in value else value.get(snake)


def _observed_at(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 128:
        raise _Invalid()
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise _Invalid()
        return parsed.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        raise _Invalid() from None


def _window(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _Invalid()
    percent = _field(raw, "usedPercent", "used_percent")
    minutes = _field(raw, "windowDurationMins", "window_minutes")
    resets = _field(raw, "resetsAt", "resets_at")
    if percent is not None and (
        type(percent) not in (int, float) or not 0 <= percent <= 100 or not math.isfinite(percent)
    ):
        raise _Invalid()
    if minutes is not None and not 1 <= _integer(minutes) <= 2**31 - 1:
        raise _Invalid()
    if resets is not None:
        _integer(resets)
    if percent is None or minutes is None or resets is None:
        return None
    return {"used_percent": percent, "window_minutes": minutes, "resets_at": _integer(resets)}


def _credits(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _Invalid()
    has_credits = _field(raw, "hasCredits", "has_credits")
    unlimited = raw.get("unlimited")
    if type(has_credits) is not bool or type(unlimited) is not bool:
        raise _Invalid()
    balance = raw.get("balance")
    if balance is not None:
        if not isinstance(balance, str) or len(balance) > 128:
            raise _Invalid()
        try:
            number = Decimal(balance)
        except InvalidOperation:
            raise _Invalid() from None
        if not number.is_finite() or number < 0 or (number and abs(number.adjusted()) > 127):
            raise _Invalid()
        balance = "0" if not number else format(number, "f")
        if "." in balance:
            balance = balance.rstrip("0").rstrip(".")
        if len(balance) > 128:
            raise _Invalid()
    return {"has_credits": has_credits, "unlimited": unlimited, "balance": balance}


def normalize_rate_limits(raw: Any, observed_at: str) -> dict[str, Any] | None:
    """Normalize a provider response or a snake_case offline rate snapshot."""
    if not isinstance(raw, dict):
        return None
    outer = raw
    by_limit = raw.get("rateLimitsByLimitId")
    if isinstance(by_limit, dict) and isinstance(by_limit.get("codex"), dict):
        raw = by_limit["codex"]
    elif "rateLimits" in raw:
        raw = raw.get("rateLimits")
    elif "rateLimitsByLimitId" in raw:
        return None
    if not isinstance(raw, dict) or not any(
        key in raw for key in ("primary", "secondary", "credits", "planType", "plan_type")
    ):
        return None
    try:
        plan = _field(raw, "planType", "plan_type")
        ordinary_source = raw if any(name in raw for name in (
            "ordinaryUsageAllowed", "ordinary_usage_allowed",
        )) else outer
        ordinary = _field(ordinary_source, "ordinaryUsageAllowed", "ordinary_usage_allowed")
        if ordinary is not None and type(ordinary) is not bool:
            raise _Invalid()
        return {
            "observed_at": _observed_at(observed_at),
            "plan_type": plan if isinstance(plan, str) and plan in PLANS else "unknown",
            "credits": _credits(raw.get("credits")),
            "primary": _window(raw.get("primary")),
            "secondary": _window(raw.get("secondary")),
            "ordinary_usage_allowed": ordinary,
        }
    except _Invalid:
        return None


def normalize_thread_usage(raw: Any) -> dict[str, Any] | None:
    """Normalize the inner provider threadUsage object, retaining no content."""
    if not isinstance(raw, dict):
        return None
    identity, groups = raw.get("threadId"), raw.get("groups")
    if not isinstance(identity, str) or not 0 < len(identity) <= 512 or not isinstance(groups, list):
        return None
    try:
        result = {
            "thread_id": identity,
            "estimated_usage_credits_micros": _integer(raw.get("estimatedUsageCreditsMicros")),
            "estimated_usage_usd_micros": _integer(raw.get("estimatedUsageUsdMicros"), nullable=True),
            "groups": [],
        }
        for raw_group in groups:
            if not isinstance(raw_group, dict):
                raise _Invalid()
            model, effort, speed = (raw_group.get(name) for name in ("model", "reasoningEffort", "speed"))
            group = {
                "model_id": model if isinstance(model, str) and model in MODELS else "unmapped",
                "reasoning_effort": effort if isinstance(effort, str) and effort in EFFORTS else "unknown",
                "speed": speed if isinstance(speed, str) and speed in ("standard", "fast", "ultrafast") else "unknown",
                "estimated_usage_credits_micros": _integer(raw_group.get("estimatedUsageCreditsMicros")),
            }
            for snake, camel in (
                ("net_new_input_tokens", "netNewInputTokens"),
                ("cached_input_tokens", "cachedInputTokens"),
                ("input_tokens", "inputTokens"), ("output_tokens", "outputTokens"),
                ("total_tokens", "totalTokens"),
            ):
                group[snake] = _integer(raw_group.get(camel), nullable=True)
            input_tokens, output_tokens, total_tokens = (group[name] for name in (
                "input_tokens", "output_tokens", "total_tokens",
            ))
            if (all(value is not None for value in (input_tokens, output_tokens, total_tokens))
                    and input_tokens + output_tokens != total_tokens):
                raise _Invalid()
            cached = group["cached_input_tokens"]
            if input_tokens is not None and cached is not None and cached > input_tokens:
                raise _Invalid()
            result["groups"].append(group)
        return result
    except _Invalid:
        return None


def _mcp_names() -> set[str]:
    """Read configured server names for launch overrides; never export config."""
    import tomllib

    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    files = [codex_home / "config.toml"]
    if os.name == "nt":
        files.append(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "OpenAI/Codex/config.toml")
    else:
        files.append(Path("/etc/codex/config.toml"))
    names: set[str] = set()
    for path in files:
        try:
            with path.open("rb") as stream:
                config = tomllib.load(stream)
            servers = config.get("mcp_servers")
            if isinstance(servers, dict):
                for name in servers:
                    if (not isinstance(name, str) or not 0 < len(name) <= 256
                            or not re.fullmatch(r"[A-Za-z0-9_-]+", name)):
                        raise _Unavailable()
                    names.add(name)
            profile = config.get("profile")
            if path == files[0] and isinstance(profile, str) and 0 < len(profile) <= 128 and not any(
                char in profile for char in ("/", "\\", ":", "\x00")
            ):
                files.append(codex_home / f"{profile}.config.toml")
        except FileNotFoundError:
            continue
        except (OSError, ValueError, subprocess.SubprocessError):
            raise _Unavailable() from None
    return names


class _StdioClient:
    """One disposable app-server process; all errors and cleanup stay bounded."""

    def __init__(self, command: list[str], timeout: float):
        self.timeout = timeout
        self._next_id = 0
        self._messages: queue.Queue[Any] = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._workdir = tempfile.TemporaryDirectory(prefix="codex-usage-read-")
        self.process = None
        self._reader = None
        try:
            self.process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, shell=False, text=True,
                encoding="utf-8", errors="strict", bufsize=1,
                cwd=self._workdir.name,
            )
            self._reader = threading.Thread(target=self._read, daemon=True)
            self._reader.start()
        except (OSError, ValueError):
            self.close()
            raise _Unavailable() from None

    def _enqueue(self, message: Any) -> None:
        while not self._stop.is_set():
            try:
                self._messages.put(message, timeout=0.1)
                return
            except queue.Full:
                continue

    def _read(self) -> None:
        try:
            assert self.process is not None and self.process.stdout is not None
            while not self._stop.is_set():
                line = self.process.stdout.readline(MAX_LINE + 1)
                if not line or len(line) > MAX_LINE:
                    self._enqueue(None)
                    return
                try:
                    message = json.loads(line)
                except ValueError:
                    self._enqueue(None)
                    return
                self._enqueue(message)
        except (OSError, UnicodeError, ValueError):
            self._enqueue(None)

    def _send(self, message: dict[str, Any]) -> None:
        try:
            assert self.process is not None and self.process.stdin is not None
            self.process.stdin.write(json.dumps(message, separators=(",", ":"), allow_nan=False) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise _Unavailable() from None

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._send({"method": method, "id": request_id, "params": params})
        deadline = time.monotonic() + self.timeout
        for _ in range(1024):
            try:
                message = self._messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise _Unavailable() from None
            if not isinstance(message, dict):
                raise _Unavailable()
            if type(message.get("id")) is not int or message["id"] != request_id:
                continue
            if "error" in message or not isinstance(message.get("result"), dict):
                raise _Unavailable()
            return message["result"]
        raise _Unavailable()

    def close(self) -> None:
        self._stop.set()
        if self.process is not None:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
        if self._reader is not None:
            self._reader.join(timeout=0.2)
        try:
            self._workdir.cleanup()
        except OSError:
            pass


def collect_account_usage(thread_ids: list[str], *, codex_bin: str | None = None,
                          timeout: float = 20.0) -> dict[str, Any]:
    """Read account metadata and official thread estimates only after opt-in.

    Timeout applies to each request. This never initiates a turn or logs in.
    Failed reads are counters, allowing independently available reads to remain.
    """
    diagnostics = dict.fromkeys(DIAGNOSTIC_FIELDS, 0)
    result = {"account_snapshot": None, "thread_estimates": [],
              "thread_observations": {}, "diagnostics": diagnostics}
    if type(timeout) not in (int, float) or not 1 <= timeout <= 60 or not math.isfinite(timeout):
        diagnostics["official_invalid_records"] += 1
        return result
    if not isinstance(thread_ids, list):
        diagnostics["official_invalid_records"] += 1
        return result
    identities = []
    seen = set()
    for identity in thread_ids:
        if not isinstance(identity, str) or not 0 < len(identity) <= 512:
            diagnostics["official_invalid_records"] += 1
        elif identity not in seen:
            identities.append(identity)
            seen.add(identity)
    client = None
    try:
        executable = codex_bin or shutil.which("codex")
        if not isinstance(executable, str) or not executable:
            raise _Unavailable()
        command = [executable, "-c", "analytics.enabled=false"]
        for name in sorted(_mcp_names()):
            command.extend(["-c", f"mcp_servers.{name}.enabled=false"])
        command.extend(["app-server", "--listen", "stdio://"])
        client = _StdioClient(command, float(timeout))
        client.request("initialize", {"clientInfo": {
            "name": "ai_observability_usage_read", "title": "Local usage accounting", "version": "1",
        }, "capabilities": None})
        client.notify("initialized", {})
        account_plan = "unknown"

        def read(method: str, params: dict[str, Any]) -> dict[str, Any] | None:
            diagnostics["official_requests"] += 1
            try:
                return client.request(method, params)
            except _Unavailable:
                diagnostics["official_unavailable"] += 1
                return None

        account = read("account/read", {"refreshToken": False})
        if account is not None:
            metadata = account.get("account")
            if isinstance(metadata, dict) and metadata.get("type") == "chatgpt":
                plan = metadata.get("planType")
                account_plan = plan if isinstance(plan, str) and plan in PLANS else "unknown"
        rates = read("account/rateLimits/read", {
            "supportsLunaReserve": False, "excludeResetCreditDetails": True,
        })
        if rates is not None:
            observed = dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            snapshot = normalize_rate_limits(rates, observed)
            if snapshot is None:
                diagnostics["official_invalid_records"] += 1
            else:
                if snapshot["plan_type"] == "unknown":
                    snapshot["plan_type"] = account_plan
                result["account_snapshot"] = snapshot
        for identity in identities:
            response = read("account/usage/read", {"threadId": identity})
            observed = dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            result["thread_observations"][identity] = observed
            if response is None:
                continue
            raw_usage = response.get("threadUsage")
            if raw_usage is None:
                diagnostics["official_thread_usage_missing"] += 1
                continue
            estimate = normalize_thread_usage(raw_usage)
            if estimate is None or estimate["thread_id"] != identity:
                diagnostics["official_invalid_records"] += 1
            else:
                estimate["observed_at"] = observed
                result["thread_estimates"].append(estimate)
    except (_Unavailable, OSError, ValueError):
        diagnostics["official_unavailable"] += 1
    finally:
        if client is not None:
            client.close()
    return result
