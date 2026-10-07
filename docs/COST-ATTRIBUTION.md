# AI usage, credits, and cost attribution

## Scope

This toolkit can explain where AI usage occurred and produce two deliberately
separate estimates when an exact reviewed model mapping exists:

1. OpenAI API list-price cost in USD.
2. Codex public token-based credit equivalents.

The supported ChatGPT-sign-in approval safety-review policy also identifies
known non-billable credit-equivalent usage without inventing an actual model.
Neither estimate replaces provider billing, the Codex usage dashboard, the
remaining allowance shown by `/status`, a subscription limit, an Enterprise
contract, or an invoice. Rate cards can change, so every estimate carries a
version and source. See the [2026-10-07 official pricing review](PRICING-REVIEW-2026-10-07.md)
for current rates, policy scope, source inconsistencies, and historical limits.

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

V3 also retains Collector-derived `billing_category=standard|auto_review|unknown`.
Incoming categories are overwritten. Only trusted `codex-app-server` plus
the exact original `codex-auto-review` pseudo-model produces `auto_review`;
role alone does not qualify for the credit-equivalent exemption.

Framework/workflow/task outcomes remain separate `ai_context.*` evidence and
must not be inferred from token activity.

## Legacy v2 recording metrics

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

These v2 metrics and cards remain an explicitly labelled legacy view. The
priced `_total` metrics multiply a cumulative token counter by a rate; their
names do not make them stable monetary counters across price changes.
New historical estimates use the separate v3 sampled-rate contract below.
Estimates retain rate-card metadata. API output uses
`cost_source=estimated_api_list_price`; credits output uses
`credit_source=estimated_public_codex_rate_card`.

The synthetic fixture uses two explicit namespaces:

- `ai-collaboration-cost-fixture` for exact-model accounting;
- `ai-collaboration-role-fixture` for approval-reviewer and subagent roles.

Antigravity smoke data uses `ai-collaboration-fixture`. Dashboards exclude all
three. Existing stored series are not rewritten or backfilled; v2 requires the
new `agent_role` label and therefore applies only to newly normalized data.

## Legacy API USD rate cards

The `openai-api-2026-08-12` card was read back from the official GPT-5.6 model
pages. Astra uses `openai-api-2026-09-07`; GPT-6 Sol and Luna use
`openai-api-2026-09-23` from the official API pricing page. GPT-6.1 Sol uses
`openai-api-2026-10-01` from its official model page. These are dated
snapshots; adding a new model does not revise older cards:

