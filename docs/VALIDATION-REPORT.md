# Validation report

## Metadata

- Version: 0.1.5
- Date: 2026-08-09
- Host: Windows, PowerShell, Python 3.13
- Runtime: Docker Desktop

## Result summary

| Gate | Result | Evidence |
| --- | --- | --- |
| Repository policy and merged Compose | PASS | `python scripts/toolkit.py validate --mode all`; Core, Corporate, Evaluation |
| Python unit tests | PASS | 36 discovered: 35 passed, 1 Windows-only POSIX executable-bit check skipped |
| Dashboard JSON and provisioning | PASS | six UIDs preserved; all panels zh-TW-first |
| Dashboard query contract | PASS | all 44 PromQL expressions equal to the v0.1.4/main baseline |
| Collector native config | PASS | pinned 0.158.0 image; Core, Evaluation, Corporate |
| Prometheus/Loki/Tempo native config | PASS | pinned 3.13.2, 3.7.6, and 3.0.2 images |
| Evaluation readiness | PASS | all seven services ready |
| Evaluation privacy and reconciliation | PASS | sentinels absent; raw/canonical token histogram sums both 1536 |
| Grafana runtime dashboards | PASS | six provisioned zh-TW dashboard titles before and after restart |
| Phoenix hybrid routing | PASS | missing/true present; header false absent; legacy resource true/false retained |
| Evaluation persistence | PASS | five owner volumes retained; data queryable after service restarts |
| Phoenix annotation rubric | PASS | five configs created/assigned idempotently; read-only check passed after restart |
| Browser visual QA | PASS | all six dashboards loaded expected panel headings; no console error |
| Hosted PR CI | PENDING | recorded after the implementation branch is pushed |
| Core hosted runtime | PENDING | part of the required PR validation workflow |
| Historical data erasure | NOT EXECUTED | not required; no owner data was deleted or rewritten |

## Runtime assertions

Every Evaluation routing fixture was present in Tempo. Phoenix contained the missing-header,
header-true, and legacy resource-true fixtures. It did not contain the header-false or legacy
resource-false fixtures. All positive cases, six Grafana dashboards, and the annotation rubric
remained queryable after the persistence restart.

Structured local evidence was written to:

- `artifacts/smoke/v0.1.5-evaluation.json`

The artifacts directory is intentionally ignored; this document records the release evidence
without committing runtime-local details.

## Publication sequence

Local implementation and runtime gates are closed. Hosted PR CI, merge, annotated tag, GitHub
Release, Issue/Project read-back, and final deployment from merged main remain separate release gates
until each is observed.
