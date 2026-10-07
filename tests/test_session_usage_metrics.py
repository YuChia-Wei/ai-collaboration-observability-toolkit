"""Synthetic v2 report boundary, attribution, merge and export checks."""
from __future__ import annotations

import copy
import csv
import io
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from scripts import session_usage as usage
from scripts import session_usage_metrics as metrics

ROOT = Path(__file__).resolve().parents[1]
KEY = bytes([41]) * 32
OWNER = "11111111-1111-4111-8111-111111111111"
STAMP = "2026-10-01T03:00:00.000000Z"


class SessionUsageMetricsTests(unittest.TestCase):
    def setUp(self):
        self.work = ROOT / "artifacts" / ("session-metrics-test-" + uuid.uuid4().hex)
        self.source = self.work / "source"
        self.source.mkdir(parents=True)
        self.rows = [json.loads(row) for row in (ROOT / "fixtures/session-usage/primary.jsonl").read_text().splitlines()]
        self.validator = Draft202012Validator(json.loads((ROOT / "schemas/session-usage-report.schema.json").read_text()), format_checker=FormatChecker())

    def tearDown(self):
        self.assertTrue(self.work.resolve().is_relative_to((ROOT / "artifacts").resolve()))
        shutil.rmtree(self.work)

    @staticmethod
    def snapshot_record(timestamp=STAMP):
        return {"timestamp": timestamp, "type": "event_msg", "payload": {"type": "token_count",
                "info": {"total_token_usage": {"total_tokens": 999999}},
                "rate_limits": {"plan_type": "enterprise", "primary": {"used_percent": 12.5, "window_minutes": 300, "resets_at": 1800000000},
                "secondary": None, "credits": {"has_credits": True, "unlimited": False, "balance": "123.45"},
                "account_id": "PRIVATE_ACCOUNT", "email": "PRIVATE_EMAIL", "rate_limit_reset_credits": {"private": "PRIVATE_VOUCHER"}}}}

    def collect(self, rows=None, **kwargs):
        (self.source / "one.jsonl").write_text("".join(json.dumps(row) + "\n" for row in (rows or self.rows)))
        report = usage.collect_report(self.source, KEY, **kwargs)
        self.validator.validate(report)
        if "usage_metrics" in report:
            metrics.validate_metrics(report["usage_metrics"], {row["session_key"] for row in report["sessions"]}, KEY)
        return report

    def merge(self, reports, **kwargs):
        paths = []
        for index, report in enumerate(reports):
            path = self.work / f"report-{index}.json"
            path.write_text(json.dumps(report))
            paths.append(path)
        return usage.merge_reports(paths, KEY, **kwargs)

    @staticmethod
    def official_result():
        return {"account_snapshot": None, "thread_estimates": [{"thread_id": OWNER,
                "estimated_usage_credits_micros": 9007199254740993,
                "estimated_usage_usd_micros": None, "groups": [{"model_id": "gpt-6.1-sol", "reasoning_effort": "high", "speed": "fast",
                "net_new_input_tokens": None, "cached_input_tokens": None, "input_tokens": None, "output_tokens": 10,
                "total_tokens": None, "estimated_usage_credits_micros": 9007199254740993}]}],
                "diagnostics": {"official_requests": 3, "official_unavailable": 0, "official_thread_usage_missing": 0, "official_invalid_records": 0}}

    def test_offline_flag_preserves_local_ledger_and_has_no_live_call(self):
        rows = self.rows + [self.snapshot_record()]
        v1 = self.collect(rows)
        with patch("scripts.codex_account_usage.collect_account_usage", side_effect=AssertionError("network forbidden")):
            v2 = self.collect(rows, include_account_usage=True)
        self.assertEqual(v1["schema_version"], "session-usage/v3")
        self.assertEqual(v2["schema_version"], "session-usage/v3")
        for name in ("responses", "groups", "summary", "diagnostics"):
            self.assertEqual(v1[name], v2[name])
        snapshot = v2["usage_metrics"]["account_snapshots"][0]
        self.assertEqual(snapshot["credits"]["balance"], "123.45")
        self.assertEqual(snapshot["scope"], "account_quota")
        self.assertEqual(snapshot["observed_in_session_key"], v2["sessions"][0]["session_key"])
        self.assertIsNone(snapshot["ordinary_usage_allowed"])
        for private in (OWNER, "PRIVATE_ACCOUNT", "PRIVATE_EMAIL", "PRIVATE_VOUCHER", KEY.hex()):
            self.assertNotIn(private, json.dumps(v2))
            self.assertNotIn(private, usage.render_csv(v2))

    def test_snapshot_balance_changes_do_not_become_session_cost(self):
        second = self.snapshot_record("2026-10-01T04:00:00.000000Z")
        second["payload"]["rate_limits"]["credits"]["balance"] = "3.45"
        report = self.collect(self.rows + [self.snapshot_record(), second], include_account_usage=True)
        self.assertEqual(len(report["usage_metrics"]["account_snapshots"]), 2)
        self.assertEqual(report["summary"]["estimated_credits"], self.collect()["summary"]["estimated_credits"])

    def test_duplicate_observations_and_overlap_are_idempotent(self):
        record = self.snapshot_record()
        report = self.collect(self.rows + [record, record], include_account_usage=True)
        self.assertEqual(report["usage_metrics"]["diagnostics"]["duplicate_snapshot_records"], 1)
        self.assertEqual(len(report["usage_metrics"]["account_snapshots"]), 1)
        merged = self.merge([report, report])
        self.assertEqual(merged["usage_metrics"], report["usage_metrics"])
        self.assertEqual(merged["summary"], report["summary"])

    def test_inherited_fork_observation_is_ignored(self):
        header = {"type": "session_meta", "payload": {"id": "private-old-owner"}}
        report = self.collect([header, self.snapshot_record()] + self.rows, include_account_usage=True)
        self.assertFalse(report["usage_metrics"]["account_snapshots"])
        self.assertEqual(report["usage_metrics"]["diagnostics"]["inherited_snapshot_records_ignored"], 1)

    def test_invalid_snapshot_does_not_erase_local_usage(self):
        bad = self.snapshot_record()
        bad["payload"]["rate_limits"]["credits"]["balance"] = "NaN"
        report = self.collect(self.rows + [bad], include_account_usage=True)
        self.assertEqual(report["summary"]["response_count"], 2)
        self.assertGreater(report["usage_metrics"]["diagnostics"]["invalid_snapshot_records"], 0)

    def test_official_estimates_are_separate_and_micros_exact(self):
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=self.official_result()) as collector:
            report = self.collect(official_usage=True)
        collector.assert_called_once_with([OWNER], codex_bin=None, timeout=20.0)
        estimate = report["usage_metrics"]["thread_estimates"][0]
        self.assertEqual(estimate["status"], "available")
        self.assertEqual(estimate["estimated_usage_credits_micros"], 9007199254740993)
        self.assertEqual(report["billing_status"], "actual_debit_unavailable")
        self.assertEqual(report["summary"], self.collect()["summary"])
        rows = list(csv.DictReader(io.StringIO(usage.render_csv(report))))
        total = next(row for row in rows if row["record_type"] == "official_thread_total")
        self.assertEqual(total["official_estimated_credits"], "9007199254.740993")
        self.assertEqual(total["estimated_usage_credits_micros"], "9007199254740993")
        self.assertEqual(total["estimated_credits"], "")
        self.assertEqual(len([row for row in rows if row["record_type"] == "official_thread_group"]), 1)

    def test_non_billable_local_review_keeps_provider_estimates_and_account_snapshot(self):
        rows = copy.deepcopy(self.rows[:7])
        rows[3]["payload"]["model"] = "codex-auto-review"
        rows[5]["timestamp"] = "2026-10-07T13:21:21Z"
        result = self.official_result()
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=result):
            report = self.collect(rows + [self.snapshot_record()], official_usage=True)
        self.assertEqual(report["schema_version"], "session-usage/v3")
        self.assertEqual(report["summary"]["estimated_credits"], "0")
        self.assertEqual(report["summary"]["non_billable_tokens"], 12000)
        self.assertEqual(report["usage_metrics"]["thread_estimates"][0]["estimated_usage_credits_micros"], 9007199254740993)
        self.assertEqual(report["usage_metrics"]["account_snapshots"][0]["credits"]["balance"], "123.45")
        self.assertEqual(report["billing_status"], "actual_debit_unavailable")
        csv_rows = list(csv.DictReader(io.StringIO(usage.render_csv(report))))
        local = next(row for row in csv_rows if row["record_type"] == "local_estimate")
        official = next(row for row in csv_rows if row["record_type"] == "official_thread_total")
        self.assertEqual(local["estimated_credits"], "0")
        self.assertEqual(official["estimated_credits"], "")
        self.assertEqual(official["non_billable_tokens"], "")

    def test_v3_metrics_survive_merge_without_schema_downgrade(self):
        baseline = self.collect()
        observed = self.collect(self.rows + [self.snapshot_record()], include_account_usage=True)
        report = self.merge([baseline, observed, observed])
        self.assertEqual(report["schema_version"], "session-usage/v3")
        self.assertEqual(report["pricing_policy"], baseline["pricing_policy"])
        self.assertEqual(report["usage_metrics"], observed["usage_metrics"])
        self.assertEqual(report["summary"], baseline["summary"])

    def test_missing_thread_usage_is_explicit_not_zero(self):
        result = self.official_result()
        result["thread_estimates"] = []
        result["diagnostics"]["official_thread_usage_missing"] = 1
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=result):
            report = self.collect(official_usage=True)
        estimate = report["usage_metrics"]["thread_estimates"][0]
        self.assertEqual(estimate["status"], "unavailable")
        self.assertIsNone(estimate["estimated_usage_credits_micros"])
        self.assertEqual(estimate["groups"], [])
        self.assertIn("official_thread_unavailable", usage.render_csv(report))

    def test_v1_and_v2_merge_preserve_metrics(self):
        card = usage.load_rate_card(usage.ARCHIVED_RATE_CARD)
        v1 = self.collect(rate_card=card)
        v2 = self.collect(self.rows + [self.snapshot_record()], include_account_usage=True, rate_card=card)
        self.assertEqual(v1["schema_version"], "session-usage/v1")
        self.assertEqual(v2["schema_version"], "session-usage/v2")
        report = self.merge([v1, v2], rate_card=card)
        self.assertEqual(report["schema_version"], "session-usage/v2")
        self.assertEqual(report["summary"], v1["summary"])
        self.assertEqual(report["usage_metrics"], v2["usage_metrics"])

    def test_latest_thread_observation_replaces_prior_cumulative_value(self):
        result = self.official_result()
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=result), patch.object(metrics, "_now", return_value=STAMP):
            first = self.collect(official_usage=True)
        result["thread_estimates"][0]["estimated_usage_credits_micros"] += 1
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=result), patch.object(metrics, "_now", return_value="2026-10-01T04:00:00.000000Z"):
            second = self.collect(official_usage=True)
        merged = self.merge([second, first, second])
        self.assertEqual(merged["usage_metrics"]["thread_estimates"], second["usage_metrics"]["thread_estimates"])

    def test_resigning_report_cannot_rebind_metric_session(self):
        report = self.collect(self.rows + [self.snapshot_record()], include_account_usage=True)
        report["usage_metrics"]["account_snapshots"][0]["observed_in_session_key"] = "a" * 64
        with self.assertRaisesRegex(usage.ReportError, "invalid_metric_observation_key"):
            self.merge([usage._sign(report, KEY)])

    def test_unknown_metric_field_rejected_even_if_resigned(self):
        report = self.collect(self.rows + [self.snapshot_record()], include_account_usage=True)
        report["usage_metrics"]["account_snapshots"][0]["email"] = "private"
        with self.assertRaisesRegex(usage.ReportError, "invalid_report_schema"):
            self.merge([usage._sign(report, KEY)])

    def test_v1_rejects_metrics_and_v2_requires_metrics(self):
        report = self.collect(rate_card=usage.load_rate_card(usage.ARCHIVED_RATE_CARD))
        report["usage_metrics"] = {"account_snapshots": [], "thread_estimates": [], "diagnostics": dict.fromkeys(metrics.DIAGNOSTICS, 0)}
        self.assertFalse(self.validator.is_valid(report))
        report["schema_version"] = "session-usage/v2"
        self.assertTrue(self.validator.is_valid(report))
        del report["usage_metrics"]
        self.assertFalse(self.validator.is_valid(report))

    def test_offline_cli_json_csv_and_merge(self):
        self.collect(self.rows + [self.snapshot_record()])
        key_file = self.work / "company.key"
        key_file.write_text(KEY.hex() + "\n")
        reports = self.work / "exports"
        reports.mkdir()
        exported = reports / "export.json"
        command = [sys.executable, str(ROOT / "scripts/toolkit.py"), "session-usage",
                   "--source-root", str(self.source), "--key-file", str(key_file),
                   "--include-account-usage", "--output", str(exported)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads(exported.read_text())
        self.validator.validate(report)
        self.assertEqual(report["schema_version"], "session-usage/v3")
        merged = self.work / "summary.csv"
        completed = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "session-usage-merge",
                                   "--reports-root", str(reports), "--key-file", str(key_file),
                                   "--format", "csv", "--output", str(merged)],
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("account_snapshot", merged.read_text())
        self.assertNotIn(OWNER, merged.read_text())

    def test_conflicting_same_time_official_totals_fail_closed(self):
        result = self.official_result()
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=result), patch.object(metrics, "_now", return_value=STAMP):
            first = self.collect(official_usage=True)
        result["thread_estimates"][0]["estimated_usage_credits_micros"] += 1
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=result), patch.object(metrics, "_now", return_value=STAMP):
            second = self.collect(official_usage=True)
        with self.assertRaisesRegex(usage.ReportError, "conflicting_thread_estimates"):
            self.merge([first, second])
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=result), patch.object(metrics, "_now", return_value="2026-10-01T04:00:00.000000Z"):
            newest = self.collect(official_usage=True)
        for reports in ([first, newest, second], [newest, second, first]):
            with self.assertRaisesRegex(usage.ReportError, "conflicting_thread_estimates"):
                self.merge(reports)

    def test_provider_read_timestamp_survives_batch_completion(self):
        result = self.official_result()
        result["thread_estimates"][0]["observed_at"] = STAMP
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=result), patch.object(metrics, "_now", return_value="2026-10-01T04:00:00.000000Z"):
            report = self.collect(official_usage=True)
        self.assertEqual(report["usage_metrics"]["thread_estimates"][0]["observed_at"], STAMP)
        result["thread_estimates"] = []
        result["thread_observations"] = {OWNER: STAMP}
        with patch("scripts.codex_account_usage.collect_account_usage", return_value=result), patch.object(metrics, "_now", return_value="2026-10-01T04:00:00.000000Z"):
            report = self.collect(official_usage=True)
        self.assertEqual(report["usage_metrics"]["thread_estimates"][0]["observed_at"], STAMP)


if __name__ == "__main__":
    unittest.main()
