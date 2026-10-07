# AI collaboration telemetry data contract

## Contract boundaries

The toolkit keeps five deliberately separate contracts:

| Contract | Purpose | Producer/normalizer | Dashboard |
|---|---|---|---|
| Native provider telemetry | Preserve a privacy-filtered provider view for troubleshooting | Provider, then Collector privacy transforms | Codex 原生 Telemetry / Claude Context 歸因 / Antigravity 用量 |
| \`ai_agent.*\` | Compare bounded usage and runtime behavior across AI coding agents | Collector normalization from verified provider fixtures | AI Agent 用量 / Codex Auto-review 用量 |
| metadata events + trace IDs | Inspect prompt submission, tool/API/sandbox events, and correlate to Tempo | Provider logs after Collector privacy transforms | AI Agent 活動 |
| \`ai_context.*\` | Reserve framework/workflow evidence: skills, rules, validation, waits, retries, outcomes | Future runtime/orchestrator instrumentation at a real execution boundary | None until a real producer exists |
| Session usage files | Review local response usage/credit equivalents and optional account snapshots or provider thread estimates by pseudonymous session | Opt-in local Codex reader; optional read-only installed app-server | Signed JSON/CSV files; no session labels in Grafana backends |

Native provider telemetry is not framework evidence. A Codex turn or tool call
must never be presented as proof that an AI Context skill, rule, or validation
step was used. Dashboards do not use fallback expressions across these
contracts.

## Shared resource attributes

| Attribute | Type | Examples | Notes |
|---|---|---|---|
| \`service.name\` | string | \`codex-app-server\`, \`antigravity\` | Low-cardinality producer identity |
| \`service.namespace\` | string | \`ai-collaboration\` | Optional bounded namespace |
| \`service.version\` | string | \`0.147.0-alpha.6.5\` | Producer version |
| \`deployment.environment.name\` | string | \`personal-local\` | Mode-controlled |
| \`ai_observability.profile\` | string | \`core\`, \`evaluation\`, \`corporate-redacted\` | Canonical toolkit profile |
| \`ai_agent.provider\` | string | \`openai\`, \`anthropic\`, \`google\` | Bounded provider |
| \`ai_agent.product\` | string | \`codex\`, \`claude-code\`, \`antigravity\` | Bounded product |
| \`ai_agent.surface\` | string | \`app-server\`, \`cli\`, \`desktop\`, \`hooks\`, \`status-line\` | Verified telemetry surface |

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
- \`skill_id\`, \`mcp_server_name\`, and \`mcp_tool_name\`: only for a verified
  provider-native attribution contract. Claude Code emits request-level skill
  and MCP attribution with documented redaction behavior; these fields are
  retained only in Core/Evaluation. Corporate removes them.
- \`mcp_tool_id\`: a user-configured safe logical ID emitted only after a Codex
  Hook exact-tool allowlist match. It never contains the raw hook tool name.
- \`content_scope\` and \`measurement_method\`: only fixed reviewed values for an
  explicitly documented local measurement. Codex Hook size-only metrics use
  \`user_prompt\` or \`hook_tool_response\` plus \`utf8_bytes\`; neither field
  carries content, a request identifier, or a token estimate.
- `billing_category`: Collector-derived `standard`, `auto_review`, or
  `unknown`. The Collector overwrites incoming values. Only trusted
  `service.name=codex-app-server` plus the original exact
  `model=codex-auto-review` signal produces `auto_review`; a caller-supplied
  role or billing category cannot grant the policy exemption.

Never use session, prompt, conversation, task UUID, validation fingerprint,
commit SHA, branch, path, user identity, account ID, call ID, trace ID, span
ID, or unrestricted raw tool name as a Prometheus or Loki index label.

## Session usage artifact contract

`session-usage/v3` is the default opt-in file contract with the reviewed
2026-10-07 card, separate from OTLP accounting schemas. It keeps authenticated HMAC session/response keys,
UTC timestamps, reviewed configuration/status fields, provider usage numbers,
coverage, and versioned credit estimates. Raw identifiers, paths, identity,
content, tool payloads, and unknown source fields are excluded. CSV provides
summaries; company merging consumes validated JSON and deduplicates response
keys, rejecting conflicting copies. V3 additionally signs the pricing policy
and its digest, plus per-response/group operation, evidence basis, charge
class, pricing basis, and non-billable token coverage. Exact
`codex-auto-review` source evidence identifies the approval safety operation;
role alone does not qualify. Within the reviewed ChatGPT personal/enterprise
credits-equivalent scope, its usage at/after the policy's local activation
becomes non-billable. Official effective date remains unknown, earlier usage
is not repriced, and actual-model metadata remains unknown. See
[the pricing review](PRICING-REVIEW-2026-10-07.md).

Local response usage comes only from native top-level `token_usage_record.payload.usage`;
cumulative token counts are ignored and unsupported formats remain partial/null.
Native thread checkpoints are reconciliation-only; missing/mismatched totals
produce partial coverage instead of a fabricated fallback.
Model and effort are configured evidence. `actual_model_id=unmapped` is kept
distinct; an explicit reroute makes affected attribution ambiguous/unpriced.
Configured speed or a documented Standard assumption affects only a public
credit equivalent, never a claim of actual debit or honored service tier.

`--include-account-usage` opts into offline allowlisted
`token_count.payload.rate_limits` snapshots; cumulative token counts remain
excluded from the local ledger. `--official-usage` also requests account limits
and optional thread estimates through an ephemeral installed Codex app-server.
Either flag adds authenticated `usage_metrics` source records for account
snapshots, thread estimates, and diagnostics while retaining v3 with the
current card; legacy v2 reports retain their prior optional-source contract.
Account balances, quota windows, and earned resets are never summed or
delta-attributed to sessions. Provider thread estimates retain exact micro-unit
values and optional model/effort/speed groups; they are not actual billed usage.
Missing estimates are explicit gaps. Merge validates v1/v2/v3 with the matching
reviewed card, rejecting different card/policy contracts, and deduplicates
each source independently, without adding estimates across sources or assuming
provider parent/child rollup scope. Snapshots deduplicate by `observation_key`;
thread estimates retain their latest observation, including `unavailable`.
CSV distinguishes local, account-snapshot, official-total, official-group, and
official-unavailable rows; thread totals and groups must not be summed.
This contract does not use Enterprise admin
Cost APIs or establish Enterprise runtime availability.

HMAC session/response/observation pseudonyms are prohibited in Prometheus and Loki index
labels just like raw session IDs. See [session usage](SESSION-USAGE.md) for CLI, rate-card, and
company key boundaries.

## Canonical AI-agent metrics

For native mappings the Collector uses \`copy_metric\`: the native metric
remains in the backend projection after privacy filtering, while the canonical
copy preserves the original instrument kind, unit, monotonicity, and aggregation
temporality.
The explicitly marked Codex Hook size-only metric is emitted directly into the
canonical namespace because it has no provider-native counterpart.

| Native input | Canonical metric | Semantics |
|---|---|---|
| \`claude_code.token.usage\` | \`ai_agent.request.token_usage.total\` | Provider-reported request token counter with token type and request attribution |
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
| Codex Hook exact MCP allowlist plus size-only | \`ai_agent.observed.mcp_tool_response.bytes\` | Opt-in Delta histogram of serialized PostToolUse response UTF-8 bytes under a safe logical tool ID |

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

\`ai_agent.observed.mcp_tool_response.bytes\` is emitted only when all three
conditions hold: \`size-only\`, the \`mcp-tool-response\` scope, and an exact raw
Hook tool-name mapping to a safe logical \`mcp_tool_id\`. The exporter reads the
response only after that match and emits only its deterministic serialized
UTF-8 byte count. It measures the Hook payload, not the exact text ultimately
placed in an LLM context and not provider tokens. Corporate mode drops it.

Claude Code's native token counter is incremented after each API request. The
Collector maps \`input\`, \`cacheRead\`, \`cacheCreation\`, and \`output\` to the
four canonical accounting classes and maps \`query_source=main/subagent\` to
bounded roles. \`skill.name\` identifies the active skill; MCP fields identify a
result consumed by that request. User-configured MCP names are normally
provider-redacted to \`custom\`. These labels make controlled attribution
possible but do not prove causality or identify an individual governance file.

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

Legacy accounting and estimate series carry \`accounting_schema=v2\` and
the bounded \`agent_role\`. The recording rules also retain the bounded
\`service_namespace\`, so owner telemetry and runtime fixtures cannot collapse
into the same Prometheus series. The supplied dashboards select v3 history or
the explicitly labelled legacy v2 view, and
exclude \`ai-collaboration-fixture\`, \`ai-collaboration-cost-fixture\`, and
\`ai-collaboration-role-fixture\` by default. Older v1 or unversioned series
remain stored and queryable but are not rewritten or included in v2 totals.

For the verified Codex contract, \`cached_input\`, \`cache_write_input\`, and
\`reasoning_output\` are diagnostic subsets. The accounting series prefers an
explicit \`non_cached_input\`; otherwise it derives uncached input as
\`input - cached_input - cache_write_input\`, clamped at zero. It counts \`output\`
once and does not add \`reasoning_output\` again. Raw provider token classes stay
queryable for reconciliation.

Selected-range token totals and the legacy v2 view use
\`increase(...[$__range])\`. Legacy priced \`_total\` metrics are token-counter
times price gauges, not stable monetary counters across rate changes. A
cumulative last value must not be presented as a selected-range estimate.
Because a first-ever counter sample has no preceding baseline, wait for a
subsequent sample before treating an interval increase as complete.

V3 records versioned token/cost/credit rate gauges at a fixed 30-second rule
interval using a two-minute token-rate window. Cost and credit panels
integrate stored rate samples at that fixed step; later immutable cards
change later samples without repricing all old token counters. Non-billable
credit coverage is separate from API-unpriced/model-unmapped coverage.
No v3 history is backfilled. Transition/range boundaries can span one rate
window, missing evaluations leave gaps, and retention can remove the samples
needed for old ranges. Newly born counters have a two-minute rate warmup
boundary; those samples do not establish usage before the counter existed.
This sampled estimate is not actual billing.

| V3 recording metric | Semantics |
|---|---|
| `ai_agent_token_usage_total{accounting_schema="v3"}` | Non-overlapping counter retaining Collector-derived `billing_category` |
| `ai_agent_token_usage_per_second` | Two-minute token-rate estimate evaluated every 30 seconds |
| `ai_agent_active_token_price_usd_per_million` | Immutable active 2026-10-07 API snapshot facts |
| `ai_agent_active_token_credit_per_million` | Immutable active 2026-10-07 public credit snapshot facts |
| `ai_agent_estimated_cost_usd_per_second` | Stored API cost-rate gauge; unknown reviewer model remains API-unpriced |
| `ai_agent_estimated_credit_usage_per_second` | Stored credit-rate gauge, including policy-backed non-billable zero with observed usage |
| `ai_agent_nonbillable_credit_token_usage_per_second` | Qualifying non-billable approval token rate |
| `ai_agent_unpriced_api_token_usage_per_second` | Token rate without an exact API price |
| `ai_agent_unpriced_credit_token_usage_per_second` | Codex token rate without a credit rate or qualifying exemption |
| `ai_agent_accounting_sample_available` | Saved token-rate evaluations gated by the latest Collector scrape result |

The `ai-agent-interval-estimates-v3` group in
`config/prometheus/rules/ai-agent-interval-cost.yml` fixes its interval at 30 seconds.
Active price joins require `timestamp(price) == time()` within that same rule
group. This admits only current-evaluation price facts, preventing old/new
card-version collisions before stale cleanup during a reload. It does not
rewrite previously stored estimates.
Rate samples retain `snapshot_read_at=2026-10-07` and
`policy_applied_from=2026-10-07T13:21:21Z` where applicable. Non-billable
credit samples carry `billing_status=non_billable`,
`billing_scope=chatgpt_credits`,
`credit_source=published_auto_review_policy`, and
`rate_card_version=openai-codex-auto-review-credits-2026-10-07`.
The policy activation is local provenance; its official historical effective
date is unverified. The default dashboard accounting view is v3, with a
separate collapsed legacy v2 row that retains the old queries/cards.
The token-rate expression requires
`max(up{job="otel-collector-exported"}) == 1`; absent/failed latest Collector
scrapes produce no integral samples. This gate does not establish native
provider freshness or completeness. On restoration the two-minute window
can bridge preceding short gaps, so sample coverage is availability of the
saved estimates, not exact scrape or provider-ingestion coverage.

Antigravity status-line token/context/quota metrics remain instantaneous
\`evidence_class=observed\` gauges. They are not transformed into
\`ai_agent_token_usage_total\`, are not accumulated with \`increase()\`, and do not
participate in cost estimation. Runtime smoke exports them under the dedicated
\`ai-collaboration-fixture\` namespace, which usage dashboards exclude.

## AI Context framework evidence

\`ai_context.*\` is reserved for independently emitted framework/workflow
evidence. The repository currently has schema and synthetic fixtures only.
\`ai-collaboration-framework\` is a portable prompts/skills/workflow source and
governed packaging harness, not a runtime that observes model requests. A
prompt cannot independently prove that its own rule was loaded, applied, or
caused an outcome, so this change does not add a framework emitter or per-unit
load-decision schema.
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

API cost is an explicitly versioned estimate, not provider billing. Legacy v2 GPT-5.6
rate card is `openai-api-2026-08-12`, denominated in USD per one million tokens,
and covers only exact `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`
accounting classes. Each output series retains `currency`,
`rate_card_version`, `rate_card_source`, `pricing_scope`, and
`cost_source=estimated_api_list_price`.

Codex credits use the separate `openai-codex-credits-2026-08-12` public rate
card. It publishes input, cached input, and output rates. Cached input is
discounted, not free. The pricing page read on 2026-09-23 states no separate
cache-write charge. `input_cache_write` stays in the credits-unpriced metric
as a class outside this three-class estimate; it does not imply an additional
charge or borrow the API 1.25x multiplier.

The `openai-api-2026-09-07` card covers exact `gpt-6-astra`
standard-context accounting classes. The `openai-codex-credits-2026-09-07`
card covers its published input, cached-input, and output rates. Both retain
their own version metadata rather than changing the GPT-5.6 cards.

The `openai-api-2026-09-23` and `openai-codex-credits-2026-09-23` cards cover
exact `gpt-6-sol` and `gpt-6-luna`. Their canonical family is `gpt-6`; a valid
producer-supplied role is retained, otherwise ordinary Codex usage defaults to
`primary`. The API card uses `rate_card_source=official_openai_pricing`;
credits use `official_codex_pricing`. Older cards and stored data remain
unchanged. New mappings apply only to newly ingested data.

Exact `gpt-6.1-sol` also uses canonical family `gpt-6`, retaining a valid
producer role and otherwise defaulting ordinary Codex usage to `primary`.
Its separate `openai-api-2026-10-01` card uses the official model page's USD
rates per million tokens: $2 input, $0.10 cached input, $2.50 cache write,
and $10 output. `openai-codex-credits-2026-10-01` uses the separately published
Standard credits rates: 50 input, 2.5 cached input, and 250 output. Cache-write
tokens remain outside the three-class credits estimate. Sources:
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and
[Codex token rates](https://learn.chatgpt.com/docs/pricing#token-rates).

V3 uses new 2026-10-07 API and credits snapshots for all seven reviewed exact
models. GPT-5.6 Sol uses API $4/$0.40/$5/$20 and credits 100/10/500; legacy
v2 cards above remain unchanged. The separate approval safety policy applies
only to the reviewed ChatGPT credits scope and preserves unknown actual-model
attribution. It does not declare API-key or Enterprise USD usage free.

No API estimate is guessed for an `unmapped` model, including current
`approval_reviewer` telemetry, or for Antigravity, Claude, or Copilot. The API
estimate does not represent Codex subscriptions, credits, Enterprise contracts,
invoices, or internal showback. The credits estimate, including policy-backed
non-billable usage, is a public rate-card
equivalent, not the official remaining plan allowance or actual debit.
Aggregated telemetry cannot determine which individual requests exceeded the
long-context threshold, so the API estimate does not apply the greater-than-272K
premium. Both estimates use standard rates and do not infer Fast mode or its
multipliers from a model identifier. See
[Cost attribution](COST-ATTRIBUTION.md).

## Privacy and routing

All backend analysis pipelines apply an initial denylist before canonical
normalization, then apply the mode's final policy:

1. initial deletion of content, tool payloads, command output, paths, credentials,
   identifiers, and known Codex underscore-form fields;
2. canonical copy/normalization;
3. final Core/Evaluation privacy filter or Corporate exact allowlist;
4. batching and local export.

## Compatibility and migration

- Core/Evaluation store newly received, privacy-filtered analytical signals in
  the existing backends after configuration starts; no duplicate source archive
  is created. Existing stored data is not migrated or reconstructed, and prior
  dropped data cannot be recovered.
- The Codex 原生 Telemetry dashboard keeps UID \`ai-codex-usage\`; human-facing text changes in
  place, with new default v3 estimate queries and separate legacy v2 queries.
  Its stable UID avoids creating a duplicate dashboard.
- The dedicated Codex Auto-review dashboard uses UID \`ai-codex-auto-review\`
  and treats approval review as a role, not a model.
- Raw privacy-filtered \`codex.*\` and \`antigravity_*\` series remain available.
- \`ai_agent.*\` remains provider-neutral; accounting schema v2 retains bounded
  role attribution, and v3 adds separate historical rate estimates and
  non-billable policy coverage without rewriting v1/v2 history.
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
