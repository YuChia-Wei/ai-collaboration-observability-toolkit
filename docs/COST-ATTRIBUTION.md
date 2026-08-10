# AI usage and cost attribution

## Scope

This toolkit can explain where AI usage occurred and can estimate public API
list-price cost for exact, reviewed model mappings. It does not replace OpenAI,
Anthropic, Google, or GitHub billing records. Subscriptions and enterprise
credits may use product-, model-, message-, or token-based rates and can change
by contract/effective date.

## Three evidence layers

```text
Official provider usage     → actual credits/contract accounting
Local accounting telemetry  → non-overlapping token classes and estimated list-price cost
Observed extension gauges   → current session/context/quota snapshots, not counters or billing
Outcome evidence            → build/test/review/accepted-change value
```

The long-term company design should import official usage into a durable ledger and reconcile it with
local task facts. This repository deliberately postpones the Admin API and ledger implementation.

## Required dimensions

Every local estimated-cost series includes:

- `ai_agent_provider`, `ai_agent_product`, and exact `model_id`;
- non-overlapping `usage_class`;
- `accounting_schema=v1` and the bounded `service_namespace` used to isolate
  real sources from synthetic verification fixtures;
- `currency`, `rate_card_version`, `rate_card_source`, and `pricing_scope`;
- `cost_source=estimated_api_list_price`;
- the reporting time range selected by the query/dashboard.

Framework/workflow/task outcomes remain separate `ai_context.*` evidence. They
must not be inferred from provider token telemetry.

## Implemented accounting and rate card

Prometheus loads `config/prometheus/rules/ai-agent-cost.yml` and produces:

- `ai_agent_token_usage_total` for non-overlapping accounting tokens;
- `ai_agent_token_price_usd_per_million` for exact rate-card facts;
- `ai_agent_estimated_cost_usd_total` only when provider/model/class matches.

`examples/otlp/codex-cost-accounting-metrics.json` is a synthetic,
privacy-sentinel-bearing runtime fixture. It exists to verify the calculation
path and is never presented as owner usage. Recording rules retain its
`service_namespace=ai-collaboration-cost-fixture`; dashboards require
`accounting_schema=v1` and exclude both known fixture namespaces. Antigravity
smoke data is similarly emitted under `ai-collaboration-fixture`.

Accounting selectors require a non-empty `model_id`. Legacy canonical series
without that new-data dimension are not rewritten or silently priced; they
remain available only in the raw canonical/provider diagnostics. Unversioned
accounting series from an earlier rule evaluation are also excluded from the
new dashboards rather than deleted or backfilled.

The initial `openai-api-2026-08-10` public API base rates are:

| Model | Uncached input | Cached input | Cache write | Output |
|---|---:|---:|---:|---:|
| `gpt-5.6-sol` | $5.00 | $0.50 | $6.25 | $30.00 |
| `gpt-5.6-terra` | $2.00 | $0.20 | $2.50 | $12.00 |
| `gpt-5.6-luna` | $0.20 | $0.02 | $0.25 | $1.20 |

All values are USD per one million tokens. Cache-write is 1.25 times the base
input price. Aggregated telemetry cannot identify which individual request
crossed the greater-than-272K threshold, so the long-context premium is not
applied. This limitation is shown in the dashboards.

`codex-auto-review` and `unmapped` remain visible as unpriced token usage.
Antigravity provides extension-observed session/context/quota gauges only, so
it has no accounting or cost series. Claude and Copilot remain unsupported
until a real, version-pinned privacy-safe fixture and defensible pricing
contract are available.

The dashboard top-row stats reduce to the last observed cumulative exporter
counter in the selected range, and the unpriced table uses `last_over_time`, so
a newly appearing series is visible immediately and survives a temporary
exporter restart in the historical view. The lower accounting/cost charts use
`increase(...[$__range])` to show changes in the selected time range. A
first-ever counter sample has no earlier baseline; the cumulative view is
therefore the authoritative initial read-back.

## Cost-source vocabulary

| Value | Meaning |
| --- | --- |
| `official` | Imported provider/admin billing or credit record |
| `vendor_reported` | Client emitted a cost estimate |
| `estimated` | Local non-overlapping token × versioned rate-card calculation |
| `allocated` | Internal showback allocation |
| `unknown` | No defensible figure |

Official credits, estimated credits, overage currency, and internal showback are separate measures.
Do not sum them into one chart.

The current recording metric uses the more explicit
`cost_source=estimated_api_list_price`; the vocabulary above remains the
provider-neutral conceptual layer for a future durable ledger.

## Rate-card update procedure

1. Verify the exact provider model page and effective/read-back date.
2. Add or replace a versioned rate-card entry; never silently reinterpret an
   existing version.
3. Keep unknown models unpriced and visible.
4. Run static tests plus `promtool check rules`, deploy Prometheus, and query the
   loaded rule group and resulting labels.
5. Compare the estimate with official billing when that source becomes
   available; record the difference instead of overwriting local telemetry.

## Useful ratios

Cost reduction alone can reward incomplete work. Pair cost with results:

```text
credits per successful task
credits per accepted change
credits per first-pass build/test success
credits per merged pull request
duplicate validation rate
manual correction rate
unattributed official-credit ratio
cache-read ratio
```

Always group by task type and model/tool before comparing people or framework versions.

## Company rollout

A team-facing system should be showback, not a productivity leaderboard:

- individuals see their detailed usage and improvement opportunities;
- teams see anonymous/aggregated workflow trends;
- AI Context maintainers see de-identified skill/rule/framework effectiveness;
- administrators see official limits and reconciliation;
- managers see project/group trends, not raw conversation content.

An Admin key belongs only in a reviewed central service. It must never be distributed to workstation
Collectors or stored in this repository.
