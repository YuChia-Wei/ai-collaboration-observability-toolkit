# Architecture

## Purpose

This toolkit supplies a stable telemetry boundary for observing AI-assisted software development. It
separates three concerns that are often incorrectly combined:

1. **Execution evidence** — latency, waits, retries, validation, tool activity, and platform health.
2. **AI-agent usage evidence** — provider-reported or locally observed token,
   latency, tool, and lifecycle signals without inferred cost.
3. **Improvement evidence** — human annotations, evaluators, datasets, and experiments comparing AI
   collaboration framework versions.

## Component topology

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Senders                                                             │
│ Codex CLI · Claude Code · Copilot · .NET apps · ai-context hooks   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ OTLP/gRPC :4317 or OTLP/HTTP :4318
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ OpenTelemetry Collector                                             │
│ receive → memory limit → redact → normalize → backend policy → batch │
└───────────────┬───────────────────┬─────────────────────┬───────────┘
                │                   │                     │
                ▼                   ▼                     ▼
          Prometheus             Loki                  Tempo
           metrics                logs                  traces
                └───────────────────┬─────────────────────┘
                                    ▼
                                  Grafana

Evaluation mode only:
minimized traces → OpenInference compatibility filter → default-on header/resource routing → Phoenix → PostgreSQL
```

## Deployment modes

### Core

- Five local services: Collector, Prometheus, Loki, Tempo, Grafana.
- Privacy-filtered native and canonical telemetry are queried through Grafana.

Core is a private-laboratory baseline, not a proof that an unknown future client field is safe. A
client upgrade requires the sentinel smoke test and representative metadata inspection.

### Evaluation

- Core plus optional Phoenix/PostgreSQL for OpenInference trace annotation.
- Generic spans stay in Tempo; header/resource opt-outs remain supported.

### Corporate

- Uses the same local LGTM services, but replaces the Collector configuration.
- It does **not** rely on the personal-mode denylist as its authoritative control.
- A strict `keep_keys` allowlist removes every unapproved resource, span, event, log, and metric
  attribute.
- Span and event names are replaced with fixed operation markers.
- Log bodies are replaced with `AI telemetry metadata event`.
- Phoenix and all Internet/external exporters are absent.
- Unknown fields fail closed by being dropped.
- Source archive pipelines and source exporters are absent.

These modes are intentionally mutually exclusive. Running multiple mode overrides over the same
published ports creates ambiguous data-governance semantics and is unsupported.

## Network boundaries

All host-published ports bind to loopback. Only Collector is host-facing OTLP
ingress. Grafana accesses internal backends; direct backend APIs require the
explicit debug overlay. No multi-user gateway or network authentication is supplied.

## Storage and retention

| Signal/system | Store | Default retention or lifecycle |
| --- | --- | --- |
| Metrics | Prometheus TSDB | 14 days (`PROMETHEUS_RETENTION`) |
| Logs | Loki filesystem TSDB | 14 days (`336h`) |
| Traces | Tempo local blocks/WAL | 14 days (`336h`) |
| Dashboards/users | Grafana SQLite volume | Persistent until intentional reset |
| Evaluations | Phoenix PostgreSQL | Persistent until intentional reset |

The defaults target one workstation, not production. `down` retains named volumes. `reset` destroys
them only when the caller supplies the exact Compose project name.

## Cardinality policy

Prometheus labels and Loki index labels must remain low-cardinality. Session, prompt, conversation,
request, trace/span, tool-call, workflow UUID, validation fingerprint, commit, branch, path, and user
identifiers are removed from metric datapoint attributes before export.

Loki indexes only:

- `service.name`
- `service.namespace`
- `deployment.environment.name`
- `ai_context.environment.profile`

Other permitted log fields remain structured metadata. High-cardinality workflow evidence belongs in
traces or a future purpose-built usage ledger, not in a metrics index.

## Reliability model

The Collector enables memory limiting, batching, retry-on-failure, and bounded sending queues. This
protects short backend restarts but is not a durable message queue. A workstation shutdown can lose
buffered telemetry. Durable offline corporate export is a roadmap item and must use a separately
reviewed, versioned feedback-bundle contract.

## Telemetry contract layers

The Collector separates three layers:

1. privacy-filtered native provider signals such as codex.* and antigravity_*;
2. canonical ai_agent.* copies for bounded cross-agent usage analysis;
3. independently emitted ai_context.* framework/workflow evidence (contract
   reserved; no production emitter or dashboard currently exists).

Canonicalization runs after an initial denylist and before the final
mode-specific privacy policy. This lets the normalizer derive bounded
categories without permitting raw model, tool, content, identifier, or path
fields to escape. Native and canonical metrics are both retained, but
dashboards never use fallback expressions across contract layers.

## Why not one all-in-one backend

The first objective is to retain the known Grafana operating model while adding a small Phoenix
experiment surface. Replacing LGTM with SigNoz, ClickStack, or OpenObserve would combine a backend
migration with the telemetry-contract experiment and make improvements difficult to attribute. The
Collector boundary keeps those comparisons possible later without changing every sender.


## v0.2.0 storage and resource boundary

No source archive or JSONL duplication runs in any mode. Historical archive
volumes are preserved until separately reviewed for export/deletion. Collector
privacy and native/canonical analytical pipelines remain in place. Corporate
uses five services with bounded memory, 7-day/1GB Prometheus block retention,
and 72-hour log/trace retention; see [company operation](COMPANY-LOW-RESOURCE.md).

Core/Evaluation bound Claude `skill.name` to `none`, `code-reviewer`, or `other`
and MCP server/tool names to `none` or `custom` before canonical copying.
Corporate removes these attribution dimensions. Unknown skill names become
`other`; arbitrary MCP names become `custom`, including on native metrics.
