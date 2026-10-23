from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime

from scripts import antigravity_quota_snapshot as quota


OBSERVED_AT = "2026-10-23T00:32:53.123456Z"
RESET_AT = "2026-10-23T05:00:00Z"
PRIVATE_SENTINELS = (
    "private.account@example.invalid",
    "ACCOUNT_PRIVATE_SENTINEL",
    "C:\\private\\workspace",
    "PRIVATE_BUCKET_DESCRIPTION",
    "PRIVATE_PROMPT_CONTENT",
)


def official_report() -> dict:
    """Synthetic values with the observed official report's public structure."""
    groups = []
    for group_name, safe_group in quota.QUOTA_GROUPS.items():
        buckets = []
        for bucket_id, (bucket_group, window) in quota.QUOTA_BUCKETS.items():
            if bucket_group == safe_group:
                buckets.append({
                    "id": bucket_id,
                    "name": PRIVATE_SENTINELS[0],
                    "description": PRIVATE_SENTINELS[3],
                    "window": window,
                    "remaining_fraction": 0.75,
                    "reset_time": RESET_AT,
                })
        groups.append({"name": group_name, "buckets": buckets})
    return {
        "status": "SUCCESS",
        "num_turns": 0,
        "conversation_id": "",
        "account": PRIVATE_SENTINELS[1],
        "email": PRIVATE_SENTINELS[0],
        "path": PRIVATE_SENTINELS[2],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "response": PRIVATE_SENTINELS[4],
        "command": {"name": "usage", "data": {"groups": groups}},
    }


def matched_snapshot() -> dict:
    snapshot = quota.normalize_quota_report(official_report(), OBSERVED_AT)
    snapshot["identity_status"] = "matched"
    return snapshot


def metrics(payload: dict) -> dict:
    entries = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    return {entry["name"]: entry for entry in entries}


def attributes(point: dict) -> dict:
    return {item["key"]: item["value"]["stringValue"] for item in point["attributes"]}


