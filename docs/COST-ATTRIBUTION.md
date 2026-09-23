# AI usage, credits, and cost attribution

## Scope

This toolkit can explain where AI usage occurred and produce two deliberately
separate estimates when an exact reviewed model mapping exists:

1. OpenAI API list-price cost in USD.
2. Codex public token-based credit equivalents.

Neither estimate replaces provider billing, the Codex usage dashboard, the
remaining allowance shown by `/status`, a subscription limit, an Enterprise
contract, or an invoice. Rate cards can change, so every estimate carries a
version and source.

## Evidence layers

```text
Official provider usage     → actual allowance, credits, contract, or invoice
Local token accounting      → non-overlapping token classes by provider/product/role/model
API USD estimate            → exact token class × versioned API list price
Codex credits estimate      → exact published Codex token class × public credits rate
Observed extension gauges   → session/context/quota snapshots, not counters or billing
Outcome evidence            → independently emitted workflow/build/test/review outcomes
```

These layers must not be summed or relabelled as each other. The long-term
company design may import official usage into a governed ledger, but this
repository does not implement that Admin API or ledger.

## Required dimensions

Every `accounting_schema=v2` token series includes:

- `ai_agent_provider`, `ai_agent_product`, and bounded `agent_role`;
- exact `model_id`, or `unmapped` when the producer did not supply one;
- one non-overlapping `usage_class`;
- bounded `service_namespace` so owner and synthetic data cannot collapse;
- `evidence_class`.

`agent_role` is independent of model and is limited to `primary`,
`approval_reviewer`, `subagent`, or `unknown`. A producer-supplied
`subagent` value is retained. Codex `model=codex-auto-review` is normalized to
`agent_role=approval_reviewer`, but it does not reveal the actual model, so its
canonical `model_id` remains `unmapped`.

Framework/workflow/task outcomes remain separate `ai_context.*` evidence and
must not be inferred from token activity.

## Recording metrics

Prometheus loads `config/prometheus/rules/ai-agent-cost.yml` and produces:

| Metric | Meaning |
|---|---|
| `ai_agent_token_usage_total` | v2 non-overlapping token counter by role/model/class |
| `ai_agent_token_price_usd_per_million` | versioned exact API USD rate |
| `ai_agent_estimated_cost_usd_total` | token × matching API rate |
| `ai_agent_token_credit_per_million` | versioned public Codex credits rate |
| `ai_agent_estimated_credit_usage_total` | Codex token × matching credits rate |
| `ai_agent_unpriced_api_token_usage_total` | token without an exact API rate |
| `ai_agent_unpriced_credit_token_usage_total` | Codex token without a published credits rate |

Estimates retain rate-card metadata. API output uses
`cost_source=estimated_api_list_price`; credits output uses
`credit_source=estimated_public_codex_rate_card`.

The synthetic fixture uses two explicit namespaces:

- `ai-collaboration-cost-fixture` for exact-model accounting;
- `ai-collaboration-role-fixture` for approval-reviewer and subagent roles.

Antigravity smoke data uses `ai-collaboration-fixture`. Dashboards exclude all
three. Existing stored series are not rewritten or backfilled; v2 requires the
new `agent_role` label and therefore applies only to newly normalized data.

## API USD rate cards

The `openai-api-2026-08-12` card was read back from the official GPT-5.6 model
pages. Astra uses `openai-api-2026-09-07`; GPT-6 Sol and Luna use
`openai-api-2026-09-23` from the official API pricing page. These are dated
snapshots; adding a new model does not revise older cards:

| Model | Uncached input | Cached input | Cache write | Output |
|---|---:|---:|---:|---:|
| `gpt-5.6-sol` | $5.00 | $0.50 | $6.25 | $30.00 |
| `gpt-5.6-terra` | $2.00 | $0.20 | $2.50 | $12.00 |
| `gpt-5.6-luna` | $0.20 | $0.02 | $0.25 | $1.20 |
| `gpt-6-astra` | $10.00 | $1.00 | $12.50 | $50.00 |
| `gpt-6-sol` | $2.00 | $0.20 | $2.50 | $10.00 |
| `gpt-6-luna` | $0.10 | $0.01 | $0.125 | $0.50 |

