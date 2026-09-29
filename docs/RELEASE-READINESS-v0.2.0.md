# v0.2.0 preparation and issue review

Review date: 2026-09-29. Status: preparation complete only after the accompanying
local commits; publication and release freeze remain pending.

## Candidate boundary

The reviewed remote baseline is `f01f21b6d6400bf0231c4ef4820af8d1b3047709`,
15 commits after v0.1.5. Local commit `a2ae304` adds restricted default backend
ports, Grafana proxy operations, tests, and synchronized documentation.
The release documentation commit is the commit containing this report. It is
not yet a hosted release candidate; no tag or Release has been created.

## Evidence and remaining gates

| Check | Observed result | Scope / remaining work |
| --- | --- | --- |
| Repository policy / Compose | PASS on 2026-09-29 | All three modes, with and without debug overlay |
| Unit tests | PASS: 86 passed, 1 skipped out of 87 | Windows POSIX executable-bit check is not applicable; sandbox permission failure cleared on host rerun |
| Evaluation quick smoke | PASS on 2026-09-29 | Existing stack; Grafana proxy, privacy, accounting, dashboards, Phoenix routing; local report `artifacts/smoke/20260929T141408Z-evaluation.json` |
| Current main hosted Core gate | PASS at `f01f21b` | [Run 36028779246](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/actions/runs/36028779246); does not cover later local commits |
| Native backend validators locally | NOT EXECUTED | Required binaries were not configured; Compose parsing is not native validation |
| New default topology applied | NOT EXECUTED | Current stack still publishes 9090/3100/3200; maintenance rollout remains deferred |
| Final candidate Core/Corporate runtime | NOT EXECUTED | Must run against the eventual clean candidate |
| Final candidate restart persistence | NOT EXECUTED | Quick smoke deliberately did not restart existing services |
| Final candidate source-archive persistence | NOT EXECUTED | Historical implementation/unit evidence is not new candidate runtime acceptance |
| Representative role/accounting observation | OPEN (#22) | Record a representative 24–48h real-data window; elapsed calendar time and fixture smoke do not prove it |
| Claude attribution bounds | OPEN (#24) | Core/Evaluation copy provider skill/MCP names into labels; finite value enforcement is not demonstrated |

Before tagging: resolve #24's accepted-input/value-bound policy and regression
evidence, complete #22 observation, validate the final clean commit in all
required modes (including persistence/native checks), and attach that evidence
to #8. Tag/Release publication is a separate action. Do not turn skipped checks
or a previous commit's successful CI into a current-candidate pass.

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
| [#8](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/8) | Keep, release tracking | Refresh scope to usage/source evidence and retain open candidate gates. |
| [#9](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/9) | Keep, first follow-up | Mapping exists; capture exact Claude CLI/Desktop versions and sanitized provenance, reconcile real input with fixture semantics. Do not repeat baseline implementation. |
| [#10](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/10) | Keep, follow-up | Choose a supported Copilot surface, acquire authorized fixture, then decide adapter. Missing signals remain unavailable. |
| [#21](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/21) | Close, completed baseline | Phoenix 20.0.0 nonroot pin/docs/tests are in main; #22 records prior isolated upgrade/persistence evidence. This does not assert it is today's newest upstream release. |
| [#22](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/22) | Keep, release acceptance | Implementation is present and fixture smoke passes; representative production observation remains unverified. |
| [#23](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/23) | Close, completed | `7edac47`, size-only opt-in, default no-read, UTF-8 measurement, Corporate rejection, privacy and wire tests. |
| [#24](https://github.com/YuChia-Wei/ai-collaboration-observability-toolkit/issues/24) | Keep, acceptance gap | `cffd3e5` delivers mapping/dashboard/Hooks; arbitrary provider skill/MCP values are copied without an explicit finite allowlist. Keep bounding/negative tests open before publication. |

Issue closure is not publication, and not-planned closure is not implementation
completion. No follow-up minor/patch version is reserved by this review.