class AntigravityQuotaSnapshotTests(unittest.TestCase):
    def test_official_report_retains_only_five_known_numeric_buckets(self) -> None:
        snapshot = quota.normalize_quota_report(official_report(), OBSERVED_AT)
        self.assertEqual(snapshot["source"], "official-cli-report")
        self.assertEqual(snapshot["identity_status"], "unverified")
        self.assertEqual(len(snapshot["buckets"]), 5)
        self.assertEqual({item["bucket"] for item in snapshot["buckets"]}, set(quota.QUOTA_BUCKETS))
        self.assertEqual(snapshot["skipped_unknown_buckets"], 0)
        self.assertEqual(snapshot["skipped_invalid_buckets"], 0)
        self.assertTrue(all(item["remaining_ratio"] == 0.75 for item in snapshot["buckets"]))
        rendered = json.dumps(snapshot, allow_nan=False)
        for sentinel in PRIVATE_SENTINELS:
            self.assertNotIn(sentinel, rendered)

    def test_input_is_not_modified(self) -> None:
        report = official_report()
        before = copy.deepcopy(report)
        quota.normalize_quota_report(report, OBSERVED_AT)
        self.assertEqual(report, before)

    def test_unknown_categories_are_omitted_and_counted(self) -> None:
        report = official_report()
        report["command"]["data"]["groups"][0]["buckets"].append({
            "id": PRIVATE_SENTINELS[1], "window": "weekly", "remaining_fraction": 0.1,
        })
        report["command"]["data"]["groups"].append({
            "name": PRIVATE_SENTINELS[0],
            "buckets": [{"id": "gemini-weekly", "window": "weekly", "remaining_fraction": 0.1}],
        })
        snapshot = quota.normalize_quota_report(report, OBSERVED_AT)
        self.assertEqual(snapshot["skipped_unknown_buckets"], 2)
        self.assertEqual(len(snapshot["buckets"]), 5)
        self.assertNotIn(PRIVATE_SENTINELS[1], json.dumps(snapshot))

    def test_bool_null_strings_and_non_finite_ratios_never_become_zero(self) -> None:
        for invalid in [True, False, None, "0", "0.25", "NaN", float("nan"), float("inf"), float("-inf"), -0.1, 1.1, [], {}]:
            with self.subTest(value_type=type(invalid).__name__):
                report = official_report()
                report["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"] = invalid
                snapshot = quota.normalize_quota_report(report, OBSERVED_AT)
                self.assertEqual(len(snapshot["buckets"]), 4)
                self.assertEqual(snapshot["skipped_invalid_buckets"], 1)
                self.assertTrue(all(item["remaining_ratio"] == 0.75 for item in snapshot["buckets"]))

    def test_actual_zero_and_one_are_preserved(self) -> None:
        report = official_report()
        raw = report["command"]["data"]["groups"][0]["buckets"]
        raw[0]["remaining_fraction"] = 0
        raw[1]["remaining_fraction"] = 1
        snapshot = quota.normalize_quota_report(report, OBSERVED_AT)
        ratios = {item["bucket"]: item["remaining_ratio"] for item in snapshot["buckets"]}
        self.assertEqual(ratios[raw[0]["id"]], 0.0)
        self.assertEqual(ratios[raw[1]["id"]], 1.0)

    def test_missing_ratio_is_omitted_without_a_zero_measurement(self) -> None:
        report = official_report()
        del report["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"]
        snapshot = quota.normalize_quota_report(report, OBSERVED_AT)
        self.assertEqual(snapshot["skipped_invalid_buckets"], 1)
        self.assertEqual(len(snapshot["buckets"]), 4)
        self.assertTrue(all(item["remaining_ratio"] == 0.75 for item in snapshot["buckets"]))

    def test_wrong_group_or_window_is_omitted(self) -> None:
        report = official_report()
        raw = report["command"]["data"]["groups"][0]["buckets"]
        raw[0]["window"] = "daily"
        raw[1]["id"] = "3p-5h"
        snapshot = quota.normalize_quota_report(report, OBSERVED_AT)
        self.assertEqual(snapshot["skipped_invalid_buckets"], 2)
        self.assertEqual(len(snapshot["buckets"]), 3)

    def test_invalid_or_missing_reset_omits_only_the_reset_measurement(self) -> None:
        for invalid in [None, "invalid", "2026-10-23T05:00:00", True, float("nan"), 1234]:
            with self.subTest(value_type=type(invalid).__name__):
                report = official_report()
                raw = report["command"]["data"]["groups"][0]["buckets"][0]
                raw["reset_time"] = invalid
                snapshot = quota.normalize_quota_report(report, OBSERVED_AT)
                bucket = next(item for item in snapshot["buckets"] if item["bucket"] == raw["id"])
                self.assertEqual(bucket["remaining_ratio"], 0.75)
                self.assertNotIn("reset_at_unix_seconds", bucket)

    def test_report_must_be_the_successful_passive_usage_command(self) -> None:
        mutations = [
            (lambda report: report.update(status="ERROR"), "report_not_successful"),
            (lambda report: report.update(num_turns=1), "report_not_passive"),
            (lambda report: report.update(num_turns=False), "report_not_passive"),
            (lambda report: report.update(num_turns="0"), "report_not_passive"),
            (lambda report: report["command"].update(name=PRIVATE_SENTINELS[4]), "unexpected_command"),
            (lambda report: report["command"].update(data={}), "invalid_quota_groups"),
        ]
        for mutate, code in mutations:
            with self.subTest(code=code):
                report = official_report()
                mutate(report)
                with self.assertRaisesRegex(quota.QuotaReportError, "^" + code + "$"):
                    quota.normalize_quota_report(report, OBSERVED_AT)

    def test_no_supported_measurements_is_an_error(self) -> None:
        report = official_report()
        report["command"]["data"]["groups"] = []
        with self.assertRaisesRegex(quota.QuotaReportError, "^no_supported_quota_buckets$"):
            quota.normalize_quota_report(report, OBSERVED_AT)

    def test_duplicate_bucket_is_rejected_instead_of_creating_ambiguous_series(self) -> None:
        report = official_report()
        raw = report["command"]["data"]["groups"][0]["buckets"]
        raw.append(copy.deepcopy(raw[0]))
        with self.assertRaisesRegex(quota.QuotaReportError, "^duplicate_quota_bucket$"):
            quota.normalize_quota_report(report, OBSERVED_AT)

    def test_timestamp_is_explicit_utc_and_cannot_fall_back_to_now(self) -> None:
        snapshot = quota.normalize_quota_report(official_report(), "2026-10-23T08:32:53.123456+08:00")
        self.assertEqual(snapshot["observed_at"], OBSERVED_AT)
        for invalid in [None, "bad", "2026-10-23T00:32:53", datetime(2026, 10, 23), 0, True]:
            with self.subTest(value_type=type(invalid).__name__):
                with self.assertRaisesRegex(quota.QuotaReportError, "^invalid_timestamp$"):
                    quota.normalize_quota_report(official_report(), invalid)

    def test_build_fails_closed_without_both_identity_gates(self) -> None:
        snapshot = matched_snapshot()
        for status in ["matched", "unverified", "mismatched", None]:
            for identity_match in [False, None, "true", 1]:
                with self.subTest(status=status, identity_match=identity_match):
                    snapshot["identity_status"] = status
                    with self.assertRaisesRegex(quota.QuotaReportError, "^identity_not_matched$"):
                        quota.build_metrics_payload(snapshot, identity_match=identity_match)
        snapshot["identity_status"] = "unverified"
        with self.assertRaisesRegex(quota.QuotaReportError, "^identity_not_matched$"):
            quota.build_metrics_payload(snapshot, identity_match=True)
        with self.assertRaisesRegex(quota.QuotaReportError, "^identity_not_matched$"):
            quota.build_metrics_payload(matched_snapshot())

    def test_payload_has_independent_quota_metrics_and_bounded_labels(self) -> None:
        payload = quota.build_metrics_payload(matched_snapshot(), identity_match=True)
        names = metrics(payload)
        self.assertEqual(set(names), {
            "antigravity_account_quota_remaining_ratio",
            "antigravity_account_quota_snapshot_timestamp_seconds",
            "antigravity_account_quota_identity_match",
            "antigravity_account_quota_reset_timestamp_seconds",
        })
        ratio = names["antigravity_account_quota_remaining_ratio"]["gauge"]["dataPoints"]
        self.assertEqual(len(ratio), 5)
        for point in ratio:
            labels = attributes(point)
            self.assertEqual(set(labels), {"tool", "source", "scope", "evidence_class", "quota_group", "bucket", "window"})
            self.assertEqual(labels["source"], quota.SOURCE)
            self.assertEqual(labels["scope"], "account")
            self.assertEqual(labels["evidence_class"], "observed")
            self.assertEqual(quota.QUOTA_BUCKETS[labels["bucket"]], (labels["quota_group"], labels["window"]))
        rendered = json.dumps(payload, allow_nan=False)
        for sentinel in PRIVATE_SENTINELS:
            self.assertNotIn(sentinel, rendered)
        self.assertNotIn("input_tokens", rendered)
        self.assertNotIn("output_tokens", rendered)
        self.assertNotIn("context", " ".join(names))
        resource = attributes(payload["resourceMetrics"][0]["resource"])
        self.assertEqual(resource["service.name"], "antigravity-quota")
        self.assertEqual(resource["ai_agent.product"], "antigravity")
        self.assertEqual(resource["ai_agent.surface"], "account")

    def test_observation_time_survives_payload_build_for_staleness_checks(self) -> None:
        snapshot = matched_snapshot()
        payload = quota.build_metrics_payload(snapshot, identity_match=True)
        expected = datetime.fromisoformat(OBSERVED_AT.replace("Z", "+00:00")).timestamp()
        names = metrics(payload)
        point = names["antigravity_account_quota_snapshot_timestamp_seconds"]["gauge"]["dataPoints"][0]
        self.assertEqual(point["asDouble"], expected)
        self.assertEqual(int(point["timeUnixNano"]) // 1_000_000_000, int(expected))
        self.assertEqual(int(point["timeUnixNano"]) % 1_000_000_000, 123456000)
        for entry in names.values():
            for data_point in entry["gauge"]["dataPoints"]:
                self.assertEqual(data_point["timeUnixNano"], point["timeUnixNano"])

    def test_snapshot_cannot_inject_unknown_labels_or_invalid_numbers(self) -> None:
        mutations = [
            lambda snapshot: snapshot.update(schema_version=True),
            lambda snapshot: snapshot.update(source=PRIVATE_SENTINELS[0]),
            lambda snapshot: snapshot.update(observed_at_unix_seconds=0),
            lambda snapshot: snapshot["buckets"][0].update(bucket=PRIVATE_SENTINELS[0]),
            lambda snapshot: snapshot["buckets"][0].update(quota_group=PRIVATE_SENTINELS[1]),
            lambda snapshot: snapshot["buckets"][0].update(remaining_ratio=float("nan")),
            lambda snapshot: snapshot["buckets"][0].update(reset_at_unix_seconds=True),
        ]
        for mutate in mutations:
            snapshot = matched_snapshot()
            mutate(snapshot)
            with self.assertRaises(quota.QuotaReportError) as failure:
                quota.build_metrics_payload(snapshot, identity_match=True)
            for sentinel in PRIVATE_SENTINELS:
                self.assertNotIn(sentinel, str(failure.exception))

    def test_unsafe_resource_options_are_rejected(self) -> None:
        with self.assertRaisesRegex(quota.QuotaReportError, "^invalid_profile$"):
            quota.build_metrics_payload(matched_snapshot(), identity_match=True, profile=PRIVATE_SENTINELS[0])
        with self.assertRaisesRegex(quota.QuotaReportError, "^invalid_service_namespace$"):
            quota.build_metrics_payload(matched_snapshot(), identity_match=True, service_namespace=PRIVATE_SENTINELS[2])

    def test_corporate_profile_matches_existing_exporter_and_keeps_identity_gate(self) -> None:
        profile = "corporate-local-redacted"
        payload = quota.build_metrics_payload(matched_snapshot(), identity_match=True, profile=profile)
        resource = attributes(payload["resourceMetrics"][0]["resource"])
        self.assertEqual(resource["ai_observability.profile"], profile)
        self.assertEqual(resource["deployment.environment.name"], profile)
        status = quota.build_identity_status_payload(False, OBSERVED_AT, profile=profile)
        self.assertEqual(status["resourceMetrics"][0]["resource"], payload["resourceMetrics"][0]["resource"])
        with self.assertRaisesRegex(quota.QuotaReportError, "^identity_not_matched$"):
            quota.build_metrics_payload(matched_snapshot(), identity_match=False, profile=profile)
        for unsupported in ["evaluation", "corporate", "core"]:
            with self.subTest(profile=unsupported):
                with self.assertRaisesRegex(quota.QuotaReportError, "^invalid_profile$"):
                    quota.build_metrics_payload(matched_snapshot(), identity_match=True, profile=unsupported)

    def test_identity_failure_only_emits_the_gate_and_keeps_quota_data_age(self) -> None:
        observed = "2026-10-23T01:00:00.654321Z"
        payload = quota.build_identity_status_payload(False, observed)
        names = metrics(payload)
        self.assertEqual(set(names), {"antigravity_account_quota_identity_match"})
        point = names["antigravity_account_quota_identity_match"]["gauge"]["dataPoints"][0]
        self.assertEqual(point["asDouble"], 0.0)
        expected = datetime.fromisoformat(observed.replace("Z", "+00:00")).timestamp()
        self.assertEqual(int(point["timeUnixNano"]) // 1_000_000_000, int(expected))
        self.assertEqual(int(point["timeUnixNano"]) % 1_000_000_000, 654321000)
        self.assertEqual(attributes(point), {
            "tool": "antigravity", "source": quota.SOURCE,
            "scope": "account", "evidence_class": "observed",
        })
        rendered = json.dumps(payload, allow_nan=False)
        for sentinel in PRIVATE_SENTINELS:
            self.assertNotIn(sentinel, rendered)
        self.assertNotIn("remaining_ratio", rendered)
        self.assertNotIn("reset_timestamp", rendered)
        self.assertNotIn("snapshot_timestamp", rendered)

    def test_identity_success_uses_the_same_series_and_resource_as_quota(self) -> None:
        status = quota.build_identity_status_payload(True, OBSERVED_AT)
        full = quota.build_metrics_payload(matched_snapshot(), identity_match=True)
        self.assertEqual(status["resourceMetrics"][0]["resource"], full["resourceMetrics"][0]["resource"])
        name = "antigravity_account_quota_identity_match"
        self.assertEqual(metrics(status)[name], metrics(full)[name])

    def test_identity_status_payload_requires_bool_and_explicit_timestamp(self) -> None:
        for invalid in [None, 0, 1, "true", "matched", {}]:
            with self.subTest(value_type=type(invalid).__name__):
                with self.assertRaisesRegex(quota.QuotaReportError, "^invalid_identity_status$"):
                    quota.build_identity_status_payload(invalid, OBSERVED_AT)
        with self.assertRaisesRegex(quota.QuotaReportError, "^invalid_timestamp$"):
            quota.build_identity_status_payload(False, "2026-10-23T00:32:53")


if __name__ == "__main__":
    unittest.main()