Values are USD per one million tokens at standard speed and base context
(at most 272K input tokens). The sources list cache writes at 1.25 times
uncached input. Aggregated telemetry cannot identify which individual request
crossed the greater-than-272K threshold or used Fast mode, so this estimate
does not apply long-context or Fast rates.

Sources:

- [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [API pricing: GPT-6 Sol and Luna, read 2026-09-23](https://developers.openai.com/api/docs/pricing)

## Codex credits rate card

The GPT-5.6 rows retain `openai-codex-credits-2026-08-12`; Astra uses
`openai-codex-credits-2026-09-07`; GPT-6 Sol and Luna use
`openai-codex-credits-2026-09-23` from the public Codex token-based table.
Older cards remain historical snapshots; they do not automatically adopt
promotional rates appearing after their read-back dates:

| Model | Input | Cached input | Output |
|---|---:|---:|---:|
| `gpt-5.6-sol` | 125 | 12.5 | 750 |
| `gpt-5.6-terra` | 50 | 5 | 300 |
| `gpt-5.6-luna` | 5 | 0.5 | 30 |
| `gpt-6-astra` | 250 | 25 | 1,250 |
| `gpt-6-sol` | 50 | 5 | 250 |
| `gpt-6-luna` | 2.5 | 0.25 | 12.5 |

Values are credits per one million tokens. Cached input has a lower rate; it is
not free. The Codex pricing page read on 2026-09-23 states that cache writes
have no separate charge and publishes only input, cached-input, and output
rates. This estimate retains those three classes; `input_cache_write` stays
visible in `ai_agent_unpriced_credit_token_usage_total` because it is outside
this accounting estimate, not because an additional charge is expected. No
API cache-write multiplier or inferred credit rate is applied.

All GPT-6 estimates use published standard rates. The Codex page lists a 2.5x
Fast-mode credit multiplier, but the canonical accounting contract does not
infer that mode from a model name or token series. API Fast pricing is a
separate schedule and is not derived from that credit multiplier.

This metric is a public rate-card equivalent, not a statement that the user's
included weekly allowance was reduced by exactly that value. Model choice,
context, reasoning, tools, caching, speed settings, and plan rules can affect
actual allowance consumption. Source: [Codex pricing and credits](https://learn.chatgpt.com/docs/pricing).

## Auto-review boundary

The Auto-review dashboard can reliably show reviewer turns, token classes,
cached ratio, average tokens per review, and share of Codex usage. With current
telemetry it cannot reliably show reviewer API USD or credits because the actual
model is absent. Those panels remain empty and the token appears in the
unpriced tables. Empty estimate output means unknown, not zero cost.

This local approval Auto-review is distinct from GitHub PR Code Review usage.
Do not combine them without an explicit producer field that proves the surface.

## Query semantics

Selected-range totals use counter deltas:

```promql
sum(increase(ai_agent_token_usage_total{accounting_schema="v2"}[$__range]))
sum(increase(ai_agent_estimated_cost_usd_total{accounting_schema="v2"}[$__range]))
sum(increase(ai_agent_estimated_credit_usage_total{accounting_schema="v2"}[$__range]))
```

A cumulative last value must not be presented as the selected-range cost.
A first-ever counter sample has no preceding baseline, so wait for another
sample before treating an `increase()` result as a complete interval.

## Rate-card update procedure

1. Read back the exact official provider/model page and effective date.
2. Replace the single active recording-rule card with a new version; do not
   silently reinterpret an existing version.
3. Keep unknown models and unpublished token classes unpriced and visible.
4. Run static/unit checks and `promtool check rules`.
5. Deploy Prometheus, verify the loaded rule group, and query the resulting
   labels and estimates.
6. Compare with official usage when available; record the difference rather
   than overwriting local telemetry.

## Company rollout

A team-facing system should be showback, not a productivity leaderboard:

- individuals see detailed usage and improvement opportunities;
- teams see anonymous or aggregated workflow trends;
- AI Context maintainers see independently emitted framework evidence;
- administrators see official limits and reconciliation;
- managers see project/group trends, not raw conversations.

An Admin key belongs only in a reviewed central service. It must never be
distributed to workstation Collectors or stored in this repository.
