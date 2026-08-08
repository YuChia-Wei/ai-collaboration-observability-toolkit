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
MODES = {"core", "evaluation", "corporate"}
PHOENIX_PROJECT = "ai-collaboration-observability-fixture"
TRACE_CORE = "11111111111111111111111111111111"
TRACE_SELECTED = "22222222222222222222222222222222"
TRACE_REJECTED = "33333333333333333333333333333333"
EXACT_IMAGES = {
    "otel-collector": "otel/opentelemetry-collector-contrib:0.158.0",
    "prometheus": "prom/prometheus:v3.13.2",
    "loki": "grafana/loki:3.7.6",
    "tempo": "grafana/tempo:3.0.2",
    "grafana": "grafana/grafana:13.1.3",
    "postgres": "postgres:18.4-alpine3.24",
    "phoenix": "arizephoenix/phoenix:version-19.19.0-nonroot",
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
    "docs/COST-ATTRIBUTION.md",
    "docs/DEPENDENCIES.md",
    "docs/RESOURCE-BASELINE.md",
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
    if "filter/phoenix-selected" not in evaluation.get("processors", {}):
        errors.append("Evaluation Collector is missing the Phoenix selection filter")
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

    if (
        evaluation.get("processors", {})
        .get("filter/phoenix-selected", {})
        .get("error_mode")
        != "propagate"
    ):
        errors.append(
            "Evaluation Collector Phoenix selection must fail closed with error_mode=propagate"
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
        "transform/privacy",
        "filter/phoenix-selected",
        "batch/phoenix",
    ]
    if phoenix_processors != required_order:
        errors.append(
            "Evaluation Collector: traces/phoenix processor order must redact before selection and batching; "
            f"found={phoenix_processors}"
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
        if 'SCOPE_VERSION = "0.1.2"' not in exporter_text:
            errors.append("Antigravity exporter: scope version must match Repository version")

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

    for path in sorted((ROOT / "scripts").glob("*.sh")):
        bash = shutil.which("bash")
        if bash:
            result = subprocess.run(
                [bash, "-n", path.relative_to(ROOT).as_posix()],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if result.returncode:
                errors.append(f"Bash {path.name}: {result.stderr.strip()}")
    for python_path in (
        ROOT / "scripts/toolkit.py",
        ROOT / "examples/antigravity/antigravity_otel_exporter.py",
    ):
        python_check = subprocess.run(
            [sys.executable, "-m", "py_compile", str(python_path)],
            capture_output=True,
            text=True,
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
                "-config.verify",
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


def send_fixture(filename: str, signal: str) -> None:
    port = os.getenv("OTLP_HTTP_PORT", "4318")
    data = render_fixture(ROOT / "examples/otlp" / filename)
    status, body = http(
        "POST",
        f"http://127.0.0.1:{port}/v1/{signal}",
        data,
        {"Content-Type": "application/json"},
    )
    if status not in {200, 202}:
        raise RuntimeError(
            f"OTLP {filename} failed: HTTP {status} "
            f"{body.decode(errors='replace')}"
        )
    print(f"SENT: {filename}")


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


def loki_query() -> tuple[dict[str, Any], bytes]:
    port = os.getenv("LOKI_PORT", "3100")
    params = urllib.parse.urlencode(
        {
            "query": '{service_name="ai-observability-fixture"}',
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
    metric_results = retry(
        "Prometheus smoke metric",
        lambda: prometheus_query("ai_context_token_usage_total"),
        bool,
    )
    report.pass_(prefix + "prometheus metric", f"series={len(metric_results)}")
    series = prometheus_series("ai_context_token_usage_total")
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

    status, body = retry(
        "Tempo core trace",
        lambda: tempo_trace(TRACE_CORE),
        lambda value: value[0] == 200,
    )
    if SENTINEL.encode() in body:
        raise RuntimeError("privacy sentinel leaked into Tempo core trace")
    report.pass_(prefix + "tempo core trace")

    if mode == "evaluation":
        for trace_id, label in [
            (TRACE_SELECTED, "selected trace"),
            (TRACE_REJECTED, "rejected trace"),
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


def _check_phoenix(report: SmokeReport, prefix: str = "") -> None:
    selected = retry(
        "Phoenix selected trace",
        lambda: phoenix_spans(TRACE_SELECTED),
        lambda value: value[0] == 200 and TRACE_SELECTED.encode() in value[2],
    )
    if SENTINEL.encode() in selected[2]:
        raise RuntimeError("privacy sentinel leaked into Phoenix selected trace")
    report.pass_(prefix + "phoenix selected trace")

    rejected = retry(
        "Phoenix rejected trace query",
        lambda: phoenix_spans(TRACE_REJECTED),
        lambda value: value[0] == 200,
    )
    if TRACE_REJECTED.encode() in rejected[2]:
        raise RuntimeError("Phoenix received the explicitly rejected trace")
    if SENTINEL.encode() in rejected[2]:
        raise RuntimeError("privacy sentinel leaked into Phoenix")
    report.pass_(prefix + "phoenix rejected trace absent")


def _check_collector_logs(mode: str, report: SmokeReport) -> None:
    result = compose_command(
        mode, ["logs", "--no-color", "otel-collector"], capture=True
    )
    text = result.stdout + result.stderr
    if SENTINEL in text:
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
        send_fixture("traces.json", "traces")
        if mode == "evaluation":
            send_fixture("phoenix-rejected-trace.json", "traces")
            send_fixture("phoenix-selected-trace.json", "traces")
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
