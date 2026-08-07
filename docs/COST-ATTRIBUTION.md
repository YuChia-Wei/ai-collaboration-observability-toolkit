# AI usage and cost attribution

## Scope

This toolkit can explain where AI usage occurred and whether it produced useful outcomes. It does not
replace OpenAI, Anthropic, Google, or GitHub billing records. Enterprise credits may use product-,
model-, message-, or token-based rates and can change by contract/effective date.

## Three evidence layers

```text
Official provider usage  → actual credits/contract accounting
Local telemetry          → task, workflow, tool, model, token, wait, retry attribution
Outcome evidence         → build/test/review/accepted-change value
```

The long-term company design should import official usage into a durable ledger and reconcile it with
local task facts. This repository deliberately postpones the Admin API and ledger implementation.

## Required dimensions

Every local cost fact should include:

- event time and reporting interval;
- provider/product/tool/model;
- token class when available;
- `ai_context.cost.value` and `ai_context.cost.unit`;
- `ai_context.cost.source`;
- framework/workflow/task classification;
- outcome;
- attribution confidence.

## Cost-source vocabulary

| Value | Meaning |
| --- | --- |
| `official` | Imported provider/admin billing or credit record |
| `vendor_reported` | Client emitted a cost estimate |
| `estimated` | Local token × versioned rate-card calculation |
| `allocated` | Internal showback allocation |
| `unknown` | No defensible figure |

Official credits, estimated credits, overage currency, and internal showback are separate measures.
Do not sum them into one chart.

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
