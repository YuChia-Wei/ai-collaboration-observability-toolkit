# AI collaboration telemetry data contract

## Contract boundaries

The v0.2.0 forward contract keeps four deliberately separate contracts:

| Contract | Purpose | Producer/normalizer | Dashboard |
|---|---|---|---|
| Native provider telemetry | Preserve a privacy-filtered provider view for troubleshooting | Provider, then Collector privacy transforms | Codex 原生 Telemetry / Antigravity 用量 |
| \`ai_agent.*\` | Compare bounded usage and runtime behavior across AI coding agents | Collector normalization from verified provider fixtures | AI Agent 用量 / Codex Auto-review 用量 |
| metadata events + trace IDs | Inspect prompt submission, tool/API/sandbox events, and correlate to Tempo | Provider logs after Collector privacy transforms | AI Agent 活動 |
| \`ai_context.*\` | Reserve framework/workflow evidence: skills, rules, validation, waits, retries, outcomes | Future explicit AI Context framework instrumentation | None until a real emitter exists |

Native provider telemetry is not framework evidence. A Codex turn or tool call
must never be presented as proof that an AI Context skill, rule, or validation
step was used. Dashboards do not use fallback expressions across these
contracts.

## Shared resource attributes

The Collector accepts OpenTelemetry resources and emits only bounded,
privacy-reviewed attributes.

| Attribute | Type | Examples | Notes |
|---|---|---|---|
| \`service.name\` | string | \`codex-app-server\`, \`antigravity\` | Low-cardinality producer identity |
| \`service.namespace\` | string | \`ai-collaboration\` | Optional bounded namespace |
| \`service.version\` | string | \`0.147.0-alpha.6.5\` | Producer version |
| \`deployment.environment.name\` | string | \`personal-local\` | Mode-controlled |
| \`ai_observability.profile\` | string | \`core\`, \`evaluation\`, \`corporate-redacted\` | Canonical toolkit profile |
| \`ai_agent.provider\` | string | \`openai\`, \`google\` | Bounded provider |
| \`ai_agent.product\` | string | \`codex\`, \`antigravity\` | Bounded product |
| \`ai_agent.surface\` | string | \`app-server\`, \`hooks\`, \`status-line\` | Verified telemetry surface |

\`ai_context.environment.profile\` remains as a deprecated compatibility alias
for 0.1.x producers. New integrations should use \`ai_observability.profile\`.

## Canonical AI-agent dimensions

Canonical metric datapoints may use only reviewed bounded dimensions:

- \`operation\`: \`turn\`, \`tool\`, \`mcp\`, \`api\`, \`compaction\`, \`thread\`.
- \`model_id\`: an exact, reviewed model identifier used only for bounded
  accounting/rate-card joins. Unknown or non-exact values become \`unmapped\`;
  raw provider values are never promoted automatically.
- \`model_family\`: normalized family, not a request/session identifier.
- \`agent_role\`: execution role independent of model: \`primary\`,
  \`approval_reviewer\`, \`subagent\`, or \`unknown\`. A producer-supplied bounded
  role is retained. Codex \`model=codex-auto-review\` maps to
  \`approval_reviewer\`, while its actual \`model_id\` remains \`unmapped\`.
- \`tool_category\`: bounded category such as \`execution\`, \`editor\`, or
  \`connector\`; raw tool names are removed from canonical copies.
- \`token_type\`: provider-reported bounded token class.
- \`success\`, \`status\`, \`type\`, and \`source\`: only when the provider
  exposes a bounded value.
- \`evidence_class\`: \`provider-reported\` for native SDK metrics or
  \`observed\` for local extension gauges.
- \`content_scope\` and \`measurement_method\`: only fixed reviewed values for an
  explicitly documented local measurement. The Codex Hook size-only metric uses
  \`user_prompt\` and \`utf8_bytes\`; neither field carries content, an identifier,
  or a token estimate.

Never use session, prompt, conversation, task UUID, validation fingerprint,
commit SHA, branch, path, user identity, account ID, call ID, trace ID, span
ID, or raw tool/skill name as a Prometheus or Loki index label.

## Canonical AI-agent metrics

For native mappings the Collector uses \`copy_metric\`: the native metric
remains available after privacy filtering, while the canonical copy preserves
the original instrument kind, unit, monotonicity, and aggregation temporality.
The explicitly marked Codex Hook size-only metric is emitted directly into the
canonical namespace because it has no provider-native counterpart.

| Native input | Canonical metric | Semantics |
|---|---|---|
| \`codex.turn.token_usage\` | \`ai_agent.turn.token_usage\` | Delta histogram, token count distribution |
| \`codex.turn.e2e_duration_ms\` | \`ai_agent.turn.duration_ms\` | Delta histogram |
| \`codex.turn.ttft.duration_ms\` | \`ai_agent.turn.ttft.duration_ms\` | Delta histogram |
| \`codex.turn.ttfm.duration_ms\` | \`ai_agent.turn.ttfm.duration_ms\` | Delta histogram |
| \`codex.tool.call\` | \`ai_agent.tool.call\` | Delta monotonic sum |
| \`codex.tool.call.duration_ms\` | \`ai_agent.tool.call.duration_ms\` | Delta histogram |
| \`codex.mcp.call\` | \`ai_agent.mcp.call\` | Delta monotonic sum |
| \`codex.mcp.call.duration_ms\` | \`ai_agent.mcp.call.duration_ms\` | Delta histogram |
| Codex Responses API duration metrics | \`ai_agent.api.*.duration_ms\` | Delta histograms |
| \`codex.task.compact\` | \`ai_agent.compaction\` | Delta monotonic sum |
| \`codex.skill.injected\` | \`ai_agent.skill.injection\` | Delta monotonic sum |
| \`codex.thread.started\` | \`ai_agent.thread.started\` | Delta monotonic sum |
| \`antigravity_session_tokens\` | \`ai_agent.observed.session_tokens\` | Instantaneous observed gauge |
| \`antigravity_context_tokens\` | \`ai_agent.observed.context_tokens\` | Instantaneous observed gauge |
| Other \`antigravity_*\` status gauges | \`ai_agent.observed.*\` | Instantaneous observed gauge |
| Codex Hook \`--capture-mode size-only\` | \`ai_agent.observed.user_prompt.bytes\` | Opt-in Delta histogram of locally measured user-prompt UTF-8 bytes; no content or token claim |

Prometheus renders dotted OTLP names with underscores and renders histograms as
\`_bucket\`, \`_count\`, and \`_sum\` series. Queries must use histogram
operations; a histogram sum must not be treated as a counter instrument in the
contract.

\`ai_agent.observed.user_prompt.bytes\` is emitted only by the explicit Codex
Hook \`size-only\` mode. Its Prometheus \`_sum\` and \`_count\` can be used with
\`increase(...[$__range])\` for a selected time range. It measures the submitted
user message before any provider-side expansion: it is not total context,
system/developer instructions, skills, tool results, framework load size,
provider token accounting, or billing. It must not be used to infer a per-turn
token ratio. Corporate mode drops it even if a source is misconfigured.

Prometheus adds provider-neutral accounting and estimate recording metrics for
the new ingestion window:

| Recording metric | Semantics |
|---|---|
| \`ai_agent_token_usage_total\` | Non-overlapping accounting classes: \`input_uncached\`, \`input_cached\`, \`input_cache_write\`, and \`output\` |
| \`ai_agent_token_price_usd_per_million\` | Versioned rate-card fact for an exact provider/model/class tuple |
| \`ai_agent_estimated_cost_usd_total\` | Accounting token total multiplied by the matching rate; absent when no exact rate exists |
| \`ai_agent_token_credit_per_million\` | Versioned public Codex credits rate for a published model/class tuple |
| \`ai_agent_estimated_credit_usage_total\` | Codex accounting token total multiplied by the matching public credits rate |
| \`ai_agent_unpriced_api_token_usage_total\` | Accounting token without an exact API rate |
| \`ai_agent_unpriced_credit_token_usage_total\` | Codex accounting token without a published credits rate |

Every new accounting and estimate series carries \`accounting_schema=v2\` and
the bounded \`agent_role\`. The recording rules also retain the bounded
\`service_namespace\`, so owner telemetry and runtime fixtures cannot collapse
into the same Prometheus series. The supplied dashboards require schema v2 and
exclude \`ai-collaboration-fixture\`, \`ai-collaboration-cost-fixture\`, and
\`ai-collaboration-role-fixture\` by default. Older v1 or unversioned series
remain stored and queryable but are not rewritten or included in v2 totals.

For the verified Codex contract, \`cached_input\`, \`cache_write_input\`, and
\`reasoning_output\` are diagnostic subsets. The accounting series prefers an
explicit \`non_cached_input\`; otherwise it derives uncached input as
\`input - cached_input - cache_write_input\`, clamped at zero. It counts \`output\`
once and does not add \`reasoning_output\` again. Raw provider token classes stay
queryable for reconciliation.

Selected-range token, API USD, and Codex credits panels use
\`increase(...[$__range])\`; a cumulative last value must not be presented as a
selected-range estimate. Because a first-ever counter sample has no preceding
baseline, wait for a subsequent sample before treating an interval increase as
complete.

Antigravity status-line token/context/quota metrics remain instantaneous
\`evidence_class=observed\` gauges. They are not transformed into
\`ai_agent_token_usage_total\`, are not accumulated with \`increase()\`, and do not
participate in cost estimation. Runtime smoke exports them under the dedicated
\`ai-collaboration-fixture\` namespace, which usage dashboards exclude.

## AI Context framework evidence

\`ai_context.*\` is reserved for independently emitted framework/workflow
evidence. The repository currently has schema and synthetic fixtures only. A
prompt cannot independently prove that its own rule was loaded, applied, or
caused an outcome, so no AI Context effectiveness/workflow dashboard is
provisioned until a deterministic framework-owned emitter or hook exists.
Typical bounded attributes include:

- framework and workflow version/type/stage;
- task type, skill ID, rule ID/state;
- validation type/tier/reuse state;
- normalized retry and wait reasons;
- task outcome and evidence class.

Initial framework metrics remain:

\`\`\`text
ai_context_workflow_duration_seconds
ai_context_wait_duration_seconds
ai_context_validation_runs_total
ai_context_validation_duplicate_total
ai_context_retry_total
ai_context_task_outcome_total
ai_context_manual_correction_total
ai_context_loaded_bytes_total
ai_context_estimated_context_tokens_total
ai_context_rule_state_total
\`\`\`

The deprecated \`ai_context_token_usage_total\`,
\`ai_context_tool_calls_total\`, and \`ai_context_cost_value_total\` names remain
queryable only as bounded 0.1.x compatibility data. They are not copied into
\`ai_agent.*\`. New provider integrations must use \`ai_agent.*\`; new framework
instrumentation must not emit provider usage under \`ai_context.*\`.

## API USD and Codex credits estimates

API cost is an explicitly versioned estimate, not provider billing. The active
rate card is \`openai-api-2026-08-12\`, denominated in USD per one million tokens,
and covers only exact \`gpt-5.6-sol\`, \`gpt-5.6-terra\`, and \`gpt-5.6-luna\`
accounting classes. Each output series retains \`currency\`,
\`rate_card_version\`, \`rate_card_source\`, \`pricing_scope\`, and
\`cost_source=estimated_api_list_price\`.

Codex credits use the separate \`openai-codex-credits-2026-08-12\` public rate
card. It publishes input, cached input, and output rates. Cached input is
discounted, not free. Because the public table does not publish a distinct
cache-write credits rate, \`input_cache_write\` stays in the credits-unpriced
metric instead of borrowing the API 1.25x multiplier.

No estimate is guessed for an \`unmapped\` model, including current
\`approval_reviewer\` telemetry, or for Antigravity, Claude, or Copilot. The API
estimate does not represent Codex subscriptions, credits, Enterprise contracts,
invoices, or internal showback. The credits estimate is a public rate-card
equivalent, not the official remaining plan allowance or actual debit.
Aggregated telemetry cannot determine which individual requests exceeded the
long-context threshold, so the API estimate does not apply the greater-than-272K
premium. See
[Cost attribution](COST-ATTRIBUTION.md).

## Privacy and routing

All modes apply an initial denylist before canonical normalization, then apply
the mode's final policy:

1. initial deletion of content, tool payloads, command output, paths, credentials,
   identifiers, and known Codex underscore-form fields;
2. canonical copy/normalization;
3. final Core/Evaluation privacy filter or Corporate exact allowlist;
4. batching and local export.

Evaluation spans reach Phoenix only after redaction and only when they declare
\`openinference.span.kind\`. Compatible spans are routed by default;
\`x-ai-observability-phoenix: false\` or legacy boolean
\`ai_context.export.phoenix=false\` opts out. Generic spans remain in Tempo. The
header-derived routing attribute is deleted before export. Corporate mode
defines no Phoenix exporter.
See [Privacy](PRIVACY.md) and the versioned
[Codex fixture](../fixtures/codex/0.146.1/README.md).

## Compatibility and migration

- The Codex 原生 Telemetry dashboard keeps UID \`ai-codex-usage\`; human-facing text changes in
  place while the PromQL contract remains stable, avoiding a duplicate dashboard.
- The dedicated Codex Auto-review dashboard uses UID \`ai-codex-auto-review\`
  and treats approval review as a role, not a model.
- Raw privacy-filtered \`codex.*\` and \`antigravity_*\` series remain available.
- \`ai_agent.*\` remains provider-neutral; accounting schema v2 adds bounded
  role attribution without rewriting v1 history.
- Existing stored series are not rewritten. \`agent_role\`, exact \`model_id\`,
  accounting, API USD, and Codex credits recording metrics apply to newly
  ingested/mapped data.
- Legacy canonical token series without \`model_id\` remain queryable in the raw
  canonical metric but are excluded from accounting and cost recording rules.
- Dashboard model variables use the non-empty all-pattern \`.+\`, preventing
  historical label-less series from re-entering the new-data accounting view.
- AI Context dashboards are retired until a real framework emitter exists;
  provider-native metrics are never used as a fallback for framework evidence.
- Producers should migrate from \`ai_context.environment.profile\` to
  \`ai_observability.profile\`; the alias remains during the 0.1.x line.
