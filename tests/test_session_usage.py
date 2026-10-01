from __future__ import annotations

import copy
import csv
import hashlib
import hmac
import io
import json
import re
import shutil
import subprocess
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from scripts import session_usage


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures/session-usage"
PRIMARY_ID = "11111111-1111-4111-8111-111111111111"
CHILD_ID = "22222222-2222-4222-8222-222222222222"
GRANDCHILD_ID = "33333333-3333-4333-8333-333333333333"
KEY = bytes([17]) * 32
OTHER_KEY = bytes([23]) * 32
TOKEN_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
)
CSV_COLUMNS = (
    "rate_card_version", "session_key", "root_session_key", "session_status",
    "agent_role", "configured_model_id", "actual_model_id", "model_id",
    "model_basis", "reasoning_effort", "configured_service_tier", "tier_basis",
    "response_count", *TOKEN_FIELDS, "estimated_credits", "unpriced_tokens",
    "pricing_status",
)
PRIVATE_TEXT = (
    PRIMARY_ID, CHILD_ID, GRANDCHILD_ID, "synthetic-turn-one", "synthetic-turn-two",
    "synthetic-response-one", "synthetic-response-two", "synthetic-child-turn",
    "synthetic-child-response", "SYNTHETIC_PRIVATE_USERNAME",
    "synthetic-private-user@example.invalid", "private-repository",
    "SYNTHETIC_PRIVATE_INSTRUCTIONS", "SYNTHETIC_PRIVATE_PROMPT",
    "SYNTHETIC_PRIVATE_TOOL_ARGUMENTS", "SYNTHETIC_PRIVATE_TOOL_OUTPUT_AND_KEY",
    "SYNTHETIC_PRIVATE_CALL_ID", "SYNTHETIC_PRIVATE_ASSISTANT_RESPONSE",
    "SYNTHETIC_PRIVATE_AGENT_NAME", KEY.hex(), OTHER_KEY.hex(),
)


class SessionUsageTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads((ROOT / "schemas/session-usage-report.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def setUp(self) -> None:
        # Workspace-created directories avoid Windows TemporaryDirectory ACL
        # restrictions and contain synthetic inputs only.
        self.work = ROOT / "artifacts" / f"session-usage-test-{uuid.uuid4().hex}"
        self.source = self.work / "source"
        self.source.mkdir(parents=True)

    def tearDown(self) -> None:
        artifacts = (ROOT / "artifacts").resolve()
        target = self.work.resolve()
        self.assertTrue(target.is_relative_to(artifacts))
        self.assertTrue(target.name.startswith("session-usage-test-"))
        shutil.rmtree(target)

    @staticmethod
    def fixture(name: str = "primary") -> list[dict]:
        return [json.loads(line) for line in (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()]

    def write_source(self, rows: list[dict], name: str = "synthetic.jsonl") -> Path:
        target = self.source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return target

    def collect(self, rows: list[dict] | None = None, **kwargs) -> dict:
        if rows is not None:
            self.write_source(rows)
        report = session_usage.collect_report(self.source, KEY, **kwargs)
        self.assert_report(report)
        return report

    def assert_report(self, report: dict) -> None:
        self.validator.validate(report)
        rendered = json.dumps(report, sort_keys=True)
        for text in PRIVATE_TEXT:
            self.assertNotIn(text, rendered)
        self.assertNotIn(str(self.source), rendered)
        self.assertEqual(report["billing_status"], "actual_debit_unavailable")
        self.assertEqual(report["estimate_kind"], "public_codex_credit_equivalent")
        self.assertRegex(report["signature"], r"^[0-9a-f]{64}$")

    def export(self, report: dict, name: str) -> Path:
        target = self.work / name
        target.write_text(json.dumps(report), encoding="utf-8")
        return target

    @staticmethod
    def resign(report: dict) -> dict:
        unsigned = {name: value for name, value in report.items() if name != "signature"}
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False).encode("utf-8")
        return {**unsigned, "signature": hmac.new(KEY, canonical, hashlib.sha256).hexdigest()}

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/toolkit.py"), *arguments],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        for text in (*PRIVATE_TEXT, str(self.work)):
            self.assertNotIn(text, result.stdout)
            self.assertNotIn(text, result.stderr)
        return result

    def cli_key(self) -> Path:
        path = self.work / "company-key.txt"
        path.write_bytes((KEY.hex() + "\n").encode("ascii"))
        return path

    @staticmethod
    def responses(report: dict) -> list[dict]:
        return sorted(report["responses"], key=lambda row: row["timestamp"])

    @staticmethod
    def first_turn_rows() -> list[dict]:
        return SessionUsageTests.fixture()[:7]

    def test_real_shaped_usage_and_configured_fast_credits(self) -> None:
        report = self.collect(self.fixture(), session_id=PRIMARY_ID)
        self.assertEqual(report["summary"]["response_count"], 2)
        self.assertEqual(report["summary"]["session_count"], 1)
        self.assertEqual(report["summary"]["tokens"], {
            "input_tokens": 11000, "cached_input_tokens": 6500,
            "cache_write_input_tokens": 1000, "output_tokens": 2100,
            "reasoning_output_tokens": 530, "total_tokens": 13100,
        })
        first, fast = self.responses(report)
        self.assertEqual(first["configured_model_id"], "gpt-6.1-sol")
        self.assertEqual(first["model_id"], "gpt-6.1-sol")
        self.assertEqual(first["actual_model_id"], "unmapped")
        self.assertEqual(first["model_basis"], "configured")
        self.assertEqual(first["reasoning_effort"], "high")
        self.assertEqual(first["configured_service_tier"], "standard")
        self.assertEqual(Decimal(first["estimated_credits"]), Decimal("0.665"))
        self.assertEqual(first["unpriced_tokens"], 1000)
        self.assertEqual(first["pricing_status"], "partial")
        self.assertEqual(fast["reasoning_effort"], "xhigh")
        self.assertEqual(fast["configured_service_tier"], "fast")
        self.assertEqual(fast["tier_basis"], "configured")
        self.assertEqual(Decimal(fast["credit_multiplier"]), Decimal(2))
        self.assertEqual(Decimal(fast["estimated_credits"]), Decimal("0.1025"))
        self.assertEqual(Decimal(report["summary"]["estimated_credits"]), Decimal("0.7675"))
        self.assertTrue(report["summary"]["metadata_complete"])
        self.assertFalse(report["summary"]["pricing_complete"])

    def test_reasoning_output_is_subset_and_cache_writes_stay_unpriced(self) -> None:
        report = self.collect(self.first_turn_rows())
        response = report["responses"][0]
        self.assertEqual(response["tokens"]["total_tokens"], 12000)
        self.assertEqual(response["tokens"]["output_tokens"], 2000)
        self.assertEqual(response["tokens"]["reasoning_output_tokens"], 500)
        self.assertEqual(Decimal(response["estimated_credits"]), Decimal("0.665"))
        self.assertEqual(response["unpriced_tokens"], 1000)

    def test_cumulative_snapshots_do_not_add_tokens(self) -> None:
        rows = self.fixture()
        snapshot = copy.deepcopy(rows[6])
        snapshot["payload"]["info"]["total_token_usage"]["input_tokens"] = 999999
        snapshot["payload"]["info"]["last_token_usage"]["input_tokens"] = 888888
        rows.append(snapshot)
        report = self.collect(rows)
        self.assertEqual(report["summary"]["response_count"], 2)
        self.assertEqual(report["summary"]["tokens"]["input_tokens"], 11000)
        self.assertEqual(Decimal(report["summary"]["estimated_credits"]), Decimal("0.7675"))

    def test_nested_response_content_is_not_a_usage_source(self) -> None:
        rows = self.first_turn_rows()
        rows.append({"timestamp": "2026-10-01T00:00:06Z", "type": "response_item", "payload": rows[5]})
        report = self.collect(rows)
        self.assertEqual(report["summary"]["response_count"], 1)

    def test_duplicate_owned_response_copies_are_idempotent(self) -> None:
        self.write_source(self.fixture(), "one.jsonl")
        self.write_source(self.fixture(), "copy/two.jsonl")
        report = self.collect()
        self.assertEqual(report["summary"]["session_count"], 1)
        self.assertEqual(report["summary"]["response_count"], 2)
        self.assertEqual(report["diagnostics"]["duplicate_response_records"], 2)
        self.assertEqual(Decimal(report["summary"]["estimated_credits"]), Decimal("0.7675"))

    def test_conflicting_duplicate_owned_response_fails_closed(self) -> None:
        rows = self.first_turn_rows()
        conflict = copy.deepcopy(rows[5])
        conflict["payload"]["usage"]["output_tokens"] += 1
        conflict["payload"]["usage"]["total_tokens"] += 1
        self.write_source([*rows, conflict])
        with self.assertRaises(session_usage.ReportError):
            session_usage.collect_report(self.source, KEY)

    def test_owned_thread_is_distinct_from_ancestor_session_and_inherited_rows(self) -> None:
        self.write_source(self.fixture(), "primary.jsonl")
        self.write_source(self.fixture("subagent"), "child.jsonl")
        primary = self.collect(session_id=PRIMARY_ID)
        self.assertEqual(primary["summary"]["response_count"], 2)
        combined = self.collect(session_id=PRIMARY_ID, include_subagents=True)
        self.assertEqual(combined["scope"], {"selection": "session_with_subagents", "includes_subagents": True})
        self.assertEqual(combined["summary"]["session_count"], 2)
        self.assertEqual(combined["summary"]["response_count"], 3)
        self.assertEqual(combined["diagnostics"]["inherited_usage_records_ignored"], 1)
        parent_key = primary["sessions"][0]["session_key"]
        child = next(row for row in combined["responses"] if row["agent_role"] == "subagent")
        self.assertNotEqual(child["session_key"], parent_key)
        self.assertEqual(child["root_session_key"], parent_key)
        self.assertEqual(child["parent_session_key"], parent_key)
        self.assertEqual(child["tokens"]["input_tokens"], 2000)
        self.assertEqual(Decimal(combined["summary"]["estimated_credits"]), Decimal("0.77275"))

    def test_fork_origin_does_not_imply_subagent_ancestry(self) -> None:
        self.write_source(self.fixture(), "primary.jsonl")
        fork = self.fixture("subagent")
        fork[0]["payload"].pop("parent_thread_id")
        fork[0]["payload"]["source"] = "cli"
        fork[0]["payload"]["forked_from_id"] = PRIMARY_ID
        fork[5]["payload"]["session_id"] = CHILD_ID
        self.write_source(fork, "fork.jsonl")
        report = self.collect(session_id=PRIMARY_ID, include_subagents=True)
        self.assertEqual(report["summary"]["session_count"], 1)
        self.assertEqual(report["summary"]["response_count"], 2)

    def test_native_usage_ancestry_includes_transitive_subagents_without_parent_metadata(self) -> None:
        self.write_source(self.fixture(), "primary.jsonl")
        self.write_source(self.fixture("subagent"), "child.jsonl")
        grandchild = [row for index, row in enumerate(self.fixture("subagent")) if index != 1]
        grandchild[0]["payload"]["id"] = GRANDCHILD_ID
        grandchild[0]["payload"].pop("parent_thread_id")
        grandchild[0]["payload"]["source"] = {"subagent": {"thread_spawn": {}}}
        for row in grandchild[1:]:
            payload = row["payload"]
            if "thread_id" in payload:
                payload["thread_id"] = GRANDCHILD_ID
            if "turn_id" in payload:
                payload["turn_id"] = "synthetic-grandchild-turn"
            if row["type"] == "token_usage_record":
                payload["session_id"] = CHILD_ID
                payload["response_id"] = "synthetic-grandchild-response"
        self.write_source(grandchild, "grandchild.jsonl")
        single = self.collect(session_id=PRIMARY_ID)
        self.assertEqual(single["summary"]["session_count"], 1)
        self.assertEqual(single["summary"]["response_count"], 2)
        combined = self.collect(session_id=PRIMARY_ID, include_subagents=True)
        self.assertEqual(combined["summary"]["session_count"], 3)
        self.assertEqual(combined["summary"]["response_count"], 4)
        self.assertEqual(Decimal(combined["summary"]["estimated_credits"]), Decimal("0.778"))
        child = next(row for row in combined["responses"] if row["agent_role"] == "subagent"
                     and row["parent_session_key"] is not None)
        grandchild_response = next(row for row in combined["responses"] if row["agent_role"] == "subagent"
                                  and row["parent_session_key"] is None)
        self.assertEqual(grandchild_response["root_session_key"], child["session_key"])
        self.assertIsNone(grandchild_response["parent_session_key"])
        for text in ("synthetic-grandchild-turn", "synthetic-grandchild-response"):
            self.assertNotIn(text, json.dumps(combined))

    def test_late_context_does_not_backfill_model_or_effort(self) -> None:
        rows = self.first_turn_rows()
        context = rows.pop(3)
        rows.append(context)
        report = self.collect(rows)
        response = report["responses"][0]
        self.assertEqual(response["model_id"], "unmapped")
        self.assertEqual(response["reasoning_effort"], "unknown")
        self.assertIsNone(response["estimated_credits"])
        self.assertFalse(report["summary"]["metadata_complete"])
        self.assertGreater(report["diagnostics"]["missing_context_records"], 0)

    def test_missing_context_marks_coverage_incomplete(self) -> None:
        rows = [row for row in self.first_turn_rows() if row["type"] != "turn_context"]
        report = self.collect(rows)
        self.assertFalse(report["summary"]["metadata_complete"])
        self.assertEqual(report["responses"][0]["model_basis"], "unknown")
        self.assertIsNone(report["summary"]["estimated_credits"])

    def test_unknown_model_and_invalid_effort_are_normalized_without_private_strings(self) -> None:
        rows = self.first_turn_rows()
        rows[3]["payload"]["model"] = "SYNTHETIC_PRIVATE_MODEL_IDENTIFIER"
        rows[3]["payload"]["effort"] = "SYNTHETIC_PRIVATE_REASONING_EFFORT"
        report = self.collect(rows)
        response = report["responses"][0]
        self.assertEqual(response["configured_model_id"], "unmapped")
        self.assertEqual(response["model_id"], "unmapped")
        self.assertEqual(response["reasoning_effort"], "unknown")
        self.assertIsNone(response["estimated_credits"])
        self.assertEqual(response["unpriced_tokens"], 12000)
        self.assertFalse(report["summary"]["metadata_complete"])
        for text in ("SYNTHETIC_PRIVATE_MODEL_IDENTIFIER", "SYNTHETIC_PRIVATE_REASONING_EFFORT"):
            self.assertNotIn(text, json.dumps(report))

    def test_unreviewed_model_suffix_is_unpriced(self) -> None:
        rows = self.first_turn_rows()
        rows[3]["payload"]["model"] = "gpt-6.1-sol-future"
        report = self.collect(rows)
        self.assertEqual(report["responses"][0]["model_id"], "unmapped")
        self.assertEqual(report["responses"][0]["pricing_status"], "unpriced")
        self.assertIsNone(report["summary"]["estimated_credits"])
        self.assertGreater(report["diagnostics"]["unknown_model_records"], 0)

    def test_rerouting_marks_the_entire_turn_ambiguous_and_unpriced(self) -> None:
        rows = self.fixture()
        rows.insert(7, {
            "timestamp": "2026-10-01T00:00:06Z", "method": "model/rerouted",
            "params": {"threadId": PRIMARY_ID, "turnId": "synthetic-turn-one", "toModel": "gpt-6-astra"},
        })
        report = self.collect(rows)
        first, unaffected = self.responses(report)
        self.assertEqual(first["configured_model_id"], "gpt-6.1-sol")
        self.assertEqual(first["actual_model_id"], "unmapped")
        self.assertEqual(first["model_id"], "unmapped")
        self.assertEqual(first["model_basis"], "routing_ambiguous")
        self.assertIsNone(first["estimated_credits"])
        self.assertEqual(first["unpriced_tokens"], 12000)
        self.assertEqual(unaffected["model_basis"], "configured")
        self.assertEqual(Decimal(report["summary"]["estimated_credits"]), Decimal("0.1025"))
        self.assertFalse(report["summary"]["metadata_complete"])

    def test_settings_changed_mid_turn_apply_to_the_next_task(self) -> None:
        rows = self.fixture()
        rows.insert(5, {
            "timestamp": "2026-10-01T00:00:04Z", "type": "event_msg",
            "payload": {"type": "thread_settings_applied", "thread_id": PRIMARY_ID,
                        "thread_settings": {"service_tier": "priority"}},
        })
        report = self.collect(rows)
        first, second = self.responses(report)
        self.assertEqual(first["configured_service_tier"], "standard")
        self.assertEqual(second["configured_service_tier"], "fast")
        self.assertEqual(Decimal(report["summary"]["estimated_credits"]), Decimal("0.7675"))

    def test_missing_tier_explicitly_reports_standard_equivalent_assumption(self) -> None:
        rows = [row for row in self.fixture() if row.get("payload", {}).get("type") != "thread_settings_applied"]
        report = self.collect(rows)
        for response in report["responses"]:
            self.assertEqual(response["configured_service_tier"], "unknown")
            self.assertEqual(response["tier_basis"], "standard_assumption")
            self.assertEqual(Decimal(response["credit_multiplier"]), Decimal(1))
        self.assertFalse(report["summary"]["metadata_complete"])
        self.assertEqual(report["diagnostics"]["unknown_tier_records"], 2)
        self.assertEqual(Decimal(report["summary"]["estimated_credits"]), Decimal("0.71625"))

    def test_invalid_tier_metadata_is_not_exported(self) -> None:
        rows = self.first_turn_rows()
        rows[1]["payload"]["thread_settings"]["service_tier"] = "SYNTHETIC_PRIVATE_SERVICE_TIER"
        report = self.collect(rows)
        self.assertEqual(report["responses"][0]["configured_service_tier"], "unknown")
        self.assertFalse(report["summary"]["metadata_complete"])
        self.assertNotIn("SYNTHETIC_PRIVATE_SERVICE_TIER", json.dumps(report))

    def test_missing_or_invalid_usage_timestamp_is_not_guessed(self) -> None:
        for timestamp in (None, "SYNTHETIC_PRIVATE_BAD_TIMESTAMP"):
            with self.subTest(timestamp=timestamp):
                rows = self.fixture()
                if timestamp is None:
                    rows[5].pop("timestamp")
                else:
                    rows[5]["timestamp"] = timestamp
                report = self.collect(rows)
                self.assertEqual(report["summary"]["response_count"], 1)
                self.assertEqual(report["diagnostics"]["invalid_usage_records"], 1)
                self.assertFalse(report["summary"]["metadata_complete"])

    def test_invalid_token_shape_is_reported_as_incomplete(self) -> None:
        rows = self.fixture()
        rows[5]["payload"]["usage"]["reasoning_output_tokens"] = 2001
        report = self.collect(rows)
        self.assertEqual(report["summary"]["response_count"], 1)
        self.assertEqual(report["diagnostics"]["invalid_usage_records"], 1)
        self.assertFalse(report["summary"]["metadata_complete"])

    def test_malformed_json_marks_coverage_incomplete_without_leaking_line(self) -> None:
        target = self.write_source(self.fixture())
        with target.open("a", encoding="utf-8") as stream:
            stream.write("SYNTHETIC_PRIVATE_INVALID_JSON\n")
        report = self.collect()
        self.assertEqual(report["diagnostics"]["invalid_json_lines"], 1)
        self.assertFalse(report["summary"]["metadata_complete"])
        self.assertNotIn("SYNTHETIC_PRIVATE_INVALID_JSON", json.dumps(report))

    def test_unsupported_source_keeps_session_usage_null(self) -> None:
        rows = [row for row in self.fixture() if row["type"] != "token_usage_record"]
        report = self.collect(rows)
        session = report["sessions"][0]
        self.assertEqual(session["status"], "unsupported_source")
        self.assertIsNone(session["tokens"])
        self.assertIsNone(session["estimated_credits"])
        self.assertEqual(report["summary"]["response_count"], 0)
        self.assertFalse(report["summary"]["metadata_complete"])
        self.assertEqual(report["diagnostics"]["unsupported_sessions"], 1)

    def test_identity_hmac_domains_and_keys_are_separate(self) -> None:
        rows = self.first_turn_rows()
        rows[2]["payload"]["turn_id"] = PRIMARY_ID
        rows[3]["payload"]["turn_id"] = PRIMARY_ID
        rows[5]["payload"]["turn_id"] = PRIMARY_ID
        rows[5]["payload"]["response_id"] = PRIMARY_ID
        self.write_source(rows)
        report = self.collect()
        response = report["responses"][0]
        self.assertEqual(len({response["session_key"], response["turn_key"], response["response_key"]}), 3)
        other = session_usage.collect_report(self.source, OTHER_KEY)
        self.assert_report(other)
        self.assertNotEqual(report["key_id"], other["key_id"])
        self.assertNotEqual(response["session_key"], other["responses"][0]["session_key"])
        self.assertNotEqual(report["signature"], other["signature"])

    def test_key_file_format_readback_and_nonoverwrite(self) -> None:
        path = self.work / "company-key.txt"
        session_usage.create_key(path)
        self.assertTrue(
            bool(re.fullmatch(r"[0-9a-f]{64}\n", path.read_bytes().decode("ascii"))),
            "created key must contain 64 lowercase hex characters and LF",
        )
        key = session_usage.read_key(path)
        self.assertEqual(len(key), 32)
        original = path.read_bytes()
        with self.assertRaises(session_usage.ReportError):
            session_usage.create_key(path)
        self.assertEqual(path.read_bytes(), original)

    def test_malformed_key_files_are_rejected(self) -> None:
        path = self.work / "bad-key.txt"
        for value in ("", "ab" * 31, "ab" * 33, "zz" * 32, "SYNTHETIC_PRIVATE_KEY"):
            with self.subTest(value=value):
                path.write_text(value + "\n", encoding="utf-8")
                with self.assertRaises(session_usage.ReportError):
                    session_usage.read_key(path)

    def test_company_overlap_merge_is_idempotent(self) -> None:
        report = self.collect(self.fixture())
        first = self.export(report, "first.json")
        merged = session_usage.merge_reports([first, first], KEY)
        self.assert_report(merged)
        self.assertEqual(merged["scope"]["selection"], "merged_reports")
        self.assertEqual(merged["summary"], report["summary"])
        self.assertEqual(merged["responses"], report["responses"])
        merged_file = self.export(merged, "merged.json")
        repeated = session_usage.merge_reports([merged_file, first], KEY)
        self.assert_report(repeated)
        self.assertEqual(repeated["summary"], merged["summary"])
        self.assertEqual(repeated["diagnostics"], merged["diagnostics"])

    def test_company_partially_overlapping_exports_deduplicate_owned_responses(self) -> None:
        full = self.collect(self.fixture())
        full_path = self.export(full, "full.json")
        self.write_source(self.first_turn_rows())
        partial = self.collect()
        partial_path = self.export(partial, "partial.json")
        merged = session_usage.merge_reports([full_path, partial_path], KEY)
        self.assert_report(merged)
        self.assertEqual(merged["summary"]["response_count"], 2)
        self.assertEqual(Decimal(merged["summary"]["estimated_credits"]), Decimal("0.7675"))

    def test_company_tampering_and_key_mismatch_are_rejected(self) -> None:
        self.write_source(self.fixture())
        report = self.collect()
        valid = self.export(report, "valid.json")
        other = session_usage.collect_report(self.source, OTHER_KEY)
        mismatched = self.export(other, "other-key.json")
        with self.assertRaises(session_usage.ReportError):
            session_usage.merge_reports([valid, mismatched], KEY)
        tampered = copy.deepcopy(report)
        tampered["summary"]["estimated_credits"] = "0"
        altered = self.export(tampered, "tampered.json")
        with self.assertRaises(session_usage.ReportError):
            session_usage.merge_reports([altered], KEY)

    def test_company_report_with_private_extra_field_is_rejected_before_merge(self) -> None:
        report = self.collect(self.fixture())
        report["responses"][0]["raw_prompt"] = "SYNTHETIC_PRIVATE_PROMPT"
        path = self.export(report, "private-extra-field.json")
        with self.assertRaises(session_usage.ReportError):
            session_usage.merge_reports([path], KEY)

    def test_company_different_rate_card_snapshots_are_rejected(self) -> None:
        self.write_source(self.fixture())
        card = copy.deepcopy(session_usage.load_rate_card())
        card["models"]["gpt-6.1-sol"]["input_cached"] = "5"
        report = session_usage.collect_report(self.source, KEY, rate_card=card)
        self.assert_report(report)
        path = self.export(report, "other-rate-card.json")
        with self.assertRaises(session_usage.ReportError):
            session_usage.merge_reports([path], KEY)

    def test_company_validly_signed_conflicting_response_is_rejected(self) -> None:
        rows = self.first_turn_rows()
        first = self.export(self.collect(rows), "first.json")
        rows[5]["payload"]["usage"]["output_tokens"] += 1
        rows[5]["payload"]["usage"]["total_tokens"] += 1
        self.write_source(rows)
        second = self.export(self.collect(), "second.json")
        with self.assertRaises(session_usage.ReportError):
            session_usage.merge_reports([first, second], KEY)

    def test_company_signed_invalid_token_invariants_are_rejected(self) -> None:
        report = self.collect(self.fixture())
        for field, value in (("cached_input_tokens", 10001), ("reasoning_output_tokens", 2001),
                             ("total_tokens", 12001)):
            with self.subTest(field=field):
                altered = copy.deepcopy(report)
                altered["responses"][0]["tokens"][field] = value
                path = self.export(self.resign(altered), "invalid-signed-tokens.json")
                with self.assertRaises(session_usage.ReportError) as raised:
                    session_usage.merge_reports([path], KEY)
                self.assertEqual(str(raised.exception), "invalid_response_tokens")

    def test_company_signed_stale_credit_calculations_are_rejected(self) -> None:
        report = self.collect(self.fixture())
        for field, value in (("estimated_credits", "999"), ("unpriced_tokens", 0),
                             ("pricing_status", "priced"), ("credit_multiplier", "2")):
            with self.subTest(field=field):
                altered = copy.deepcopy(report)
                altered["responses"][0][field] = value
                path = self.export(self.resign(altered), "invalid-signed-pricing.json")
                with self.assertRaises(session_usage.ReportError) as raised:
                    session_usage.merge_reports([path], KEY)
                self.assertEqual(str(raised.exception), "invalid_response_pricing")

    def test_company_signed_inconsistent_model_and_tier_bases_are_rejected(self) -> None:
        report = self.collect(self.fixture())
        for field, value in (("model_basis", "routing_ambiguous"), ("configured_model_id", "unmapped"),
                             ("configured_service_tier", "unknown"), ("tier_basis", "standard_assumption")):
            with self.subTest(field=field):
                altered = copy.deepcopy(report)
                altered["responses"][0][field] = value
                path = self.export(self.resign(altered), "invalid-signed-provenance.json")
                with self.assertRaises(session_usage.ReportError) as raised:
                    session_usage.merge_reports([path], KEY)
                self.assertEqual(str(raised.exception), "invalid_response_metadata")

    def test_company_signed_response_parent_and_role_must_match_owning_session(self) -> None:
        report = self.collect(self.fixture())
        for field, value in (("parent_session_key", "0" * 64), ("agent_role", "subagent")):
            with self.subTest(field=field):
                altered = copy.deepcopy(report)
                altered["responses"][0][field] = value
                path = self.export(self.resign(altered), "invalid-signed-parent-role.json")
                with self.assertRaises(session_usage.ReportError) as raised:
                    session_usage.merge_reports([path], KEY)
                self.assertEqual(str(raised.exception), "invalid_report_relationships")

    def test_company_duplicate_session_descriptor_with_conflicting_metadata_is_rejected(self) -> None:
        report = self.collect(self.fixture())
        duplicate = copy.deepcopy(report["sessions"][0])
        duplicate["parent_session_key"] = "0" * 64
        report["sessions"].append(duplicate)
        path = self.export(self.resign(report), "conflicting-signed-descriptors.json")
        with self.assertRaises(session_usage.ReportError) as raised:
            session_usage.merge_reports([path], KEY)
        self.assertEqual(str(raised.exception), "conflicting_session_metadata")

    def test_company_aggregates_are_recomputed_from_authenticated_unique_responses(self) -> None:
        report = self.collect(self.fixture())
        altered = copy.deepcopy(report)
        altered["summary"]["response_count"] = 999
        altered["summary"]["estimated_credits"] = "999"
        altered["groups"][0]["estimated_credits"] = "999"
        path = self.export(self.resign(altered), "stale-signed-aggregates.json")
        merged = session_usage.merge_reports([path], KEY)
        self.assert_report(merged)
        self.assertEqual(merged["summary"], report["summary"])
        self.assertEqual(merged["groups"], report["groups"])

    def test_csv_has_only_approved_group_columns_and_no_private_content(self) -> None:
        report = self.collect(self.fixture())
        rendered = session_usage.render_csv(report)
        reader = csv.DictReader(io.StringIO(rendered))
        self.assertEqual(tuple(reader.fieldnames or ()), CSV_COLUMNS)
        rows = list(reader)
        self.assertEqual(len(rows), len(report["groups"]))
        self.assertEqual(sum(int(row["response_count"]) for row in rows), 2)
        for text in PRIVATE_TEXT:
            self.assertNotIn(text, rendered)
        self.assertNotIn(str(self.source), rendered)

    def test_csv_unsupported_session_has_blank_usage_placeholders(self) -> None:
        report = self.collect([row for row in self.fixture() if row["type"] != "token_usage_record"])
        rows = list(csv.DictReader(io.StringIO(session_usage.render_csv(report))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_status"], "unsupported_source")
        for field in (*TOKEN_FIELDS, "response_count", "estimated_credits"):
            self.assertEqual(rows[0][field], "")

    def test_schema_rejects_private_fields_at_every_exported_object_boundary(self) -> None:
        report = self.collect(self.fixture())
        for location in (
            (), ("scope",), ("sessions", 0), ("responses", 0), ("responses", 0, "tokens"),
            ("groups", 0), ("groups", 0, "tokens"), ("summary",), ("summary", "tokens"),
            ("diagnostics",),
        ):
            with self.subTest(location=location):
                altered = copy.deepcopy(report)
                obj = altered
                for part in location:
                    obj = obj[part]
                obj["raw_prompt"] = "SYNTHETIC_PRIVATE_PROMPT"
                self.assertTrue(list(self.validator.iter_errors(altered)))

    def test_usage_payload_extra_content_is_removed(self) -> None:
        rows = self.first_turn_rows()
        rows[5]["payload"]["raw_prompt"] = "SYNTHETIC_PRIVATE_PROMPT"
        rows[5]["payload"]["usage"]["tool_result"] = "SYNTHETIC_PRIVATE_TOOL_OUTPUT_AND_KEY"
        report = self.collect(rows)
        self.assertEqual(set(report["responses"][0]["tokens"]), set(TOKEN_FIELDS))
        self.assertEqual(Decimal(report["summary"]["estimated_credits"]), Decimal("0.665"))

    def test_response_identity_is_scoped_to_owning_session(self) -> None:
        self.write_source(self.fixture(), "primary.jsonl")
        child = self.fixture("subagent")
        child[5]["payload"]["response_id"] = "synthetic-response-one"
        self.write_source(child, "child.jsonl")
        report = self.collect(session_id=PRIMARY_ID, include_subagents=True)
        self.assertEqual(report["summary"]["response_count"], 3)
        self.assertEqual(len({row["response_key"] for row in report["responses"]}), 3)

    def test_current_public_card_is_explicit_and_bad_rates_fail_closed(self) -> None:
        card = session_usage.load_rate_card()
        self.assertEqual(card["version"], "openai-codex-credits-2026-10-01")
        self.assertEqual(card["models"]["gpt-6.1-sol"], {
            "input_uncached": "50", "input_cached": "2.5", "output": "250",
        })
        self.assertEqual(card["speed_multipliers"]["fast"], "2")
        for invalid in ("NaN", "-1", "Infinity", "SYNTHETIC_PRIVATE_RATE"):
            with self.subTest(invalid=invalid):
                altered = copy.deepcopy(card)
                altered["models"]["gpt-6.1-sol"]["input_cached"] = invalid
                path = self.export(altered, "bad-rate-card.json")
                with self.assertRaises(session_usage.ReportError):
                    session_usage.load_rate_card(path)

    def test_direct_custom_rate_cards_are_validated_at_both_api_boundaries(self) -> None:
        self.write_source(self.fixture())
        valid_path = self.export(self.collect(), "valid.json")
        for invalid in (None, "NaN", "SYNTHETIC_PRIVATE_RATE"):
            with self.subTest(invalid=invalid):
                card = copy.deepcopy(session_usage.load_rate_card())
                card["models"]["gpt-6.1-sol"]["input_cached"] = invalid
                for operation in (
                    lambda: session_usage.collect_report(self.source, KEY, rate_card=card),
                    lambda: session_usage.merge_reports([valid_path], KEY, rate_card=card),
                ):
                    with self.assertRaises(session_usage.ReportError) as raised:
                        operation()
                    self.assertEqual(str(raised.exception), "invalid_rate_card")

    def test_cli_json_stdout_is_parseable_and_privacy_safe(self) -> None:
        self.write_source(self.fixture())
        result = self.run_cli("session-usage", "--source-root", str(self.source),
                              "--key-file", str(self.cli_key()), "--session-id", PRIMARY_ID)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assert_report(report)
        self.assertEqual(report["summary"]["response_count"], 2)
        self.assertEqual(report["scope"]["selection"], "single_session")

    def test_cli_csv_stdout_has_approved_header(self) -> None:
        self.write_source(self.fixture())
        result = self.run_cli("session-usage", "--source-root", str(self.source),
                              "--key-file", str(self.cli_key()), "--format", "csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        reader = csv.DictReader(io.StringIO(result.stdout))
        self.assertEqual(tuple(reader.fieldnames or ()), CSV_COLUMNS)
        self.assertEqual(len(list(reader)), 2)

    def test_cli_key_creation_is_exclusive_and_prints_only_safe_confirmation(self) -> None:
        path = self.work / "created-key.txt"
        result = self.run_cli("session-key", "--output", str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "KEY: created")
        key_bytes = path.read_bytes()
        self.assertTrue(bool(re.fullmatch(rb"[0-9a-f]{64}\n", key_bytes)))
        self.assertNotIn(key_bytes.strip().decode("ascii"), result.stdout + result.stderr)
        repeated = self.run_cli("session-key", "--output", str(path))
        self.assertNotEqual(repeated.returncode, 0)
        self.assertTrue(path.read_bytes() == key_bytes, "exclusive key creation must preserve the existing key")

    def test_cli_signed_merge_excludes_its_output_and_is_idempotent(self) -> None:
        self.write_source(self.fixture())
        report = self.collect()
        reports_root = self.work / "reports"
        reports_root.mkdir()
        for name in ("one.json", "overlap.json"):
            (reports_root / name).write_text(json.dumps(report), encoding="utf-8")
        output = reports_root / "merged.json"
        arguments = ("session-usage-merge", "--reports-root", str(reports_root),
                     "--key-file", str(self.cli_key()), "--output", str(output))
        first = self.run_cli(*arguments)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), "REPORT: sessions=1 responses=2")
        first_report = json.loads(output.read_text(encoding="utf-8"))
        self.assert_report(first_report)
        repeated = self.run_cli(*arguments)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        repeated_report = json.loads(output.read_text(encoding="utf-8"))
        self.assert_report(repeated_report)
        self.assertEqual(repeated_report, first_report)

    def test_cli_output_refuses_key_card_and_raw_source_overwrite(self) -> None:
        source_path = self.write_source(self.fixture())
        key_path = self.cli_key()
        card_path = self.work / "selected-card.json"
        card_path.write_text(json.dumps(session_usage.load_rate_card()), encoding="utf-8")
        protected = (key_path, card_path, source_path, self.source / "new-report.json")
        for target in protected:
            with self.subTest(target=target.name):
                original = target.read_bytes() if target.exists() else None
                result = self.run_cli(
                    "session-usage", "--source-root", str(self.source),
                    "--key-file", str(key_path), "--rate-card", str(card_path),
                    "--output", str(target),
                )
                self.assertNotEqual(result.returncode, 0)
                if original is None:
                    self.assertFalse(target.exists())
                else:
                    self.assertTrue(target.read_bytes() == original, "protected input must remain unchanged")

    def test_cli_errors_expose_only_bounded_diagnostic_codes(self) -> None:
        self.write_source(self.fixture())
        key = self.cli_key()
        missing_id = "SYNTHETIC_PRIVATE_MISSING_SESSION_ID"
        result = self.run_cli("session-usage", "--source-root", str(self.source),
                              "--key-file", str(key), "--session-id", missing_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("session_not_found", result.stdout + result.stderr)
        self.assertNotIn(missing_id, result.stdout + result.stderr)
        missing_root = self.work / "SYNTHETIC_PRIVATE_MISSING_SOURCE"
        result = self.run_cli("session-usage", "--source-root", str(missing_root), "--key-file", str(key))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid_source_root", result.stdout + result.stderr)
        self.assertNotIn(str(missing_root), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
