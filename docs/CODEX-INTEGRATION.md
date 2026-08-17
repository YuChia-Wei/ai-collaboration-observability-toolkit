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

Evaluation sends privacy-safe spans that already declare `openinference.span.kind`
to Phoenix by default. Generic Codex internal spans remain in Tempo. To opt all
compatible Codex traces out, add `headers = { "x-ai-observability-phoenix" = "false" }`
inside the `otlp-http` trace exporter table.
Codex does not apply `[otel]` from project-local `.codex/config.toml`, so this is a user-level setting;
per-project routing requires a producer that can attach the header or legacy resource attribute.

## Opt-in lifecycle Hooks experiment

Codex CLI 0.146.1 exposes stable lifecycle Hooks. The toolkit's
[`examples/codex-hooks`](../examples/codex-hooks/README.md) experiment uses
`UserPromptSubmit`/`Stop` to create an OpenInference `AGENT` span and
`PreToolUse`/`PostToolUse` to create bounded child `TOOL` spans. These traces go
through the same loopback Collector; no second OTLP ingress is introduced.

The exporter defaults to a strict input allowlist. In `metadata-only` mode it
never reads or persists prompt, assistant message, tool input/response, cwd, or
transcript fields. Raw session, turn, and tool IDs are used only to locate
hashed local state; exported trace and span IDs are newly generated. Tool names
become one of five fixed categories.

### Opt-in size-only prompt measurement

The project-local Hook command can explicitly use `--capture-mode size-only`.
Only for `UserPromptSubmit`, it reads `prompt` in memory to calculate a UTF-8
byte length, then emits the Delta histogram
`ai_agent.observed.user_prompt.bytes`. It never exports the text, a hash, a
path, an ID, tool data, or a per-turn correlation key. The fixed metric
dimensions are `operation=turn`, `evidence_class=observed`,
`content_scope=user_prompt`, and `measurement_method=utf8_bytes`.

This is a locally observed submission size, not tokens, complete model context,
AI Context/framework load evidence, or billing. It does not join individual
prompt submissions to provider-reported token usage. Corporate profiles reject
the mode in the Hook, and the Corporate Collector independently drops the
metric if a source is misconfigured.

Hooks do not expose a truthful per-model-call boundary or token/cost fields, so
the experiment does not emit `LLM` spans and does not replace native Codex
usage telemetry. Hosted tools and some specialized tool paths may bypass tool
hooks. Treat the resulting Phoenix tree as partial lifecycle evidence, not a
complete accounting or enforcement boundary.

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
work. Framework hooks must add `ai_context.*` evidence separately; asking the
prompt to self-report this state is not independent evidence.

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
uses narrowly scoped canonical recording metrics for token accounting, API USD,
Codex credits, and unpriced coverage. AI Agent 用量 queries only `ai_agent_*`;
Codex Auto-review 用量 isolates `agent_role=approval_reviewer`; AI Agent 活動
reads metadata-only Loki events and links them to Tempo. The AI Context
dashboards are retired until a real framework emitter exists. No dashboard
substitutes provider activity for framework evidence.

Exact Codex models are mapped to bounded `model_id` before the raw model label
is removed from the canonical copy. Unknown models become `unmapped` and remain
visible without a price. `agent_role` is a separate bounded dimension:
`primary`, `approval_reviewer`, `subagent`, or `unknown`. A producer-supplied
subagent role is retained. The current `codex-auto-review` pseudo-model maps to
`approval_reviewer`, but because it does not reveal the actual model, its
canonical `model_id` remains `unmapped` and both estimates remain absent.

API USD uses a versioned public API card. Codex credits use a separate public
token-based rate card and are an estimate, not the official remaining plan
allowance or actual debit. Cached input is discounted rather than free. The
public credits table does not list a cache-write-specific rate, so cache-write
tokens remain visible as credits-unpriced. Raw `token_type` panels remain
available to reconcile the non-overlapping accounting classes. The API estimate
does not apply the greater-than-272K premium because aggregated telemetry cannot
identify affected requests.

Before changing a live Codex configuration, create a same-directory backup.
For this toolkit, change only the [otel] block, keep all three endpoints on the
Collector loopback ports, and set log_user_prompt=false. Restart Codex after
the configuration change; do not terminate an active session merely to apply
telemetry settings.

After any Codex upgrade, record both versions, compare emitted names/kinds/
units/temporality with the fixture, replay all three signals through every
Collector mode, then verify native and canonical histogram sums/counts
reconcile before updating the mapping.
