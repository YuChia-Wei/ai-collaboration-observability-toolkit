# Codex session usage reports

The opt-in `session-usage` command reads a locally selected Codex rollout
directory and reports configured model, reasoning effort, provider-reported
response token usage, and estimated public credit equivalents. It writes a
metadata-only JSON or CSV report for local review and company aggregation.

The default report and merge run without Docker or a network connection.
Optional account snapshots and official thread estimates keep their own source
records, separate from the local response ledger. `--official-usage` contacts
Codex services through an ephemeral installed Codex app-server. It does not
change Codex configuration, Collector pipelines, dashboards, or running services.
Reports are separate from the aggregate Prometheus accounting contract.

## Local report

Use a private directory outside the repository for reports and keys. On
Windows, run the following from the toolkit repository:

```powershell
$reportDir = Join-Path $env:LOCALAPPDATA 'AiUsageReports'
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
$keyFile = Join-Path $reportDir 'session-usage.key'
py -3 scripts/toolkit.py session-key --output $keyFile
$sourceRoot = Join-Path $env:USERPROFILE '.codex\sessions'
py -3 scripts/toolkit.py session-usage --source-root $sourceRoot --key-file $keyFile --output (Join-Path $reportDir 'usage.json')
```

`session-key` creates 32 random bytes encoded as 64 hexadecimal characters. It
creates the key file exclusively and refuses to overwrite an existing file.
For subsequent reports, reuse the existing key. Protect its file permissions
using the workstation or company secret-management policy; the command does
not provision company access controls.

The source directory must be explicit. Archived rollout directories can be
selected separately. Omitting `--output` prints the sanitized report to stdout;
it never prints the key or copies the source transcript.
Output cannot overwrite the key file, selected rate card, or source JSONL.

To inspect one session, use its raw identifier only as a local selector:

```powershell
py -3 scripts/toolkit.py session-usage --source-root $sourceRoot --key-file $keyFile --session-id '<local-session-id>' --output (Join-Path $reportDir 'session.json')
```

The raw identifier is excluded from the report. A filtered session excludes
descendants by default. Add `--include-subagents` to include descendants linked
through parent chains or native usage ancestry. With no session filter, the
report includes all physical threads in the selected directory.

The reader scans the whole explicit source directory to discover metadata and
ancestry before applying the session filter. Usage totals follow the selected
scope, but diagnostics remain conservative and scan-wide. An unrelated malformed
file in that directory can therefore make completeness false. Narrow the source
directory when a smaller authorized source set is needed.

## Optional account and official usage

Add `--include-account-usage` to retain allowlisted account quota and credit
snapshots already present in local `token_count.payload.rate_limits` events.
This option remains offline; the cumulative token counts in those events are
not added to the response ledger.

```powershell
py -3 scripts/toolkit.py session-usage --source-root $sourceRoot --key-file $keyFile --session-id '<local-session-id>' --include-account-usage --output (Join-Path $reportDir 'session-with-account.json')
```

Add `--official-usage` to request current account limits and an available
provider estimate for each selected physical thread. It also includes local
account snapshots. The command uses the installed Codex executable; choose
another installed executable with `--codex-bin <path>`. The default official
request timeout is 20 seconds per request and can be set from 1 to 60 seconds
with `--official-timeout`.

```powershell
py -3 scripts/toolkit.py session-usage --source-root $sourceRoot --key-file $keyFile --session-id '<local-session-id>' --official-usage --official-timeout 20 --output (Join-Path $reportDir 'session-with-official.json')
```

The read-only integration starts an ephemeral app-server and uses
`account/read` with `refreshToken=false`, `account/rateLimits/read` with
`supportsLunaReserve=false` and `excludeResetCreditDetails=true`, and
`account/usage/read` with each selected `threadId`. It does not start or resume
a model turn, redeem earned resets, purchase credits, or send workspace emails.
Use an existing Codex sign-in; the report never includes authentication secrets
or the raw account/thread identifiers used by the requests.

Account quota percentages, reset windows, purchased/shared credit balances,
and earned rate-limit resets describe different quantities. A balance snapshot
is never summed across threads or subtracted to attribute a debit to one
session. Other users, concurrent threads, and eligible features can share the
same allowance or credit pool.

Official thread values are provider estimates, not actual billed debits. Keep
their exact integer micro-unit values and model/effort/speed groups separate
from the local token-derived credit equivalent. Missing thread estimates remain
explicit gaps. The parent/child inclusion scope of a provider estimate is
unverified; do not add parent and subagent estimates as a session bill or add
the same cost across these sources.

