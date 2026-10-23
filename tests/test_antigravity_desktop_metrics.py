from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import unittest

import yaml

from scripts import antigravity_desktop_metrics as contract


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 23, 12, 0, 0, 123000, tzinfo=timezone.utc)
STREAM_KEYS = {"service_name", "service_namespace", "ai_observability_profile", "source"}
PRIVATE_TEXT = "private-user@example.invalid C:/private/conversation-id private-native-id"


def tokens() -> dict:
    return {
        "read_success": True, "ledger_start_at": NOW - timedelta(days=1),
        "totals": {"total_output_tokens": 100, "thinking_output_tokens": 20,
                   "response_output_tokens": 80},
        "generation_count": 2, "read_limited": True,
    }


def context() -> dict:
    return {
        "read_success": True, "generation_verified": True, "is_latest_generation": True,
        "source_timestamp_seconds": (NOW - timedelta(seconds=5)).timestamp(),
        "estimated_tokens_used": 600, "max_context_tokens": 1000,
    }


def metrics(payload: dict) -> dict[str, dict]:
    items = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    if len(items) != len({item["name"] for item in items}):
        raise AssertionError("duplicate_metric_names")
    return {item["name"].removeprefix("antigravity_desktop_"): item for item in items}


def gauge_value(metric: dict) -> float:
    return metric["gauge"]["dataPoints"][0]["asDouble"]


def attributes(point: dict) -> dict:
    return {item["key"]: item["value"]["stringValue"] for item in point["attributes"]}


