# ADR 0002: Retain LGTM and add Phoenix as an optional evaluation layer

- Status: Accepted
- Date: 2026-08-07

## Decision

Prometheus, Loki, Tempo, and Grafana remain the primary execution evidence system. Phoenix is enabled
only in Evaluation mode. Since v0.1.4, it receives already-redacted traces by default and supports an
explicit OTLP-header or legacy resource-attribute opt-out.

## Rationale

LGTM is already understood and covers host/platform/workflow evidence. Phoenix supplies annotations,
evaluators, datasets, and experiments without forcing a storage/UI migration.

## Consequences

Some information exists in both Tempo and Phoenix. Default and negative routing require runtime
tests, and temporary routing metadata must be removed before export. Phoenix is not deployed on
Corporate workstations.
