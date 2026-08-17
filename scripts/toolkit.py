#!/usr/bin/env python3
"""Operate and validate the AI Collaboration Observability Toolkit.

The script intentionally uses the Python standard library plus PyYAML. It does
not inspect source code, prompts, tool output, or host files outside this repo.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "AI_OBSERVABILITY_SECRET_SENTINEL_7F3B9D"
ANTIGRAVITY_SENTINEL = "ANTIGRAVITY_PRIVATE_SENTINEL_93F2"
CODEX_FIXTURE_SENTINEL = "codex_fixture_private_sentinel"
MODES = {"core", "evaluation", "corporate"}
PHOENIX_PROJECT = "ai-collaboration-observability-fixture"
TRACE_CORE = "11111111111111111111111111111111"
TRACE_SELECTED = "22222222222222222222222222222222"
TRACE_REJECTED = "33333333333333333333333333333333"
TRACE_CODEX = "44444444444444444444444444444444"
TRACE_PHOENIX_DEFAULT = "55555555555555555555555555555555"
TRACE_PHOENIX_HEADER_TRUE = "66666666666666666666666666666666"
TRACE_PHOENIX_HEADER_FALSE = "88888888888888888888888888888888"
TRACE_PHOENIX_GENERIC = "99999999999999999999999999999999"
PHOENIX_ROUTING_HEADER = "x-ai-observability-phoenix"
PHOENIX_ROUTING_ATTRIBUTE = "ai_observability.routing.phoenix"
PHOENIX_ANNOTATION_CONFIGS = ROOT / "config/phoenix/annotation-configs.zh-TW.json"
EXACT_IMAGES = {
    "otel-collector": "otel/opentelemetry-collector-contrib:0.158.0",
    "prometheus": "prom/prometheus:v3.13.2",
    "loki": "grafana/loki:3.7.6",
    "tempo": "grafana/tempo:3.0.2",
    "grafana": "grafana/grafana:13.1.3",
    "postgres": "postgres:18.4-alpine3.24",
    "phoenix": "arizephoenix/phoenix:version-20.0.0-nonroot",
}
IMAGE_ENV_VARS = {
    "otel-collector": "OTEL_COLLECTOR_IMAGE",
    "prometheus": "PROMETHEUS_IMAGE",
    "loki": "LOKI_IMAGE",
    "tempo": "TEMPO_IMAGE",
    "grafana": "GRAFANA_IMAGE",
    "postgres": "POSTGRES_IMAGE",
    "phoenix": "PHOENIX_IMAGE",
}
IMAGE_TEMPLATE = re.compile(
    r"^\$\{(?P<variable>[A-Z][A-Z0-9_]*):-(?P<default>[^}]+)\}$"
)


def image_default(value: str) -> str | None:
    """Return the exact committed default from a Compose image expression."""
    match = IMAGE_TEMPLATE.fullmatch(value)
    if match:
        return match.group("default")
    return None if "${" in value else value


def image_variable(value: str) -> str | None:
    match = IMAGE_TEMPLATE.fullmatch(value)
    return match.group("variable") if match else None


REQUIRED_DOCS = {
    "README.md",
    "README.en.md",
    "AGENTS.md",
    "GEMINI.md",
    "CLAUDE.md",
    "SECURITY.md",
    "docs/ARCHITECTURE.md",
    "docs/DATA-CONTRACT.md",
    "docs/PRIVACY.md",
    "docs/OPERATIONS.md",
    "docs/TROUBLESHOOTING.md",
    "docs/CODEX-INTEGRATION.md",
    "docs/ANTIGRAVITY-INTEGRATION.md",
    "docs/PHOENIX-INTEGRATION.md",
    "docs/PHOENIX-READING-GUIDE.zh-TW.md",
    "docs/TELEMETRY-GLOSSARY.zh-TW.md",
    "docs/PROVIDER-SUPPORT.md",
    "docs/COST-ATTRIBUTION.md",
    "docs/DEPENDENCIES.md",
    "docs/RESOURCE-BASELINE.md",
    "docs/RELEASE-NOTES-v0.1.3.md",
    "docs/RELEASE-NOTES-v0.1.4.md",
    "docs/RELEASE-NOTES-v0.1.5.md",
    "docs/IMPLEMENTATION-REPORT.md",
    "docs/VALIDATION-REPORT.md",
    "requirements.txt",
    "requirements-dev.txt",
    "VERSION",
    "CHANGELOG.md",
}


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def yaml_load(path: Path) -> Any:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def timestamp_slug() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def compose_files(mode: str) -> list[Path]:
    if mode not in MODES:
        raise ValueError(f"unsupported mode: {mode}")
    files = [ROOT / "compose.yaml"]
    if mode == "evaluation":
        files.append(ROOT / "compose.evaluation.yaml")
    elif mode == "corporate":
        files.append(ROOT / "compose.corporate.yaml")
    return files


def compose_args(mode: str) -> list[str]:
    args: list[str] = []
    for file in compose_files(mode):
        args.extend(["-f", str(file)])
    return args


def find_compose() -> list[str] | None:
    """Return Docker Compose v2/5 command; legacy docker-compose v1 is rejected."""
    explicit = os.environ.get("DOCKER_COMPOSE_BIN")
    if explicit:
        return [explicit]
    docker = shutil.which("docker")
    if not docker:
        return None
    probe = subprocess.run([docker, "compose", "version"], capture_output=True, text=True)
    return [docker, "compose"] if probe.returncode == 0 else None


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture)
    if check and result.returncode != 0:
        if capture:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
        raise RuntimeError(
            f"command failed with exit code {result.returncode}: {' '.join(cmd)}"
        )
    return result


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_env_file() -> None:
    for key, value in parse_env(ROOT / ".env").items():
        os.environ.setdefault(key, value)


def require_env_file() -> None:
    if not (ROOT / ".env").exists():
        raise RuntimeError(
            ".env is missing. Copy .env.example to .env, review the local-only "
            "passwords, then retry."
        )


def project_name() -> str:
    load_env_file()
    return os.getenv("COMPOSE_PROJECT_NAME", "ai-collaboration-observability")


def require_compose(*, require_daemon: bool = True) -> list[str]:
    compose = find_compose()
    if not compose:
        raise RuntimeError(
            "Docker Compose v2 or newer is required; legacy docker-compose v1 is unsupported"
        )
    if require_daemon:
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("Docker CLI is not available")
        probe = subprocess.run([docker, "info"], capture_output=True, text=True)
        if probe.returncode != 0:
            detail = probe.stderr.strip() or probe.stdout.strip()
            raise RuntimeError(f"Docker daemon is unavailable: {detail}")
    return compose


def compose_command(
    mode: str, tail: list[str], *, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    compose = require_compose()
    load_env_file()
    return run(compose + compose_args(mode) + tail, capture=capture)


def _tracked_env_error() -> str | None:
    if ".env" not in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines():
        return "Repository policy: .gitignore must ignore .env"
    if not (ROOT / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return "Repository policy: .env is tracked by Git" if result.returncode == 0 else None


def _iter_source_files() -> Iterable[Path]:
    excluded_parts = {".git", "__pycache__", ".pytest_cache", "artifacts"}
    binary_suffixes = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".zip",
        ".bundle",
        ".pyc",
    }
    for path in ROOT.rglob("*"):
        if not path.is_file() or excluded_parts.intersection(path.parts):
            continue
        if path.suffix.lower() in binary_suffixes:
            continue
        yield path



def _markdown_link_errors() -> list[str]:
    errors: list[str] = []
    pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    root_resolved = ROOT.resolve()
    for path in sorted(ROOT.rglob("*.md")):
        if {".git", "artifacts", "__pycache__"}.intersection(path.parts):
            continue
        for raw_target in pattern.findall(path.read_text(encoding="utf-8")):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#", "plugin://", "sandbox:")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            candidate = (path.parent / urllib.parse.unquote(target)).resolve()
            try:
                candidate.relative_to(root_resolved)
            except ValueError:
                errors.append(
                    f"Markdown link escapes repository: {path.relative_to(ROOT)} -> {raw_target}"
                )
                continue
            if not candidate.exists():
                errors.append(
                    f"Broken Markdown link: {path.relative_to(ROOT)} -> {raw_target}"
                )
    return errors

def static_validate() -> list[str]:
    errors: list[str] = []

    for required in sorted(REQUIRED_DOCS):
        if not (ROOT / required).is_file():
            errors.append(f"Required file missing: {required}")

    errors.extend(_markdown_link_errors())

    for path in _iter_source_files():
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            errors.append(f"UTF-8 BOM is forbidden: {path.relative_to(ROOT)}")

    yaml_files = sorted([*ROOT.rglob("*.yml"), *ROOT.rglob("*.yaml")])
    json_files = sorted(ROOT.rglob("*.json"))
    toml_files = sorted(ROOT.rglob("*.toml"))
    for path in yaml_files:
        if ".git" in path.parts or "artifacts" in path.parts:
            continue
        try:
            yaml_load(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"YAML {path.relative_to(ROOT)}: {exc}")
    for path in json_files:
        if ".git" in path.parts or "artifacts" in path.parts:
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"JSON {path.relative_to(ROOT)}: {exc}")
    for path in toml_files:
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"TOML {path.relative_to(ROOT)}: {exc}")

    try:
        load_phoenix_annotation_configs()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Phoenix annotation configs: {exc}")

    markdown_link = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts or "artifacts" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in markdown_link.finditer(text):
            raw_target = match.group(1).strip()
            target = raw_target.split()[0].strip("<>") if raw_target else ""
            if not target or target.startswith(
                ("#", "http://", "https://", "mailto:", "plugin://", "sandbox:")
            ):
                continue
            target = urllib.parse.unquote(target.split("#", 1)[0])
            if target and not (path.parent / target).resolve().exists():
                errors.append(
                    f"Markdown link {path.relative_to(ROOT)}: missing local target {target}"
                )

    compose_paths = [
        ROOT / "compose.yaml",
        ROOT / "compose.evaluation.yaml",
        ROOT / "compose.corporate.yaml",
    ]
    compose_text = "\n".join(
        path.read_text(encoding="utf-8") for path in compose_paths
    )
    if "container_name:" in compose_text:
        errors.append("Compose policy: container_name is forbidden")
    if re.search(
        r"image:\s*[^\n]+:(?:latest|edge|nightly)(?:\s|$)", compose_text
    ):
        errors.append("Compose policy: floating image tag is forbidden")
    for path in compose_paths:
        document = yaml_load(path) or {}
        for service_name, service in (document.get("services") or {}).items():
            image = service.get("image")
            if image:
                committed_default = image_default(image)
                if committed_default is None:
                    errors.append(
                        f"Compose policy: {service_name} image override lacks an exact default: {image}"
                    )
                elif (
                    ":" not in committed_default.rsplit("/", 1)[-1]
                    or committed_default.endswith(":latest")
                    or ":edge" in committed_default
                    or ":nightly" in committed_default
                ):
                    errors.append(
                        f"Compose policy: {service_name} image is not exactly pinned: {image}"
                    )
            for port in service.get("ports") or []:
                published = (
                    port
                    if isinstance(port, str)
                    else str(port.get("host_ip", ""))
                )
                if not published.startswith("127.0.0.1:"):
                    errors.append(
                        f"Compose policy: {path.name}/{service_name} published port "
                        f"is not loopback-only: {port}"
                    )

    base_compose = yaml_load(ROOT / "compose.yaml") or {}
    evaluation_compose = yaml_load(ROOT / "compose.evaluation.yaml") or {}
    image_expressions = {
        **{
            name: service.get("image")
            for name, service in (base_compose.get("services") or {}).items()
            if service.get("image")
        },
        **{
            name: service.get("image")
            for name, service in (evaluation_compose.get("services") or {}).items()
            if service.get("image")
        },
    }
    env_defaults = parse_env(ROOT / ".env.example")
    for service_name, expected_image in EXACT_IMAGES.items():
        expression = image_expressions.get(service_name)
        if not isinstance(expression, str):
            errors.append(f"Compose policy: required image is missing for {service_name}")
            continue
        if image_default(expression) != expected_image:
            errors.append(
                f"Compose policy: {service_name} default must be {expected_image}, found {expression}"
            )
        expected_variable = IMAGE_ENV_VARS[service_name]
        if image_variable(expression) != expected_variable:
            errors.append(
                f"Compose policy: {service_name} must use {expected_variable}, found {expression}"
            )
        if env_defaults.get(expected_variable) != expected_image:
            errors.append(
                f".env.example: {expected_variable} must be {expected_image}, "
                f"found {env_defaults.get(expected_variable)}"
            )

    postgres_volumes = (evaluation_compose.get("services", {}).get("postgres", {}).get("volumes") or [])
    if "phoenix-postgres-data:/var/lib/postgresql" not in postgres_volumes:
        errors.append("PostgreSQL 18 policy: persist the volume at /var/lib/postgresql")
    if "phoenix-postgres-data:/var/lib/postgresql/data" in postgres_volumes:
        errors.append("PostgreSQL 18 policy: legacy /var/lib/postgresql/data mount is forbidden")
    phoenix_environment = (
        evaluation_compose.get("services", {}).get("phoenix", {}).get("environment")
        or {}
    )
    if phoenix_environment.get("PHOENIX_DISABLE_AGENT_ASSISTANT") != "true":
        errors.append(
            "Evaluation Compose policy: Phoenix Agent must stay disabled to preserve "
            "the content-minimization default"
        )
    evaluation_dependencies = (
        evaluation_compose.get("services", {})
        .get("otel-collector", {})
        .get("depends_on")
        or []
    )
    expected_evaluation_dependencies = {
        "loki": {"condition": "service_started"},
        "tempo": {"condition": "service_started"},
        "phoenix": {"condition": "service_started"},
    }
    if evaluation_dependencies != expected_evaluation_dependencies:
        errors.append(
            "Evaluation Compose policy: Collector dependencies must explicitly preserve "
            "loki and tempo and add phoenix with service_started conditions"
        )

    tracked_env = _tracked_env_error()
    if tracked_env:
        errors.append(tracked_env)

    collector_dir = ROOT / "config/otel-collector"
    core = yaml_load(collector_dir / "core.yaml")
    evaluation = yaml_load(collector_dir / "evaluation.yaml")
    corporate = yaml_load(collector_dir / "corporate.yaml")
    if "otlphttp/loki" not in core.get("exporters", {}):
        errors.append("Core Collector must use Loki native OTLP/HTTP exporter")
    if (
        core.get("exporters", {})
        .get("otlphttp/loki", {})
        .get("endpoint")
        != "http://loki:3100/otlp"
    ):
        errors.append("Core Collector Loki endpoint must be http://loki:3100/otlp")
    evaluation_processors = evaluation.get("processors", {})
    for processor_name in (
        "attributes/phoenix-routing",
        "filter/phoenix-routing",
        "attributes/phoenix-routing-cleanup",
    ):
        if processor_name not in evaluation_processors:
            errors.append(
                f"Evaluation Collector is missing the {processor_name} processor"
            )
    evaluation_protocols = (
        ((evaluation.get("receivers") or {}).get("otlp") or {}).get("protocols")
        or {}
    )
    for protocol in ("grpc", "http"):
        if (evaluation_protocols.get(protocol) or {}).get("include_metadata") is not True:
            errors.append(
                f"Evaluation Collector OTLP {protocol} must include request metadata"
            )
    phoenix_exporter = evaluation.get("exporters", {}).get("otlphttp/phoenix")
    if not isinstance(phoenix_exporter, dict):
        errors.append("Evaluation Collector is missing the OTLP/HTTP Phoenix exporter")
    else:
        if phoenix_exporter.get("endpoint") != "http://phoenix:6006":
            errors.append("Evaluation Collector Phoenix endpoint must be http://phoenix:6006")
        if (phoenix_exporter.get("headers") or {}).get("x-project-name") != PHOENIX_PROJECT:
            errors.append("Evaluation Collector Phoenix project header is missing or unstable")
    if any(
        "phoenix" in str(key).lower() for key in corporate.get("exporters", {})
    ):
        errors.append("Corporate Collector must not define a Phoenix exporter")
    if "transform/corporate_allowlist" not in corporate.get("processors", {}):
        errors.append("Corporate Collector must use transform/corporate_allowlist")
    corporate_text = (collector_dir / "corporate.yaml").read_text(encoding="utf-8")
    for required in [
        "keep_keys",
        'set(body, "AI telemetry metadata event")',
        'set(name, "AI telemetry operation")',
        'set(name, "AI telemetry event")',
    ]:
        if required not in corporate_text:
            errors.append(f"Corporate policy missing: {required}")
    corporate_allowlist = corporate_text[
        corporate_text.find("transform/corporate_allowlist") :
    ]
    for required in [
        "context: scope",
        'set(status.message, "")',
        'set(trace_state, "")',
        'set(description, "")',
    ]:
        if required not in corporate_allowlist:
            errors.append(f"Corporate fail-closed policy missing: {required}")
    for profile_name in ["core.yaml", "evaluation.yaml"]:
        profile_text = (collector_dir / profile_name).read_text(encoding="utf-8")
        for required in [
            'delete_key(attributes, "prompt")',
            'delete_key(attributes, "response")',
            'delete_key(attributes, "tool.result")',
            'set(body, "AI telemetry metadata event")',
            'set(status.message, "")',
            'set(trace_state, "")',
        ]:
            if required not in profile_text:
                errors.append(f"{profile_name} privacy policy missing: {required}")

    for profile_name, profile, transform_name in [
        ("core.yaml", core, "transform/privacy"),
        ("evaluation.yaml", evaluation, "transform/privacy"),
        ("corporate.yaml", corporate, "transform/corporate_allowlist"),
    ]:
        transform = profile.get("processors", {}).get(transform_name, {})
        if transform.get("error_mode") != "propagate":
            errors.append(
                f"{profile_name} privacy policy must fail closed with error_mode=propagate"
            )
        contexts = {
            group.get("context") for group in transform.get("metric_statements", [])
        }
        expected_contexts = {"resource", "scope", "metric", "datapoint", "exemplar"}
        if contexts != expected_contexts:
            errors.append(
                f"{profile_name} metric privacy contexts must be {sorted(expected_contexts)}, "
                f"found={sorted(contexts)}"
            )
        prometheus = profile.get("exporters", {}).get("prometheus", {})
        expected_prometheus = {
            "enable_open_metrics": False,
            "without_scope_info": True,
            "translation_strategy": "UnderscoreEscapingWithoutSuffixes",
        }
        for key, expected in expected_prometheus.items():
            if prometheus.get(key) != expected:
                errors.append(
                    f"{profile_name} Prometheus exporter {key} must be {expected!r}"
                )

        processors = profile.get("processors", {})
        if processors.get("transform/privacy_initial", {}).get("error_mode") != "propagate":
            errors.append(
                f"{profile_name} initial privacy policy must fail closed with error_mode=propagate"
            )
        if processors.get("transform/ai_agent", {}).get("error_mode") != "propagate":
            errors.append(
                f"{profile_name} canonical AI-agent transform must fail closed"
            )
        pipelines = (profile.get("service") or {}).get("pipelines") or {}
        for signal, batch_name in (
            ("logs", "batch/logs"),
            ("metrics", "batch/metrics"),
            ("traces", "batch/traces"),
        ):
            expected_order = [
                "memory_limiter",
                "resource/normalize",
                "transform/privacy_initial",
                "transform/ai_agent",
                transform_name,
                batch_name,
            ]
            if profile_name == "corporate.yaml" and signal == "metrics":
                filter_name = "filter/corporate_drop_opt_in_prompt_size"
                filter_config = processors.get(filter_name, {})
                if filter_config.get("error_mode") != "propagate":
                    errors.append(
                        "corporate.yaml opt-in prompt-size filter must fail closed"
                    )
                if filter_config.get("metric_conditions") != [
                    'metric.name == "ai_agent.observed.user_prompt.bytes"'
                ]:
                    errors.append(
                        "corporate.yaml opt-in prompt-size filter must drop only the documented metric"
                    )
                expected_order.insert(-1, filter_name)
            found = (pipelines.get(signal) or {}).get("processors") or []
            if found != expected_order:
                errors.append(
                    f"{profile_name} {signal} processor order must be {expected_order}; "
                    f"found={found}"
                )

        profile_text = (collector_dir / profile_name).read_text(encoding="utf-8")
        for raw_name, canonical_name in (
            ("codex.turn.token_usage", "ai_agent.turn.token_usage"),
            ("codex.turn.e2e_duration_ms", "ai_agent.turn.duration_ms"),
            ("codex.turn.ttft.duration_ms", "ai_agent.turn.ttft.duration_ms"),
            ("codex.tool.call", "ai_agent.tool.call"),
            ("codex.mcp.call", "ai_agent.mcp.call"),
            ("codex.task.compact", "ai_agent.compaction"),
            ("codex.skill.injected", "ai_agent.skill.injection"),
            ("codex.thread.started", "ai_agent.thread.started"),
            ("antigravity_session_tokens", "ai_agent.observed.session_tokens"),
        ):
            statement = (
                f'copy_metric(name="{canonical_name}") where name == "{raw_name}"'
            )
            if statement not in profile_text:
                errors.append(
                    f"{profile_name} canonical mapping missing: {raw_name} -> {canonical_name}"
                )

    if (
        evaluation.get("processors", {})
        .get("filter/phoenix-routing", {})
        .get("error_mode")
        != "propagate"
    ):
        errors.append(
            "Evaluation Collector Phoenix routing must fail closed with error_mode=propagate"
        )
    if (
        evaluation.get("processors", {})
        .get("filter/phoenix-openinference", {})
        .get("error_mode")
        != "propagate"
    ):
        errors.append(
            "Evaluation Collector Phoenix compatibility filter must fail closed with error_mode=propagate"
        )
    for forbidden in [
        "prompt.content",
        "tool.result",
        "authorization",
        "user.email",
        "organization.id",
        "absolute_path",
        "repository.name",
        "file.path",
    ]:
        if f'"{forbidden}"' in corporate_allowlist:
            errors.append(f"Corporate allowlist contains forbidden field: {forbidden}")

    loki = yaml_load(ROOT / "config/loki/loki.yml")
    label_rules = loki["limits_config"]["otlp_config"]["resource_attributes"][
        "attributes_config"
    ]
    labels = set(label_rules[0].get("attributes", []))
    expected_labels = {
        "service.name",
        "service.namespace",
        "deployment.environment.name",
        "ai_context.environment.profile",
    }
    if labels != expected_labels:
        errors.append(
            "Loki policy: index labels must exactly match the approved low-cardinality set; "
            f"found={sorted(labels)}"
        )
    if loki.get("limits_config", {}).get("reject_old_samples_max_age") != "336h":
        errors.append(
            "Loki policy: reject_old_samples_max_age must match the 336h retention window"
        )

    datasource_config = yaml_load(
        ROOT / "config/grafana/provisioning/datasources/datasources.yml"
    )
    for datasource in datasource_config.get("datasources", []):
        json_data = datasource.get("jsonData") or {}
        if (
            datasource.get("uid") == "prometheus"
            and "exemplarTraceIdDestinations" in json_data
        ):
            errors.append(
                "Grafana policy: Prometheus exemplar links are forbidden while OpenMetrics is disabled"
            )
        if datasource.get("uid") == "tempo" and "serviceMap" in json_data:
            errors.append(
                "Grafana policy: Tempo serviceMap is forbidden until a metrics-generator is configured"
            )

    tempo = yaml_load(ROOT / "config/tempo/tempo.yml") or {}
    retention = (
        ((tempo.get("overrides") or {}).get("defaults") or {})
        .get("compaction", {})
        .get("block_retention")
    )
    if retention != "336h":
        errors.append(
            f"Tempo policy: scoped block_retention must be 336h, found {retention!r}"
        )
    if "compactor" in tempo:
        errors.append(
            "Tempo policy: Tempo 3 monolithic local configuration must not use a legacy top-level compactor block"
        )

    phoenix_pipeline = (
        ((evaluation.get("service") or {}).get("pipelines") or {}).get("traces/phoenix")
        or {}
    )
    if phoenix_pipeline.get("exporters") != ["otlphttp/phoenix"]:
        errors.append(
            "Evaluation Collector: traces/phoenix must export only through otlphttp/phoenix"
        )
    phoenix_processors = phoenix_pipeline.get("processors") or []
    required_order = [
        "memory_limiter",
        "resource/normalize",
        "transform/privacy_initial",
        "transform/ai_agent",
        "transform/privacy",
        "filter/phoenix-openinference",
        "attributes/phoenix-routing",
        "filter/phoenix-routing",
        "attributes/phoenix-routing-cleanup",
        "batch/phoenix",
    ]
    if phoenix_processors != required_order:
        errors.append(
            "Evaluation Collector: traces/phoenix must redact, route, clean routing metadata, then batch; "
            f"found={phoenix_processors}"
        )

    routing_actions = (
        evaluation_processors.get("attributes/phoenix-routing", {}).get("actions")
        or []
    )
    if routing_actions != [
        {
            "key": PHOENIX_ROUTING_ATTRIBUTE,
            "from_context": f"metadata.{PHOENIX_ROUTING_HEADER}",
            "default_value": "true",
            "action": "upsert",
        }
    ]:
        errors.append(
            "Evaluation Collector Phoenix routing must default missing headers to true"
        )
    routing_conditions = (
        evaluation_processors.get("filter/phoenix-routing", {})
        .get("traces", {})
        .get("span", [])
    )
    expected_routing_conditions = [
        'resource.attributes["ai_context.export.phoenix"] == false',
        f'attributes["{PHOENIX_ROUTING_ATTRIBUTE}"] == "false"',
    ]
    if routing_conditions != expected_routing_conditions:
        errors.append(
            "Evaluation Collector Phoenix routing must preserve resource opt-out and header false opt-out"
        )
    compatibility_conditions = (
        evaluation_processors.get("filter/phoenix-openinference", {})
        .get("traces", {})
        .get("span", [])
    )
    if compatibility_conditions != [
        'attributes["openinference.span.kind"] == nil'
    ]:
        errors.append(
            "Evaluation Collector Phoenix compatibility filter must retain only OpenInference spans"
        )
    cleanup_actions = (
        evaluation_processors.get("attributes/phoenix-routing-cleanup", {}).get(
            "actions"
        )
        or []
    )
    if cleanup_actions != [
        {"key": PHOENIX_ROUTING_ATTRIBUTE, "action": "delete"}
    ]:
        errors.append(
            "Evaluation Collector must delete temporary Phoenix routing metadata"
        )

    selected = json.loads(
        (ROOT / "examples/otlp/phoenix-selected-trace.json").read_text(
            encoding="utf-8"
        )
    )
    rejected = json.loads(
        (ROOT / "examples/otlp/phoenix-rejected-trace.json").read_text(
            encoding="utf-8"
        )
    )
    for payload, expected in [(selected, True), (rejected, False)]:
        attrs = payload["resourceSpans"][0]["resource"]["attributes"]
        value = next(
            (
                x["value"].get("boolValue")
                for x in attrs
                if x["key"] == "ai_context.export.phoenix"
            ),
            None,
        )
        if value is not expected:
            errors.append(f"Phoenix selection fixture must use boolean {expected}")
        project = next(
            (
                x["value"].get("stringValue")
                for x in attrs
                if x["key"] == "openinference.project.name"
            ),
            None,
        )
        if project != PHOENIX_PROJECT:
            errors.append(
                "Phoenix fixtures must set a deterministic openinference.project.name"
            )

    for filename, expected_trace in (
        ("phoenix-default-trace.json", TRACE_PHOENIX_DEFAULT),
        ("phoenix-header-true-trace.json", TRACE_PHOENIX_HEADER_TRUE),
        ("phoenix-header-false-trace.json", TRACE_PHOENIX_HEADER_FALSE),
    ):
        payload = json.loads(
            (ROOT / "examples/otlp" / filename).read_text(encoding="utf-8")
        )
        resource = payload["resourceSpans"][0]
        attrs = resource["resource"]["attributes"]
        if any(x["key"] == "ai_context.export.phoenix" for x in attrs):
            errors.append(f"{filename} must exercise missing resource selection")
        observed_trace = resource["scopeSpans"][0]["spans"][0]["traceId"]
        if observed_trace != expected_trace:
            errors.append(f"{filename} has an unexpected trace ID")

    generic = json.loads(
        (ROOT / "examples/otlp/phoenix-generic-trace.json").read_text(
            encoding="utf-8"
        )
    )
    generic_span = generic["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    if generic_span["traceId"] != TRACE_PHOENIX_GENERIC:
        errors.append("phoenix-generic-trace.json has an unexpected trace ID")
    if any(
        attribute["key"] == "openinference.span.kind"
        for attribute in generic_span.get("attributes", [])
    ):
        errors.append("Phoenix generic fixture must not declare OpenInference span kind")

    for config_name in ["config.toml.example", "config.corporate.toml.example"]:
        config = tomllib.loads(
            (ROOT / "examples/codex" / config_name).read_text(encoding="utf-8")
        )
        otel = config.get("otel", {})
        if otel.get("log_user_prompt") is not False:
            errors.append(f"Codex {config_name}: log_user_prompt must be false")
        for key, suffix in [
            ("exporter", "/v1/logs"),
            ("trace_exporter", "/v1/traces"),
            ("metrics_exporter", "/v1/metrics"),
        ]:
            endpoint = (
                ((otel.get(key) or {}).get("otlp-http") or {}).get("endpoint", "")
            )
            if not endpoint.startswith("http://127.0.0.1:") or not endpoint.endswith(
                suffix
            ):
                errors.append(
                    f"Codex {config_name}: invalid local {key} endpoint"
                )

    antigravity_root = ROOT / "examples/antigravity"
    antigravity_exporter = antigravity_root / "antigravity_otel_exporter.py"
    if not antigravity_exporter.is_file():
        errors.append("Antigravity example: canonical exporter is missing")
    else:
        exporter_text = antigravity_exporter.read_text(encoding="utf-8")
        for forbidden_reader in (
            'open(payload.get("transcriptPath")',
            'open(payload.get("transcript_path")',
            'artifactDirectoryPath).read',
        ):
            if forbidden_reader in exporter_text:
                errors.append(
                    f"Antigravity exporter must not read transcript/artifact content ({forbidden_reader})"
                )
        if 'payload.get("modelName")' not in exporter_text:
            errors.append("Antigravity exporter: documented Hook modelName support is missing")
        if 'payload.get("toolCall")' in exporter_text or 'payload["toolCall"]' in exporter_text:
            errors.append("Antigravity exporter: must not inspect toolCall content")
        repository_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if f'SCOPE_VERSION = "{repository_version}"' not in exporter_text:
            errors.append("Antigravity exporter: scope version must match Repository version")
        for required in (
            '"ai_observability.profile": profile',
            '"ai_agent.provider": "google"',
            '"ai_agent.product": product',
            '"ai_agent.surface": surface',
            '"ai_agent.evidence.class": "observed"',
        ):
            if required not in exporter_text:
                errors.append(f"Antigravity exporter: canonical contract missing {required}")

    expected_antigravity_operations = {
        "file-operation",
        "search-operation",
        "execution-operation",
        "agent-collaboration",
        "interaction-operation",
    }
    hook_files = sorted((antigravity_root / "config").glob("hooks.*.json.example"))
    if len(hook_files) != 4:
        errors.append(
            f"Antigravity example: expected four Hook variants, found {len(hook_files)}"
        )
    for path in hook_files:
        config = json.loads(path.read_text(encoding="utf-8"))
        definition = config.get("ai-observability") or {}
        if "PreToolUse" in definition:
            errors.append(
                f"Antigravity {path.name}: passive telemetry must not configure PreToolUse"
            )
        for event in ("PreInvocation", "PostInvocation", "PostToolUse", "Stop"):
            if event not in definition:
                errors.append(f"Antigravity {path.name}: missing {event}")
        commands = path.read_text(encoding="utf-8")
        if "antigravity_otel_exporter.py" not in commands:
            errors.append(f"Antigravity {path.name}: exporter command missing")
        if "--product antigravity" not in commands:
            errors.append(f"Antigravity {path.name}: bounded product argument missing")
        operation_values: set[str] = set()
        for matcher in definition.get("PostToolUse", []):
            if matcher.get("matcher") in {None, "", "*"}:
                errors.append(
                    f"Antigravity {path.name}: PostToolUse must classify tools through explicit matchers"
                )
            for hook in matcher.get("hooks", []):
                command = str(hook.get("command", ""))
                marker = " --operation "
                if marker not in command:
                    errors.append(
                        f"Antigravity {path.name}: PostToolUse command must pass a bounded operation"
                    )
                    continue
                operation_values.add(command.split(marker, 1)[1].split(" ", 1)[0])
        if operation_values != expected_antigravity_operations:
            errors.append(
                f"Antigravity {path.name}: unexpected operation set {sorted(operation_values)}"
            )
        if ".corporate." in path.name:
            if "--profile corporate-local-redacted" not in commands:
                errors.append(f"Antigravity {path.name}: corporate profile missing")
            if "--no-include-session-hash" not in commands:
                errors.append(
                    f"Antigravity {path.name}: corporate session hash disable flag missing"
                )

    if (antigravity_root / "plugin").exists():
        errors.append(
            "Antigravity example: do not ship a second plugin route beside direct Hooks"
        )

    status_files = sorted(
        (antigravity_root / "config").glob(
            "settings.statusline.*.json.fragment.example"
        )
    )
    if len(status_files) != 4:
        errors.append(
            f"Antigravity example: expected four status-line variants, found {len(status_files)}"
        )
    for path in status_files:
        config = json.loads(path.read_text(encoding="utf-8"))
        status_line = config.get("statusLine") or {}
        command = str(status_line.get("command", ""))
        if status_line.get("type") != "command" or " statusline " not in f" {command} ":
            errors.append(f"Antigravity {path.name}: invalid statusLine command")
        if "--product antigravity" not in command:
            errors.append(f"Antigravity {path.name}: bounded product argument missing")
        if ".corporate." in path.name and "--no-include-session-hash" not in command:
            errors.append(
                f"Antigravity {path.name}: corporate status line must disable session hash"
            )

    post_tool_fixture = antigravity_root / "fixtures/post-tool-use.json"
    if not post_tool_fixture.is_file():
        errors.append("Antigravity example: PostToolUse privacy fixture is missing")
    else:
        fixture = json.loads(post_tool_fixture.read_text(encoding="utf-8"))
        if not isinstance(fixture.get("toolCall"), dict):
            errors.append("Antigravity fixture: documented toolCall object is missing")
        if not fixture.get("modelName"):
            errors.append("Antigravity fixture: documented modelName is missing")
        if ANTIGRAVITY_SENTINEL not in json.dumps(fixture):
            errors.append("Antigravity fixture: privacy sentinel is missing")

    antigravity_dashboard = ROOT / "config/grafana/dashboards/antigravity-usage.json"
    if not antigravity_dashboard.is_file():
        errors.append("Antigravity example: usage dashboard is missing")
    else:
        dashboard_text = antigravity_dashboard.read_text(encoding="utf-8")
        for metric_name in (
            "antigravity_session_tokens",
            "antigravity_context_tokens",
            "antigravity_context_used_ratio",
            "antigravity_quota_remaining_ratio",
            "antigravity_background_task_count",
            "antigravity_artifact_count",
            "antigravity_context_exceeds_200k",
            "antigravity_pending_input_count",
            "antigravity_tool_confirmation_pending",
        ):
            if metric_name not in dashboard_text:
                errors.append(f"Antigravity dashboard: missing {metric_name}")

    codex_fixture = ROOT / "fixtures/codex/0.146.1"
    for filename in (
        "README.md",
        "mapping.yaml",
        "metrics.sanitized.json",
        "logs.sanitized.json",
        "traces.sanitized.json",
        "prometheus-series.md",
    ):
        if not (codex_fixture / filename).is_file():
            errors.append(f"Codex fixture: missing {filename}")
    for filename in ("metrics.sanitized.json", "logs.sanitized.json", "traces.sanitized.json"):
        path = codex_fixture / filename
        if path.is_file():
            try:
                rendered = render_fixture(path).decode("utf-8")
                if CODEX_FIXTURE_SENTINEL not in rendered:
                    errors.append(f"Codex fixture: privacy sentinel missing from {filename}")
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"Codex fixture {filename}: {exc}")

    dashboards = ROOT / "config/grafana/dashboards"
    dashboard_contract = {
        "codex-usage.json": {
            "required": ("codex_", "Estimated cost", "公開 API"),
            "forbidden": ("ai_context_", "antigravity_"),
        },
        "ai-agent-usage.json": {
            "required": (
                "ai_agent_",
                "Estimated cost",
                "公開 API",
                "Telemetry 距今",
                "所選範圍 Token",
                "所選範圍回合數",
                "Codex 預估 Credits",
                "agent_role",
            ),
            "forbidden": ("codex_", "ai_context_", "antigravity_"),
        },
        "codex-auto-review.json": {
            "required": (
                "ai_agent_",
                "approval_reviewer",
                "Codex Credits 未估價",
                "不是免費",
            ),
            "forbidden": ("codex_", "ai_context_", "antigravity_"),
        },
        "ai-agent-activity.json": {
            "required": ("event_name", "codex.user_prompt", "trace_id"),
            "forbidden": ("ai_context_", "antigravity_"),
        },
        "antigravity-usage.json": {
            "required": ("antigravity_", "目前不猜價"),
            "forbidden": ("codex_", "ai_agent_", "ai_context_"),
        },
    }
    for filename, rules in dashboard_contract.items():
        path = dashboards / filename
        if not path.is_file():
            errors.append(f"Dashboard contract: missing {filename}")
            continue
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        expressions = "\n".join(
            str(target.get("expr", ""))
            for panel in dashboard.get("panels", [])
            for target in panel.get("targets", [])
        )
        rendered = json.dumps(dashboard, ensure_ascii=False)
        for required in rules["required"]:
            haystack = expressions if required.endswith("_") else rendered
            if required not in haystack:
                errors.append(f"Dashboard contract {filename}: missing {required}")
        for forbidden in rules["forbidden"]:
            if forbidden in expressions:
                errors.append(
                    f"Dashboard contract {filename}: forbidden cross-contract query {forbidden}"
                )
        if filename == "codex-usage.json":
            allowed_canonical = {
                "ai_agent_token_usage_total",
                "ai_agent_token_price_usd_per_million",
                "ai_agent_estimated_cost_usd_total",
                "ai_agent_provider",
                "ai_agent_product",
            }
            observed_canonical = set(
                re.findall(r"\bai_agent_[a-z0-9_]+", expressions)
            )
            unexpected = observed_canonical - allowed_canonical
            if unexpected:
                errors.append(
                    "Dashboard contract codex-usage.json: unexpected canonical "
                    f"recording metric(s) {sorted(unexpected)}"
                )

    allowed_sentinel_paths = {
        "SECURITY.md",
        "docs/PRIVACY.md",
        "docs/IMPLEMENTATION-BRIEF.md",
        "scripts/toolkit.py",
    }
    for path in _iter_source_files():
        relative = str(path.relative_to(ROOT)).replace("\\", "/")
        text = path.read_text(encoding="utf-8", errors="ignore")
        if SENTINEL in text and not (
            relative.startswith("examples/otlp/")
            or relative.startswith("examples/antigravity/fixtures/")
            or relative.startswith("tests/")
            or relative in allowed_sentinel_paths
        ):
            errors.append(
                f"Sentinel leaked outside fixture/test/privacy surfaces: {relative}"
            )
        if ANTIGRAVITY_SENTINEL in text and not (
            relative.startswith("examples/antigravity/fixtures/")
            or relative == "tests/test_antigravity_example.py"
            or relative == "scripts/toolkit.py"
        ):
            errors.append(
                f"Antigravity sentinel leaked outside fixture/test surfaces: {relative}"
            )

    bash = shutil.which("bash")
    bash_available = False
    if bash:
        probe = subprocess.run(
            [bash, "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        bash_available = probe.returncode == 0
        if not bash_available:
            print(
                "SKIP: bash is installed but unavailable in this execution environment"
            )
    else:
        print("SKIP: bash not available; shell syntax validation is performed in CI")
    if bash_available:
        for path in sorted((ROOT / "scripts").glob("*.sh")):
            result = subprocess.run(
                [bash, "-n", path.relative_to(ROOT).as_posix()],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode:
                detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
                errors.append(
                    f"Bash {path.name} (exit {result.returncode}): {detail}"
                )
    for python_path in (
        ROOT / "scripts/toolkit.py",
        ROOT / "examples/antigravity/antigravity_otel_exporter.py",
    ):
        python_check = subprocess.run(
            [sys.executable, "-m", "py_compile", str(python_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if python_check.returncode:
            errors.append(
                f"Python syntax ({display_path(python_path)}): {python_check.stderr.strip()}"
            )

    try:
        import jsonschema  # type: ignore[import-not-found]

        schema_examples = [
            (
                ROOT / "schemas/feedback-bundle.schema.json",
                ROOT / "examples/feedback-bundle.json",
            ),
            (
                ROOT / "schemas/ai-context-telemetry.schema.json",
                ROOT / "examples/ai-context-event.json",
            ),
        ]
        for schema_path, example_path in schema_examples:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            example = json.loads(example_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(example)
    except ModuleNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        errors.append(f"JSON Schema validation: {exc}")

    return errors


def _validate_binary(binary: str, args: list[str], name: str) -> str | None:
    result = subprocess.run(
        [binary, *args], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode:
        return f"{name}: {result.stderr.strip() or result.stdout.strip()}"
    return None


def external_validate(mode: str) -> list[str]:
    errors: list[str] = []
    modes = sorted(MODES) if mode == "all" else [mode]
    compose = find_compose()
    if compose:
        for item in modes:
            result = subprocess.run(
                compose + compose_args(item) + ["config", "--quiet"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if result.returncode:
                errors.append(
                    f"Compose {item}: {result.stderr.strip() or result.stdout.strip()}"
                )
            else:
                print(f"PASS: Compose config ({item})")
    else:
        print("SKIP: Docker Compose v2+ executable not available")

    otelcol = os.environ.get("OTELCOL_BIN")
    if otelcol:
        for config in ["core.yaml", "evaluation.yaml", "corporate.yaml"]:
            error = _validate_binary(
                otelcol,
                [
                    "validate",
                    f"--config={ROOT / 'config/otel-collector' / config}",
                ],
                f"Collector {config}",
            )
            if error:
                errors.append(error)
            else:
                print(f"PASS: Collector config ({config})")
    else:
        print(
            "SKIP: OTELCOL_BIN not set; native Collector validation is performed in CI"
        )

    promtool = os.environ.get("PROMTOOL_BIN")
    if promtool:
        error = _validate_binary(
            promtool,
            [
                "check",
                "config",
                str(ROOT / "config/prometheus/prometheus.yml"),
            ],
            "Prometheus",
        )
        if error:
            errors.append(error)
        else:
            print("PASS: Prometheus config")
    else:
        print(
            "SKIP: PROMTOOL_BIN not set; native Prometheus validation is performed in CI"
        )

    loki_bin = os.environ.get("LOKI_BIN")
    if loki_bin:
        error = _validate_binary(
            loki_bin,
            [
                f"-config.file={ROOT / 'config/loki/loki.yml'}",
                "-verify-config=true",
            ],
            "Loki",
        )
        if error:
            errors.append(error)
        else:
            print("PASS: Loki config")
    else:
        print("SKIP: LOKI_BIN not set; native Loki validation is performed in CI")

    tempo_bin = os.environ.get("TEMPO_BIN")
    if tempo_bin:
        error = _validate_binary(
            tempo_bin,
            [
                f"-config.file={ROOT / 'config/tempo/tempo.yml'}",
                "-config.verify=true",
            ],
            "Tempo",
        )
        if error:
            errors.append(error)
        else:
            print("PASS: Tempo config")
    else:
        print("SKIP: TEMPO_BIN not set; native Tempo validation is performed in CI")

    pwsh = shutil.which("pwsh")
    if pwsh:
        script = """
