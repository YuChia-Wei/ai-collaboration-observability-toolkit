# Official pricing review and historical estimate boundary

Reviewed on 2026-10-07. This review covers ChatGPT personal-plan and
Business/Enterprise/Edu **credit-based** Codex usage, plus the separate public
API list-price equivalent. It does not establish an Enterprise USD agreement,
an actual debit, or the policy's historical effective date.

## Official sources and scope

The [Codex pricing page](https://learn.chatgpt.com/docs/pricing#token-rates)
links to the canonical
[Business/Enterprise/Edu credit-based rate card](https://help.openai.com/en/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing).
Its Notes explicitly state that, when signed in with a ChatGPT account,
auto-review safety checks are free and do not count toward plan usage limits.
Code review and other Codex tasks continue to use their applicable rates. The
[Codex with ChatGPT help article](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)
provides the same ChatGPT-sign-in boundary.

This exemption applies to approval safety review at the permission boundary.
It does not make GitHub PR code review, local `/review`, ordinary subagents,
or unknown-model requests free. It does not establish a zero API price for
API-key calls. `codex-auto-review` identifies the approval operation, not an
actual model; missing actual-model evidence remains `unmapped`.

Two official pages still have different wording at review time:

- [Agent approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security#automatic-approval-reviews)
  says extra automatic-review calls can add to Codex usage.
- The [Enterprise USD token-based rate card](https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing)
  includes auto review in billable activity and identifies GPT-5.6 Luna.

The newer credit-card exemption is the basis for the supported ChatGPT
credit-equivalent policy. The conflicting Enterprise USD wording requires
agreement-specific confirmation before extending this policy to USD contracts.
Document update times do not prove a billing effective date. No reviewed
source supplies an exact start date for this exemption, so this toolkit does
not backfill earlier usage as free or infer the actual reviewer model from
those pages.

## Reviewed Standard rate snapshots

The following are read-back snapshots, not historical effective schedules.
Only the seven exact models already supported by this toolkit are included.
New snapshots use new version identifiers; earlier versions stay unchanged.

API prices are USD per one million tokens at Standard speed and at most
272K input tokens, read from the
[official API pricing table](https://developers.openai.com/api/docs/pricing).

| Exact model | Uncached input | Cached input | Cache write | Output |
|---|---:|---:|---:|---:|
| `gpt-5.6-sol` | $4.00 | $0.40 | $5.00 | $20.00 |
| `gpt-5.6-terra` | $2.00 | $0.20 | $2.50 | $12.00 |
| `gpt-5.6-luna` | $0.20 | $0.02 | $0.25 | $1.20 |
| `gpt-6-astra` | $10.00 | $1.00 | $12.50 | $50.00 |
| `gpt-6-sol` | $2.00 | $0.20 | $2.50 | $10.00 |
| `gpt-6-luna` | $0.10 | $0.01 | $0.125 | $0.50 |
| `gpt-6.1-sol` | $2.00 | $0.10 | $2.50 | $10.00 |

Public Codex rates are credits per one million tokens, read from the
[official credit rate card](https://help.openai.com/en/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing)
and [Learn token rates](https://learn.chatgpt.com/docs/pricing#token-rates).

| Exact model | Input | Cached input | Output |
|---|---:|---:|---:|
| `gpt-5.6-sol` | 100 | 10 | 500 |
| `gpt-5.6-terra` | 50 | 5 | 300 |
| `gpt-5.6-luna` | 5 | 0.5 | 30 |
| `gpt-6-astra` | 250 | 25 | 1,250 |
| `gpt-6-sol` | 50 | 5 | 250 |
| `gpt-6-luna` | 2.5 | 0.25 | 12.5 |
| `gpt-6.1-sol` | 50 | 2.5 | 250 |

Codex has no separate cache-write charge. The existing three-class credit
estimate continues to expose cache-write tokens outside its priced coverage;
it does not invent an API-style surcharge. The approval exemption is a
separate operation policy and covers its observed token classes. Paid-credit
Fast mode uses 2x Standard rates; GPT-6 Astra Ultrafast uses 6x. Included
subscription allowance uses different multipliers and is not reconstructed
from these credit equivalents. GPT-5.6 Sol promotional pricing is stated to
last at least through 2026-11-21; that is not a promise of an unchanged rate
after that date.

## Why retrospective dashboards can change

Multiplying an accumulated token counter by a price creates a gauge, even if
the metric name ends in `_total`. Applying `increase()` to that priced gauge
does not create a stable monetary counter when its price changes. A decrease
can look like a counter reset; an increase can charge the already accumulated
tokens again. Merely attaching a new rate-card label also creates a new series
whose first sample contains old token totals, so the deployment boundary still
cannot be treated as an exact historical charge.

For example, 1,000,000 uncached GPT-5.6 Sol tokens and 100,000 output tokens
produce 200 credits under the legacy 125/12.5/750 card, but 150 credits under
the reviewed 100/10/500 card. The corresponding API equivalent changes from
$8 under $5/$30 input/output to $6 under $4/$20. Repricing the same usage
reduces the apparent historical credit and USD values by 25%, without any
change in token usage. Re-exporting old usage with a newly selected card has
the same comparison effect and must say which snapshot it used.

## Historical dashboard design

Legacy accounting schema v2 and all its original cards remain available as
an explicitly labelled legacy view. Their values are not relabelled as v3 or
silently changed to the new promotional prices. Legacy v2 cost and credit
metrics retain their existing estimation limitations.

Schema v3 prices the token **rate observed at evaluation time**, with a fixed
30-second rule interval, and records separate USD/credit rate gauges. Each
sample carries its card and policy provenance. Selected-range cost and credit
panels integrate these stored rate samples using the fixed 30-second step.
A later price change therefore affects later stored samples, rather than
recomputing all old counter values with the newest price. Cards are immutable:
any new price or policy requires a new version, even for the same model.
Active price joins admit only price facts with `timestamp(price) == time()`
from the current rule-group evaluation. On a reload that changes the card
version, old and new price facts can otherwise coexist for one evaluation
before stale-series cleanup, causing a duplicate join and an estimate gap.
The timestamp guard avoids that transition collision without changing stored
historical estimate samples. Keep the active facts and their dependent joins
in the same rule group and preserve this guard on future card updates.
The default dashboards use v3 and preserve a separate collapsed legacy v2
row. Historical sample-coverage panels count saved rule evaluations; they do
not prove complete provider ingestion or billing reconciliation. The token-rate
expression additionally requires a successful latest Collector scrape via
`max(up{job="otel-collector-exported"}) == 1`. Failed or absent latest
Collector scrapes suppress new integral samples. A successful scrape does
not establish that the native producer supplied fresh or complete usage.

This is a sampled historical estimate, not a per-request billing ledger. The
two-minute token-rate window crosses deployment, price-change, and selected
range boundaries. The transition can therefore attribute some preceding
usage to the newly active rate for approximately one window. After scrape
restoration, `rate()` can bridge preceding short gaps within that window;
coverage reports saved rate evaluations, not exact scrape success across
the whole window. Rule outages, delayed native ingestion, and missing initial
counter baselines can leave incomplete estimates. Newly born counters also
warm up within this window, without establishing usage before their first
observation. The fixed-step integral does not fabricate missing
samples; it must not be shown as complete actual spend. Model attribution,
API context/speed modifiers, and official agreement rules retain their
existing limits.

No backfill of v3 history is performed. A range before deployment has no v3
estimate. Prometheus retention removes the supporting rate samples along with
other metrics; Corporate retains at most its configured 7-day/1GB block
budget. Historical estimates cannot survive removed source samples without
a separately authorized export or ledger. This change creates no remote
ledger or new telemetry ingress.

## Offline reports and future updates

Saved signed reports contain their selected card metadata and calculated
equivalents. Changing the repository's default card does not rewrite those
files. Merge validates the card digest and policy contract; it does not
reprice authenticated input. Legacy v1/v2 reports require their matching
archived card and retain their original unpriced-reviewer meaning.

The default v3 policy records a local activation of
`2026-10-07T13:21:21Z`, sources, review date, scope, and an unknown official
effective date. Only exact approval-operation evidence at/after that local
boundary receives non-billable pricing. Older reviewer records remain
unpriced. This adoption time is not presented as OpenAI's policy start date.
The new and legacy cards are preserved under `config/session-usage/archives/`.

Re-exporting a rollout is a new estimate using the explicitly selected card.
The read-back date alone cannot select a historically effective price for
each response. Keep an older report if its original estimate matters, and
choose its reviewed archived card when reproducing that estimate. Reports
with different cards must be compared separately rather than merged as one
homogeneous credit total. Source tokens, metadata completeness, pricing
coverage, provider estimates, balances, and actual debit remain distinct.

Future maintenance requires fetching the exact official table and policy,
recording billing scope and known/unknown effective dates, issuing a new
immutable card/policy version, running static/unit/native validators, and
checking stored sample provenance after an authorized deployment. Any runtime
claim additionally requires observed container assertions. This review itself
does not establish a deployment or runtime pass.
