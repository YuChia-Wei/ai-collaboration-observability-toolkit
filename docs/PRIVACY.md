# Privacy and data minimization

## Threat model

Development telemetry can accidentally copy the most sensitive parts of a software project:
prompts, generated answers, shell commands, source code, diffs, file paths, API keys, cookies,
authorization headers, user identities, and internal repository names. A loopback endpoint reduces
network exposure but does not remove the risk of durable storage, backups, screenshots, or later
centralization.

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

The backend analysis pipelines retain their initial denylist and normalization.
`transform/privacy` then performs three reductions before backend export:

1. deletes known content-, credential-, identity-, path-, command-, database-statement-, and
   exception-message attributes from resources, spans, span events, logs, and metrics;
2. replaces every log body with `AI telemetry metadata event`;
3. keeps only an explicit bounded label set on metric resources, datapoints, and exemplars.

Backend privacy transforms use `error_mode: propagate`. When a privacy statement cannot be applied, the affected
payload is rejected instead of bypassing minimization. The Prometheus exporter also disables
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

- Logs use a fixed metadata marker and spans/events use fixed operation names.
- Phoenix and external exporters are absent; no source archive pipeline exists.
- Skill/MCP attribution and opt-in content-derived size metrics are removed.
- Resource and datapoint dimensions are limited before Prometheus export.



A production company rollout additionally requires security/data-owner approval, user notice,
backend access controls, audit logging, retention/deletion rules, pseudonym key management, and a
reviewed redacted-feedback export process. This Repository is a technical baseline, not that approval.

## Opt-in session usage files

The offline [session usage report](SESSION-USAGE.md) reads an explicitly
selected local Codex rollout directory and retains only reviewed metadata.
Raw session/response IDs support local selection, ancestry, and HMAC
pseudonym generation; they are excluded from output. Prompt/assistant/reasoning
text, tool payloads, command output, source code, paths, identities, account
fields, credentials, and unknown source fields are not copied to reports.

Company JSON reports use HMAC-SHA-256 session/response keys and authenticated
metadata. CSV is a summary view. Export and merge require a private key file;
the key value is excluded from `.env`, CLI literals, reports, and repository
files. Merging validates the schema, HMAC, key identity, and reviewed rate card
and rejects conflicting response copies. Shared-key integrity does not prove
provider billing or prevent an authorized key holder from creating a report.

Pseudonymous session/response keys remain high-cardinality identifiers. They
must never become Prometheus labels or Loki index labels. This separate file
workflow does not loosen the Collector allowlist, enable a source archive,
or upload company data. Access, retention, deletion, key distribution, and
rotation remain company controls.

## Sentinel test

`AI_OBSERVABILITY_SECRET_SENTINEL_7F3B9D` is embedded in synthetic OTLP fixtures inside fields that
must be removed. Runtime validation fails when the sentinel, its synthetic email, synthetic bearer
value, synthetic absolute paths, or prohibited fixture keys appear in:

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

## Claude Code native metrics

The Claude example enables only native metrics. It explicitly disables session
and account UUID metric dimensions and leaves prompt, tool-detail, tool-content,
raw API body, log, and trace export disabled. Claude Code can still attach
identity fields such as user e-mail to standard telemetry, so the Collector's
initial denylist remains mandatory and removes them before normalization.

Core and Evaluation retain only the documented request-level `skill.name`,
`mcp_server.name`, and `mcp_tool.name` attribution after mapping them to the
canonical label keys. User-configured MCP names are provider-redacted to
`custom` unless sensitive tool-detail logging is enabled; this repository tells
users not to enable it. Corporate drops skill and MCP attribution entirely.

## Codex lifecycle Hook bridge

The opt-in Codex Hooks example applies an allowlist before writing local state
or building OTLP. Its default `metadata-only` mode consumes only the event name,
active model slug, tool name for fixed category mapping, and IDs needed for
local turn/tool correlation. It does not inspect `prompt`,
`last_assistant_message`, `tool_input`, `tool_response`, `cwd`, or
`transcript_path`.

An explicit `--capture-mode size-only` is the sole exception. The default
`user-prompt` scope reads `UserPromptSubmit.prompt` in memory to compute a UTF-8
byte count. The separate `mcp-tool-response` scope reads
`PostToolUse.tool_response` only after the exact raw Hook tool name matches a
user-provided allowlist entry; the emitted label is the configured safe logical
ID, never that raw tool name. Only the byte number is emitted in the relevant
histogram. Content, hashes, source paths, IDs, and per-turn linkage remain absent
from local state, OTLP attributes, capture artifacts, logs, and debug output.
Invalid or missing mode configuration falls back to `metadata-only`. Corporate
profiles reject the mode and the Corporate Collector drops both content-derived
metrics as defense in depth.

Raw session, turn, and tool IDs are never serialized. Their SHA-256 values are
used only as local state path components, while exported trace and span IDs are
random. The state contains timestamps, random correlation IDs, model slug, and
bounded tool category, then removes completed turn/tool files. The endpoint is
restricted to loopback so the Collector remains the only host telemetry
ingress and the authoritative second privacy boundary.


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
