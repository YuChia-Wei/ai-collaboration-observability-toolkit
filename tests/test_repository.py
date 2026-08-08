from __future__ import annotations

import importlib.util
import json
import os
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

    def test_phoenix_selection_and_exporter_are_explicit(self) -> None:
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
        pipeline = config["service"]["pipelines"]["traces/phoenix"]
        self.assertEqual(pipeline["exporters"], ["otlphttp/phoenix"])
        self.assertLess(
            pipeline["processors"].index("transform/privacy"),
            pipeline["processors"].index("filter/phoenix-selected"),
        )
        exporter = config["exporters"]["otlphttp/phoenix"]
        self.assertEqual(exporter["endpoint"], "http://phoenix:6006")
        self.assertEqual(exporter["headers"]["x-project-name"], toolkit.PHOENIX_PROJECT)

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

    def test_dashboard_contracts_do_not_cross_query_boundaries(self) -> None:
        rules = {
            "codex-usage.json": ("codex_", {"ai_agent_", "ai_context_", "antigravity_"}),
            "ai-agent-usage.json": ("ai_agent_", {"codex_", "ai_context_", "antigravity_"}),
            "ai-context-effectiveness.json": (
                "ai_context_",
                {"codex_", "ai_agent_", "antigravity_"},
            ),
            "ai-workflow-efficiency.json": (
                "ai_context_",
                {"codex_", "ai_agent_", "antigravity_"},
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
        for filename in ("codex-usage.json", "ai-agent-usage.json"):
            text = (ROOT / "config/grafana/dashboards" / filename).read_text(
                encoding="utf-8"
            )
            self.assertIn("Cost is unavailable", text)
            self.assertNotIn("Estimated cost", text)

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
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "0.1.3")
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
