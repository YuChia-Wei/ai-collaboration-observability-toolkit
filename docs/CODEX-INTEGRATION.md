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
