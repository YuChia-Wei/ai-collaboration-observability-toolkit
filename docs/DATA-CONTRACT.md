# AI collaboration telemetry data contract

## Contract boundaries

Version 0.1.3 defines three deliberately separate contracts:

| Contract | Purpose | Producer/normalizer | Dashboard |
|---|---|---|---|
| Native provider telemetry | Preserve a privacy-filtered provider view for troubleshooting | Provider, then Collector privacy transforms | Codex 原生 Telemetry / Antigravity 用量 |
| \`ai_agent.*\` | Compare bounded usage and runtime behavior across AI coding agents | Collector normalization from verified provider fixtures | AI Agent 用量 |
| \`ai_context.*\` | Explain framework/workflow evidence: skills, rules, validation, waits, retries, outcomes | AI Context framework instrumentation | AI Context 有效性 / AI 工作流程效率 |

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
- \`tool_category\`: bounded category such as \`execution\`, \`editor\`, or
  \`connector\`; raw tool names are removed from canonical copies.
- \`token_type\`: provider-reported bounded token class.
- \`success\`, \`status\`, \`type\`, and \`source\`: only when the provider
  exposes a bounded value.
- \`evidence_class\`: \`provider-reported\` for native SDK metrics or
  \`observed\` for local extension gauges.

Never use session, prompt, conversation, task UUID, validation fingerprint,
commit SHA, branch, path, user identity, account ID, call ID, trace ID, span
ID, or raw tool/skill name as a Prometheus or Loki index label.

## Canonical AI-agent metrics

The Collector uses \`copy_metric\`: the native metric remains available after
privacy filtering, while the canonical copy preserves the original instrument
kind, unit, monotonicity, and aggregation temporality.

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

Prometheus renders dotted OTLP names with underscores and renders histograms as
\`_bucket\`, \`_count\`, and \`_sum\` series. Queries must use histogram
operations; a histogram sum must not be treated as a counter instrument in the
contract.

Prometheus adds three provider-neutral recording metrics for the new ingestion
window:

| Recording metric | Semantics |
|---|---|
| \`ai_agent_token_usage_total\` | Non-overlapping accounting classes: \`input_uncached\`, \`input_cached\`, \`input_cache_write\`, and \`output\` |
| \`ai_agent_token_price_usd_per_million\` | Versioned rate-card fact for an exact provider/model/class tuple |
| \`ai_agent_estimated_cost_usd_total\` | Accounting token total multiplied by the matching rate; absent when no exact rate exists |

Every new accounting and estimated-cost series carries
\`accounting_schema=v1\`. The recording rules also retain the bounded
\`service_namespace\`, so owner telemetry and runtime fixtures cannot collapse
into the same Prometheus series. The supplied dashboards require schema v1 and
exclude \`ai-collaboration-fixture\` and \`ai-collaboration-cost-fixture\` by
default. Older unversioned series remain stored and queryable but are not
rewritten or included in the new usage totals.

For the verified Codex contract, \`cached_input\`, \`cache_write_input\`, and
\`reasoning_output\` are diagnostic subsets. The accounting series prefers an
explicit \`non_cached_input\`; otherwise it derives uncached input as
\`input - cached_input - cache_write_input\`, clamped at zero. It counts \`output\`
once and does not add \`reasoning_output\` again. Raw provider token classes stay
queryable for reconciliation.

Dashboard cumulative stats reduce to the last observed recording value in the
selected range, and the unpriced table uses \`last_over_time\`. Range charts use
\`increase()\`; because a first-ever counter sample has no preceding baseline,
operators should use the cumulative stat for the initial read-back and the
range chart for subsequent changes.

Antigravity status-line token/context/quota metrics remain instantaneous
\`evidence_class=observed\` gauges. They are not transformed into
\`ai_agent_token_usage_total\`, are not accumulated with \`increase()\`, and do not
participate in cost estimation. Runtime smoke exports them under the dedicated
\`ai-collaboration-fixture\` namespace, which usage dashboards exclude.

## AI Context framework evidence

\`ai_context.*\` is reserved for independently emitted framework/workflow
evidence. Typical bounded attributes include:

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

## Cost

Cost is an explicitly versioned estimate, not provider billing. The initial
rate card is \`openai-api-2026-08-10\`, denominated in USD per one million tokens,
and covers only exact \`gpt-5.6-sol\`, \`gpt-5.6-terra\`, and \`gpt-5.6-luna\`
accounting classes. Each output series retains \`currency\`,
\`rate_card_version\`, \`rate_card_source\`, \`pricing_scope\`, and
\`cost_source=estimated_api_list_price\`.

No price is guessed for \`codex-auto-review\`, \`unmapped\`, Antigravity, Claude,
or Copilot. Those usage/observation series remain visible without a cost
series. The initial rate card represents public API base pricing only; it does
not represent Codex subscriptions, credits, enterprise contracts, invoices,
or internal showback. Aggregated telemetry cannot determine which individual
requests exceeded the long-context threshold, so the initial estimate does
not apply the greater-than-272K premium. See
[Cost attribution](COST-ATTRIBUTION.md).

## Privacy and routing

All modes apply an initial denylist before canonical normalization, then apply
the mode's final policy:

1. initial deletion of content, tool payloads, command output, paths, credentials,
   identifiers, and known Codex underscore-form fields;
2. canonical copy/normalization;
3. final Core/Evaluation privacy filter or Corporate exact allowlist;
4. batching and local export.

Evaluation traces reach Phoenix only after redaction and are routed by default.
\`x-ai-observability-phoenix: false\` or legacy boolean
\`ai_context.export.phoenix=false\` opts out. The header-derived routing attribute
is deleted before export. Corporate mode defines no Phoenix exporter.
See [Privacy](PRIVACY.md) and the versioned
[Codex fixture](../fixtures/codex/0.146.1/README.md).

## Compatibility and migration

- The Codex 原生 Telemetry dashboard keeps UID \`ai-codex-usage\`; human-facing text changes in
  place while the PromQL contract remains stable, avoiding a duplicate dashboard.
- Raw privacy-filtered \`codex.*\` and \`antigravity_*\` series remain available.
- \`ai_agent.*\` is additive in 0.1.3.
- Existing stored series are not rewritten. Exact \`model_id\`, accounting, and
  cost recording metrics apply to newly ingested/mapped data.
- Legacy canonical token series without \`model_id\` remain queryable in the raw
  canonical metric but are excluded from accounting and cost recording rules.
- Dashboard model variables use the non-empty all-pattern \`.+\`, preventing
  historical label-less series from re-entering the new-data accounting view.
- AI Context dashboards no longer fall back to provider-native metrics.
- Producers should migrate from \`ai_context.environment.profile\` to
  \`ai_observability.profile\`; the alias remains during the 0.1.x line.
