"""Private, read-only bindings for locally installed Antigravity clients.

Authentication material and account identifiers stay in this process. Public
verification results contain fixed codes and booleans only. The native ID token
is a local account binding, not a remotely attested or signature-verified JWT.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import ssl
import struct
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Callable


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
KEYRING_TARGET = "gemini:antigravity"
RPC_PREFIX = "/exa.language_server_pb.LanguageServerService/"
REVIEWED_DESKTOP_VERSION = "2.25.0"
ALLOWED_METHODS = frozenset({"GetUserStatus", "GetCascadeTrajectoryGeneratorMetadata"})
_CASCADE_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z", re.ASCII)


class LocalVerificationError(RuntimeError):
    """A fixed, non-sensitive failure code suitable for operator output."""

    def __init__(self, code: str, evidence: dict | None = None):
        super().__init__(code)
        self.code = code
        self.evidence = evidence or {"status": "unavailable", "reason": code}


@dataclass(repr=False)
class _Identity:
    email: str
    subject: str
    fingerprint: bytes
    id_token_current: bool
    access_token_current: bool


@dataclass(repr=False)
class _Binding:
    cli: _Identity
    desktop_email: str


def _credential_blob() -> bytes:
    if os.name != "nt":
        raise LocalVerificationError("windows_required")
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class Credential(ctypes.Structure):
        _fields_ = [
            ("flags", wintypes.DWORD), ("type", wintypes.DWORD),
            ("target", wintypes.LPWSTR), ("comment", wintypes.LPWSTR),
            ("written", FileTime), ("size", wintypes.DWORD),
            ("blob", ctypes.POINTER(ctypes.c_ubyte)),
            ("persist", wintypes.DWORD), ("attribute_count", wintypes.DWORD),
            ("attributes", ctypes.c_void_p), ("alias", wintypes.LPWSTR),
            ("username", wintypes.LPWSTR),
        ]

    library = ctypes.WinDLL("Advapi32", use_last_error=True)
    library.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    library.CredReadW.restype = wintypes.BOOL
    library.CredFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.POINTER(Credential)()
    if not library.CredReadW(KEYRING_TARGET, 1, 0, ctypes.byref(pointer)):
        raise LocalVerificationError("cli_keyring_unavailable")
    try:
        credential = pointer.contents
        if not 0 < credential.size <= 65536:
            raise LocalVerificationError("cli_keyring_invalid")
        return ctypes.string_at(credential.blob, credential.size)
    finally:
        library.CredFree(pointer)


def _expiry_is_current(value: object, now: float) -> bool:
    if not isinstance(value, str):
        return False
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return expiry.tzinfo is not None and expiry.timestamp() > now
    except (ValueError, OverflowError):
        return False


def _identity_from_blob(blob: bytes, now: float | None = None) -> _Identity:
    now = time.time() if now is None else now
    try:
        data = json.loads(blob.decode("utf-8"))
        encoded = data["id_token"].split(".")
        if len(encoded) != 3:
            raise ValueError
        claims = json.loads(base64.urlsafe_b64decode(
            encoded[1] + "=" * (-len(encoded[1]) % 4)
        ))
        if claims.get("iss") not in {
            "https://accounts.google.com", "accounts.google.com"
        }:
            raise ValueError
        email = claims["email"]
        subject = claims["sub"]
        expiry = claims["exp"]
        if (not isinstance(email, str) or "@" not in email
                or email != email.strip() or not isinstance(subject, str)
                or not subject or claims.get("email_verified") is not True
                or not isinstance(expiry, (int, float)) or isinstance(expiry, bool)):
            raise ValueError
        token = data["token"]
        access_current = (
            isinstance(token.get("access_token"), str)
            and bool(token["access_token"])
            and _expiry_is_current(token.get("expiry"), now)
        )
        return _Identity(email.casefold(), subject, hashlib.sha256(blob).digest(),
                         expiry > now, access_current)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise LocalVerificationError("cli_keyring_invalid") from None


def _powershell_json(command: str) -> object:
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-Command", "$ErrorActionPreference='Stop';" + command],
            capture_output=True, timeout=15, check=False,
        )
        if completed.returncode or len(completed.stdout) > MAX_RESPONSE_BYTES:
            raise LocalVerificationError("desktop_process_unavailable")
        return json.loads(completed.stdout.decode("utf-8-sig"))
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
        raise LocalVerificationError("desktop_process_unavailable") from None


def _processes() -> list[dict]:
    if os.name != "nt":
        raise LocalVerificationError("windows_required")
    command = """
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $rows=@(Get-CimInstance Win32_Process -Filter "Name = 'language_server.exe'" |
      ForEach-Object {
        $owner=Invoke-CimMethod -InputObject $_ -MethodName GetOwnerSid
        if($owner.Sid -eq $sid) {
          [PSCustomObject]@{pid=[int]$_.ProcessId;executable=$_.ExecutablePath;
            command_line=$_.CommandLine;created=$_.CreationDate.ToString('o')}
        }
      })
    ConvertTo-Json -InputObject $rows -Compress
    """
    rows = _powershell_json(command)
    expected = Path(os.environ.get("LOCALAPPDATA", "")) / (
        "Programs/Antigravity/resources/bin/language_server.exe"
    )
    if not expected.is_file() or not isinstance(rows, list):
        raise LocalVerificationError("desktop_process_unavailable")
    return [row for row in rows if isinstance(row, dict)
            and isinstance(row.get("executable"), str)
            and os.path.normcase(os.path.abspath(row["executable"]))
            == os.path.normcase(os.path.abspath(expected))]


def _flag(command: str, name: str) -> str | None:
    match = re.search(
        r'(?:^|\s)--?' + re.escape(name) + r'(?:=|\s+)(?:"([^"\r\n]+)"|([^\s"\r\n]+))',
        command,
    )
    return (match.group(1) or match.group(2)) if match else None


def get_desktop_version() -> str:
    """Read the official installed package version without launching an agent."""
    archive = Path(os.environ.get("LOCALAPPDATA", "")) / (
        "Programs/Antigravity/resources/app.asar"
    )
    try:
        with archive.open("rb") as stream:
            prefix = stream.read(16)
            if len(prefix) != 16:
                raise ValueError
            _, header_size, _, json_size = struct.unpack("<4I", prefix)
            if not 0 < json_size < header_size <= 4 * 1024 * 1024:
                raise ValueError
            header = json.loads(stream.read(json_size))
            package = header["files"]["package.json"]
            size, offset = package["size"], int(package["offset"])
            if not isinstance(size, int) or not 0 < size <= 65536 or offset < 0:
                raise ValueError
            stream.seek(8 + header_size + offset)
            data = json.loads(stream.read(size))
        version = data.get("version")
        if data.get("name") != "antigravity" or not isinstance(version, str):
            raise ValueError
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError
        return version
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise LocalVerificationError("desktop_version_unavailable") from None


def _validate_request(method: str, payload: dict) -> None:
    if method not in ALLOWED_METHODS:
        raise LocalVerificationError("desktop_method_rejected")
    if not isinstance(payload, dict):
        raise LocalVerificationError("desktop_request_rejected")
    if method == "GetUserStatus":
        if payload:
            raise LocalVerificationError("desktop_request_rejected")
        return
    # The reviewed 2.25.0 shipped Request DescriptorProto has exactly these
    # fields. IncludeMessages is always false: message content is not requested.
    if (set(payload) != {"cascadeId", "generatorMetadataOffset", "includeMessages"}
            or not isinstance(payload["cascadeId"], str)
            or not _CASCADE_ID.fullmatch(payload["cascadeId"])
            or type(payload["generatorMetadataOffset"]) is not int
            or not 0 <= payload["generatorMetadataOffset"] < 2**32
            or payload["includeMessages"] is not False):
        raise LocalVerificationError("desktop_request_rejected")
    if get_desktop_version() != REVIEWED_DESKTOP_VERSION:
        raise LocalVerificationError("desktop_version_review_required")


def _owned_ports(pid: int) -> list[int]:
    rows = _powershell_json(
        "$ports=@(Get-NetTCPConnection -State Listen | Where-Object {"
        f"$_.OwningProcess -eq {int(pid)} -and "
        "$_.LocalAddress -in @('127.0.0.1','::1','0.0.0.0','::')} | "
        "Select-Object -ExpandProperty LocalPort -Unique);"
        "ConvertTo-Json -InputObject $ports -Compress"
    )
    return [port for port in rows if isinstance(port, int) and 0 < port < 65536]


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LocalVerificationError("desktop_redirect_rejected")


class DesktopClient:
    """Read-only metadata RPC client pinned to the current user's local server."""

    def __init__(self):
        self._process = None
        self._port = None
        self._csrf = None
        self._opener = None
        self._initial_status = None

    def __enter__(self):
        for process in _processes():
            command = process.get("command_line", "")
            csrf = _flag(command, "csrf_token")
            if not csrf or not isinstance(process.get("pid"), int):
                continue
            owned = _owned_ports(process["pid"])
            configured = _flag(command, "https_server_port")
            ports = owned
            if configured and configured.isdecimal() and int(configured):
                ports = [int(configured)] if int(configured) in owned else []
            for port in ports:
                try:
                    certificate = ssl.get_server_certificate(
                        ("127.0.0.1", port), timeout=2
                    )
                    context = ssl.create_default_context(cadata=certificate)
                    context.check_hostname = False
                    self._process, self._port, self._csrf = process, port, csrf
                    self._opener = urllib.request.build_opener(
                        urllib.request.ProxyHandler({}), _RejectRedirect(),
                        urllib.request.HTTPSHandler(context=context),
                    )
                    self._initial_status = self.request("GetUserStatus", {})
                    return self
                except Exception:
                    self._opener = None
        self.close()
        raise LocalVerificationError("desktop_rpc_unavailable")

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def close(self):
        self._process = self._port = self._csrf = self._opener = None
        self._initial_status = None

    def _check_process(self):
        process = self._process
        if process is None or not any(
            row.get("pid") == process["pid"]
            and row.get("created") == process.get("created")
            and _flag(row.get("command_line", ""), "csrf_token") == self._csrf
            for row in _processes()
        ) or self._port not in _owned_ports(process["pid"]):
            raise LocalVerificationError("desktop_process_changed")

    def request(self, method: str, payload: dict) -> dict:
        _validate_request(method, payload)
        if self._opener is None:
            raise LocalVerificationError("desktop_client_unavailable")
        self._check_process()
        body = dict(payload)
        body["metadata"] = {
            "ideName": "antigravity", "extensionName": "antigravity",
            "ideVersion": "2.25.0", "locale": "en",
        }
        request = urllib.request.Request(
            f"https://127.0.0.1:{self._port}{RPC_PREFIX}{method}",
            data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json",
                     "Connect-Protocol-Version": "1",
                     "X-Codeium-Csrf-Token": self._csrf},
        )
        try:
            with self._opener.open(request, timeout=5) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise LocalVerificationError("desktop_response_too_large")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise LocalVerificationError("desktop_response_invalid")
            return result
        except LocalVerificationError:
            raise
        except Exception:
            raise LocalVerificationError("desktop_rpc_failed") from None


