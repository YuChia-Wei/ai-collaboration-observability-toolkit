"""Account binding, local RPC containment and privacy regression coverage."""

import base64
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/antigravity_local.py"
SPEC = importlib.util.spec_from_file_location("antigravity_local", MODULE_PATH)
local = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = local
SPEC.loader.exec_module(local)


def credential(email="one@example.invalid", subject="fixture-one", expiry=2000,
               issuer="https://accounts.google.com", verified=True,
               access_expiry="2030-01-01T00:00:00Z", access_token="fixture-access"):
    claims = {"email": email, "sub": subject, "exp": expiry, "iss": issuer,
              "email_verified": verified}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return json.dumps({"id_token": "header." + payload.decode() + ".signature",
                       "token": {"access_token": access_token,
                                 "expiry": access_expiry}}).encode()


def binding(email="one@example.invalid", subject="fixture-one", blob=None,
            desktop_email=None):
    cli = local._identity_from_blob(blob or credential(email, subject), now=1000)
    return local._Binding(cli, email if desktop_email is None else desktop_email)


class LocalIdentityTests(unittest.TestCase):
    def test_official_probe_refreshes_only_expired_same_account_binding(self):
        before = binding(blob=credential(expiry=900))
        after = binding(blob=credential(access_token="fixture-refreshed"))
        probe = mock.Mock(return_value={"private": "one@example.invalid"})
        with mock.patch.object(local, "_binding", side_effect=[before, after]) as read:
            self.assertIsNone(local.refresh_expired_cli_binding(probe))
        self.assertEqual(read.call_args_list, [mock.call(require_current=False), mock.call()])
        probe.assert_called_once_with()

    def test_refresh_cannot_authorize_account_switch(self):
        expired = binding(blob=credential(expiry=900))
        for after in (binding("two@example.invalid", "fixture-two"),
                      binding(subject="different-subject")):
            with mock.patch.object(local, "_binding", side_effect=[expired, after]):
                with self.assertRaisesRegex(local.LocalVerificationError,
                                            "^account_binding_changed$"):
                    local.refresh_expired_cli_binding(lambda: {})

    def test_refresh_rejects_mismatch_and_current_binding_before_probe(self):
        for before, code in (
            (binding(blob=credential(expiry=900), desktop_email="two@example.invalid"),
             "account_mismatch"),
            (binding(), "cli_auth_not_expired"),
        ):
            probe = mock.Mock(return_value={})
            with mock.patch.object(local, "_binding", return_value=before):
                with self.assertRaisesRegex(local.LocalVerificationError, "^" + code + "$"):
                    local.refresh_expired_cli_binding(probe)
            probe.assert_not_called()

    def test_refresh_requires_current_post_binding_and_suppresses_probe_error(self):
        expired = binding(blob=credential(expiry=900))
        with mock.patch.object(local, "_binding", side_effect=[expired,
                local.LocalVerificationError("cli_auth_expired")]):
            with self.assertRaisesRegex(local.LocalVerificationError, "^cli_auth_expired$"):
                local.refresh_expired_cli_binding(lambda: {})
        with mock.patch.object(local, "_binding", return_value=expired):
            with self.assertRaisesRegex(local.LocalVerificationError,
                                        "^cli_refresh_probe_failed$"):
                local.refresh_expired_cli_binding(mock.Mock(side_effect=RuntimeError(
                    "one@example.invalid private-provider-response")))

    def test_native_binding_normalizes_email_without_returning_identity(self):
        identity = local._identity_from_blob(credential("ONE@example.invalid"), now=1000)
        self.assertEqual(identity.email, "one@example.invalid")
        evidence = local._evidence(local._Binding(identity, "one@example.invalid"))
        self.assertTrue(evidence["same_account"])
        serialized = json.dumps(evidence)
        for forbidden in (identity.email, identity.subject, "fixture-access", "signature"):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn(identity.email, repr(identity))

    def test_rejects_foreign_issuer_unverified_email_and_malformed_claims(self):
        for blob in (credential(issuer="https://example.invalid"),
                     credential(verified=False), credential(email="missing-domain"),
                     credential(subject=""), credential(expiry=True), b"[]", b"{}"):
            with self.subTest(blob_type=type(blob).__name__):
                with self.assertRaisesRegex(local.LocalVerificationError,
                                            "^cli_keyring_invalid$"):
                    local._identity_from_blob(blob, now=1000)

    def test_tracks_id_and_access_expiry_independently(self):
        identity = local._identity_from_blob(credential(expiry=900), now=1000)
        self.assertFalse(identity.id_token_current)
        self.assertTrue(identity.access_token_current)
        identity = local._identity_from_blob(
            credential(access_expiry="1970-01-01T00:00:01Z"), now=1000)
        self.assertTrue(identity.id_token_current)
        self.assertFalse(identity.access_token_current)
        self.assertFalse(local._expiry_is_current("2030-01-01T00:00:00", 1000))

    def test_expired_native_identity_does_not_contact_desktop(self):
        with mock.patch.object(local, "_credential_blob", return_value=credential(expiry=0)), \
             mock.patch.object(local, "DesktopClient") as client:
            evidence = local.verify_same_account()
        self.assertEqual(evidence["status"], "unavailable")
        self.assertFalse(evidence["cli_id_token_current"])
        self.assertTrue(evidence["cli_access_token_current"])
        client.assert_not_called()

    def test_verification_suppresses_unexpected_sensitive_error(self):
        with mock.patch.object(local, "_binding", side_effect=ValueError(
                "one@example.invalid fixture-access")):
            self.assertEqual(local.verify_same_account(), {
                "status": "unavailable", "reason": "local_verification_failed"})

    def test_stable_binding_wraps_exactly_one_read(self):
        before = binding()
        reader = mock.Mock(return_value={"data": []})
        with mock.patch.object(local, "_binding", side_effect=[before, before]):
            report, evidence = local.collect_verified(reader)
        reader.assert_called_once_with()
        self.assertEqual(report, {"data": []})
        self.assertEqual(evidence["status"], "matched")
        self.assertTrue(evidence["binding_stable_during_read"])

    def test_mismatch_prevents_official_read(self):
        reader = mock.Mock()
        with mock.patch.object(local, "_binding", return_value=binding(
                desktop_email="other@example.invalid")):
            with self.assertRaisesRegex(local.LocalVerificationError, "^account_mismatch$"):
                local.collect_verified(reader)
        reader.assert_not_called()

    def test_two_matched_accounts_do_not_hide_switch_during_read(self):
        with mock.patch.object(local, "_binding", side_effect=[
                binding(), binding("two@example.invalid", "fixture-two")]):
            with self.assertRaisesRegex(local.LocalVerificationError,
                                        "^account_binding_changed$") as caught:
                local.collect_verified(lambda: {})
        self.assertFalse(caught.exception.evidence["binding_stable_during_read"])
        self.assertNotIn("@", json.dumps(caught.exception.evidence))

    def test_changed_native_credential_requires_fresh_read(self):
        after = binding(blob=credential(access_token="fixture-refreshed"))
        with mock.patch.object(local, "_binding", side_effect=[binding(), after]):
            with self.assertRaisesRegex(local.LocalVerificationError,
                                        "^account_binding_changed$"):
                local.collect_verified(lambda: {})

    def test_desktop_switch_after_read_blocks_export(self):
        with mock.patch.object(local, "_binding", side_effect=[
                binding(), binding(desktop_email="other@example.invalid")]):
            with self.assertRaisesRegex(local.LocalVerificationError, "^account_mismatch$"):
                local.collect_verified(lambda: {})

    def test_non_object_official_report_rejected(self):
        before = binding()
        with mock.patch.object(local, "_binding", side_effect=[before, before]):
            with self.assertRaisesRegex(local.LocalVerificationError,
                                        "^official_report_invalid$"):
                local.collect_verified(lambda: [])


