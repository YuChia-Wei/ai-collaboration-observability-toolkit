# Codex session usage reports

The opt-in `session-usage` command reads a locally selected Codex rollout
directory and reports configured model, reasoning effort, provider-reported
response token usage, and estimated public credit equivalents. It writes a
metadata-only JSON or CSV report for local review and company aggregation.

It runs without Docker or a network connection. It does not change Codex
configuration, Collector pipelines, dashboards, or running services. Reports
are separate from the aggregate Prometheus accounting contract.

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

## Company export and merge

Provision the same company-controlled key securely to exporters and the
authorized merge operator. Independently generated keys produce different
pseudonyms and cannot be merged as one company dataset. Never send the key
with a report, pass its value on the command line, place it in `.env`, or commit
it to the repository. `--key-file` supplies a local file reference.

Keep exported JSON reports in a company-controlled directory. JSON uses
`session-usage/v1`, with HMAC authentication, pseudonymous session/response
keys, response-level records, and group/session summaries. CSV is a summary
view for review; retain JSON for validated merging and deduplication.

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
| `actual_model_id` | Always `unmapped` in this contract |
| `configured_service_tier`, `tier_basis` | Configured speed or the explicit `standard_assumption` |
| `estimated_credits`, `pricing_status`, `unpriced_tokens` | Decimal-string equivalent or null, with `priced`/`partial`/`unpriced` coverage |
| `summary.metadata_complete`, `pricing_complete`, `diagnostics` | Gaps that prevent treating observed totals as complete usage |
| `billing_status` | `actual_debit_unavailable` |

Summary token totals cover accepted records only. A partial total is not a
complete session bill. Merged source diagnostic counters retain the maximum
reported count rather than pretending overlapping diagnostic counts are
company-wide sums; derived session totals are recomputed.

## Source and attribution boundaries

The supported usage source is a top-level `token_usage_record` with the six
numeric usage fields under `payload.usage`. Cumulative token snapshots are
ignored. Older or unsupported formats yield missing/partial coverage and null
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
Its version is `openai-codex-credits-2026-10-01`. It is a read-back snapshot of
the [official public token rates](https://learn.chatgpt.com/docs/pricing#token-rates),
not a claim about a historical effective date or an Enterprise agreement.
Use `--rate-card <reviewed-json>` on export and merge to select another reviewed
card; merged reports must match the selected card's digest.

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

The session report's current GPT-5.6 Sol row is 100/10/500. The older
Prometheus rate cards retain their dated historical snapshots, including
125/12.5/750 in `openai-codex-credits-2026-08-12`. Do not combine outputs with
different cards or silently reinterpret old versions. See
[cost attribution](COST-ATTRIBUTION.md) for the aggregate dashboard contract.

## Privacy and operation

Only reviewed metadata is retained: HMAC linkage, UTC timestamps, bounded
configuration/status fields, usage numbers, coverage, and rate-card/estimate
metadata. Raw session/response identifiers are used only for local selection,
membership, and pseudonym generation. Reports exclude prompts, assistant or
reasoning text, tool payloads, source code, command output, absolute paths,
user/account identity, and credentials. Unknown fields are not copied.

Session and response keys are high-cardinality report fields. Neither raw IDs
nor their HMAC forms may become Prometheus labels or Loki index labels.
Reports do not upload to a central service or create a source archive.

Company rollout still requires the existing data-owner/security review, user
notice, access controls, retention/deletion rules, and key management described
in [privacy policy](PRIVACY.md). This command provides the file format and
local minimization boundary; it does not deploy those organizational controls.
Rotate keys through that policy and keep reports separated by key identity.
