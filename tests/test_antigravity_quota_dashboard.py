from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

from scripts.antigravity_desktop_metrics import METRIC_NAMES as DESKTOP_METRIC_NAMES


ROOT = Path(__file__).resolve().parents[1]
QUOTA_NAMES = {
    "antigravity_account_quota_remaining_ratio",
    "antigravity_account_quota_reset_timestamp_seconds",
    "antigravity_account_quota_snapshot_timestamp_seconds",
    "antigravity_account_quota_identity_match",
}
QUOTA_DIMENSIONS = {"scope", "quota_group", "bucket", "window"}
FIXTURE_EXCLUSION = 'service_namespace!~"^ai-collaboration(-cost|-role)?-fixture$"'
STREAM_KEYS = {
    "service_name", "service_namespace", "ai_observability_profile", "source", "scope",
}


class AntigravityQuotaDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dashboard = json.loads(
            (ROOT / "config/grafana/dashboards/antigravity-usage.json").read_text(
                encoding="utf-8"
            )
        )

    def quota_panels(self) -> list[dict]:
        return [
            panel
            for panel in self.dashboard["panels"]
            if any(
                "antigravity_account_quota_" in target.get("expr", "")
                for target in panel.get("targets", [])
            )
        ]

    def test_account_snapshots_use_instant_queries_and_keep_source_boundary(self) -> None:
        panels = self.quota_panels()
        self.assertEqual(len(panels), 4)
        for panel in panels:
            for target in panel["targets"]:
                expression = target["expr"]
                self.assertTrue(target["instant"])
                self.assertFalse(target["range"])
                self.assertIn('source="official-cli-report"', expression)
                self.assertIn('scope="account"', expression)
                self.assertIn(FIXTURE_EXCLUSION, expression)
                self.assertNotIn("antigravity_quota_remaining_ratio{", expression)
                self.assertNotIn("or vector(0)", expression)
                self.assertNotIn("last_over_time", expression)
                self.assertNotIn("max by (type)", expression)

    def test_ratio_and_reset_keep_bucket_rows_and_require_fresh_matching_identity(self) -> None:
        tables = [panel for panel in self.quota_panels() if panel["type"] == "table"]
        self.assertEqual(len(tables), 2)
        for panel in tables:
            expression = panel["targets"][0]["expr"]
            self.assertIn("time() - antigravity_account_quota_snapshot_timestamp_seconds", expression)
            self.assertIn("<= 180", expression)
            self.assertIn("antigravity_account_quota_identity_match", expression)
            self.assertIn("== 1", expression)
            self.assertNotRegex(expression, r"\b(max|sum|avg)\s*(by\s*\([^)]*\))?\s*\(")
            shown_columns = panel["transformations"][0]["options"]["include"]["names"]
            self.assertEqual(set(shown_columns), {"quota_group", "bucket", "window", "Value"})
            self.assertEqual(panel["fieldConfig"]["defaults"]["noValue"], "No data")
        ratio = next(panel for panel in tables if "remaining_ratio" in panel["targets"][0]["expr"])
        self.assertEqual(ratio["fieldConfig"]["defaults"]["unit"], "percent")
        self.assertIn("100 *", ratio["targets"][0]["expr"])

    def test_each_bucket_must_belong_to_the_current_source_snapshot(self) -> None:
        tables = [panel for panel in self.quota_panels() if panel["type"] == "table"]
        for panel in tables:
            expression = panel["targets"][0]["expr"]
            expected_metric = (
                "antigravity_account_quota_remaining_ratio"
                if "remaining_ratio" in expression
                else "antigravity_account_quota_reset_timestamp_seconds"
            )
            # Collector retains old bucket series. A fresh global snapshot alone
            # cannot establish that a bucket was present in that snapshot.
            self.assertIn(f"abs(timestamp({expected_metric}{{", expression)
            self.assertIn("group_left antigravity_account_quota_snapshot_timestamp_seconds{", expression)
            self.assertIn(") <= 0.001)", expression)
            bucket_joins = [
                {key.strip() for key in keys.split(",")}
                for keys in re.findall(r"and on \(([^)]+)\) \(abs\(timestamp", expression)
            ]
            self.assertEqual(bucket_joins, [STREAM_KEYS | {"quota_group", "bucket", "window"}])

    def test_namespace_and_profile_cannot_unlock_another_stream(self) -> None:
        for panel in self.quota_panels():
            expression = panel["targets"][0]["expr"]
            joins = [
                {key.strip() for key in keys.split(",")}
                for keys in re.findall(r"\bon \(([^)]+)\)", expression)
            ]
            for keys in joins:
                self.assertTrue(STREAM_KEYS <= keys, (panel["title"], keys))
            if panel["type"] == "table":
                # Per-point timestamp, global age and identity checks all use
                # the same complete stream key, even when bucket keys differ.
                self.assertEqual(len(joins), 4)
                self.assertEqual(joins[1:], [STREAM_KEYS, STREAM_KEYS, STREAM_KEYS])
            elif expression.startswith("antigravity_account_quota_identity_match{"):
                self.assertEqual(joins, [STREAM_KEYS])

    def test_snapshot_age_is_visible_and_turns_red_when_stale(self) -> None:
        age = next(
            panel
            for panel in self.quota_panels()
            if panel["targets"][0]["expr"].startswith("clamp_min(time() -")
        )
        self.assertNotIn("<= 180", age["targets"][0]["expr"])
        self.assertIn(
            {"color": "red", "value": 180},
            age["fieldConfig"]["defaults"]["thresholds"]["steps"],
        )
        self.assertEqual(age["fieldConfig"]["defaults"]["noValue"], "No data")

    def test_identity_zero_covers_unavailable_and_mismatched_accounts(self) -> None:
        identity = next(
            panel
            for panel in self.quota_panels()
            if panel["targets"][0]["expr"].startswith("antigravity_account_quota_identity_match{")
        )
        mapping = identity["fieldConfig"]["defaults"]["mappings"][0]["options"]
        self.assertEqual(mapping["0"]["text"], "未確認／不相符")
        self.assertEqual(mapping["1"]["text"], "同帳戶已確認")
        self.assertNotIn("== 1", identity["targets"][0]["expr"])

    def test_quota_dimensions_are_allowed_only_for_exact_snapshot_metric_names(self) -> None:
        for mode in ("core", "evaluation", "corporate"):
            config = yaml.safe_load(
                (ROOT / "config/otel-collector" / f"{mode}.yaml").read_text(
                    encoding="utf-8"
                )
            )
            processor = config["processors"][
                "transform/corporate_allowlist" if mode == "corporate" else "transform/privacy"
            ]
            statements = [
                statement
                for group in processor["metric_statements"]
                if group["context"] == "datapoint"
                for statement in group["statements"]
                if statement.startswith("keep_keys(attributes,")
            ]
            quota_statement = next(
                statement for statement in statements if '"quota_group"' in statement
            )
            keys_text, condition = quota_statement.split("]) where ", 1)
            keys = set(json.loads(keys_text.removeprefix("keep_keys(attributes, ") + "]"))
            self.assertEqual(
                keys,
                QUOTA_DIMENSIONS | {"tool", "source", "evidence_class"},
                mode,
            )
            allowed_names = set(re.findall(r'metric\.name == "([^"]+)"', condition))
            self.assertEqual(allowed_names, QUOTA_NAMES, mode)
            self.assertNotIn("IsMatch", condition, mode)
            legacy_statement = next(statement for statement in statements if statement != quota_statement)
            legacy_keys_text, legacy_condition = legacy_statement.split("]) where ", 1)
            legacy_keys = set(json.loads(legacy_keys_text.removeprefix("keep_keys(attributes, ") + "]"))
            self.assertFalse(QUOTA_DIMENSIONS & legacy_keys, mode)
            self.assertTrue(legacy_condition.startswith("not ("), mode)
            self.assertTrue(legacy_condition.endswith(")"), mode)
            self.assertEqual(
                set(re.findall(r'metric\.name == "([^"]+)"', legacy_condition)),
                QUOTA_NAMES | DESKTOP_METRIC_NAMES,
                mode,
            )


if __name__ == "__main__":
    unittest.main()
