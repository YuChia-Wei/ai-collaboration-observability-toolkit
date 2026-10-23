from __future__ import annotations

import contextlib
import io
import json
import unittest
from argparse import Namespace
from unittest import mock

from scripts import antigravity_desktop as desktop


class DesktopUsageBoundaryTests(unittest.TestCase):
    def test_partial_read_preserves_unknowns_and_does_not_claim_active_or_exported(self):
        tokens = {"status": "partial", "input_tokens": None, "sampled_output_tokens": 17}
        context = {"status": "observed", "estimated_tokens_used": 81}
        with mock.patch("scripts.antigravity_desktop_tokens.collect_desktop_tokens", return_value=tokens):
            with mock.patch("scripts.antigravity_desktop_context.collect_desktop_context", return_value=context):
                result = desktop.collect_desktop_usage(max_conversations=1, max_rows=20)
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["tokens"]["input_tokens"])
        self.assertEqual(result["tokens"]["sampled_output_tokens"], 17)
        self.assertEqual(result["context"]["estimated_tokens_used"], 81)
        self.assertEqual(result["current_active_conversation"], "unknown")
        self.assertEqual(result["export_status"], "not-supported")

    def test_private_provider_exceptions_never_reach_json_output(self):
        private = "private-account@example.invalid C:/private/conversation-id tool-output"
        output = io.StringIO()
        with mock.patch("scripts.antigravity_desktop_tokens.collect_desktop_tokens", side_effect=RuntimeError(private)):
            with mock.patch("scripts.antigravity_desktop_context.collect_desktop_context", side_effect=RuntimeError(private)):
                with contextlib.redirect_stdout(output):
                    code = desktop.run(Namespace(max_conversations=1, max_rows=20, output=None))
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["tokens"]["error"], "desktop_token_read_unavailable")
        self.assertEqual(report["context"]["error"], "desktop_context_read_unavailable")
        self.assertNotIn(private, output.getvalue())

    def test_invalid_limits_are_rejected_before_opening_either_source(self):
        for conversations, rows in ((0, 20), (4, 20), (1, 0), (1, 4097), (True, 20)):
            with self.subTest(conversations=conversations, rows=rows):
                with mock.patch("scripts.antigravity_desktop_tokens.collect_desktop_tokens") as read:
                    with self.assertRaisesRegex(ValueError, "^invalid_desktop_read_limits$"):
                        desktop.collect_desktop_usage(max_conversations=conversations, max_rows=rows)
                read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
