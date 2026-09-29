# v0.2.0 release readiness

Review date: 2026-09-29. Local implementation and runtime acceptance are complete.
The release commit, hosted CI result, and remote annotated tag readback are recorded
in [release tracker #8](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/8).
This document does not claim a GitHub Release was published.

## Candidate scope

Restricted backend ports, provider usage/accounting and dashboards, a five-service
Corporate profile with a 1664 MiB aggregate container memory limit, shorter retention,
pinned patch upgrades, finite attribution values, and removal of source archive.
Phoenix/PostgreSQL remain optional in Evaluation; Corporate includes neither.
See [dependency assessment](DEPENDENCY-REVIEW-v0.2.0.md) and
[company deployment guide](COMPANY-LOW-RESOURCE.md).

## Observed validation

| Check | Result | Scope |
| --- | --- | --- |
| Repository policy / Compose | PASS | All three modes, with and without debug overlay |
| Unit tests | PASS: 57 passed, 1 skipped out of 58 | Windows POSIX executable-bit check skipped; archive-only tests removed with the retired component |
| Native configuration validators | PASS | Pinned Collector image validates all modes; pinned Prometheus, Loki and Tempo images validate normal and Corporate configs |
| Core, Corporate, Evaluation runtime | PASS | Actual isolated Docker stacks; ingestion, privacy, accounting, dashboards and mode-specific routing assertions |
| Restart persistence | PASS in all three modes | Backend data survives actual container restart |
| Arbitrary attribution negative checks | PASS in all three modes | Sensitive synthetic skill/MCP names absent from raw/canonical labels; 4720-token totals preserved; Corporate removes attribution |
| Actual container topology | PASS | Five services in Core/Corporate, seven in Evaluation; no archive, no backend host bindings, no observed OOM |
| Corporate resource constraints | PASS | Docker inspect confirms memory/swap limits; fresh synthetic workload snapshot approximately 344 MiB across five services |
| Existing personal deployment upgrade | NOT EXECUTED | Existing containers and volumes retained; isolated tests do not deploy the new profile to personal or company systems |

Runtime reports are local ignored artifacts: `artifacts/v020-{mode}-smoke.json`,
`artifacts/v020-{mode}-resources.json`, and the corresponding run logs. Hosted CI
uploads its own independently produced runtime evidence. Docker/WSL overhead is
excluded from the memory figures; small synthetic data is not a representative
company workload or a controlled before/after performance comparison.

## Real-data accounting observation (#22)

A read-only query of the existing personal stack at 2026-09-29T14:45:53Z examined
a 48-hour window excluding fixture namespaces. Available samples span about
46.9 hours. Primary/reviewer token classes were present; current accounting keys
had at most one series, no negative token classes or priced unknown models were
observed, and recording-rule failures did not increase in the queried window.
The local summary is `artifacts/v020-accounting-observation.json`.
This is sampled real usage, not proof of uninterrupted 48-hour uptime or company
workload coverage. Deterministic token reconciliation additionally passed in each
isolated mode. Exact Claude client/version provenance remains follow-up #9.

## Migration limits

The old source archive volume (about 18.8 GiB in the observed personal deployment)
was not deleted and no disk space is claimed reclaimed. Shorter retention can
expire existing data after deployment; back up needed data and merge existing
`.env` image overrides with the new pinned defaults before upgrading. Evaluation
PostgreSQL stays on major 18; read its patch migration notes before reusing data.

## Issue disposition

All 11 open issues were reviewed against current source, docs, tests, and online
bodies. Closed historical issues remain unchanged. Decisions below distinguish
delivered implementation from obsolete planning and outstanding acceptance.

| Issue | Disposition | Reason / next bounded work |
| --- | --- | --- |
| [#4](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/4) | Close, not planned | Framework-owned runtime emitters and old v0.2.0 grouping conflict with ADR 0004. Reopen only around a real runtime/hook producer and one bounded workflow. |
| [#5](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/5) | Close, not planned | Full evaluator/experiment loop depends on unavailable #4 evidence; Hooks/routing do not satisfy it. Reopen with a curated dataset, deterministic evaluator, budget, and owner. |
| [#6](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/6) | Keep, conditional post-0.2.0 | Aggregate feedback export / official CSV reconciliation may be useful; require data authority and a bounded slice. Remove obsolete version reservations. |
| [#7](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/7) | Keep, deferred proposal | Compare only if measured resource/query pain justifies it; retaining LGTM is valid. No dependency on an assumed v0.3.0 loop. |
| [#8](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/8) | Release tracking | Corporate low-resource profile, source archive removal, exact release commit CI and tag readback. |
| [#9](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/9) | Keep, first follow-up | Mapping exists; capture exact Claude CLI/Desktop versions and sanitized provenance, reconcile real input with fixture semantics. Do not repeat baseline implementation. |
| [#10](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/10) | Keep, follow-up | Choose a supported Copilot surface, acquire authorized fixture, then decide adapter. Missing signals remain unavailable. |
| [#21](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/21) | Close, completed baseline | Phoenix 20.0.0 nonroot pin/docs/tests are in main; #22 records prior isolated upgrade/persistence evidence. This does not assert it is today's newest upstream release. |
| [#22](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/22) | Acceptance completed | Real-data observation spans approximately 46.9 hours; fixture accounting and restart persistence pass in all three modes. See limits below. |
| [#23](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/23) | Close, completed | `7edac47`, size-only opt-in, default no-read, UTF-8 measurement, Corporate rejection, privacy and wire tests. |
| [#24](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/24) | Acceptance completed | Finite skill/MCP values are enforced before raw/canonical export; adversarial runtime checks pass in all three modes. Exact-client provenance remains #9. |

Issue closure is not publication, and not-planned closure is not implementation
completion. No follow-up minor/patch version is reserved by this review.
