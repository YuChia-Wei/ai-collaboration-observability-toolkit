# Privacy and data minimization

## Threat model

Development telemetry can accidentally copy the most sensitive parts of a software project:
prompts, generated answers, shell commands, source code, diffs, file paths, API keys, cookies,
authorization headers, user identities, and internal repository names. A loopback endpoint reduces
network exposure but does not remove the risk of durable storage, backups, screenshots, or later
centralization.

The Collector is therefore a data-loss-prevention boundary, not merely a router.

## Default prohibited content

The toolkit must not persist these values by default:

- user prompt or full conversation text;
- assistant response or reasoning text;
- tool arguments, tool output, or raw MCP payloads;
- complete command lines or process arguments;
- source code, generated code, file contents, or diffs;
- absolute Windows, WSL, Linux, or macOS paths;
- access/refresh tokens, API keys, passwords, secrets, cookies, authorization headers;
- email addresses, account IDs, organization IDs, or real names;
- internal ticket, issue, repository, branch, or commit identifiers in corporate export.

Codex is configured with `log_user_prompt=false`, but sender configuration is not trusted as the only
control.

## Core and evaluation controls

`transform/privacy` performs three independent reductions before fan-out:

1. deletes known content-, credential-, identity-, path-, command-, database-statement-, and
   exception-message attributes from resources, spans, span events, logs, and metrics;
2. replaces every log body with `AI telemetry metadata event`;
3. keeps only an explicit bounded label set on metric resources, datapoints, and exemplars.

The transform uses `error_mode: propagate`. When a privacy statement cannot be applied, the affected
payload is dropped instead of bypassing minimization. The Prometheus exporter also disables
OpenMetrics exemplar output, scope labels, and automatic type/unit suffixes so the committed
dashboard metric names remain deterministic.

Span names are not globally replaced in personal modes because operation names are useful for trace
analysis. Senders must therefore use content-free operation names; the Collector removes sensitive
attributes but cannot prove that every future client keeps free text out of its span name. This is a
practical private-lab policy, not a mathematical guarantee. New AI client versions must be tested
before broad rollout.

Phoenix receives only the output of this transform and only spans declaring
`openinference.span.kind`. Compatible Evaluation routing is default-on; the
header and legacy resource opt-outs are routing controls, not privacy mechanisms.
Temporary header-derived routing metadata is deleted before export, and every
forwarded span must already be safe. Generic spans remain in Tempo.

## Corporate controls

Corporate mode applies an explicit metadata allowlist directly. Unknown fields are discarded rather
than passed through. In addition:

- span names become `AI telemetry operation`;
- span-event names become `AI telemetry event`;
- log bodies become `AI telemetry metadata event`;
- metric datapoint labels use the same bounded label policy as personal mode;
- no Phoenix or Internet exporter exists in the profile.

A production company rollout additionally requires security/data-owner approval, user notice,
backend access controls, audit logging, retention/deletion rules, pseudonym key management, and a
reviewed redacted-feedback export process. This Repository is a technical baseline, not that approval.

## Sentinel test

`AI_OBSERVABILITY_SECRET_SENTINEL_7F3B9D` is embedded in synthetic OTLP fixtures inside fields that
must be removed. Runtime validation fails when the sentinel, its synthetic email, synthetic bearer
value, synthetic absolute paths, or prohibited fixture keys appear in:

- Prometheus query results;
- Loki query results;
- Tempo trace payloads;
- Phoenix selected-project trace payloads.

The sentinel is not a production secret. It is a deterministic canary proving that the configured
route applies its minimization processors. A failed sentinel assertion blocks release of the
configuration change.

## Hashing guidance

A plain unsalted SHA-256 of a small identifier set can be reversed by dictionary attack. Corporate
pseudonyms or repository categories should use HMAC-SHA-256 with a company-held secret and explicit
key version. The key must not be passed as telemetry, stored in `.env`, or committed here.

## Local access

Published ports bind to loopback. Grafana has authentication, but Prometheus, Loki, Tempo, Collector,
and Phoenix local endpoints do not. Treat the workstation account as the security boundary. Do not
change bind addresses for team sharing; design an authenticated internal deployment instead.

## Codex normalization and existing local data

Version 0.1.3 adds a first-pass denylist before canonical normalization. It
covers dotted, underscored, and hyphenated forms used by current Codex
telemetry, including arguments, conversation_id, user_account_id, call_id,
trace_id, span_id, prompt_length, raw tool/MCP names and payloads, endpoints,
host names, and path-bearing fields. The final privacy processor still runs
after normalization.

The versioned Codex fixture intentionally injects a synthetic privacy sentinel
into metrics, logs, and traces. Runtime smoke verifies that the sentinel and
forbidden labels are absent in the new Prometheus/Loki/Tempo time window.

Collector policy changes are forward-looking. Data written to persistent
volumes before 0.1.3 may contain attributes that the older policy admitted.
The release does not silently delete those volumes. Irreversible cleanup
requires an explicit Owner decision and a reviewed backup/retention procedure.
A successful 0.1.3 privacy smoke proves the new ingestion window, not
retroactive erasure.

## Antigravity local bridges

The Antigravity examples consume Hooks and, for the CLI, custom status-line JSON. Those payloads may
contain workspace/transcript/artifact paths, raw errors, e-mail, plan identity, VCS branch, conversation
ID, and quota reset timestamps. The committed exporter uses a metadata allowlist and does not export or
persist those fields.

`PostToolUse` is handled after execution. Its documented `toolCall` object can contain a tool name,
arguments, commands, paths, and other sensitive values. The `hooks.json` matcher therefore supplies only
a fixed low-cardinality operation category, and the exporter never reads `toolCall`. The example retains
that category, step index, and success/error classification; it does not serialize raw error text,
tool arguments/results, or unknown fields. `PreToolUse` is intentionally absent because it must return
a permission decision and could change the agent's security behavior.

The exporter derives optional personal session pseudonyms with HMAC-SHA-256 using either an explicit
local salt or an automatically generated user-local key. Corporate examples disable the session
attribute. The selected Collector profile remains the authoritative second-layer minimization boundary.
Export failure is best-effort and must not alter tool permissions, model flow, or normal termination.

## Codex lifecycle Hook bridge

The opt-in Codex Hooks example applies an allowlist before writing local state
or building OTLP. Its default `metadata-only` mode consumes only the event name,
active model slug, tool name for fixed category mapping, and IDs needed for
local turn/tool correlation. It does not inspect `prompt`,
`last_assistant_message`, `tool_input`, `tool_response`, `cwd`, or
`transcript_path`.

An explicit `--capture-mode size-only` is the sole exception: for
`UserPromptSubmit` it reads `prompt` in memory to compute a UTF-8 byte count.
Only that number is emitted in `ai_agent.observed.user_prompt.bytes`, with
fixed reviewed dimensions. Prompt text, hashes, source paths, IDs, and
per-turn linkage remain absent from local state, OTLP attributes, capture
artifacts, logs, and debug output. Invalid or missing mode configuration falls
back to `metadata-only`. Corporate profiles reject the mode and the Corporate
Collector also drops this metric as a defense in depth.

Raw session, turn, and tool IDs are never serialized. Their SHA-256 values are
used only as local state path components, while exported trace and span IDs are
random. The state contains timestamps, random correlation IDs, model slug, and
bounded tool category, then removes completed turn/tool files. The endpoint is
restricted to loopback so the Collector remains the only host telemetry
ingress and the authoritative second privacy boundary.