class DesktopContainmentTests(unittest.TestCase):
    def test_only_reviewed_readonly_methods_are_allowed(self):
        client = local.DesktopClient()
        with self.assertRaisesRegex(local.LocalVerificationError,
                                    "^desktop_method_rejected$"):
            client.request("SendUserCascadeMessage", {})

    def test_context_metadata_request_cannot_request_messages_or_extra_fields(self):
        request = {"cascadeId": "00000000-0000-0000-0000-000000000001",
                   "generatorMetadataOffset": 0, "includeMessages": False}
        with mock.patch.object(local, "get_desktop_version", return_value="2.25.0"):
            local._validate_request("GetCascadeTrajectoryGeneratorMetadata", request)
            for changed in (
                {**request, "includeMessages": True},
                {**request, "includeMessages": 0},
                {**request, "cascadeId": "private-account@example.invalid"},
                {**request, "generatorMetadataOffset": True},
                {**request, "generatorMetadataOffset": -1},
                {**request, "generatorMetadataOffset": 2**32},
                {**request, "prompt": "private prompt"},
            ):
                with self.assertRaisesRegex(local.LocalVerificationError,
                                            "^desktop_request_rejected$"):
                    local._validate_request("GetCascadeTrajectoryGeneratorMetadata", changed)
        with mock.patch.object(local, "get_desktop_version", return_value="2.26.0"):
            with self.assertRaisesRegex(local.LocalVerificationError,
                                        "^desktop_version_review_required$"):
                local._validate_request("GetCascadeTrajectoryGeneratorMetadata", request)

    def test_user_status_cannot_smuggle_payload(self):
        with self.assertRaisesRegex(local.LocalVerificationError,
                                    "^desktop_request_rejected$"):
            local._validate_request("GetUserStatus", {"metadata": {"account": "private"}})

    def test_redirects_cannot_forward_local_csrf(self):
        with self.assertRaisesRegex(local.LocalVerificationError,
                                    "^desktop_redirect_rejected$"):
            local._RejectRedirect().redirect_request(
                None, None, 302, "found", {}, "https://example.invalid")

    def test_process_flags_allow_both_forms_without_reporting_values(self):
        self.assertEqual(local._flag('server --csrf_token "fixture one"', "csrf_token"),
                         "fixture one")
        self.assertEqual(local._flag("server --https_server_port=1234", "https_server_port"),
                         "1234")
        self.assertIsNone(local._flag("server --not_csrf_token=x", "csrf_token"))

    def test_client_uses_loopback_and_strict_response_size_limit(self):
        client = local.DesktopClient()
        client._csrf, client._port = "fixture-csrf", 1234
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"x" * (local.MAX_RESPONSE_BYTES + 1)
        client._opener = mock.Mock()
        client._opener.open.return_value = response
        with mock.patch.object(client, "_check_process"):
            with self.assertRaisesRegex(local.LocalVerificationError,
                                        "^desktop_response_too_large$"):
                client.request("GetUserStatus", {})
        request = client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url,
            "https://127.0.0.1:1234" + local.RPC_PREFIX + "GetUserStatus")
        self.assertEqual(request.method, "POST")
        response.read.assert_called_once_with(local.MAX_RESPONSE_BYTES + 1)

    def test_reused_pid_or_unowned_port_is_rejected(self):
        client = local.DesktopClient()
        client._process = {"pid": 1234, "created": "first"}
        client._csrf, client._port = "fixture-csrf", 1234
        with mock.patch.object(local, "_processes", return_value=[{
                "pid": 1234, "created": "second", "command_line":
                "server --csrf_token fixture-csrf"}]), \
             mock.patch.object(local, "_owned_ports", return_value=[1234]):
            with self.assertRaisesRegex(local.LocalVerificationError,
                                        "^desktop_process_changed$"):
                client._check_process()


if __name__ == "__main__":
    unittest.main()
