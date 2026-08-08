# Validation report

## Metadata

- Version: 0.1.3
- Date: 2026-08-09
- Host: Windows, PowerShell, Python 3.13.14
- Docker: 29.6.2
- Docker Compose: v5.3.1

## Result summary

| Gate | Result | Evidence |
| --- | --- | --- |
| Static repository policy | PASS | toolkit validate --mode all --static-only |
| Python unit tests | PASS | 34 discovered: 33 passed, 1 Windows-only POSIX executable-bit check skipped |
| Bash syntax | PASS | WSL bash -n scripts/*.sh |
| PowerShell parser | PASS | toolkit full validation |
| Compose merged config | PASS | Core, Corporate, Evaluation |
| Collector native config | PASS | pinned 0.158.0 image; Core, Evaluation, Corporate |
| Prometheus native config | PASS | promtool from pinned 3.13.2 image |
| Loki native config | PASS | pinned 3.7.6 verify-config |
| Tempo native config | PASS | pinned 3.0.2 config.verify=true |
| Evaluation readiness | PASS | Collector, Prometheus, Loki, Tempo, Grafana, Postgres/Phoenix |
| Evaluation OTLP and privacy | PASS | Legacy and Codex logs/metrics/traces accepted; sentinels absent |
| Native/canonical reconciliation | PASS | Codex token histogram raw_sum 1536 equals canonical_sum 1536 |
| Grafana | PASS | Three datasources healthy; both v0.1.3 dashboard UIDs/titles loaded |
| Phoenix routing | PASS | Selected trace present; rejected trace absent |
| Evaluation persistence | PASS | Five named volumes present and data queryable after restart |
| Corporate isolation | PASS | Alternate ports/project, five services, no Phoenix |
| Corporate privacy/persistence | PASS | Same Codex reconciliation/privacy checks passed after restart |
| Corporate test cleanup | PASS | Exact test containers, network, and four test volumes removed |
| Codex sender config | PASS (file) | Backup exists; one-line change; three loopback endpoints verified |
| Codex restart acceptance | NOT EXECUTED | Owner restart required; active process intentionally not terminated |
| Historical data erasure | NOT EXECUTED | Destructive cleanup not authorized and not required for forward policy |
| Hosted PR CI | PENDING | Recorded after pull request creation |

## Evaluation runtime assertions

- Stack readiness passed for every service.
- Raw and canonical Codex token histogram sums reconciled exactly.
- Forbidden Codex resource/datapoint attributes and the fixture sentinel did
  not appear in the new Prometheus series metadata.
- The Codex log privacy window was present in Loki without the sentinel.
- The Codex trace was present in Tempo without the sentinel.
- Codex Native Telemetry loaded at UID ai-codex-usage.
- AI Agent Usage loaded at UID ai-agent-usage.
- Phoenix accepted only the explicitly selected fixture.
- All checks repeated successfully after service restart.

Structured local reports were written to:

- artifacts/smoke/v0.1.3-evaluation.json
- artifacts/smoke/v0.1.3-corporate.json

The artifacts directory is intentionally ignored; this document records the
release evidence without committing runtime-local details.

## Native validator commands

    docker run --rm --volume <repo>/config/otel-collector:/etc/otelcol:ro \
      otel/opentelemetry-collector-contrib:0.158.0 \
      validate --config=/etc/otelcol/<mode>.yaml

    docker run --rm --entrypoint=/bin/promtool \
      --volume <repo>/config/prometheus:/etc/prometheus:ro \
      prom/prometheus:v3.13.2 check config /etc/prometheus/prometheus.yml

    docker run --rm --volume <repo>/config/loki:/etc/loki:ro \
      grafana/loki:3.7.6 -config.file=/etc/loki/loki.yml -verify-config=true

    docker run --rm --volume <repo>/config/tempo:/etc/tempo:ro \
      grafana/tempo:3.0.2 -config.file=/etc/tempo/tempo.yml -config.verify=true

## Release blockers

Local implementation/runtime blockers are closed. Hosted CI, merge, annotated
tag, GitHub Release, Project read-back, and deployment from merged main remain
release-sequence gates and must not be reported as complete before they occur.
