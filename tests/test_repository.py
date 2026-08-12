from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("toolkit", ROOT / "scripts/toolkit.py")
assert spec and spec.loader
toolkit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = toolkit
spec.loader.exec_module(toolkit)


class RepositoryTests(unittest.TestCase):
    maxDiff = None

    def test_mode_files_are_unambiguous(self) -> None:
        self.assertEqual([p.name for p in toolkit.compose_files("core")], ["compose.yaml"])
        self.assertEqual(
            [p.name for p in toolkit.compose_files("evaluation")],
            ["compose.yaml", "compose.evaluation.yaml"],
        )
        self.assertEqual(
            [p.name for p in toolkit.compose_files("corporate")],
            ["compose.yaml", "compose.corporate.yaml"],
        )

    def test_static_policy(self) -> None:
        self.assertEqual(toolkit.static_validate(), [])

    def test_exact_images_are_committed_with_reviewable_overrides(self) -> None:
        base = toolkit.yaml_load(ROOT / "compose.yaml")
        evaluation = toolkit.yaml_load(ROOT / "compose.evaluation.yaml")
        expressions = {
            **{name: value["image"] for name, value in base["services"].items() if "image" in value},
            **{
                name: value["image"]
                for name, value in evaluation["services"].items()
                if "image" in value
            },
        }
        defaults = {name: toolkit.image_default(value) for name, value in expressions.items()}
        self.assertEqual(defaults, toolkit.EXACT_IMAGES)
        env = toolkit.parse_env(ROOT / ".env.example")
        for service, expected in toolkit.EXACT_IMAGES.items():
            variable = toolkit.IMAGE_ENV_VARS[service]
            self.assertEqual(toolkit.image_variable(expressions[service]), variable)
            self.assertEqual(env[variable], expected)
            self.assertFalse(expected.endswith(":latest"))

    def test_host_ports_are_loopback_bound(self) -> None:
        for file in ("compose.yaml", "compose.evaluation.yaml"):
            data = toolkit.yaml_load(ROOT / file)
            for service in data.get("services", {}).values():
                for port in service.get("ports", []) or []:
                    self.assertIsInstance(port, str)
                    self.assertTrue(port.startswith("127.0.0.1:"), port)

    def test_postgres_18_uses_the_version_aware_volume_root(self) -> None:
        evaluation = toolkit.yaml_load(ROOT / "compose.evaluation.yaml")
        volumes = evaluation["services"]["postgres"]["volumes"]
        self.assertIn("phoenix-postgres-data:/var/lib/postgresql", volumes)
        self.assertNotIn("phoenix-postgres-data:/var/lib/postgresql/data", volumes)
        self.assertEqual(
            evaluation["services"]["otel-collector"]["depends_on"],
            {
                "loki": {"condition": "service_started"},
                "tempo": {"condition": "service_started"},
                "phoenix": {"condition": "service_started"},
            },
        )

    def test_prometheus_is_not_an_otlp_or_remote_write_receiver(self) -> None:
        text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertNotIn("--web.enable-remote-write-receiver", text)
        self.assertNotIn("--web.enable-otlp-receiver", text)

    def test_collector_pipelines_reference_declared_components(self) -> None:
        for path in sorted((ROOT / "config/otel-collector").glob("*.yaml")):
            data = toolkit.yaml_load(path)
            declared = {
                "receivers": set(data["receivers"]),
                "processors": set(data["processors"]),
                "exporters": set(data["exporters"]),
            }
            for pipeline_name, pipeline in data["service"]["pipelines"].items():
                for kind in declared:
                    self.assertFalse(
                        set(pipeline[kind]) - declared[kind],
                        (path.name, pipeline_name, kind, pipeline[kind]),
                    )
                self.assertEqual(pipeline["processors"][0], "memory_limiter")
                privacy = (
                    "transform/corporate_allowlist"
                    if path.name == "corporate.yaml"
                    else "transform/privacy"
                )
                self.assertIn("transform/privacy_initial", pipeline["processors"])
                self.assertIn("transform/ai_agent", pipeline["processors"])
                self.assertIn(privacy, pipeline["processors"])
                initial_index = pipeline["processors"].index("transform/privacy_initial")
                canonical_index = pipeline["processors"].index("transform/ai_agent")
                privacy_index = pipeline["processors"].index(privacy)
                self.assertLess(initial_index, canonical_index)
                self.assertLess(canonical_index, privacy_index)
                for index, processor in enumerate(pipeline["processors"]):
                    if processor.startswith("batch/"):
                        self.assertGreater(index, privacy_index)

    def test_privacy_profiles_clear_payload_and_non_attribute_free_text(self) -> None:
        for name in ("core.yaml", "evaluation.yaml"):
            text = (ROOT / "config/otel-collector" / name).read_text(encoding="utf-8")
            for statement in (
                'delete_key(attributes, "prompt")',
                'delete_key(attributes, "response")',
                'delete_key(attributes, "tool.result")',
                'set(body, "AI telemetry metadata event")',
                'set(status.message, "")',
                'set(trace_state, "")',
            ):
                self.assertIn(statement, text, (name, statement))
            config = toolkit.yaml_load(ROOT / "config/otel-collector" / name)
            self.assertEqual(
                config["processors"]["transform/privacy"]["error_mode"],
                "propagate",
            )
            statements = "\n".join(
                statement
                for group in config["processors"]["transform/privacy"]["trace_statements"]
                for statement in group["statements"]
            )
            self.assertTrue(any(x in statements for x in (r"tool(?:\.call)?", r"tool(?:\\.call)?")))
            self.assertTrue(any(x in statements for x in (r"gen_ai\.(?:prompt|completion", r"gen_ai\\.(?:prompt|completion")))

    def test_corporate_allowlist_preserves_only_bounded_ai_agent_metadata(self) -> None:
        text = (ROOT / "config/otel-collector/corporate.yaml").read_text(
            encoding="utf-8"
        )
        for attribute in (
            "ai_agent.provider",
            "ai_agent.product",
            "ai_agent.surface",
            "ai_agent.operation",
            "ai_agent.tool.category",
            "ai_agent.model.family",
            "ai_agent.evidence.class",
        ):
            self.assertIn(attribute, text)
        self.assertNotIn('"ai_agent.session.id"', text)
        self.assertNotIn('"ai_agent.user.id"', text)
        self.assertIn('"model_id"', text)

    def test_phoenix_hybrid_routing_and_exporter_are_explicit(self) -> None:
        for filename, expected, trace_id in (
            ("phoenix-selected-trace.json", True, toolkit.TRACE_SELECTED),
            ("phoenix-rejected-trace.json", False, toolkit.TRACE_REJECTED),
        ):
            payload = json.loads((ROOT / "examples/otlp" / filename).read_text())
            resource = payload["resourceSpans"][0]
            attrs = resource["resource"]["attributes"]
            selection = next(x["value"] for x in attrs if x["key"] == "ai_context.export.phoenix")
            project = next(x["value"] for x in attrs if x["key"] == "openinference.project.name")
            observed_trace = resource["scopeSpans"][0]["spans"][0]["traceId"]
            self.assertEqual(selection, {"boolValue": expected})
            self.assertEqual(project, {"stringValue": toolkit.PHOENIX_PROJECT})
            self.assertEqual(observed_trace, trace_id)

        config = toolkit.yaml_load(ROOT / "config/otel-collector/evaluation.yaml")
        protocols = config["receivers"]["otlp"]["protocols"]
        self.assertTrue(protocols["grpc"]["include_metadata"])
        self.assertTrue(protocols["http"]["include_metadata"])
        pipeline = config["service"]["pipelines"]["traces/phoenix"]
        self.assertEqual(pipeline["exporters"], ["otlphttp/phoenix"])
        self.assertLess(
            pipeline["processors"].index("transform/privacy"),
            pipeline["processors"].index("attributes/phoenix-routing"),
        )
        self.assertLess(
            pipeline["processors"].index("transform/privacy"),
            pipeline["processors"].index("filter/phoenix-openinference"),
        )
        self.assertLess(
            pipeline["processors"].index("filter/phoenix-openinference"),
            pipeline["processors"].index("attributes/phoenix-routing"),
        )
        self.assertLess(
            pipeline["processors"].index("filter/phoenix-routing"),
            pipeline["processors"].index("attributes/phoenix-routing-cleanup"),
        )
        compatibility = config["processors"]["filter/phoenix-openinference"]
        self.assertEqual(compatibility["error_mode"], "propagate")
        self.assertEqual(
            compatibility["traces"]["span"],
            ['attributes["openinference.span.kind"] == nil'],
        )
        route_action = config["processors"]["attributes/phoenix-routing"]["actions"][0]
        self.assertEqual(
            route_action["from_context"],
            f"metadata.{toolkit.PHOENIX_ROUTING_HEADER}",
        )
        self.assertEqual(route_action["default_value"], "true")
        cleanup_action = config["processors"][
            "attributes/phoenix-routing-cleanup"
        ]["actions"][0]
        self.assertEqual(cleanup_action["key"], toolkit.PHOENIX_ROUTING_ATTRIBUTE)
        self.assertEqual(cleanup_action["action"], "delete")

        for filename, trace_id in (
            ("phoenix-default-trace.json", toolkit.TRACE_PHOENIX_DEFAULT),
            ("phoenix-header-true-trace.json", toolkit.TRACE_PHOENIX_HEADER_TRUE),
            ("phoenix-header-false-trace.json", toolkit.TRACE_PHOENIX_HEADER_FALSE),
        ):
            payload = json.loads((ROOT / "examples/otlp" / filename).read_text())
            resource = payload["resourceSpans"][0]
            attrs = resource["resource"]["attributes"]
            self.assertFalse(
                any(x["key"] == "ai_context.export.phoenix" for x in attrs)
            )
            self.assertEqual(
                resource["scopeSpans"][0]["spans"][0]["traceId"], trace_id
            )
        exporter = config["exporters"]["otlphttp/phoenix"]
        self.assertEqual(exporter["endpoint"], "http://phoenix:6006")
        self.assertEqual(exporter["headers"]["x-project-name"], toolkit.PHOENIX_PROJECT)

        generic = json.loads(
            (ROOT / "examples/otlp/phoenix-generic-trace.json").read_text()
        )
        generic_span = generic["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        self.assertEqual(generic_span["traceId"], toolkit.TRACE_PHOENIX_GENERIC)
        self.assertFalse(
            any(
                attribute["key"] == "openinference.span.kind"
                for attribute in generic_span.get("attributes", [])
            )
        )

    def test_corporate_mode_is_allowlist_only_and_has_no_phoenix(self) -> None:
        compose = (ROOT / "compose.corporate.yaml").read_text(encoding="utf-8")
        self.assertNotIn("phoenix:", compose)
        self.assertNotIn("postgres:", compose)
        config = toolkit.yaml_load(ROOT / "config/otel-collector/corporate.yaml")
        self.assertIn("transform/corporate_allowlist", config["processors"])
        self.assertNotIn("transform/privacy", config["processors"])
        self.assertFalse(any("phoenix" in name for name in config["exporters"]))
        self.assertEqual(
            config["processors"]["transform/corporate_allowlist"]["error_mode"],
            "propagate",
        )
        text = (ROOT / "config/otel-collector/corporate.yaml").read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("context: scope"), 3)
        self.assertIn('set(name, "AI telemetry operation")', text)
        self.assertIn('set(name, "AI telemetry event")', text)
        self.assertIn('set(body, "AI telemetry metadata event")', text)
        self.assertIn('set(status.message, "")', text)
        self.assertIn('set(trace_state, "")', text)
        self.assertIn('set(description, "")', text)

    def test_metric_allowlists_exclude_high_cardinality_identifiers(self) -> None:
        forbidden = {
            "session.id",
            "conversation.id",
            "prompt.id",
            "ai_context.workflow.id",
            "ai_context.task.id",
            "ai_context.validation.fingerprint",
            "ai_context.user.pseudonym",
            "absolute_path",
        }
        for path in sorted((ROOT / "config/otel-collector").glob("*.yaml")):
            data = toolkit.yaml_load(path)
            transform = (
                "transform/corporate_allowlist"
                if path.name == "corporate.yaml"
                else "transform/privacy"
            )
            groups = data["processors"][transform]["metric_statements"]
            statements = "\n".join(statement for group in groups for statement in group["statements"])
            for field in forbidden:
                self.assertNotIn(f'"{field}"', statements, (path.name, field))

    def test_prometheus_exporter_uses_stable_names_without_exemplars(self) -> None:
        for path in sorted((ROOT / "config/otel-collector").glob("*.yaml")):
            data = toolkit.yaml_load(path)
            exporter = data["exporters"]["prometheus"]
            self.assertFalse(exporter["enable_open_metrics"])
            self.assertTrue(exporter["without_scope_info"])
            self.assertEqual(
                exporter["translation_strategy"],
                "UnderscoreEscapingWithoutSuffixes",
            )

    def test_agent_role_and_exact_model_are_mapped_before_raw_model_is_removed(self) -> None:
        expected = {
            "gpt-5.6-sol": "gpt-5.6-sol",
            "gpt-5.6-terra": "gpt-5.6-terra",
            "gpt-5.6-luna": "gpt-5.6-luna",
        }
        for path in sorted((ROOT / "config/otel-collector").glob("*.yaml")):
            text = path.read_text(encoding="utf-8")
            self.assertIn('set(attributes["model_id"], "unmapped")', text)
            self.assertIn('set(attributes["agent_role"], "unknown")', text)
            delete_index = text.index('delete_key(attributes, "model")')
            for source, model_id in expected.items():
                statement = f'set(attributes["model_id"], "{model_id}")'
                self.assertIn(statement, text, (path.name, source))
                self.assertLess(text.index(statement), delete_index, (path.name, source))
            reviewer = 'set(attributes["agent_role"], "approval_reviewer")'
            primary = 'set(attributes["agent_role"], "primary")'
            self.assertIn(reviewer, text, path.name)
            self.assertIn(primary, text, path.name)
            self.assertLess(text.index(reviewer), delete_index, path.name)
            self.assertLess(text.index(primary), delete_index, path.name)
            self.assertNotIn(
                'set(attributes["model_id"], "codex-auto-review")', text, path.name
            )
            self.assertNotIn(
                'set(attributes["model_family"], "codex-auto-review")', text, path.name
            )
            self.assertIn('"agent_role"', text, path.name)

    def test_prometheus_rate_card_is_versioned_and_exact_model_only(self) -> None:
        prometheus = toolkit.yaml_load(ROOT / "config/prometheus/prometheus.yml")
        self.assertEqual(prometheus["rule_files"], ["/etc/prometheus/rules/*.yml"])
        compose = toolkit.yaml_load(ROOT / "compose.yaml")
        self.assertIn(
            "./config/prometheus/rules:/etc/prometheus/rules:ro",
            compose["services"]["prometheus"]["volumes"],
        )

        config = toolkit.yaml_load(ROOT / "config/prometheus/rules/ai-agent-cost.yml")
        rules = config["groups"][0]["rules"]
        prices = [rule for rule in rules if rule["record"] == "ai_agent_token_price_usd_per_million"]
        self.assertEqual(len(prices), 12)
        expected = {
            ("gpt-5.6-sol", "input_uncached"): 5.0,
            ("gpt-5.6-sol", "input_cached"): 0.5,
            ("gpt-5.6-sol", "input_cache_write"): 6.25,
            ("gpt-5.6-sol", "output"): 30.0,
            ("gpt-5.6-terra", "input_uncached"): 2.0,
            ("gpt-5.6-terra", "input_cached"): 0.2,
            ("gpt-5.6-terra", "input_cache_write"): 2.5,
            ("gpt-5.6-terra", "output"): 12.0,
            ("gpt-5.6-luna", "input_uncached"): 0.2,
            ("gpt-5.6-luna", "input_cached"): 0.02,
            ("gpt-5.6-luna", "input_cache_write"): 0.25,
            ("gpt-5.6-luna", "output"): 1.2,
        }
        observed = {}
        for rule in prices:
            labels = rule["labels"]
            self.assertEqual(labels["ai_agent_provider"], "openai")
            self.assertEqual(labels["currency"], "USD")
            self.assertEqual(labels["rate_card_version"], "openai-api-2026-08-12")
            self.assertEqual(labels["rate_card_source"], "official_openai_model_pages")
            self.assertEqual(labels["pricing_scope"], "base_standard_context")
            value = float(rule["expr"].removeprefix("vector(").removesuffix(")"))
            observed[(labels["model_id"], labels["usage_class"])] = value
        self.assertEqual(observed, expected)
        self.assertFalse(any("codex-auto-review" in str(rule) for rule in prices))

        credit_rates = [
            rule for rule in rules if rule["record"] == "ai_agent_token_credit_per_million"
        ]
        expected_credits = {
            ("gpt-5.6-sol", "input_uncached"): 125.0,
            ("gpt-5.6-sol", "input_cached"): 12.5,
            ("gpt-5.6-sol", "output"): 750.0,
            ("gpt-5.6-terra", "input_uncached"): 50.0,
            ("gpt-5.6-terra", "input_cached"): 5.0,
            ("gpt-5.6-terra", "output"): 300.0,
            ("gpt-5.6-luna", "input_uncached"): 5.0,
            ("gpt-5.6-luna", "input_cached"): 0.5,
            ("gpt-5.6-luna", "output"): 30.0,
        }
        observed_credits = {}
        for rule in credit_rates:
            labels = rule["labels"]
            self.assertEqual(labels["credit_unit"], "credits")
            self.assertEqual(
                labels["rate_card_version"], "openai-codex-credits-2026-08-12"
            )
            self.assertEqual(labels["rate_card_source"], "official_codex_pricing")
            self.assertEqual(labels["pricing_scope"], "published_token_classes")
            value = float(rule["expr"].removeprefix("vector(").removesuffix(")"))
            observed_credits[(labels["model_id"], labels["usage_class"])] = value
        self.assertEqual(observed_credits, expected_credits)
        self.assertFalse(
            any(rule["labels"]["usage_class"] == "input_cache_write" for rule in credit_rates)
        )

        accounting = [rule for rule in rules if rule["record"] == "ai_agent_token_usage_total"]
        self.assertEqual(
            {rule["labels"]["usage_class"] for rule in accounting},
            {"input_uncached", "input_cached", "input_cache_write", "output"},
        )
        for rule in accounting:
            self.assertIn('model_id!=""', rule["expr"])
            self.assertIn('agent_role!=""', rule["expr"])
            self.assertIn("agent_role", rule["expr"])
            self.assertIn("service_namespace", rule["expr"])
            self.assertEqual(rule["labels"]["accounting_schema"], "v2")
        cost = next(rule for rule in rules if rule["record"] == "ai_agent_estimated_cost_usd_total")
        self.assertIn("group_left", cost["expr"])
        self.assertIn("rate_card_version", cost["expr"])
        self.assertIn('model_id!=""', cost["expr"])
        self.assertIn('agent_role!=""', cost["expr"])
        self.assertIn('accounting_schema="v2"', cost["expr"])
        credits = next(
            rule for rule in rules if rule["record"] == "ai_agent_estimated_credit_usage_total"
        )
        self.assertIn('ai_agent_product="codex"', credits["expr"])
        self.assertIn("ai_agent_token_credit_per_million", credits["expr"])
        self.assertIn('accounting_schema="v2"', credits["expr"])
        unpriced = {
            rule["record"]
            for rule in rules
            if rule["record"].startswith("ai_agent_unpriced_")
        }
        self.assertEqual(
            unpriced,
            {
                "ai_agent_unpriced_api_token_usage_total",
                "ai_agent_unpriced_credit_token_usage_total",
            },
        )

        fixture = json.loads(
            toolkit.render_fixture(
                ROOT / "examples/otlp/codex-cost-accounting-metrics.json"
            ).decode("utf-8")
        )
        points = fixture["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0][
            "histogram"
        ]["dataPoints"]
        token_values = {
            next(
                attribute["value"]["stringValue"]
                for attribute in point["attributes"]
                if attribute["key"] == "token_type"
            ): point["sum"]
            for point in points
        }
        accounting_values = {
            "input_uncached": token_values["input"]
            - token_values["cached_input"]
            - token_values["cache_write_input"],
            "input_cached": token_values["cached_input"],
            "input_cache_write": token_values["cache_write_input"],
            "output": token_values["output"],
        }
        self.assertEqual(
            accounting_values,
            {
                "input_uncached": 3000,
                "input_cached": 6000,
                "input_cache_write": 1000,
                "output": 2000,
            },
        )
        estimated = sum(
            value * expected[("gpt-5.6-sol", usage_class)] / 1_000_000
            for usage_class, value in accounting_values.items()
        )
        self.assertAlmostEqual(estimated, 0.08425)
        estimated_credits = sum(
            value * expected_credits[("gpt-5.6-sol", usage_class)] / 1_000_000
            for usage_class, value in accounting_values.items()
            if ("gpt-5.6-sol", usage_class) in expected_credits
        )
        self.assertAlmostEqual(estimated_credits, 1.95)

        role_points = fixture["resourceMetrics"][1]["scopeMetrics"][0]["metrics"][0][
            "histogram"
        ]["dataPoints"]
        auto_review_points = [
            point
            for point in role_points
            if any(
                attribute["key"] == "model"
                and attribute["value"]["stringValue"] == "codex-auto-review"
                for attribute in point["attributes"]
            )
        ]
        self.assertEqual(len(auto_review_points), 4)
        subagent_points = [
            point
            for point in role_points
            if any(
                attribute["key"] == "agent_role"
                and attribute["value"]["stringValue"] == "subagent"
                for attribute in point["attributes"]
            )
        ]
        self.assertEqual(len(subagent_points), 4)

    def test_loki_only_indexes_approved_low_cardinality_attributes(self) -> None:
        loki = toolkit.yaml_load(ROOT / "config/loki/loki.yml")
        items = loki["limits_config"]["otlp_config"]["resource_attributes"]["attributes_config"]
        labels = next(item["attributes"] for item in items if item["action"] == "index_label")
        self.assertEqual(
            set(labels),
            {
                "service.name",
                "service.namespace",
                "deployment.environment.name",
                "ai_context.environment.profile",
            },
        )
        self.assertEqual(loki["limits_config"]["retention_period"], "336h")
        self.assertEqual(
            loki["limits_config"]["reject_old_samples_max_age"], "336h"
        )

    def test_tempo_three_configuration_uses_override_retention(self) -> None:
        tempo = toolkit.yaml_load(ROOT / "config/tempo/tempo.yml")
        self.assertNotIn("compactor", tempo)
        self.assertEqual(tempo["overrides"]["defaults"]["compaction"]["block_retention"], "336h")

    def test_fixtures_render_to_json(self) -> None:
        for path in sorted((ROOT / "examples/otlp").glob("*.json")):
            rendered = toolkit.render_fixture(path)
            json.loads(rendered)
            self.assertNotIn(b"{{", rendered)

    def test_dashboards_and_provisioning_are_parseable(self) -> None:
        uids: set[str] = set()
        for path in sorted((ROOT / "config/grafana/dashboards").glob("*.json")):
            dashboard = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(dashboard["title"])
            self.assertTrue(dashboard["panels"])
            self.assertNotIn(dashboard["uid"], uids)
            uids.add(dashboard["uid"])
            for panel in dashboard["panels"]:
                self.assertTrue(panel.get("description"), (path.name, panel["id"]))
        datasources = toolkit.yaml_load(
            ROOT / "config/grafana/provisioning/datasources/datasources.yml"
        )
        self.assertEqual(
            {item["uid"] for item in datasources["datasources"]},
            {"prometheus", "loki", "tempo"},
        )
        by_uid = {item["uid"]: item for item in datasources["datasources"]}
        self.assertNotIn(
            "exemplarTraceIdDestinations",
            by_uid["prometheus"].get("jsonData", {}),
        )
        self.assertNotIn("serviceMap", by_uid["tempo"].get("jsonData", {}))

    def test_dashboards_are_zh_tw_first_and_keep_stable_uids(self) -> None:
        expected = {
            "ai-agent-activity.json": "ai-agent-activity",
            "ai-agent-usage.json": "ai-agent-usage",
            "antigravity-usage.json": "ai-antigravity-usage",
            "codex-auto-review.json": "ai-codex-auto-review",
            "codex-usage.json": "ai-codex-usage",
            "collector-health.json": "ai-collector-health",
        }
        dashboard_dir = ROOT / "config/grafana/dashboards"
        self.assertEqual({path.name for path in dashboard_dir.glob("*.json")}, set(expected))
        for filename, uid in expected.items():
            dashboard = json.loads((dashboard_dir / filename).read_text(encoding="utf-8"))
            self.assertEqual(dashboard["uid"], uid)
            self.assertRegex(dashboard["title"], r"[\u4e00-\u9fff]")
            self.assertRegex(dashboard["description"], r"[\u4e00-\u9fff]")
            for panel in dashboard["panels"]:
                self.assertRegex(panel["title"], r"[\u4e00-\u9fff]", (filename, panel["id"]))
                self.assertRegex(
                    panel["description"], r"[\u4e00-\u9fff]", (filename, panel["id"])
                )

    def test_phoenix_zh_tw_annotation_rubric_is_complete(self) -> None:
        configs = toolkit.load_phoenix_annotation_configs()
        self.assertEqual(
            {config["name"] for config in configs},
            {"執行結果", "問題類型", "是否值得保留為案例", "人工判斷原因", "後續處置"},
        )
        self.assertEqual(
            {config["type"] for config in configs}, {"CATEGORICAL", "FREEFORM"}
        )

    def test_dashboard_contracts_do_not_cross_query_boundaries(self) -> None:
        rules = {
            "ai-agent-usage.json": ("ai_agent_", {"codex_", "ai_context_", "antigravity_"}),
            "ai-agent-activity.json": ("event_name", {"ai_context_", "antigravity_"}),
            "codex-auto-review.json": (
                "approval_reviewer",
                {"codex_", "ai_context_", "antigravity_"},
            ),
            "antigravity-usage.json": (
                "antigravity_",
                {"codex_", "ai_agent_", "ai_context_"},
            ),
        }
        for filename, (required, forbidden) in rules.items():
            dashboard = json.loads(
                (ROOT / "config/grafana/dashboards" / filename).read_text(
                    encoding="utf-8"
                )
            )
            expressions = "\n".join(
                target.get("expr", "")
                for panel in dashboard["panels"]
                for target in panel.get("targets", [])
            )
            self.assertIn(required, expressions, filename)
            for prefix in forbidden:
                self.assertNotIn(prefix, expressions, (filename, prefix))

        activity = json.loads(
            (ROOT / "config/grafana/dashboards/ai-agent-activity.json").read_text(
                encoding="utf-8"
            )
        )
        activity_expressions = "\n".join(
            target.get("expr", "")
            for panel in activity["panels"]
            for target in panel.get("targets", [])
        )
        self.assertIn("codex.user_prompt", activity_expressions)
        self.assertIn("trace_id", activity_expressions)
        self.assertNotIn("prompt.content", activity_expressions)
        self.assertNotIn("tool.result", activity_expressions)

        codex = json.loads(
            (ROOT / "config/grafana/dashboards/codex-usage.json").read_text(
                encoding="utf-8"
            )
        )
        codex_expressions = "\n".join(
            target.get("expr", "")
            for panel in codex["panels"]
            for target in panel.get("targets", [])
        )
        self.assertIn("codex_", codex_expressions)
        self.assertNotIn("ai_context_", codex_expressions)
        self.assertNotIn("antigravity_", codex_expressions)
        allowed_canonical = {
            "ai_agent_token_usage_total",
            "ai_agent_estimated_cost_usd_total",
            "ai_agent_token_price_usd_per_million",
            "ai_agent_provider",
            "ai_agent_product",
        }
        self.assertEqual(
            set(re.findall(r"\bai_agent_[a-z0-9_]+", codex_expressions)),
            allowed_canonical,
        )
        fixture_exclusion = (
            'service_namespace!~"^ai-collaboration(-cost|-role)?-fixture$"'
        )
        self.assertIn('accounting_schema="v2"', codex_expressions)
        self.assertIn(fixture_exclusion, codex_expressions)

        provider_neutral = json.loads(
            (ROOT / "config/grafana/dashboards/ai-agent-usage.json").read_text(
                encoding="utf-8"
            )
        )
        provider_neutral_expressions = "\n".join(
            target.get("expr", "")
            for panel in provider_neutral["panels"]
            for target in panel.get("targets", [])
        )
        self.assertIn('accounting_schema="v2"', provider_neutral_expressions)
        self.assertIn('agent_role=~"$agent_role"', provider_neutral_expressions)
        self.assertIn("ai_agent_estimated_credit_usage_total", provider_neutral_expressions)
        self.assertIn("ai_agent_unpriced_credit_token_usage_total", provider_neutral_expressions)
        self.assertIn(fixture_exclusion, provider_neutral_expressions)

        for filename, dashboard in (
            ("codex-usage.json", codex),
            ("ai-agent-usage.json", provider_neutral),
        ):
            cost_stat = next(
                panel
                for panel in dashboard["panels"]
                if panel["type"] == "stat"
                and any(
                    "ai_agent_estimated_cost_usd_total" in target.get("expr", "")
                    for target in panel.get("targets", [])
                )
            )
            self.assertIn("所選範圍", cost_stat["title"], filename)
            self.assertNotIn("最後觀測", cost_stat["title"], filename)
            self.assertIn("公開 API", cost_stat["description"], filename)
            self.assertIn("不是", cost_stat["description"], filename)
            self.assertIn("未估價", cost_stat["description"], filename)
            cost_target = cost_stat["targets"][0]
            self.assertTrue(cost_target.get("instant"), filename)
            self.assertIn(
                "sum(increase(ai_agent_estimated_cost_usd_total",
                cost_target["expr"],
                filename,
            )
            self.assertIn("[$__range]))", cost_target["expr"], filename)
            self.assertNotRegex(
                cost_target["expr"],
                r"sum\(ai_agent_estimated_cost_usd_total",
                filename,
            )

        antigravity = json.loads(
            (ROOT / "config/grafana/dashboards/antigravity-usage.json").read_text(
                encoding="utf-8"
            )
        )
        antigravity_expressions = "\n".join(
            target.get("expr", "")
            for panel in antigravity["panels"]
            for target in panel.get("targets", [])
        )
        self.assertIn(fixture_exclusion, antigravity_expressions)
        for filename, variable_name in (
            ("codex-usage.json", "model"),
            ("ai-agent-usage.json", "model_id"),
        ):
            dashboard = json.loads(
                (ROOT / "config/grafana/dashboards" / filename).read_text(
                    encoding="utf-8"
                )
            )
            variable = next(
                item
                for item in dashboard["templating"]["list"]
                if item["name"] == variable_name
            )
            self.assertEqual(variable["allValue"], ".+", filename)
            self.assertIn(fixture_exclusion, variable["definition"], filename)
            if filename == "ai-agent-usage.json":
                self.assertIn('accounting_schema="v2"', variable["definition"])

        role_variable = next(
            item
            for item in provider_neutral["templating"]["list"]
            if item["name"] == "agent_role"
        )
        self.assertEqual(role_variable["allValue"], ".+")
        self.assertIn('accounting_schema="v2"', role_variable["definition"])
        self.assertIn(fixture_exclusion, role_variable["definition"])

        credit_stat = next(
            panel
            for panel in provider_neutral["panels"]
            if panel["type"] == "stat"
            and any(
                "ai_agent_estimated_credit_usage_total" in target.get("expr", "")
                for target in panel.get("targets", [])
            )
        )
        self.assertIn("所選範圍", credit_stat["title"])
        self.assertIn("不是", credit_stat["description"])
        self.assertIn("未估價", credit_stat["description"])
        self.assertTrue(credit_stat["targets"][0].get("instant"))
        self.assertIn(
            "sum(increase(ai_agent_estimated_credit_usage_total",
            credit_stat["targets"][0]["expr"],
        )

        reviewer = json.loads(
            (ROOT / "config/grafana/dashboards/codex-auto-review.json").read_text(
                encoding="utf-8"
            )
        )
        reviewer_expressions = "\n".join(
            target.get("expr", "")
            for panel in reviewer["panels"]
            for target in panel.get("targets", [])
        )
        self.assertIn('agent_role="approval_reviewer"', reviewer_expressions)
        self.assertIn('accounting_schema="v2"', reviewer_expressions)
        self.assertIn("ai_agent_unpriced_api_token_usage_total", reviewer_expressions)
        self.assertIn("ai_agent_unpriced_credit_token_usage_total", reviewer_expressions)
        self.assertIn(fixture_exclusion, reviewer_expressions)
        reviewer_text = (ROOT / "config/grafana/dashboards/codex-auto-review.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("不是免費", reviewer_text)
        self.assertIn("unmapped", reviewer_text)

        for filename in (
            "codex-usage.json",
            "ai-agent-usage.json",
            "codex-auto-review.json",
        ):
            text = (ROOT / "config/grafana/dashboards" / filename).read_text(encoding="utf-8")
            self.assertTrue("Estimated cost" in text or "API 預估費用" in text)
            self.assertIn("公開 API", text)
            self.assertIn("不是", text)
        antigravity_text = (
            ROOT / "config/grafana/dashboards/antigravity-usage.json"
        ).read_text(encoding="utf-8")
        self.assertIn("目前不猜價", antigravity_text)
        self.assertNotIn("ai_agent_estimated_cost_usd_total", antigravity_text)

    def test_codex_fixture_preserves_metric_semantics_and_contains_privacy_inputs(self) -> None:
        root = ROOT / "fixtures/codex/0.146.1"
        metrics = json.loads(
            toolkit.render_fixture(root / "metrics.sanitized.json").decode("utf-8")
        )
        instruments = {
            metric["name"]: metric
            for resource in metrics["resourceMetrics"]
            for scope in resource["scopeMetrics"]
            for metric in scope["metrics"]
        }
        token = instruments["codex.turn.token_usage"]["histogram"]
        self.assertEqual(token["aggregationTemporality"], 1)
        self.assertIn("bucketCounts", token["dataPoints"][0])
        tool = instruments["codex.tool.call"]["sum"]
        self.assertEqual(tool["aggregationTemporality"], 1)
        self.assertTrue(tool["isMonotonic"])
        for filename in (
            "metrics.sanitized.json",
            "logs.sanitized.json",
            "traces.sanitized.json",
        ):
            self.assertIn(
                toolkit.CODEX_FIXTURE_SENTINEL,
                (root / filename).read_text(encoding="utf-8"),
            )

    def test_codex_examples_export_all_signals_without_prompt_content(self) -> None:
        for name in ("config.toml.example", "config.corporate.toml.example"):
            config = tomllib.loads((ROOT / "examples/codex" / name).read_text(encoding="utf-8"))
            otel = config["otel"]
            self.assertFalse(otel["log_user_prompt"])
            self.assertIn("otlp-http", otel["exporter"])
            self.assertIn("otlp-http", otel["trace_exporter"])
            self.assertIn("otlp-http", otel["metrics_exporter"])

    def test_feedback_bundle_example_matches_schema(self) -> None:
        schema = json.loads((ROOT / "schemas/feedback-bundle.schema.json").read_text())
        instance = json.loads((ROOT / "examples/feedback-bundle.json").read_text())
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(instance)), [])

    def test_ai_context_event_example_matches_schema(self) -> None:
        schema = json.loads((ROOT / "schemas/ai-context-telemetry.schema.json").read_text())
        instance = json.loads((ROOT / "examples/ai-context-event.json").read_text())
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(instance)), [])

    def test_version_and_requirement_metadata(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "0.1.5")
        self.assertEqual((ROOT / "requirements-dev.txt").read_text(), "-r requirements.txt\n")

    def test_cli_exposes_explicit_report_snapshot_and_persistence_options(self) -> None:
        smoke = subprocess.run(
            [sys.executable, "scripts/toolkit.py", "smoke", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("--persistence-check", smoke)
        self.assertIn("--report", smoke)
        snapshot = subprocess.run(
            [sys.executable, "scripts/toolkit.py", "snapshot", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("--output", snapshot)

    def test_reset_refuses_without_exact_confirmation(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "destructive reset refused"):
            toolkit.reset("core", None)
        with self.assertRaisesRegex(RuntimeError, "destructive reset refused"):
            toolkit.reset("core", "wrong-project")

    def test_local_env_file_is_allowed_when_untracked(self) -> None:
        env_path = ROOT / ".env"
        previous = env_path.read_bytes() if env_path.exists() else None
        try:
            env_path.write_text("COMPOSE_PROJECT_NAME=test-only\n", encoding="utf-8")
            errors = toolkit.static_validate()
            self.assertFalse(any(".env" in error and "tracked" in error for error in errors), errors)
        finally:
            if previous is None:
                env_path.unlink(missing_ok=True)
            else:
                env_path.write_bytes(previous)

    def test_duplicate_yaml_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.yaml"
            path.write_text("a: 1\na: 2\n", encoding="utf-8")
            with self.assertRaises(Exception):
                toolkit.yaml_load(path)

    def test_wrappers_are_executable_on_posix(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX executable bits are not applicable on Windows")
        for path in (ROOT / "scripts").glob("*.sh"):
            self.assertTrue(os.access(path, os.X_OK), path)


if __name__ == "__main__":
    unittest.main()
