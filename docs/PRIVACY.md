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

Phoenix receives only the output of this transform and only after explicit trace selection. Selection
is not a privacy mechanism; the selected trace must already be safe.

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

## Antigravity JSON Hooks bridge

The committed Antigravity example does not read transcript contents, artifacts, prompts, tool
arguments/results, workspace paths, raw errors, or raw conversation IDs. A local HMAC key derives
trace identifiers, and the selected Collector profile remains the authoritative minimization boundary.
The bridge is best-effort and must not alter tool permissions or agent termination behavior.