def _binding(*, require_current: bool = True) -> _Binding:
    cli = _identity_from_blob(_credential_blob())
    evidence = {
        "status": "unavailable", "reason": "cli_auth_expired",
        "cli_id_token_current": cli.id_token_current,
        "cli_access_token_current": cli.access_token_current,
    }
    if require_current and (not cli.id_token_current or not cli.access_token_current):
        raise LocalVerificationError("cli_auth_expired", evidence)
    with DesktopClient() as client:
        response = client._initial_status
        email = response.get("userStatus", {}).get("email")
        if not isinstance(email, str) or not email or email != email.strip():
            raise LocalVerificationError("desktop_identity_unavailable")
        return _Binding(cli, email.casefold())


def _evidence(binding: _Binding) -> dict:
    same = hmac.compare_digest(binding.cli.email.encode(),
                               binding.desktop_email.encode())
    return {
        "status": "matched" if same else "mismatch",
        "cli_identity_source": "windows_native_keyring",
        "desktop_identity_source": "same_user_local_metadata_rpc",
        "cli_id_token_current": binding.cli.id_token_current,
        "cli_access_token_current": binding.cli.access_token_current,
        "local_binding_only": True,
        "same_account": same,
    }


def verify_same_account() -> dict:
    """Return only fixed enums/booleans; never return account identifiers."""
    try:
        return _evidence(_binding())
    except LocalVerificationError as error:
        return dict(error.evidence)
    except Exception:
        return {"status": "unavailable", "reason": "local_verification_failed"}


