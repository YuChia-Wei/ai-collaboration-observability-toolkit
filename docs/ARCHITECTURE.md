# Architecture

## Purpose

This toolkit supplies a stable telemetry boundary for observing AI-assisted software development. It
separates three concerns that are often incorrectly combined:

1. **Execution evidence** — latency, waits, retries, validation, tool activity, and platform health.
2. **Usage and cost evidence** — token classes, model/tool attribution, and official-versus-estimated cost.
3. **Improvement evidence** — human annotations, evaluators, datasets, and experiments comparing AI
   collaboration framework versions.

Grafana LGTM is the execution/usage layer. Phoenix is an optional improvement layer. The
OpenTelemetry Collector is the canonical ingress, minimization, cardinality, and routing boundary.

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
│ receive → memory limit → normalize → minimize/allowlist → batch    │
└───────────────┬───────────────────┬─────────────────────┬───────────┘
                │                   │                     │
                ▼                   ▼                     ▼
          Prometheus             Loki                  Tempo
           metrics                logs                  traces
                └───────────────────┬─────────────────────┘
                                    ▼
                                  Grafana

Evaluation mode only:
minimized traces → explicit resource-attribute filter → Phoenix → PostgreSQL
```

## Deployment modes

### Core

- General local development and framework observation.
- All three signals flow to the LGTM backends.
- Phoenix is absent.
- Known content-bearing attributes are removed.
- Log bodies are replaced with a constant metadata marker before Loki export.
- Span names retain operational meaning, but obvious absolute paths and secret-shaped fragments are
  replaced.

Core is a private-laboratory baseline, not a proof that an unknown future client field is safe. A
client upgrade requires the sentinel smoke test and representative metadata inspection.

### Evaluation

- Adds Phoenix and PostgreSQL.
- Every minimized trace still reaches Tempo.
- Only traces whose **resource** contains boolean
  `ai_context.export.phoenix=true` reach Phoenix.
- The selection filter runs after the same privacy transform used by the Tempo route.
- Runtime smoke sends one selected and one rejected trace, confirms both in Tempo, and confirms only
  the selected trace through Phoenix's project trace API.

### Corporate

- Uses the same local LGTM services, but replaces the Collector configuration.
- It does **not** rely on the personal-mode denylist as its authoritative control.
- A strict `keep_keys` allowlist removes every unapproved resource, span, event, log, and metric
  attribute.
- Span and event names are replaced with fixed operation markers.
- Log bodies are replaced with `AI telemetry metadata event`.
- Phoenix and all Internet/external exporters are absent.
- Unknown fields fail closed by being dropped.

These modes are intentionally mutually exclusive. Running multiple mode overrides over the same
published ports creates ambiguous data-governance semantics and is unsupported.

## Network boundaries

Every host-published port in committed Compose is explicitly bound to `127.0.0.1`. Container-to-
container communication uses the private `observability` bridge. The toolkit does not provide an
authentication gateway or TLS for network exposure. Editing Compose to bind a service to `0.0.0.0`
without adding those controls is a security exception, not a normal configuration change.

Only the Collector publishes OTLP ports to the host. Tempo and Phoenix OTLP receivers are internal to
the Compose network, so development tools cannot bypass the Collector policy by using a backend
receiver directly.

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

## Why not one all-in-one backend

The first objective is to retain the known Grafana operating model while adding a small Phoenix
experiment surface. Replacing LGTM with SigNoz, ClickStack, or OpenObserve would combine a backend
migration with the telemetry-contract experiment and make improvements difficult to attribute. The
Collector boundary keeps those comparisons possible later without changing every sender.