$failed = $false
Get-ChildItem -LiteralPath "scripts" -Filter "*.ps1" | ForEach-Object {
  $tokens = $null
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors)
  if ($errors.Count -gt 0) {
    $failed = $true
    $errors | ForEach-Object { Write-Error "$($_.Extent.File): $($_.Message)" }
  }
}
if ($failed) { exit 1 }
"""
        result = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            errors.append(
                f"PowerShell parser: {result.stderr.strip() or result.stdout.strip()}"
            )
        else:
            print("PASS: PowerShell parser")
    else:
        print("SKIP: pwsh not available; PowerShell parsing is performed in CI")
    return errors


def render_fixture(path: Path) -> bytes:
    now = time.time_ns()
    text = path.read_text(encoding="utf-8")
    text = text.replace("{{TIME_UNIX_NANO}}", str(now))
    text = text.replace("{{START_TIME_UNIX_NANO}}", str(now - 50_000_000))
    text = text.replace("{{END_TIME_UNIX_NANO}}", str(now))
    json.loads(text)
    return text.encode("utf-8")


def http(
    method: str,
    url: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, data=data, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def load_phoenix_annotation_configs() -> list[dict[str, Any]]:
    configs = json.loads(PHOENIX_ANNOTATION_CONFIGS.read_text(encoding="utf-8"))
    if not isinstance(configs, list) or not configs:
        raise ValueError("annotation configuration must be a non-empty array")
    names: set[str] = set()
    required_names = {
        "執行結果",
        "問題類型",
        "是否值得保留為案例",
        "人工判斷原因",
        "後續處置",
    }
    for config in configs:
        if not isinstance(config, dict):
            raise ValueError("every annotation configuration must be an object")
        name = config.get("name")
        config_type = config.get("type")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError(f"annotation configuration name is missing or duplicated: {name!r}")
        names.add(name)
        if config_type not in {"CATEGORICAL", "FREEFORM"}:
            raise ValueError(f"unsupported annotation configuration type for {name}: {config_type}")
        if not isinstance(config.get("description"), str) or not config["description"].strip():
            raise ValueError(f"annotation configuration description is required: {name}")
        if config_type == "CATEGORICAL":
            if config.get("optimization_direction") not in {"MINIMIZE", "MAXIMIZE", "NONE"}:
                raise ValueError(f"invalid optimization direction: {name}")
            values = config.get("values")
            if not isinstance(values, list) or not values:
                raise ValueError(f"categorical values are required: {name}")
            labels = [value.get("label") for value in values if isinstance(value, dict)]
            if len(labels) != len(values) or any(not isinstance(label, str) for label in labels):
                raise ValueError(f"categorical labels are invalid: {name}")
    if names != required_names:
        raise ValueError(
            "annotation configuration names must exactly match the zh-TW operational rubric"
        )
    return configs


def _annotation_payload(config: dict[str, Any]) -> dict[str, Any]:
    keys = {"name", "type", "description"}
    if config["type"] == "CATEGORICAL":
        keys.update({"optimization_direction", "values"})
    return {key: config.get(key) for key in keys}


def _json_response(status: int, body: bytes, operation: str) -> dict[str, Any]:
    if not 200 <= status < 300:
        detail = body.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Phoenix {operation} failed: HTTP {status} {detail}")
    payload = json.loads(body or b"{}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Phoenix {operation} returned a non-object response")
    return payload


def phoenix_annotations(project: str, *, apply: bool) -> None:
    """Check or idempotently provision the zh-TW rubric for one Phoenix project."""
    if not project.strip():
        raise ValueError("Phoenix project must not be empty")
    base = urls("evaluation")["Phoenix"].rstrip("/")
    project_path = urllib.parse.quote(project, safe="")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    configs = load_phoenix_annotation_configs()

    assigned_status, assigned_body = http(
        "GET", f"{base}/v1/projects/{project_path}/annotation_configs?limit=100"
    )
    assigned_payload = _json_response(
        assigned_status, assigned_body, f"project annotation lookup for {project}"
    )
    assigned_names = {
        item.get("name")
        for item in assigned_payload.get("data", [])
        if isinstance(item, dict)
    }
    pending: list[str] = []

    for expected in configs:
        name = expected["name"]
        name_path = urllib.parse.quote(name, safe="")
        status, body = http("GET", f"{base}/v1/annotation_configs/{name_path}")
        actual: dict[str, Any] | None = None
        if status == 200:
            actual = _json_response(status, body, f"annotation lookup for {name}").get("data")
            if not isinstance(actual, dict):
                raise RuntimeError(f"Phoenix annotation lookup returned no data for {name}")
        elif status != 404:
            _json_response(status, body, f"annotation lookup for {name}")

        desired = _annotation_payload(expected)
        if actual is None:
            if not apply:
                pending.append(f"missing config: {name}")
                continue
            create_status, create_body = http(
                "POST",
                f"{base}/v1/annotation_configs",
                data=json.dumps(desired, ensure_ascii=False).encode("utf-8"),
                headers=headers,
            )
            actual = _json_response(
                create_status, create_body, f"annotation creation for {name}"
            ).get("data")
            print(f"CREATED: Phoenix annotation config {name}")
        elif any(actual.get(key) != value for key, value in desired.items()):
            if not apply:
                pending.append(f"drifted config: {name}")
                continue
            config_id = urllib.parse.quote(str(actual.get("id", "")), safe="")
            update_status, update_body = http(
                "PUT",
                f"{base}/v1/annotation_configs/{config_id}",
                data=json.dumps(desired, ensure_ascii=False).encode("utf-8"),
                headers=headers,
            )
            actual = _json_response(
                update_status, update_body, f"annotation update for {name}"
            ).get("data")
            print(f"UPDATED: Phoenix annotation config {name}")

        if name not in assigned_names:
            if not apply:
                pending.append(f"not assigned to {project}: {name}")
                continue
            assign_status, assign_body = http(
                "PUT",
                f"{base}/v1/projects/{project_path}/annotation_configs/{name_path}",
            )
            _json_response(assign_status, assign_body, f"annotation assignment for {name}")
            print(f"ASSIGNED: {name} -> {project}")

    if pending:
        for item in pending:
            print(f"DRIFT: {item}", file=sys.stderr)
        raise RuntimeError(
            "Phoenix zh-TW annotation rubric is not provisioned; rerun with --apply"
        )
    print(f"PASS: Phoenix zh-TW annotation rubric for project {project}")


def wait_url(name: str, url: str, timeout: float = 180.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            status, body = http("GET", url, timeout=4.0)
            if 200 <= status < 400:
                print(f"READY: {name} ({url})")
                return
            last_error = f"HTTP {status}: {body[:200]!r}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"timeout waiting for {name}: {last_error}")


def urls(mode: str) -> dict[str, str]:
    load_env_file()
    result = {
        "Grafana": f"http://127.0.0.1:{os.getenv('GRAFANA_PORT', '3000')}",
        "Prometheus": (
            f"http://127.0.0.1:{os.getenv('PROMETHEUS_PORT', '9090')}"
        ),
        "Loki": f"http://127.0.0.1:{os.getenv('LOKI_PORT', '3100')}",
        "Tempo": f"http://127.0.0.1:{os.getenv('TEMPO_PORT', '3200')}",
        "OTLP gRPC": f"127.0.0.1:{os.getenv('OTLP_GRPC_PORT', '4317')}",
        "OTLP HTTP": (
            f"http://127.0.0.1:{os.getenv('OTLP_HTTP_PORT', '4318')}"
        ),
    }
    if mode == "evaluation":
        result["Phoenix"] = (
            f"http://127.0.0.1:{os.getenv('PHOENIX_PORT', '6006')}"
        )
    return result


def wait_stack(mode: str) -> None:
    load_env_file()
    wait_url(
        "Collector",
        f"http://127.0.0.1:{os.getenv('OTEL_HEALTH_PORT', '13133')}/",
    )
    wait_url(
        "Prometheus",
        f"http://127.0.0.1:{os.getenv('PROMETHEUS_PORT', '9090')}/-/ready",
    )
    wait_url(
        "Loki", f"http://127.0.0.1:{os.getenv('LOKI_PORT', '3100')}/ready"
    )
    wait_url(
        "Tempo", f"http://127.0.0.1:{os.getenv('TEMPO_PORT', '3200')}/ready"
    )
    wait_url(
        "Grafana",
        f"http://127.0.0.1:{os.getenv('GRAFANA_PORT', '3000')}/api/health",
    )
    if mode == "evaluation":
        wait_url(
            "Phoenix",
            f"http://127.0.0.1:{os.getenv('PHOENIX_PORT', '6006')}/healthz",
        )


def send_fixture(
    filename: str,
    signal: str,
    *,
    directory: Path | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    port = os.getenv("OTLP_HTTP_PORT", "4318")
    fixture_directory = directory or ROOT / "examples/otlp"
    data = render_fixture(fixture_directory / filename)
    status, body = http(
        "POST",
        f"http://127.0.0.1:{port}/v1/{signal}",
        data,
        {"Content-Type": "application/json", **(headers or {})},
    )
    if status not in {200, 202}:
        raise RuntimeError(
            f"OTLP {filename} failed: HTTP {status} "
            f"{body.decode(errors='replace')}"
        )
    print(f"SENT: {filename}")


def send_antigravity_status_fixture(mode: str) -> None:
    port = os.getenv("OTLP_HTTP_PORT", "4318")
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    profile = (
        "corporate-local-redacted" if mode == "corporate" else "personal-local"
    )
    with tempfile.TemporaryDirectory(
        dir=artifacts, prefix="antigravity-smoke-"
    ) as directory:
        state_dir = Path(directory) / "state"
        command = [
            sys.executable,
            str(ROOT / "examples/antigravity/antigravity_otel_exporter.py"),
            "statusline",
            "--endpoint",
            f"http://127.0.0.1:{port}",
            "--profile",
            profile,
            "--product",
            "antigravity",
            "--service-namespace",
            "ai-collaboration-fixture",
            "--state-dir",
            str(state_dir),
            "--timeout",
            "2",
        ]
        if mode == "corporate":
            command.append("--no-include-session-hash")
        result = subprocess.run(
            command,
            cwd=ROOT,
            input=(
                ROOT / "examples/antigravity/fixtures/statusline.json"
            ).read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or "AGY Gemini 3.6 Flash" not in result.stdout:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Antigravity status-line fixture failed: {detail}")
    print("SENT: Antigravity status-line fixture")


def retry(
    name: str,
    fn: Callable[[], Any],
    predicate: Callable[[Any], bool],
    timeout: float = 90.0,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = fn()
            if predicate(last):
                return last
            last_error = f"last result did not satisfy assertion: {last!r}"[:500]
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"timeout waiting for {name}: {last_error}")


def prometheus_query(expr: str) -> list[dict[str, Any]]:
    port = os.getenv("PROMETHEUS_PORT", "9090")
    query = urllib.parse.urlencode({"query": expr})
    status, body = http(
        "GET", f"http://127.0.0.1:{port}/api/v1/query?{query}"
    )
    payload = json.loads(body)
    if status != 200 or payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    return payload["data"]["result"]


def prometheus_series(metric: str) -> list[dict[str, str]]:
    port = os.getenv("PROMETHEUS_PORT", "9090")
    query = urllib.parse.urlencode({"match[]": metric})
    status, body = http(
        "GET", f"http://127.0.0.1:{port}/api/v1/series?{query}"
    )
    payload = json.loads(body)
    if status != 200 or payload.get("status") != "success":
        raise RuntimeError(f"Prometheus series query failed: {payload}")
    return payload.get("data", [])


def prometheus_scalar(expr: str) -> float:
    results = prometheus_query(expr)
    if len(results) != 1:
        raise RuntimeError(f"expected one Prometheus scalar series for {expr!r}: {results}")
    return float(results[0]["value"][1])


def loki_query(
    service_name: str = "ai-observability-fixture",
    service_namespace: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    port = os.getenv("LOKI_PORT", "3100")
    selector = f'service_name="{service_name}"'
    if service_namespace:
        selector += f',service_namespace="{service_namespace}"'
    params = urllib.parse.urlencode(
        {
            "query": "{" + selector + "}",
            "limit": "100",
            "start": str(time.time_ns() - 15 * 60 * 1_000_000_000),
            "end": str(time.time_ns()),
        }
    )
    status, body = http(
        "GET", f"http://127.0.0.1:{port}/loki/api/v1/query_range?{params}"
    )
    payload = json.loads(body)
    if status != 200 or payload.get("status") != "success":
        raise RuntimeError(f"Loki query failed: {payload}")
    return payload, body


def tempo_trace(trace_id: str) -> tuple[int, bytes]:
    port = os.getenv("TEMPO_PORT", "3200")
    return http("GET", f"http://127.0.0.1:{port}/api/traces/{trace_id}")


def grafana_headers() -> dict[str, str]:
    user = os.getenv("GRAFANA_ADMIN_USER", "admin")
    password = os.getenv("GRAFANA_ADMIN_PASSWORD", "change-me-local-only")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def grafana_datasource_health(uid: str) -> dict[str, Any]:
    port = os.getenv("GRAFANA_PORT", "3000")
    status, body = http(
        "GET",
        f"http://127.0.0.1:{port}/api/datasources/uid/"
        f"{urllib.parse.quote(uid)}/health",
        headers=grafana_headers(),
    )
    payload = json.loads(body or b"{}")
    if status != 200:
        raise RuntimeError(
            f"Grafana datasource {uid} health failed: HTTP {status} {payload}"
        )
    return payload


def grafana_dashboard(uid: str) -> dict[str, Any]:
    port = os.getenv("GRAFANA_PORT", "3000")
    status, body = http(
        "GET",
        f"http://127.0.0.1:{port}/api/dashboards/uid/"
        f"{urllib.parse.quote(uid)}",
        headers=grafana_headers(),
    )
    payload = json.loads(body or b"{}")
    if status != 200:
        raise RuntimeError(
            f"Grafana dashboard {uid} lookup failed: HTTP {status} {payload}"
        )
    return payload


def phoenix_spans(trace_id: str) -> tuple[int, dict[str, Any], bytes]:
    port = os.getenv("PHOENIX_PORT", "6006")
    query = urllib.parse.urlencode({"trace_id": trace_id, "limit": 100})
    url = (
        f"http://127.0.0.1:{port}/v1/projects/"
        f"{urllib.parse.quote(PHOENIX_PROJECT, safe='')}/spans?{query}"
    )
    status, body = http("GET", url)
    payload = json.loads(body or b"{}") if body else {}
    return status, payload, body


@dataclass
class SmokeReport:
    mode: str
    started_at: str = field(default_factory=utc_now)
    checks: list[dict[str, str]] = field(default_factory=list)

    def pass_(self, name: str, detail: str = "") -> None:
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
        self.checks.append({"name": name, "status": "PASS", "detail": detail})

    def skip(self, name: str, detail: str) -> None:
        print(f"[SKIP] {name} — {detail}")
        self.checks.append({"name": name, "status": "SKIP", "detail": detail})

    def fail(self, name: str, detail: str) -> None:
        print(f"[FAIL] {name} — {detail}", file=sys.stderr)
        self.checks.append({"name": name, "status": "FAIL", "detail": detail})

    def write(self, path: Path | None = None) -> Path:
        if path is None:
            directory = ROOT / "artifacts/smoke"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{timestamp_slug()}-{self.mode}.json"
        else:
            path = path if path.is_absolute() else ROOT / path
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "mode": self.mode,
                    "started_at": self.started_at,
                    "completed_at": utc_now(),
                    "checks": self.checks,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"REPORT: {display_path(path)}")
        return path

    @property
    def failed(self) -> bool:
        return any(check["status"] == "FAIL" for check in self.checks)


def _check_backend_data(
    mode: str, report: SmokeReport, prefix: str = ""
) -> None:
    def current_or_recent(selector: str) -> str:
        return f"max_over_time({selector}[15m])" if prefix else selector

    metric_results = retry(
        "Prometheus smoke metric",
        lambda: prometheus_query("ai_agent_token_usage_total"),
        bool,
    )
    report.pass_(prefix + "prometheus metric", f"series={len(metric_results)}")
    series = prometheus_series("ai_agent_token_usage_total")
    forbidden = {
        "session_id",
        "session.id",
        "absolute_path",
        "user_email",
        "user.email",
    }
    leaked_labels = sorted({key for item in series for key in item if key in forbidden})
    if leaked_labels:
        raise RuntimeError(
            f"high-cardinality/private Prometheus labels found: {leaked_labels}"
        )
    if SENTINEL in json.dumps(series):
        raise RuntimeError("privacy sentinel leaked into Prometheus series metadata")
    report.pass_(prefix + "prometheus label policy")

    raw_sum, canonical_sum = retry(
        "Codex raw/canonical token histogram reconciliation",
        lambda: (
            prometheus_scalar(
                'sum(codex_turn_token_usage_sum{service_namespace="ai-collaboration-fixture"})'
            ),
            prometheus_scalar(
                'sum(ai_agent_turn_token_usage_sum{service_namespace="ai-collaboration-fixture"})'
            ),
        ),
        lambda value: value[0] > 0 and abs(value[0] - value[1]) < 0.000001,
    )
    canonical_series = prometheus_series(
        'ai_agent_turn_token_usage_sum{service_namespace="ai-collaboration-fixture"}'
    )
    canonical_rendered = json.dumps(canonical_series)
    if CODEX_FIXTURE_SENTINEL in canonical_rendered:
        raise RuntimeError("Codex privacy sentinel leaked into canonical Prometheus series")
    forbidden_codex_labels = {
        "arguments",
        "call_id",
        "conversation_id",
        "prompt_length",
        "session_id",
        "tool",
        "tool_name",
        "trace_id",
        "user_account_id",
    }
    leaked_codex_labels = sorted(
        {
            key
            for item in canonical_series
            for key in item
            if key in forbidden_codex_labels
        }
    )
    if leaked_codex_labels:
        raise RuntimeError(
            f"forbidden Codex canonical labels found: {leaked_codex_labels}"
        )
    report.pass_(
        prefix + "codex raw/canonical histogram",
        f"raw_sum={raw_sum:g}, canonical_sum={canonical_sum:g}",
    )

    expected_accounting = {
        "input_uncached": 3000.0,
        "input_cached": 6000.0,
        "input_cache_write": 1000.0,
        "output": 2000.0,
    }
    accounting_values = retry(
        "Codex token accounting classes",
        lambda: {
            usage_class: prometheus_scalar(
                "sum("
                + current_or_recent(
                    "ai_agent_token_usage_total{"
                    'ai_agent_provider="openai",ai_agent_product="codex",'
                    'model_id="gpt-5.6-sol",'
                    'agent_role="primary",'
                    'service_namespace="ai-collaboration-cost-fixture",'
                    'accounting_schema="v2",'
                    f'usage_class="{usage_class}"}}'
                )
                + ")"
            )
            for usage_class in expected_accounting
        },
        lambda value: all(
            abs(value[usage_class] - expected) < 0.000001
            for usage_class, expected in expected_accounting.items()
        ),
    )
    estimated_cost = retry(
        "Codex estimated public API cost",
        lambda: prometheus_scalar(
            "sum("
            + current_or_recent(
                'ai_agent_estimated_cost_usd_total{ai_agent_provider="openai",'
                'ai_agent_product="codex",model_id="gpt-5.6-sol",'
                'agent_role="primary",'
                'service_namespace="ai-collaboration-cost-fixture",'
                'accounting_schema="v2"}'
            )
            + ")"
        ),
        lambda value: abs(value - 0.08425) < 0.000000001,
    )
    estimated_credits = retry(
        "Codex estimated public credits",
        lambda: prometheus_scalar(
            "sum("
            + current_or_recent(
                'ai_agent_estimated_credit_usage_total{ai_agent_provider="openai",'
                'ai_agent_product="codex",model_id="gpt-5.6-sol",'
                'agent_role="primary",'
                'service_namespace="ai-collaboration-cost-fixture",'
                'accounting_schema="v2"}'
            )
            + ")"
        ),
        lambda value: abs(value - 1.95) < 0.000000001,
    )
    reviewer_accounting = retry(
        "Codex approval-reviewer token accounting",
        lambda: {
            usage_class: prometheus_scalar(
                "sum("
                + current_or_recent(
                    "ai_agent_token_usage_total{"
                    'ai_agent_provider="openai",ai_agent_product="codex",'
                    'agent_role="approval_reviewer",model_id="unmapped",'
                    'service_namespace="ai-collaboration-role-fixture",'
                    'accounting_schema="v2",'
                    f'usage_class="{usage_class}"}}'
                )
                + ")"
            )
            for usage_class in ("input_uncached", "input_cached", "output")
        },
        lambda value: value
        == {"input_uncached": 2000.0, "input_cached": 6000.0, "output": 1000.0},
    )
    subagent_series = retry(
        "Codex producer-supplied subagent role",
        lambda: prometheus_query(
            'ai_agent_turn_token_usage_sum{service_namespace="ai-collaboration-role-fixture",'
            'agent_role="subagent",model_id="gpt-5.6-terra"}'
        ),
        lambda value: bool(value),
    )
    if prometheus_query(
        'ai_agent_estimated_cost_usd_total{agent_role="approval_reviewer",'
        'service_namespace="ai-collaboration-role-fixture"}'
    ):
        raise RuntimeError("unmapped Codex auto-review usage was unexpectedly priced")
    if prometheus_query(
        'ai_agent_estimated_credit_usage_total{agent_role="approval_reviewer",'
        'service_namespace="ai-collaboration-role-fixture"}'
    ):
        raise RuntimeError("unmapped Codex auto-review usage unexpectedly consumed credits")
    unpriced_cache_write = retry(
        "Codex credits unpriced cache-write boundary",
        lambda: prometheus_scalar(
            "sum("
            + current_or_recent(
                'ai_agent_unpriced_credit_token_usage_total{model_id="gpt-5.6-sol",'
                'agent_role="primary",usage_class="input_cache_write",'
                'service_namespace="ai-collaboration-cost-fixture",'
                'accounting_schema="v2"}'
            )
            + ")"
        ),
        lambda value: abs(value - 1000.0) < 0.000001,
    )
    price_series = prometheus_query("ai_agent_token_price_usd_per_million")
    if len(price_series) != 12:
        raise RuntimeError(
            f"expected 12 exact rate-card series, found {len(price_series)}"
        )
    credit_series = prometheus_query("ai_agent_token_credit_per_million")
    if len(credit_series) != 9:
        raise RuntimeError(
            f"expected 9 published Codex credit-rate series, found {len(credit_series)}"
        )
    report.pass_(
        prefix + "codex role/token accounting and estimates",
        f"classes={accounting_values}, estimated_usd={estimated_cost:g}, "
        f"estimated_credits={estimated_credits:g}, reviewer={reviewer_accounting}, "
        f"subagent_series={len(subagent_series)}, "
        f"unpriced_cache_write={unpriced_cache_write:g}",
    )

    raw_antigravity, canonical_antigravity = retry(
        "Antigravity raw/canonical observed session tokens",
        lambda: (
            prometheus_scalar(
                "sum("
                + current_or_recent(
                    'antigravity_session_tokens{ai_agent_provider="google",'
                    'ai_agent_product="antigravity",'
                    'service_namespace="ai-collaboration-fixture"}'
                )
                + ")"
            ),
            prometheus_scalar(
                "sum("
                + current_or_recent(
                    'ai_agent_observed_session_tokens{ai_agent_provider="google",'
                    'ai_agent_product="antigravity",'
                    'service_namespace="ai-collaboration-fixture"}'
                )
                + ")"
            ),
        ),
        lambda value: value[0] > 0 and abs(value[0] - value[1]) < 0.000001,
    )
    observed_context_ratio = prometheus_scalar(
        "max("
        + current_or_recent(
            'ai_agent_observed_context_used_ratio{ai_agent_provider="google",'
            'ai_agent_product="antigravity",'
            'service_namespace="ai-collaboration-fixture"}'
        )
        + ")"
    )
    observed_quota_ratio = prometheus_scalar(
        "max("
        + current_or_recent(
            'ai_agent_observed_quota_remaining_ratio{ai_agent_provider="google",'
            'ai_agent_product="antigravity",'
            'service_namespace="ai-collaboration-fixture"}'
        )
        + ")"
    )
    if prometheus_query(
        'ai_agent_estimated_cost_usd_total{ai_agent_provider="google"}'
    ):
        raise RuntimeError("extension-observed Antigravity gauges were unexpectedly priced")
    report.pass_(
        prefix + "antigravity observed usage boundary",
        "session_tokens="
        f"{canonical_antigravity:g}, context_ratio={observed_context_ratio:g}, "
        f"quota_ratio={observed_quota_ratio:g}, estimated_cost=absent",
    )

    loki_payload, loki_raw = retry(
        "Loki smoke log",
        loki_query,
        lambda value: bool(value[0].get("data", {}).get("result")),
    )
    if SENTINEL.encode() in loki_raw:
        raise RuntimeError("privacy sentinel leaked into Loki")
    if b"AI telemetry metadata event" not in loki_raw:
        raise RuntimeError("Loki received no normalized metadata-only log body")
    report.pass_(
        prefix + "loki log", f"streams={len(loki_payload['data']['result'])}"
    )

    codex_loki_payload, codex_loki_raw = retry(
        "Loki Codex sanitized log",
        lambda: loki_query("codex-app-server", "ai-collaboration-fixture"),
        lambda value: bool(value[0].get("data", {}).get("result")),
    )
    if CODEX_FIXTURE_SENTINEL.encode() in codex_loki_raw:
        raise RuntimeError("Codex privacy sentinel leaked into Loki")
    report.pass_(
        prefix + "codex loki privacy window",
        f"streams={len(codex_loki_payload['data']['result'])}",
    )

    antigravity_loki_payload, antigravity_loki_raw = retry(
        "Loki Antigravity sanitized status log",
        lambda: loki_query("antigravity"),
        lambda value: bool(value[0].get("data", {}).get("result")),
    )
    if ANTIGRAVITY_SENTINEL.encode() in antigravity_loki_raw:
        raise RuntimeError("Antigravity privacy sentinel leaked into Loki")
    report.pass_(
        prefix + "antigravity loki privacy window",
        f"streams={len(antigravity_loki_payload['data']['result'])}",
    )

    status, body = retry(
        "Tempo core trace",
        lambda: tempo_trace(TRACE_CORE),
        lambda value: value[0] == 200,
    )
    if SENTINEL.encode() in body:
        raise RuntimeError("privacy sentinel leaked into Tempo core trace")
    report.pass_(prefix + "tempo core trace")

    status, codex_trace = retry(
        "Tempo Codex sanitized trace",
        lambda: tempo_trace(TRACE_CODEX),
        lambda value: value[0] == 200,
    )
    if CODEX_FIXTURE_SENTINEL.encode() in codex_trace:
        raise RuntimeError("Codex privacy sentinel leaked into Tempo")
    report.pass_(prefix + "codex tempo privacy window")

    if mode == "evaluation":
        for trace_id, label in [
            (TRACE_SELECTED, "selected trace"),
            (TRACE_REJECTED, "rejected trace"),
            (TRACE_PHOENIX_DEFAULT, "default-routed trace"),
            (TRACE_PHOENIX_HEADER_TRUE, "header-true trace"),
            (TRACE_PHOENIX_HEADER_FALSE, "header-false trace"),
            (TRACE_PHOENIX_GENERIC, "generic trace"),
        ]:
            status, body = retry(
                f"Tempo {label}",
                lambda trace_id=trace_id: tempo_trace(trace_id),
                lambda value: value[0] == 200,
            )
            if SENTINEL.encode() in body:
                raise RuntimeError(f"privacy sentinel leaked into Tempo {label}")
            report.pass_(prefix + "tempo " + label)


def _check_grafana(report: SmokeReport, prefix: str = "") -> None:
    for uid in ["prometheus", "loki", "tempo"]:
        payload = retry(
            f"Grafana datasource {uid}",
            lambda uid=uid: grafana_datasource_health(uid),
            lambda value: (
                str(value.get("status", "")).upper() in {"OK", "SUCCESS"}
                or str(value.get("message", ""))
                .lower()
                .startswith("data source is working")
            ),
        )
        detail = str(payload.get("message", payload.get("status", "OK")))
        report.pass_(prefix + f"grafana datasource {uid}", detail)
    for uid, title in (
        ("ai-collector-health", "Collector 健康狀態（Collector Health）"),
        ("ai-codex-usage", "Codex 原生 Telemetry（Codex Native Telemetry）"),
        ("ai-codex-auto-review", "Codex Auto-review 用量（Approval Reviewer）"),
        ("ai-agent-usage", "AI Agent 用量（AI Agent Usage）"),
        ("ai-agent-activity", "AI Agent 活動（Metadata 與 Trace）"),
        ("ai-antigravity-usage", "Antigravity 用量（觀測值，非帳務）"),
    ):
        payload = retry(
            f"Grafana dashboard {uid}",
            lambda uid=uid: grafana_dashboard(uid),
            lambda value, title=title: (
                (value.get("dashboard") or {}).get("title") == title
            ),
        )
        report.pass_(
            prefix + f"grafana dashboard {uid}",
            str((payload.get("dashboard") or {}).get("title", "")),
        )


def _check_phoenix(report: SmokeReport, prefix: str = "") -> None:
    for trace_id, label in (
        (TRACE_SELECTED, "legacy selected trace"),
        (TRACE_PHOENIX_DEFAULT, "missing-header default trace"),
        (TRACE_PHOENIX_HEADER_TRUE, "header-true trace"),
    ):
        observed = retry(
            f"Phoenix {label}",
            lambda trace_id=trace_id: phoenix_spans(trace_id),
            lambda value, trace_id=trace_id: (
                value[0] == 200 and trace_id.encode() in value[2]
            ),
        )
        for forbidden in (
            SENTINEL.encode(),
            PHOENIX_ROUTING_HEADER.encode(),
            PHOENIX_ROUTING_ATTRIBUTE.encode(),
        ):
            if forbidden in observed[2]:
                raise RuntimeError(f"private or routing metadata leaked into {label}")
        report.pass_(prefix + "phoenix " + label)

    for trace_id, label in (
        (TRACE_REJECTED, "legacy resource opt-out trace"),
        (TRACE_PHOENIX_HEADER_FALSE, "header-false trace"),
        (TRACE_PHOENIX_GENERIC, "generic non-OpenInference trace"),
    ):
        rejected = retry(
            f"Phoenix {label} query",
            lambda trace_id=trace_id: phoenix_spans(trace_id),
            lambda value: value[0] == 200,
        )
        if trace_id.encode() in rejected[2]:
            raise RuntimeError(f"Phoenix received the {label}")
        if SENTINEL.encode() in rejected[2]:
            raise RuntimeError("privacy sentinel leaked into Phoenix")
        report.pass_(prefix + "phoenix " + label + " absent")


def _check_collector_logs(mode: str, report: SmokeReport) -> None:
    result = compose_command(
        mode, ["logs", "--no-color", "otel-collector"], capture=True
    )
    text = result.stdout + result.stderr
    for sentinel in (SENTINEL, ANTIGRAVITY_SENTINEL, CODEX_FIXTURE_SENTINEL):
        if sentinel in text:
            raise RuntimeError("privacy sentinel leaked into Collector logs")
    report.pass_("collector logs sentinel absent")


def _verify_named_volumes(mode: str, report: SmokeReport) -> None:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker CLI unavailable while verifying named volumes")
    result = subprocess.run(
        [
            docker,
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={project_name()}",
            "--format",
            "{{.Name}}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    volumes = sorted(
        line.strip() for line in result.stdout.splitlines() if line.strip()
    )
    expected_fragments = [
        "grafana-data",
        "loki-data",
        "prometheus-data",
        "tempo-data",
    ]
    if mode == "evaluation":
        expected_fragments.append("phoenix-postgres-data")
    missing = [
        fragment
        for fragment in expected_fragments
        if not any(fragment in volume for volume in volumes)
    ]
    if missing:
        raise RuntimeError(
            f"expected named volumes are missing: {missing}; found={volumes}"
        )
    report.pass_("named volumes present", ", ".join(volumes))


def _restart_and_verify(mode: str, report: SmokeReport) -> None:
    compose_command(
        mode, ["restart", "otel-collector", "prometheus", "loki", "tempo"]
    )
    if mode == "evaluation":
        compose_command(mode, ["restart", "postgres"])
        compose_command(mode, ["restart", "phoenix"])
    wait_stack(mode)
    _check_backend_data(mode, report, prefix="after restart: ")
    _check_grafana(report, prefix="after restart: ")
    if mode == "evaluation":
        _check_phoenix(report, prefix="after restart: ")
    report.pass_("named-volume persistence after restart")


def smoke(
    mode: str,
    *,
    verify_persistence: bool,
    report_path: Path | None = None,
) -> None:
    report = SmokeReport(mode)
    try:
        wait_stack(mode)
        report.pass_("stack readiness")
        send_fixture("logs.json", "logs")
        send_fixture("metrics.json", "metrics")
        send_fixture("codex-cost-accounting-metrics.json", "metrics")
        send_antigravity_status_fixture(mode)
        send_fixture("traces.json", "traces")
        codex_fixture = ROOT / "fixtures/codex/0.146.1"
        send_fixture("logs.sanitized.json", "logs", directory=codex_fixture)
        send_fixture("metrics.sanitized.json", "metrics", directory=codex_fixture)
        send_fixture("traces.sanitized.json", "traces", directory=codex_fixture)
        if mode == "evaluation":
            send_fixture("phoenix-rejected-trace.json", "traces")
            send_fixture("phoenix-selected-trace.json", "traces")
            send_fixture("phoenix-default-trace.json", "traces")
            send_fixture(
                "phoenix-header-true-trace.json",
                "traces",
                headers={PHOENIX_ROUTING_HEADER: "true"},
            )
            send_fixture(
                "phoenix-header-false-trace.json",
                "traces",
                headers={PHOENIX_ROUTING_HEADER: "false"},
            )
            send_fixture("phoenix-generic-trace.json", "traces")
        report.pass_("collector OTLP HTTP")
        _check_backend_data(mode, report)
        _check_grafana(report)
        if mode == "evaluation":
            _check_phoenix(report)
        _check_collector_logs(mode, report)
        _verify_named_volumes(mode, report)
        if verify_persistence:
            _restart_and_verify(mode, report)
        else:
            report.skip(
                "named-volume persistence after restart",
                "run again with --persistence-check when restart durability must be verified",
            )
    except Exception as exc:  # noqa: BLE001
        report.fail("smoke execution", str(exc))
    finally:
        report.write(report_path)
    if report.failed:
        raise RuntimeError(f"{mode} smoke test failed")
    print(f"PASS: {mode} smoke and privacy assertions")


def print_urls(mode: str) -> None:
    print("Local endpoints:")
    for name, value in urls(mode).items():
        print(f"  {name:12} {value}")


def up(mode: str) -> None:
    require_env_file()
    load_env_file()
    if os.getenv("GRAFANA_ADMIN_PASSWORD", "") == "change-me-local-only":
        print(
            "WARN: GRAFANA_ADMIN_PASSWORD still uses the local example value",
            file=sys.stderr,
        )
    if (
        mode == "evaluation"
        and os.getenv("PHOENIX_POSTGRES_PASSWORD", "")
        == "change-me-local-only"
    ):
        print(
            "WARN: PHOENIX_POSTGRES_PASSWORD still uses the local example value",
            file=sys.stderr,
        )
    errors = static_validate()
    if errors:
        raise RuntimeError("source validation failed:\n- " + "\n- ".join(errors))
    compose = require_compose()
    check = subprocess.run(
        compose + compose_args(mode) + ["config", "--quiet"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if check.returncode:
        detail = check.stderr.strip() or check.stdout.strip()
        raise RuntimeError(f"Compose config is invalid: {detail}")
    compose_command(mode, ["up", "-d", "--remove-orphans"])
    wait_stack(mode)
    print_urls(mode)


def down(mode: str) -> None:
    compose_command(mode, ["down", "--remove-orphans"])
    print(
        "Named volumes were retained. Use reset-data only when destructive deletion is intended."
    )


def status(mode: str) -> None:
    compose_command(mode, ["ps"])
    print_urls(mode)
    print("Readiness:")
    for name, url in urls(mode).items():
        if name.startswith("OTLP"):
            continue
        health_url = url
        if name == "Prometheus":
            health_url += "/-/ready"
        elif name == "Loki":
            health_url += "/ready"
        elif name == "Tempo":
            health_url += "/ready"
        elif name == "Grafana":
            health_url += "/api/health"
        elif name == "Phoenix":
            health_url += "/healthz"
        try:
            code, _ = http("GET", health_url, timeout=3)
            print(f"  {name:12} HTTP {code}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:12} unavailable: {exc}")
    logs = compose_command(
        mode,
        ["logs", "--since", "15m", "--no-color", "otel-collector"],
        capture=True,
    )
    suspicious = [
        line
        for line in (logs.stdout + logs.stderr).splitlines()
        if re.search(
            r"(?i)\b(error|failed|retry|refused|timeout|dropped)\b", line
        )
    ]
    print("Recent Collector exporter/error summary:")
    if suspicious:
        for line in suspicious[-20:]:
            print("  " + line[:500])
    else:
        print("  none found in the last 15 minutes")


def reset(mode: str, confirmation: str | None) -> None:
    expected = project_name()
    if confirmation != expected:
        raise RuntimeError(
            "destructive reset refused. Re-run with "
            f"--confirm {expected!r} to delete only this Compose project's volumes"
        )
    docker = shutil.which("docker")
    if docker:
        listing = subprocess.run(
            [
                docker,
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={expected}",
                "--format",
                "{{.Name}}",
            ],
            capture_output=True,
            text=True,
        )
        print("Volumes scheduled for deletion:")
        print(listing.stdout.strip() or "  (none currently found)")
    compose_command(mode, ["down", "--volumes", "--remove-orphans"])
    print(f"Deleted volumes belonging to Compose project {expected!r}.")


def resource_snapshot(mode: str, output: Path | None = None) -> Path:
    compose = require_compose()
    load_env_file()
    docker = shutil.which("docker")
    assert docker
    compose_version = subprocess.run(
        compose + ["version", "--short"], capture_output=True, text=True
    )
    docker_version = subprocess.run(
        [docker, "version", "--format", "{{json .}}"],
        capture_output=True,
        text=True,
    )
    ids = subprocess.run(
        compose + compose_args(mode) + ["ps", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    container_ids = [line.strip() for line in ids.stdout.splitlines() if line.strip()]
    stats: list[dict[str, Any]] = []
    if container_ids:
        result = subprocess.run(
            [docker, "stats", "--no-stream", "--format", "{{json .}}", *container_ids],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            try:
                stats.append(json.loads(line))
            except json.JSONDecodeError:
                stats.append({"raw": line})
    images = subprocess.run(
        compose + compose_args(mode) + ["images", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    docker_detail: Any = docker_version.stderr.strip()
    if docker_version.returncode == 0 and docker_version.stdout.strip():
        docker_detail = json.loads(docker_version.stdout)
    payload = {
        "schema_version": "1.0",
        "captured_at": utc_now(),
        "mode": mode,
        "compose_project": project_name(),
        "docker_version": docker_detail,
        "compose_version": (
            compose_version.stdout.strip() or compose_version.stderr.strip()
        ),
        "images": images.stdout.strip(),
        "container_stats": stats,
    }
    if output is None:
        directory = ROOT / "artifacts/resource-snapshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{timestamp_slug()}-{mode}.json"
    else:
        path = output if output.is_absolute() else ROOT / output
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"SNAPSHOT: {display_path(path)}")
    return path


def validate(mode: str, *, static_only: bool) -> None:
    errors = static_validate()
    if not static_only:
        errors.extend(external_validate(mode))
    if errors:
        for error in errors:
            print("ERROR:", error, file=sys.stderr)
        raise RuntimeError(f"validation failed with {len(errors)} error(s)")
    print("PASS: repository configuration and policy validation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument(
        "--mode", choices=["all", *sorted(MODES)], default="all"
    )
    validate_parser.add_argument("--static-only", action="store_true")

    for name in ["up", "down", "status", "wait"]:
        command = sub.add_parser(name)
        command.add_argument("--mode", choices=sorted(MODES), default="core")

    snapshot_parser = sub.add_parser("snapshot")
    snapshot_parser.add_argument("--mode", choices=sorted(MODES), default="core")
    snapshot_parser.add_argument(
        "--output",
        type=Path,
        help="Write the resource snapshot to this repository-relative or absolute path.",
    )

    smoke_parser = sub.add_parser("smoke")
    smoke_parser.add_argument("--mode", choices=sorted(MODES), default="core")
    persistence_group = smoke_parser.add_mutually_exclusive_group()
    persistence_group.add_argument(
        "--persistence-check",
        action="store_true",
        help="Restart the stack and verify that named-volume data remains queryable.",
    )
    persistence_group.add_argument(
        "--skip-persistence",
        action="store_true",
        help=(
            "Compatibility flag that explicitly keeps the quick non-restart smoke mode; "
            "the persistence assertion is recorded as SKIP, never PASS."
        ),
    )
    smoke_parser.add_argument(
        "--report",
        type=Path,
        help="Write the smoke report to this repository-relative or absolute path.",
    )

    annotations_parser = sub.add_parser("phoenix-annotations")
    annotations_parser.add_argument(
        "--project", required=True, help="Phoenix project name or ID to receive the rubric."
    )
    annotations_parser.add_argument(
        "--apply",
        action="store_true",
        help="Create or update configs and assign them; without this flag the command is read-only.",
    )

    reset_parser = sub.add_parser("reset")
    reset_parser.add_argument("--mode", choices=sorted(MODES), default="core")
    reset_parser.add_argument("--confirm")

    args = parser.parse_args()
    try:
        if args.command == "validate":
            validate(args.mode, static_only=args.static_only)
        elif args.command == "up":
            up(args.mode)
        elif args.command == "down":
            down(args.mode)
        elif args.command == "status":
            status(args.mode)
        elif args.command == "wait":
            wait_stack(args.mode)
        elif args.command == "smoke":
            smoke(
                args.mode,
                verify_persistence=args.persistence_check,
                report_path=args.report,
            )
        elif args.command == "reset":
            reset(args.mode, args.confirm)
        elif args.command == "snapshot":
            resource_snapshot(args.mode, args.output)
        elif args.command == "phoenix-annotations":
            phoenix_annotations(args.project, apply=args.apply)
        return 0
    except (
        RuntimeError,
        urllib.error.URLError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