def collect_verified(reader: Callable[[], dict]) -> tuple[dict, dict]:
    """Guard one official read with stable CLI and desktop account bindings."""
    before = _binding()
    evidence = _evidence(before)
    if evidence["status"] != "matched":
        raise LocalVerificationError("account_mismatch", evidence)
    result = reader()
    after = _binding()
    after_evidence = _evidence(after)
    if after_evidence["status"] != "matched":
        raise LocalVerificationError("account_mismatch", after_evidence)
    stable = (
        hmac.compare_digest(before.cli.fingerprint, after.cli.fingerprint)
        and hmac.compare_digest(before.cli.email.encode(), after.cli.email.encode())
        and hmac.compare_digest(before.cli.subject.encode(), after.cli.subject.encode())
        and hmac.compare_digest(before.desktop_email.encode(), after.desktop_email.encode())
    )
    if not stable:
        raise LocalVerificationError("account_binding_changed", {
            "status": "unavailable", "reason": "account_binding_changed",
            "same_account": True, "binding_stable_during_read": False,
        })
    if not isinstance(result, dict):
        raise LocalVerificationError("official_report_invalid")
    evidence["binding_stable_during_read"] = True
    return result, evidence


def refresh_expired_cli_binding(probe: Callable[[], dict]) -> None:
    """Permit one trusted official passive probe to refresh an expired login.

    The caller must bind the probe to the reviewed official CLI executable.
    Its report is discarded: a separate collect_verified read is required for
    export. Native credentials may change, but the account binding may not.
    No OAuth refresh request is implemented here.
    """
    before = _binding(require_current=False)
    evidence = _evidence(before)
    if evidence["status"] != "matched":
        raise LocalVerificationError("account_mismatch", evidence)
    if before.cli.id_token_current and before.cli.access_token_current:
        raise LocalVerificationError("cli_auth_not_expired")
    try:
        discarded_report = probe()
        if not isinstance(discarded_report, dict):
            raise LocalVerificationError("cli_refresh_probe_invalid")
        del discarded_report
    except LocalVerificationError:
        raise
    except Exception:
        raise LocalVerificationError("cli_refresh_probe_failed") from None
    after = _binding()
    after_evidence = _evidence(after)
    if after_evidence["status"] != "matched":
        raise LocalVerificationError("account_mismatch", after_evidence)
    if not (
        hmac.compare_digest(before.cli.email.encode(), after.cli.email.encode())
        and hmac.compare_digest(before.cli.subject.encode(), after.cli.subject.encode())
        and hmac.compare_digest(before.desktop_email.encode(), after.desktop_email.encode())
    ):
        raise LocalVerificationError("account_binding_changed")
