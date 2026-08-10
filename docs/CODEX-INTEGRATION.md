# Codex CLI integration

## Configuration location

Use the user-level configuration because Codex OpenTelemetry settings are not intended to be silently
overridden by an arbitrary project:

- Windows: `%USERPROFILE%\.codex\config.toml`
- WSL/Linux/macOS: `~/.codex/config.toml`

Merge, do not replace, the example:

```toml
[otel]
environment = "personal-local"
log_user_prompt = false
exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "binary" } }
trace_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/traces", protocol = "binary" } }
metrics_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/metrics", protocol = "binary" } }
```

The current Codex configuration resolves logs, traces, and metrics independently; metrics otherwise
may use a different default exporter. Explicitly setting all three prevents a false assumption that
one endpoint covers every signal.

Evaluation sends privacy-safe traces to Phoenix by default. To opt all Codex traces out, add
`headers = { "x-ai-observability-phoenix" = "false" }` inside the `otlp-http` trace exporter table.
Codex does not apply `[otel]` from project-local `.codex/config.toml`, so this is a user-level setting;
per-project routing requires a producer that can attach the header or legacy resource attribute.

## Privacy

`log_user_prompt=false` is mandatory but insufficient. Client versions may add new tool or event
attributes, so the Collector performs content-field deletion and value redaction. Run the sentinel
smoke test after a Codex upgrade.

## Verification

1. Start core mode.
2. Merge the config and restart Codex.
3. Begin a new Codex session and perform a small read-only task.
4. In Grafana, confirm Collector accepted log/span/metric counters increase.
5. Search Loki and Tempo by `service.name` and inspect only metadata fields.
6. Confirm no prompt, response, command, source, diff, path, email, or secret is present.

Codex native events do not automatically know which AI Context skill/rule/document affected the
work. Framework hooks must add `ai_context.*` evidence separately.

## Corporate mode

Change only the environment classification if desired:

```toml
environment = "corporate-local-redacted"
```

The Collector's corporate allowlist remains authoritative. Do not distribute a configuration that
sends company telemetry to a personal or Internet endpoint.

## Desktop application boundary

Codex CLI telemetry support does not prove ChatGPT Desktop Codex mode uses the same configuration or
event schema. Treat the desktop surface as unsupported until its data path is independently verified.

## Version 0.1.3 tested contract

Version 0.1.3 is verified against Codex CLI 0.146.1 (rust-v0.146.1, commit
79b4f03d35962b005b007a015113b38930711665). The observed app-server resource
reported 0.147.0-alpha.6.5. The versioned privacy-safe replay fixture is under
fixtures/codex/0.146.1.

Codex counters are monotonic OTLP sums and token/duration instruments are OTLP
histograms. The v0.146.1 exporter uses Delta temporality. The Collector copies
metrics so the ai_agent.* form retains the original instrument type and
temporality; Prometheus exposes histogram bucket/count/sum series.

The Collector retains privacy-filtered codex.* telemetry and creates a separate
ai_agent.* copy. Codex 原生 Telemetry keeps native `codex_*` diagnostics and
uses only three narrowly scoped canonical recording metrics for token
accounting, rate-card facts, and estimated cost. AI Agent 用量 queries only
`ai_agent_*`, and AI Context dashboards query only `ai_context_*`. No dashboard
substitutes provider activity for framework evidence.

Exact Codex models are mapped to bounded `model_id` before the raw model label
is removed from the canonical copy. Unknown models become `unmapped` and remain
visible without a price. The estimate uses versioned public API base rates; it
is not Codex subscription/credit/invoice data and does not apply the
greater-than-272K premium because aggregated telemetry cannot identify the
affected requests. Raw `token_type` panels remain available to reconcile the
non-overlapping accounting classes.

Before changing a live Codex configuration, create a same-directory backup.
For this toolkit, change only the [otel] block, keep all three endpoints on the
Collector loopback ports, and set log_user_prompt=false. Restart Codex after
the configuration change; do not terminate an active session merely to apply
telemetry settings.

After any Codex upgrade, record both versions, compare emitted names/kinds/
units/temporality with the fixture, replay all three signals through every
Collector mode, then verify native and canonical histogram sums/counts
reconcile before updating the mapping.