Codex CLI 0.157.1's generated native schema includes optional `threadUsage`
estimates. The [public app-server documentation](https://learn.chatgpt.com/docs/app-server)
describes account summaries and rate limits but does not yet document that
extension. An authenticated Pro read accepted a selected local thread request
but returned no `threadUsage` in the observed sample. The reason is unknown;
this does not establish a Pro exclusion or Enterprise-only availability.
Enterprise runtime behavior has not been verified.

Personal included allowance, paid credits, and an Enterprise agreement must
remain distinct. Enterprise can use credit-based or USD usage-based agreements.
Official [account methods](https://learn.chatgpt.com/docs/app-server),
[pricing](https://learn.chatgpt.com/docs/pricing), and
[workspace usage and cost guidance](https://learn.chatgpt.com/docs/enterprise/chatgpt-work-usage-and-cost)
describe these boundaries. Eligible Enterprise administrators have a separate
[Cost API reporting route](https://learn.chatgpt.com/docs/enterprise/work-admin-faq);
this command does not use that API or claim its session-level billing coverage.

## Company export and merge

Provision the same company-controlled key securely to exporters and the
authorized merge operator. Independently generated keys produce different
pseudonyms and cannot be merged as one company dataset. Never send the key
with a report, pass its value on the command line, place it in `.env`, or commit
it to the repository. `--key-file` supplies a local file reference.

Keep exported JSON reports in a company-controlled directory. The reviewed
default card selects `session-usage/v3`, with HMAC authentication, pseudonymous
session/response keys, response-level records, group/session summaries, and
signed pricing-policy provenance. Either optional usage flag adds signed
source-specific usage records while retaining v3. CSV includes summary rows
and, when requested, the optional source
records; retain JSON for validated merging and deduplication.

```powershell
py -3 scripts/toolkit.py session-usage --source-root $sourceRoot --key-file $keyFile --include-subagents --format json --output (Join-Path $reportDir 'company-export.json')
py -3 scripts/toolkit.py session-usage-merge --reports-root '<company-json-export-directory>' --key-file $keyFile --format json --output (Join-Path $reportDir 'company-summary.json')
py -3 scripts/toolkit.py session-usage-merge --reports-root '<company-json-export-directory>' --key-file $keyFile --format csv --output (Join-Path $reportDir 'company-summary.csv')
```

Merge validates each report's schema, HMAC, key identity, and rate-card digest.
It counts each response key once, including when a single-session export
overlaps an all-session export. Conflicting copies fail closed instead of
silently selecting a value. HMAC establishes integrity among holders of the
shared key; it does not make a report provider-authenticated usage or billing.
Merge accepts v1, v2, and v3 exports with their matching reviewed card. The
legacy card is archived at
[`config/session-usage/archives/openai-codex-credits-2026-10-01.json`](../config/session-usage/archives/openai-codex-credits-2026-10-01.json).
Use `--rate-card` with that card to merge old v1/v2 exports; their original
unpriced-reviewer semantics remain unchanged. Different card digests or policy
contracts cannot silently merge or reprice one another. Optional sources
deduplicate independently. Merge never adds account balances or official
estimates to local response cost totals.
Account snapshots deduplicate by exact `observation_key`. For each thread,
merge retains the newest official observation, including when that newest
observation is `unavailable`; conflicting observations at the same timestamp
fail closed. Optional diagnostic counters retain source-report maxima.

## Reading a report

The exact allowed fields are defined in
[`schemas/session-usage-report.schema.json`](../schemas/session-usage-report.schema.json).
Unknown fields are rejected on merge.

| Field | Meaning |
|---|---|
| `scope.selection`, `includes_subagents` | Selected session scope and descendant inclusion |
| `sessions[].status` | `observed`, `partial`, or `unsupported_source`; an unsupported session retains null usage |
| `responses[]`, `response_key` | Native response records and HMAC identity for overlap deduplication |
| `groups[]` | Totals by session/root, role, configured model, effort, and service tier |
| `configured_model_id`, `reasoning_effort`, `model_basis` | Reviewed configuration evidence, routing ambiguity, or unknown attribution |
| `actual_model_id` | Always `unmapped` in the local response ledger |
| `configured_service_tier`, `tier_basis` | Configured speed or the explicit `standard_assumption` |
| `estimated_credits`, `pricing_status`, `unpriced_tokens` | Decimal-string equivalent or null, with `priced`/`partial`/`unpriced`/`non_billable` coverage |
| `operation`, `operation_basis` | Bounded operation and its evidence; only exact `codex-auto-review` evidence identifies approval safety review |
| `charge_class`, `pricing_basis`, `non_billable_tokens` | Applied charge category and basis; observed non-billable tokens remain distinct from unknown-price tokens |
| `pricing_policy`, `pricing_policy_sha256` | Signed v3 policy, sources, verified date, scope, local activation, and digest |
| `summary.metadata_complete`, `pricing_complete`, `diagnostics` | Gaps that prevent treating observed totals as complete usage |
| `billing_status` | `actual_debit_unavailable` |

For v2/v3, the signed `usage_metrics` object has `account_snapshots`,
`thread_estimates`, and its own `diagnostics`. These do not change the local
response ledger or its pricing/completeness calculations.

| Optional field | Meaning |
|---|---|
| `account_snapshots[].source`, `scope` | `rollout` or `app_server`; always `account_quota` |
| `observed_at`, `observation_key` | UTC observation timestamp and HMAC identity for source deduplication |
| `observed_in_session_key` | Pseudonymous local thread where a rollout snapshot was seen; null for the live account read; not a charge attribution |
| `plan_type` | Allowlisted provider plan category or `unknown`; not proof of a billing agreement |
| `credits` | Nullable `{has_credits, unlimited, balance}`; balance is a decimal string or null |
| `primary`, `secondary` | Nullable `{used_percent, window_minutes, resets_at}`; reset time is Unix seconds |
| `ordinary_usage_allowed` | Nullable service-reported eligibility flag |
| `thread_estimates[].session_key`, `status` | Selected pseudonymous physical thread; `available` or `unavailable` |
| `estimate_kind`, `scope` | `provider_estimated_usage`, `thread_scope_unverified` |
| `estimated_usage_credits_micros`, `estimated_usage_usd_micros` | Exact integer micro-units when returned; missing values remain null |
| `thread_estimates[].groups` | Optional provider model/effort/speed breakdown with token counts and credit micro-units |
| `usage_metrics.diagnostics` | Invalid, duplicate, inherited, missing-snapshot, failed-request, or missing-official-estimate counts |

Each official group contains bounded `model_id`, `reasoning_effort`, `speed`,
nullable token fields (`net_new_input_tokens`, `cached_input_tokens`,
`input_tokens`, `output_tokens`, `total_tokens`), and integer
`estimated_usage_credits_micros`. These
are the provider estimate's grouping fields; they do not overwrite configured
local response attribution or prove an actual billed model or speed tier.

V2/v3 CSV adds `record_type` so each source is readable independently:

| Record type | Meaning |
|---|---|
| `local_estimate` | Local response group and public `estimated_credits` |
| `local_unavailable` | Local session with no supported response group |
| `account_snapshot` | Point-in-time account quota/credit observation |
| `official_thread_total` | Available thread estimate |
| `official_thread_group` | Breakdown of that thread estimate |
| `official_thread_unavailable` | No valid official thread estimate returned |

Official CSV rows keep `official_estimated_credits` separate from local
`estimated_credits`; it is the exact credit micro-unit value divided by one
million. Add `--format csv` to either optional export command for this view.
Do not sum a thread total with its groups, or totals across unverified
parent/child scope. CSV is not an import ledger and is not accepted by merge.
V3 CSV also carries operation, charge class, non-billable tokens, pricing
basis, and policy version/digest/scope/source/activation provenance. These
fields do not turn provider estimates or balance rows into local billing.

Summary token totals cover accepted records only. A partial total is not a
complete session bill. Merged source diagnostic counters retain the maximum
reported count rather than pretending overlapping diagnostic counts are
company-wide sums; derived session totals are recomputed.

## Source and attribution boundaries

The local response ledger supports a top-level `token_usage_record` with the six
numeric usage fields under `payload.usage`. Cumulative token counts are
ignored, including when optional account snapshots are enabled. Older or
unsupported formats yield missing/partial coverage and null
usage or estimates; absence is not fabricated as zero consumption.

The native `thread_token_usage` checkpoint is used only to reconcile a physical
thread's accepted response deltas. A missing or mismatched checkpoint sets
`unverified_thread_totals` and partial metadata coverage; it is not substituted
for missing response usage.

The six fields are `input_tokens`, `cached_input_tokens`,
`cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens`, and
`total_tokens`. Cached and cache-write input are subsets of input. The
uncached class is `input - cached_input - cache_write_input`; the report
prices those non-overlapping input classes and output once.

A response record follows the native usage boundary. It is not necessarily
one user-visible assistant message or one submitted prompt: tool use and
other model operations can create additional responses. Do not add reasoning
output tokens to output tokens again; reasoning tokens are a diagnostic
subset. Repeated or overlapping exports must not be added before deduplication.

Model and reasoning effort describe the configuration associated with the
usage record. They do not prove the model or effort actually used after
provider routing. `actual_model_id` remains `unmapped`; an explicit reroute
event makes the affected turn's attribution ambiguous and unpriced. Missing
configuration or an unknown model must remain visible in coverage/status
fields. Reasoning effort has no separately inferred credit multiplier.

## Credit estimate

The default reviewed card is
[`config/session-usage/codex-credit-rates.json`](../config/session-usage/codex-credit-rates.json).
Its version is `openai-codex-credits-2026-10-07` using card schema v2. It is a
read-back snapshot of the
[official public token rates](https://learn.chatgpt.com/docs/pricing#token-rates),
not a claim about a historical effective date or an Enterprise agreement.
Use `--rate-card <reviewed-json>` on export and merge to select another reviewed
card; merged reports must match the selected card's digest.

The reviewed [ChatGPT credit rate card](https://help.openai.com/en/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing)
exempts approval safety auto-review when signed in with a ChatGPT account.
V3 records `operation=approval_auto_review` only from the exact
`codex-auto-review` source signal, with `operation_basis=codex_auto_review_signal`.
An `approval_reviewer` role alone does not qualify. The supported policy scope
is `chatgpt_personal_and_enterprise_credits`; it does not establish API-key or
Enterprise USD contract billing, and the report performs no new sign-in probe.

The policy has `verified_on=2026-10-07`, `official_effective_from=null`, and
`local_activation=2026-10-07T13:21:21Z`. The local activation is the start of
this toolkit's policy application, not an asserted OpenAI effective date.
Only matching approval operations at or after that boundary become
`charge_class=non_billable`, `pricing_status=non_billable`, with a `"0"`
credit equivalent and their observed usage in `non_billable_tokens`. Earlier
reviewer records remain unpriced. The actual model remains `unmapped`, and
missing model metadata can still make metadata completeness partial even
when non-billable pricing coverage is complete. No unknown model, generic
subagent, local `/review`, or GitHub PR review receives this exemption.
See [official verification and limitations](PRICING-REVIEW-2026-10-07.md).

| Configured model | Input | Cached input | Output |
|---|---:|---:|---:|
| `gpt-5.6-sol` | 100 | 10 | 500 |
| `gpt-5.6-terra` | 50 | 5 | 300 |
| `gpt-5.6-luna` | 5 | 0.5 | 30 |
| `gpt-6-astra` | 250 | 25 | 1,250 |
| `gpt-6-sol` | 50 | 5 | 250 |
| `gpt-6-luna` | 2.5 | 0.25 | 12.5 |
| `gpt-6.1-sol` | 50 | 2.5 | 250 |

Values are Standard credits per million tokens. For the published three
classes, the estimate multiplies non-overlapping token counts by the matching
rates and divides by one million. Cache-write tokens have no separate
published credit charge and stay outside this estimate, with their unpriced
coverage visible. Unknown or ambiguous model attribution has no guessed rate.

For example, GPT-6.1 Sol at Standard with 10,000 input tokens, including 6,000
cached and 1,000 cache-write tokens, plus 2,000 output tokens gives
`(3000 × 50 + 6000 × 2.5 + 2000 × 250) / 1000000 = 0.665` credits equivalent.
The 1,000 cache-write tokens stay visible as unpriced, so pricing coverage is
partial even though the three-class estimate is available.

Configured `standard`/`default` uses 1x; `fast`/`priority` uses the published 2x
purchased-credit/Enterprise pay-as-you-go multiplier. Configured Astra
`ultrafast` uses 6x. A missing or unrecognized tier produces an explicitly assumed
Standard-equivalent estimate. Configuration does not prove the tier was
honored. Included subscription limits use different multipliers: Fast 2.5x
and Astra Ultrafast 8x. The report does not estimate remaining included
allowance, an actual credit debit, API USD, or a greater-than-272K API premium.

The session report's reviewed GPT-5.6 Sol row is 100/10/500. The older
Prometheus rate cards retain their dated historical snapshots, including
125/12.5/750 in `openai-codex-credits-2026-08-12`. Do not combine outputs with
different cards or silently reinterpret old versions. See
[cost attribution](COST-ATTRIBUTION.md) for the aggregate dashboard contract.

Saved signed reports keep their selected card, policy, digest, and calculated
equivalents when a later default card changes. Re-exporting old rollouts is a
new estimate under the explicitly selected card; no per-response historical
rate is inferred from the card's read-back date. Preserve the original report
or select its archived card when reproducing an earlier estimate. The
2026-10-07 default card is also archived as an immutable snapshot.

## Privacy and operation

Only reviewed metadata is retained: HMAC linkage, UTC timestamps, bounded
configuration/status fields, usage numbers, coverage, and rate-card/estimate
metadata. Raw session/response identifiers are used only for local selection,
membership, and pseudonym generation. Reports exclude prompts, assistant or
reasoning text, tool payloads, source code, command output, absolute paths,
user/account identity, and credentials. Unknown fields are not copied.

Session, response, and observation keys are high-cardinality report fields.
Neither raw IDs nor their HMAC forms may become Prometheus labels or Loki index labels.
Reports do not upload to a central service or create a source archive.

Company rollout still requires the existing data-owner/security review, user
notice, access controls, retention/deletion rules, and key management described
in [privacy policy](PRIVACY.md). This command provides the file format and
local minimization boundary; it does not deploy those organizational controls.
Rotate keys through that policy and keep reports separated by key identity.
