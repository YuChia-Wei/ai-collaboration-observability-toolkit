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

## API USD rate card

The active `openai-api-2026-08-12` card was read back from the official model
pages:

| Model | Uncached input | Cached input | Cache write | Output |
|---|---:|---:|---:|---:|
| `gpt-5.6-sol` | $5.00 | $0.50 | $6.25 | $30.00 |
| `gpt-5.6-terra` | $2.00 | $0.20 | $2.50 | $12.00 |
| `gpt-5.6-luna` | $0.20 | $0.02 | $0.25 | $1.20 |

Values are USD per one million tokens. The model pages state that cache writes
are billed at 1.25 times uncached input. Aggregated telemetry cannot identify
which individual request crossed the greater-than-272K threshold, so this
estimate does not apply the long-context premium.

Sources:

- [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

## Codex credits rate card

The active `openai-codex-credits-2026-08-12` card follows the public Codex
token-based table:

| Model | Input | Cached input | Output |
|---|---:|---:|---:|
| `gpt-5.6-sol` | 125 | 12.5 | 750 |
| `gpt-5.6-terra` | 50 | 5 | 300 |
| `gpt-5.6-luna` | 5 | 0.5 | 30 |

Values are credits per one million tokens. Cached input has a lower rate; it is
not free. The public Codex table does not publish a separate cache-write credits
rate, so `input_cache_write` remains visible in
`ai_agent_unpriced_credit_token_usage_total` instead of borrowing the API
cache-write multiplier.

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