class AntigravityDesktopMetricsTests(unittest.TestCase):
    def build(self, token_report=None, context_report=None, **extra) -> dict:
        return contract.build_metrics_payload(
            observed_at=NOW, tokens=tokens() if token_report is None else token_report,
            context=context() if context_report is None else context_report, **extra,
        )

    def test_counters_preserve_deduplicated_ledger_start_and_observed_types_only(self) -> None:
        result = metrics(self.build())
        total = result["generation_observed_tokens_total"]["sum"]
        self.assertEqual(total["aggregationTemporality"], 2)
        self.assertTrue(total["isMonotonic"])
        values = {attributes(point)["token_type"]: point["asDouble"] for point in total["dataPoints"]}
        self.assertEqual(values, tokens()["totals"])
        self.assertNotIn("uncached_input_tokens", values)
        for point in total["dataPoints"]:
            self.assertEqual(point["startTimeUnixNano"], str(contract._time_ns(NOW - timedelta(days=1))))
            self.assertEqual(point["timeUnixNano"], str(contract._time_ns(NOW)))
        self.assertEqual(result["generation_records_total"]["sum"]["dataPoints"][0]["asDouble"], 2)

    def test_context_snapshot_values_keep_observation_time_and_source_time_stays_separate(self) -> None:
        result = metrics(self.build())
        poll_ns = str(contract._time_ns(NOW))
        for name in ("latest_context_estimated_tokens", "latest_context_capacity_tokens", "latest_context_used_ratio"):
            self.assertEqual(result[name]["gauge"]["dataPoints"][0]["timeUnixNano"], poll_ns)
        self.assertEqual(gauge_value(result["latest_context_estimated_tokens"]), 600)
        self.assertEqual(gauge_value(result["latest_context_used_ratio"]), 0.6)
        source = result["latest_context_source_timestamp_seconds"]["gauge"]["dataPoints"][0]
        self.assertEqual(source["timeUnixNano"], poll_ns)
        self.assertEqual(source["asDouble"], context()["source_timestamp_seconds"])
        for point in result["read_success"]["gauge"]["dataPoints"]:
            self.assertEqual(point["timeUnixNano"], poll_ns)

    def test_unknown_capacity_is_not_inferred_and_its_retained_gauges_are_closed(self) -> None:
        report = context()
        report.pop("max_context_tokens")
        result = metrics(self.build(context_report=report))
        self.assertIn("latest_context_estimated_tokens", result)
        self.assertNotIn("latest_context_capacity_tokens", result)
        self.assertNotIn("latest_context_used_ratio", result)
        availability = {attributes(point)["component"]: point["asDouble"]
                        for point in result["latest_context_available"]["gauge"]["dataPoints"]}
        self.assertEqual(availability, {"estimate": 1, "capacity": 0, "ratio": 0})

    def test_explicit_zero_estimate_is_retained_but_missing_estimate_is_not_zero(self) -> None:
        zero = context()
        zero["estimated_tokens_used"] = 0
        self.assertEqual(gauge_value(metrics(self.build(context_report=zero))["latest_context_estimated_tokens"]), 0)
        absent = context()
        absent.pop("estimated_tokens_used")
        result = metrics(self.build(context_report=absent))
        self.assertNotIn("latest_context_estimated_tokens", result)
        self.assertTrue(all(point["asDouble"] == 0 for point in result["latest_context_available"]["gauge"]["dataPoints"]))

    def test_unverified_missing_future_and_non_latest_sources_cannot_publish_context_values(self) -> None:
        cases = [
            {"generation_verified": False}, {"read_success": False}, {"is_latest_generation": False},
            {"source_timestamp_seconds": None},
            {"source_timestamp_seconds": (NOW + timedelta(seconds=1)).timestamp()},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                report = {**context(), **overrides}
                result = metrics(self.build(context_report=report))
                self.assertNotIn("latest_context_estimated_tokens", result)
                self.assertTrue(all(point["asDouble"] == 0 for point in result["latest_context_available"]["gauge"]["dataPoints"]))

    def test_old_generation_with_a_fresh_verified_read_remains_a_valid_snapshot(self) -> None:
        historical_time = (NOW - timedelta(minutes=13)).timestamp()
        report = {**context(), "source_timestamp_seconds": historical_time}
        result = metrics(self.build(context_report=report))
        self.assertEqual(gauge_value(result["latest_context_estimated_tokens"]), 600)
        self.assertEqual(gauge_value(result["latest_context_source_timestamp_seconds"]), historical_time)
        self.assertEqual(gauge_value(result["latest_context_used_ratio"]), 0.6)
        self.assertTrue(all(point["asDouble"] == 1 for point in result["latest_context_available"]["gauge"]["dataPoints"]))
        self.assertEqual(result["latest_context_estimated_tokens"]["gauge"]["dataPoints"][0]["timeUnixNano"], str(contract._time_ns(NOW)))

    def test_unavailable_reader_still_publishes_immediate_health_and_gate_zero(self) -> None:
        result = metrics(self.build(token_report={"read_success": False}, context_report={"read_success": False}))
        self.assertNotIn("generation_observed_tokens_total", result)
        self.assertNotIn("generation_latest_source_timestamp_seconds", result)
        self.assertEqual(gauge_value(result["latest_generation_verified"]), 0)
        self.assertTrue(all(point["asDouble"] == 0 for point in result["read_success"]["gauge"]["dataPoints"]))

    def test_failed_token_read_does_not_refresh_counters_from_persisted_ledger_totals(self) -> None:
        persisted = {**tokens(), "read_success": False,
                     "latest_source_timestamp_seconds": (NOW - timedelta(hours=2)).timestamp()}
        result = metrics(self.build(token_report=persisted))
        self.assertNotIn("generation_observed_tokens_total", result)
        self.assertNotIn("generation_records_total", result)
        token_health = next(point for point in result["read_success"]["gauge"]["dataPoints"]
                            if attributes(point)["component"] == "tokens")
        self.assertEqual(token_health["asDouble"], 0)
        self.assertIn("read_timestamp_seconds", result)
        self.assertIn("generation_read_limited", result)
        self.assertIn("generation_latest_source_timestamp_seconds", result)

    def test_ui_selection_flag_does_not_substitute_for_generation_metadata_verification(self) -> None:
        report = context()
        report.pop("generation_verified")
        report["selection_verified"] = True
        result = metrics(self.build(context_report=report))
        self.assertEqual(gauge_value(result["latest_generation_verified"]), 0)
        self.assertNotIn("latest_context_estimated_tokens", result)
        self.assertTrue(all("_active_" not in name for name in contract.METRIC_NAMES))

    def test_private_extra_metadata_is_never_exported_and_corporate_uses_the_same_contract(self) -> None:
        token_report = {**tokens(), "native_id": PRIVATE_TEXT, "path": PRIVATE_TEXT}
        context_report = {**context(), "selector": PRIVATE_TEXT, "model": PRIVATE_TEXT}
        payload = self.build(token_report=token_report, context_report=context_report, profile="corporate-local-redacted")
        self.assertNotIn(PRIVATE_TEXT, json.dumps(payload))
        for metric in metrics(payload).values():
            for point in metric.get("gauge", metric.get("sum"))["dataPoints"]:
                self.assertLessEqual(set(attributes(point)), {"tool", "source", "evidence_class", "token_type", "component"})
        self.assertLessEqual(set(item["name"] for item in metrics(payload).values()), contract.METRIC_NAMES)

    def test_invalid_ledger_data_rejects_instead_of_fabricating_counters(self) -> None:
        for overrides in ({"totals": {"email": 1}}, {"totals": {"total_output_tokens": True}},
                          {"generation_count": -1}, {"ledger_start_at": NOW + timedelta(seconds=1)}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(contract.DesktopMetricsError):
                    self.build(token_report={**tokens(), **overrides})

    def test_exact_desktop_metric_allowlist_does_not_expand_other_metrics(self) -> None:
        for mode in ("core", "evaluation", "corporate"):
            config = yaml.safe_load((ROOT / "config/otel-collector" / f"{mode}.yaml").read_text(encoding="utf-8"))
            processor = config["processors"]["transform/corporate_allowlist" if mode == "corporate" else "transform/privacy"]
            statements = [s for group in processor["metric_statements"] if group["context"] == "datapoint"
                          for s in group["statements"] if s.startswith("keep_keys(attributes,")]
            desktop = next(s for s in statements if '"component"' in s)
            keys_text, condition = desktop.split("]) where ", 1)
            keys = set(json.loads(keys_text.removeprefix("keep_keys(attributes, ") + "]"))
            self.assertEqual(keys, {"tool", "source", "evidence_class", "token_type", "component"})
            self.assertEqual(set(re.findall(r'metric\.name == "([^"]+)"', condition)), contract.METRIC_NAMES)
            self.assertNotIn("IsMatch", condition)
            legacy = next(s for s in statements if '"event.name"' in s)
            self.assertNotIn('"component"', legacy)
            self.assertTrue(legacy.split("]) where ", 1)[1].startswith("not ("))
            self.assertTrue(contract.METRIC_NAMES <= set(re.findall(r'metric\.name == "([^"]+)"', legacy)))

    def test_dashboard_keeps_desktop_source_health_and_context_gates_separate(self) -> None:
        dashboard = json.loads((ROOT / "config/grafana/dashboards/antigravity-usage.json").read_text(encoding="utf-8"))
        desktop_panels = [panel for panel in dashboard["panels"]
                          if any("antigravity_desktop_" in target.get("expr", "") for target in panel.get("targets", []))]
        self.assertTrue(desktop_panels)
        for panel in desktop_panels:
            for target in panel["targets"]:
                expr = target["expr"]
                self.assertTrue(target["instant"])
                self.assertIn('source="desktop-local-metadata"', expr)
                self.assertIn('service_namespace!~"^ai-collaboration(-cost|-role)?-fixture$"', expr)
                self.assertNotIn("last_over_time", expr)
                self.assertNotIn("rate(", expr)
                self.assertNotIn("or vector(0)", expr)
                for keys in re.findall(r"\bon \(([^)]+)\)", expr):
                    self.assertTrue(STREAM_KEYS <= {key.strip() for key in keys.split(",")})
                if any(name in expr for name in ("latest_context_estimated_tokens{", "latest_context_capacity_tokens{", "latest_context_used_ratio{")):
                    self.assertIn("abs(timestamp(", expr)
                    self.assertIn("<= 0.001", expr)
                    self.assertIn("latest_context_available", expr)
                    self.assertIn("latest_generation_verified", expr)
                    self.assertIn("read_success", expr)
                    self.assertIn("<= 180", expr)
                    self.assertIn('read_timestamp_seconds{', expr)
                    self.assertNotIn('latest_context_source_timestamp_seconds{', expr)
        ledger = next(panel for panel in desktop_panels if "generation_observed_tokens_total" in panel["targets"][0]["expr"])
        self.assertNotRegex(ledger["targets"][0]["expr"], r"\b(sum|avg|max|rate)\s*\(")
        self.assertIn("子集", ledger["description"])
        for panel in desktop_panels:
            expression = panel["targets"][0]["expr"]
            if "generation_observed_tokens_total" in expression or "generation_records_total" in expression:
                self.assertIn("antigravity_desktop_read_success{", expression)
                self.assertIn('component="tokens"} == 1', expression)


if __name__ == "__main__":
    unittest.main()
