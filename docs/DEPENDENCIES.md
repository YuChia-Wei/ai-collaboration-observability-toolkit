# Dependency inventory

## v0.1.3 dependency impact

Version 0.1.3 adds no container image or Python package dependency. It uses the
already pinned Collector 0.158.0 transform processor copy_metric operation and
the existing Grafana/Prometheus/Loki/Tempo/Phoenix images. The Antigravity
exporter remains Python-standard-library only. The Codex fixture is replayed
through OTLP/HTTP by the existing toolkit.

Pins were reviewed on 2026-08-07. Every Compose image expression contains an exact committed default;
`.env.example`, `scripts/toolkit.py`, and repository tests assert the same value. A controlled image
override remains possible, but floating tags and unmatched defaults fail validation.

| Component | Committed image/version | License | Role | Selection notes |
| --- | --- | --- | --- | --- |
| OpenTelemetry Collector Contrib | `otel/opentelemetry-collector-contrib:0.158.0` | Apache-2.0 | OTLP ingress, minimization, cardinality, routing | Pinned Collector Contrib baseline used by the repository validation and routing profiles |
| Prometheus | `prom/prometheus:v3.13.2` | Apache-2.0 | Metrics store/query | Pinned metrics baseline; validate migration notes before changing major or minor versions |
| Loki | `grafana/loki:3.7.6` | AGPL-3.0 | Native OTLP log store/query | Uses filesystem TSDB v13 and structured metadata |
| Tempo | `grafana/tempo:3.0.2` | AGPL-3.0 | Trace store/query | Uses the Tempo 3 monolithic local-storage configuration |
| Grafana | `grafana/grafana:13.1.3` | AGPL-3.0 | Dashboards and cross-signal exploration | Provisioned datasources/dashboards; no floating plugin installation |
| Phoenix | `arizephoenix/phoenix:version-19.19.0-nonroot` | Elastic License 2.0 | Optional AI trace evaluation | Evaluation receives minimized traces by default with explicit opt-out |
| PostgreSQL | `postgres:18.4-alpine3.24` | PostgreSQL License | Phoenix persistence | Exact image tag; PostgreSQL 18 data volume mounts at `/var/lib/postgresql` |
| PyYAML | `6.0.3` | MIT | YAML parsing and duplicate-key/policy validation | Pinned in `requirements.txt` |
| jsonschema | `4.26.0` | MIT | Feedback-bundle schema validation | Pinned in `requirements.txt` |

## Official references

- OpenTelemetry Collector releases: <https://github.com/open-telemetry/opentelemetry-collector-releases>
- Prometheus releases and LTS policy: <https://github.com/prometheus/prometheus/releases> and
  <https://prometheus.io/docs/introduction/release-cycle/>
- Loki releases: <https://github.com/grafana/loki/releases>
- Tempo releases: <https://github.com/grafana/tempo/releases>
- Grafana releases: <https://github.com/grafana/grafana/releases>
- Phoenix releases and self-hosted image tags: <https://github.com/Arize-ai/phoenix/releases> and
  <https://arize.com/docs/phoenix/self-hosting>
- PostgreSQL official image metadata: <https://github.com/docker-library/official-images/blob/master/library/postgres>

## Update policy

1. Never use `latest`, `edge`, or `nightly`. Image expressions may use only the reviewed `${VAR:-exact-image:tag}` form.
2. Update the Compose default, matching `.env.example` value, `scripts/toolkit.py::EXACT_IMAGES`, this inventory, and tests in one change.
3. Prefer stable releases; preview/RC versions require a recorded ADR or implementation-report reason.
4. Review migration notes and image-platform compatibility before changing a pin.
5. Run all Collector native validations and core runtime smoke/persistence tests.
6. Run evaluation and corporate runtime smoke tests before a tagged release.
7. Record unexecuted checks as `NOT EXECUTED`; never infer compatibility from YAML parsing alone.

This toolkit does not vendor component binaries or container images.
CI uses the Docker Compose plugin provided by the GitHub-hosted runner and validates component
configuration with the exact pinned container images above.

## Antigravity local exporters

`examples/antigravity/antigravity_otel_exporter.py` uses only the Python standard library. It does not
add a package dependency to the observability containers. Python is required only on the host running
the optional Antigravity Hook/status-line bridge; no `pip install` is required for this exporter.