| Model | Uncached input | Cached input | Cache write | Output |
|---|---:|---:|---:|---:|
| `gpt-5.6-sol` | $5.00 | $0.50 | $6.25 | $30.00 |
| `gpt-5.6-terra` | $2.00 | $0.20 | $2.50 | $12.00 |
| `gpt-5.6-luna` | $0.20 | $0.02 | $0.25 | $1.20 |
| `gpt-6-astra` | $10.00 | $1.00 | $12.50 | $50.00 |
| `gpt-6-sol` | $2.00 | $0.20 | $2.50 | $10.00 |
| `gpt-6-luna` | $0.10 | $0.01 | $0.125 | $0.50 |
| `gpt-6.1-sol` | $2.00 | $0.10 | $2.50 | $10.00 |

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
- [GPT-6.1 Sol, read 2026-10-01](https://developers.openai.com/api/docs/models/gpt-6.1-sol)

## Legacy Codex credits rate cards

The GPT-5.6 rows retain `openai-codex-credits-2026-08-12`; Astra uses
`openai-codex-credits-2026-09-07`; GPT-6 Sol and Luna use
`openai-codex-credits-2026-09-23`; GPT-6.1 Sol uses
`openai-codex-credits-2026-10-01` from the public Codex token-based table.
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
| `gpt-6.1-sol` | 50 | 2.5 | 250 |

Values are credits per one million tokens. Cached input has a lower rate; it is
not free. The Codex pricing page read on 2026-10-01 states that cache writes
have no separate charge and publishes only input, cached-input, and output
rates. This estimate retains those three classes; `input_cache_write` stays
visible in `ai_agent_unpriced_credit_token_usage_total` because it is outside
this accounting estimate, not because an additional charge is expected. No
API cache-write multiplier or inferred credit rate is applied.

All GPT-6 estimates use published standard rates. The Codex page read on
2026-10-01 lists a 2x Fast multiplier for purchased credits and Enterprise
pay-as-you-go usage, and 2.5x for included subscription usage. The canonical
accounting contract does not infer that mode from a model name or token series.
API Fast pricing is a separate schedule and is not derived from those multipliers.

This metric is a public rate-card equivalent, not a statement that the user's
included weekly allowance was reduced by exactly that value. Model choice,
context, reasoning, tools, caching, speed settings, and plan rules can affect
actual allowance consumption. Source: [Codex pricing and credits](https://learn.chatgpt.com/docs/pricing).

## Session credit reports

The opt-in [session usage command](SESSION-USAGE.md) creates offline JSON/CSV
from native per-response usage records. It groups by pseudonymous session and
configured model/effort and keeps actual model attribution unknown;
explicit reroutes make affected records unpriced.
Effort is metadata and has no guessed price multiplier. Company merging
authenticates reports and deduplicates response keys before totaling credits.

Its separate current card,
[`config/session-usage/codex-credit-rates.json`](../config/session-usage/codex-credit-rates.json),
was reviewed again on 2026-10-07. It uses the published GPT-5.6 Sol rates of
100/10/500 credits per million input/cached/output tokens. Historical
v2 Prometheus cards above keep their original snapshots. A read-back date is not
an inferred historical effective date; the current file card must not be used
to silently reinterpret old estimates.

Configured Fast/priority uses the published 2x purchased-credit/Enterprise
pay-as-you-go multiplier; Astra Ultrafast uses 6x. A missing or unrecognized tier is explicitly
a Standard-equivalent assumption. Honored tier, actual debit, and remaining
included allowance are unavailable. These report equivalents and aggregate
Prometheus estimates overlap in purpose and must not be summed together.

## Auto-review boundary

The Auto-review dashboard can reliably show reviewer turns, token classes,
cached ratio, average tokens per review, and share of Codex usage. The
[official credit rate card](https://help.openai.com/en/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing)
states that approval safety checks are free and excluded from plan usage when
signed in with a ChatGPT account. For that supported policy, v3 separates
non-billable reviewer tokens from credits-unpriced tokens. A policy-backed
zero credit equivalent does not require knowing the actual reviewer model.
API USD still remains unavailable when that model is absent. No-data output
remains no data; a constant zero must not conceal missing telemetry.

This policy does not establish API-key or Enterprise USD agreement pricing.
Those scopes remain outside the supported credit-equivalent exemption. The
official exemption's historical effective date is unknown, so older v2 data
is not changed to zero credits.

This local approval Auto-review is distinct from GitHub PR Code Review usage.
Do not combine them without an explicit producer field that proves the surface.

## Historical v3 estimates and query semantics

V3 uses the 2026-10-07 reviewed cards shown in
[the pricing review](PRICING-REVIEW-2026-10-07.md#reviewed-standard-rate-snapshots),
including GPT-5.6 Sol API $4/$0.40/$5/$20 and credits 100/10/500.
Prices apply to an observed two-minute token rate at each fixed 30-second rule
evaluation. Separate cost and credit rate gauges retain versioned card/policy
metadata. Dashboard totals integrate stored samples with that fixed step,
so a new price affects later samples without repricing all historical tokens.
Known non-billable usage has separate coverage from both priced and unknown
usage. Model coverage and API coverage remain separate from credit coverage.

| V3 metric | Meaning |
|---|---|
| `ai_agent_token_usage_total{accounting_schema="v3"}` | Token counter retaining the derived billing category |
| `ai_agent_token_usage_per_second` | Two-minute token rate at each rule evaluation |
| `ai_agent_active_token_price_usd_per_million` | Reviewed active API snapshot facts |
| `ai_agent_active_token_credit_per_million` | Reviewed active public-credit snapshot facts |
| `ai_agent_estimated_cost_usd_per_second` | Stored versioned USD-rate gauge |
| `ai_agent_estimated_credit_usage_per_second` | Stored versioned credit-rate gauge |
| `ai_agent_nonbillable_credit_token_usage_per_second` | Policy-backed non-billable token rate, separate from unknown-price usage |
| `ai_agent_unpriced_api_token_usage_per_second` | Observed token rate without an exact API price |
| `ai_agent_unpriced_credit_token_usage_per_second` | Observed Codex token rate without a credit rate or qualifying exemption |
| `ai_agent_accounting_sample_available` | Stored token-rate evaluation availability, gated by the latest Collector scrape result |

The `ai-agent-interval-estimates-v3` group in
`config/prometheus/rules/ai-agent-interval-cost.yml` runs every 30 seconds. Ordinary
rates use `openai-api-2026-10-07` and `openai-codex-credits-2026-10-07`.
Qualifying safety-review credits use
`rate_card_version=openai-codex-auto-review-credits-2026-10-07`,
`credit_source=published_auto_review_policy`,
`billing_status=non_billable`, and `billing_scope=chatgpt_credits`.
The default dashboard view is v3; a separate collapsed legacy v2 row keeps
the earlier queries and cards.

For example, the fixed-step cost integral is:

```promql
sum(sum_over_time(ai_agent_estimated_cost_usd_per_second{accounting_schema="v3"}[$__range])) * 30
```

Use the same fixed step for the credit-rate gauge. Do not apply `increase()`
to either gauge, use a variable query step as seconds, or combine legacy and
v3 views into one bill. The token-rate expression is gated by
`max(up{job="otel-collector-exported"}) == 1`; a failed or absent latest
Collector scrape produces no integral sample. Sample coverage reports saved
rate evaluations with that gate, not successful upstream provider ingestion
or billing reconciliation. A successful Collector scrape can still contain
stale or incomplete provider usage.

The result is a sampled estimate. A two-minute window crosses deployment,
price-change, and selected-range boundaries. After scrape restoration the
window still smooths preceding samples; short scrape gaps can be bridged by
`rate()` once the latest scrape succeeds. Missing evaluations, delayed native
ingestion, and missing initial baselines can leave incomplete estimates. A
newly born counter also warms up within the two-minute window; its first
sampled rates must not be extrapolated backward as complete earlier usage.
Existing v2 series
are not backfilled. Retention can remove the rate samples needed to calculate
earlier estimates. Card dates are read-back dates, not assumed provider
effective dates. None of these estimates establishes actual debit.

Token totals and the explicitly selected legacy v2 view use counter deltas:

```promql
sum(increase(ai_agent_token_usage_total{accounting_schema="v2"}[$__range]))
sum(increase(ai_agent_estimated_cost_usd_total{accounting_schema="v2"}[$__range]))
sum(increase(ai_agent_estimated_credit_usage_total{accounting_schema="v2"}[$__range]))
```

A cumulative last value must not be presented as the selected-range cost.
A first-ever counter sample has no preceding baseline, so wait for another
sample before treating an `increase()` result as a complete interval.

## Rate-card update procedure

1. Fetch the exact official table and policy; record scope, review date, and
   any known effective date. Leave the effective date unknown if it is absent.
2. Add a new immutable v3 card/policy version. Keep legacy v2 and archived
   session cards unchanged; do not silently reinterpret an existing version.
   Keep price facts and dependent joins in the same rule group, including the
   `timestamp(price) == time()` guard on active facts. During a version-change
   reload, old and new price facts can coexist before stale cleanup and cause
   a duplicate join for one evaluation without that guard. Only facts written
   at the current evaluation may price its token rate; stored historical
   estimate samples remain unchanged.
3. Keep unknown models and unpublished token classes unpriced and visible.
4. Run static/unit checks and `promtool check rules`.
5. After an authorized deployment, verify loaded legacy and v3 groups, fixed
   interval, stored sample provenance, and coverage around the transition.
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
