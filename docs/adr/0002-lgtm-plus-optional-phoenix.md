# ADR 0002: Retain LGTM and add Phoenix as an optional evaluation layer

- Status: Accepted
- Date: 2026-08-07

## Decision

Prometheus, Loki, Tempo, and Grafana remain the primary execution evidence system. Phoenix is enabled
only in evaluation mode and receives explicit curated traces.

## Rationale

LGTM is already understood and covers host/platform/workflow evidence. Phoenix supplies annotations,
evaluators, datasets, and experiments without forcing a storage/UI migration.

## Consequences

Some information exists in both Tempo and Phoenix. Selection and privacy require negative routing
tests. Phoenix is not deployed on every corporate workstation.
