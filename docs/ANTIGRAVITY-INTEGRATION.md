# Google Antigravity integration

## Decision

The toolkit does not assume a native Antigravity OTLP exporter. The documented local extension point is JSON Hooks, packaged either at workspace level under `.agents/plugins/` or globally under `~/.gemini/config/plugins/`.

The committed example therefore implements a small standard-library Python bridge:

```text
Antigravity JSON Hooks
        │ metadata-only stdin JSON
        ▼
examples/antigravity/plugin/scripts/emit_otel.py
        │ OTLP/HTTP JSON
        ▼
127.0.0.1:4318 OpenTelemetry Collector
        ├─ Loki
        ├─ Tempo
        └─ Collector privacy/allowlist processors
```

Antigravity's Account `Enable Telemetry` setting controls product data sharing with Google. It is not a local Collector endpoint and is independent from this plugin.

## Hook selection

The example enables:

- `PreInvocation`: records a local start timestamp only;
- `PostInvocation`: emits a completed model-invocation span and metadata log;
- `PostToolUse`: emits a metadata log for an approved bounded operation category;
- `Stop`: emits the overall agent-session span and terminal metadata log.

It intentionally excludes `PreToolUse`. That event requires a permission decision, so using it for passive measurement could change the user's existing allow/ask/deny behavior. The default integration prioritizes non-interference over exact tool timing.

## Privacy contract

The bridge consumes the official common fields but does not export or inspect:

- `workspacePaths`;
- `transcriptPath` contents;
- `artifactDirectoryPath` contents;
- tool arguments or output;
- raw error strings;
- raw `conversationId`.

A local random HMAC key derives stable trace/span identifiers. The key remains in the OS user state directory and is not sent to the Collector. The Collector still applies the selected core or corporate policy before backend fan-out.

## Signals

### Logs

Events include:

- `antigravity.model.invocation.completed`;
- `antigravity.tool.completed`;
- `antigravity.agent.stopped`.

The log body is always the constant `AI telemetry metadata event`.

### Traces

- `antigravity.agent.session` is the session/root span;
- `antigravity.model.invocation` spans use the session span as parent;
- tool completion is represented as a log only because the passive `PostToolUse` payload has no start timestamp.

### Metrics

The bridge does not emit metrics in version 0.1.1. Counts and duration distributions can initially be derived from Loki/Tempo. Native Antigravity token and credit data are not present in the documented hook payload.

## Configuration

The bridge accepts the standard base endpoint `OTEL_EXPORTER_OTLP_ENDPOINT` and prefers `AI_OBSERVABILITY_OTLP_HTTP_ENDPOINT` when both are set. The endpoint must be HTTP(S); signal paths are appended automatically.

All exports are best-effort with a short timeout. Failures are swallowed and hook responses remain valid so observability cannot block normal agent operation.

## Compatibility maintenance

After an Antigravity upgrade:

1. compare the official JSON Hooks schema and supported tool list;
2. run a synthetic task in core mode;
3. verify model/session traces and each operation category;
4. inspect the Collector and backend data for unexpected attributes;
5. rerun corporate mode before company use;
6. do not add transcript parsing merely to populate a dashboard.

## Official references

- Hooks: `https://www.antigravity.google/docs/hooks`
- Plugins: `https://www.antigravity.google/docs/plugins`
- Settings and account telemetry: `https://www.antigravity.google/docs/settings`
- CLI credits: `https://www.antigravity.google/docs/cli/credits`
