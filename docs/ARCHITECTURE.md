# Architecture

## Purpose

This toolkit supplies a stable telemetry boundary for observing AI-assisted software development. It
separates three concerns that are often incorrectly combined:

1. **Execution evidence** — latency, waits, retries, validation, tool activity, and platform health.
2. **AI-agent usage evidence** — provider-reported or locally observed token,
   latency, tool, and lifecycle signals without inferred cost.
3. **Improvement evidence** — human annotations, evaluators, datasets, and experiments comparing AI
   collaboration framework versions.

Grafana LGTM is the execution/usage layer. Phoenix is an optional improvement layer. The
OpenTelemetry Collector is the canonical host ingress and backend analysis policy
boundary. An internal source archive service separately redacts received OTLP
records before local persistence.

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

Core/Evaluation, from the same OTLP receiver, before backend transforms:
receive → memory limit → additive metadata → internal source-archive service
                                            recursive privacy → local OTLP JSONL
                                                                (collector-source-data)
```

## Deployment modes

### Core

- General local development and framework observation.
- All three signals flow to the LGTM backends.
- All three signals also flow to independent source archive pipelines, enabled
  automatically. They retain privacy-filtered OTLP JSONL before canonical
  mapping, metric label reduction, or backend conversion.
- Phoenix is absent.
- Known content-bearing attributes are removed.
- Log bodies are replaced with a constant metadata marker before Loki export.
- Span names retain operational meaning, but obvious absolute paths and secret-shaped fragments are
  replaced.

Core is a private-laboratory baseline, not a proof that an unknown future client field is safe. A
client upgrade requires the sentinel smoke test and representative metadata inspection.

### Evaluation

- Adds Phoenix and PostgreSQL.
- Includes the same source archive as Core. Evaluation adds analysis features;
  it is not an option to capture unredacted content or all workstation data.
- Every minimized trace still reaches Tempo.
- Minimized spans that declare `openinference.span.kind` reach Phoenix by default.
  Generic/internal spans remain in Tempo because Phoenix cannot infer LLM or
  evaluation semantics from them. The OTLP header
  `x-ai-observability-phoenix: false` or legacy boolean resource attribute
  `ai_context.export.phoenix=false` opts out.
- The routing processors run after the same privacy transform used by the Tempo route. Temporary
  header-derived routing metadata is deleted before Phoenix export.
- Runtime smoke verifies missing-header, header-true, and header-false semantic
  traces in Tempo and confirms only the first two through Phoenix's project span
  API. Legacy resource true/false remains covered, and a generic trace is
  required in Tempo but absent from Phoenix.

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
- The shared source service may remain idle; switching profiles does not erase
  a previous Core/Evaluation archive.

These modes are intentionally mutually exclusive. Running multiple mode overrides over the same
published ports creates ambiguous data-governance semantics and is unsupported.

## Network boundaries

Every host-published port in committed Compose is explicitly bound to `127.0.0.1`. Container-to-
container communication uses the private `observability` bridge. The toolkit does not provide an
authentication gateway or TLS for network exposure. Editing Compose to bind a service to `0.0.0.0`
without adding those controls is a security exception, not a normal configuration change.

Only the Collector publishes OTLP ports to the host. Tempo, Phoenix, and
`source-archive:4320` receivers are internal to the Compose network. Host tools
must use the Collector endpoint. The source service handles the unnormalized
copy inside that private network and recursively redacts it before writing any
archive record; the backend analysis routes retain their Collector transforms.

## Storage and retention

| Signal/system | Store | Default retention or lifecycle |
| --- | --- | --- |
| Source logs/metrics/traces (Core/Evaluation) | `collector-source-data`, OTLP JSONL | Append on restart; no automatic expiration, rotation, or deletion |
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

These index restrictions apply to backend projections, not the source archive.
The archive keeps safe unknown dimensions and original histogram points so a
future analysis does not depend on today's metric allowlist or mapping. Privacy
redaction still removes sensitive attributes before any source file is written.

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

The internal source service preserves data before backend-specific transformations
and appends privacy-filtered JSONL with filesystem sync. It does not provide
a durable ingestion acknowledgement protocol or unlimited storage. Disk full,
memory pressure, privacy transform errors, transport failures, and process
crashes can still prevent retention. Source files have no TTL or automatic
rotation; monitor disk use and explicitly export or maintain them. The source
exporter's sending queue is disabled; it does not persist unredacted pending
requests. A backend retention window does not prune this volume.

The source service bounds individual requests to 16 MiB, recursive processing to
64 levels, and active ingestion to eight requests. Invalid or oversized
requests fail rather than bypass redaction. Collector retries are bounded; an
archive failure is not an unlimited offline spool.

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

In Core/Evaluation a separate source archive sits beside these analysis layers.
It requires no known provider or canonical mapping and receives the OTLP input
before normalization. Additive provenance metadata precedes the private source
service, whose recursive sanitizer runs before file append. The source and canonical views are independent
copies; adding a mapping later does not require changing the archive's accepted
signal names. The archive is forward-only and cannot restore previously dropped
or never-sent data.

The only host-facing telemetry ingress remains the OpenTelemetry Collector.
Phoenix is not an ingress and receives already-redacted, OpenInference-compatible
Evaluation spans under the default-on routing contract. Tempo remains the general
minimized trace query backend; the source archive also retains generic and
Phoenix-opted-out spans after its privacy transform.

## Why not one all-in-one backend

The first objective is to retain the known Grafana operating model while adding a small Phoenix
experiment surface. Replacing LGTM with SigNoz, ClickStack, or OpenObserve would combine a backend
migration with the telemetry-contract experiment and make improvements difficult to attribute. The
Collector boundary keeps those comparisons possible later without changing every sender.
