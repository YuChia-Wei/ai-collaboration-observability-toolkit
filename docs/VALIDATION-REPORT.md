# Validation report

## Metadata

- Version: 0.1.4
- Date: 2026-08-09
- Host: Windows, PowerShell, Python 3.13.14
- Runtime: Docker Desktop

## Result summary

| Gate | Result | Evidence |
| --- | --- | --- |
| Repository policy and merged Compose | PASS | `python scripts/toolkit.py validate --mode all`; Core, Corporate, Evaluation |
| Python unit tests | PASS | 34 discovered: 33 passed, 1 Windows-only POSIX executable-bit check skipped |
| Shell/PowerShell syntax | PASS | Git Bash `bash -n`; PowerShell parser in toolkit validation |
| Collector native config | PASS | pinned 0.158.0 image; Core, Evaluation, Corporate |
| Prometheus/Loki/Tempo native config | PASS | pinned 3.13.2, 3.7.6, and 3.0.2 images |
| Evaluation readiness | PASS | all seven services ready |
| Evaluation privacy and reconciliation | PASS | sentinels absent; raw/canonical token histogram sums both 1536 |
| Phoenix hybrid routing | PASS | missing/true present; header false absent; legacy resource true/false retained |
| Routing metadata cleanup | PASS | header name and temporary attribute absent from Phoenix payloads |
| Evaluation persistence | PASS | five owner volumes retained; data queryable after service restarts |
| Corporate isolation | PASS | alternate ports/project; five services; no Phoenix |
| Corporate privacy/persistence | PASS | privacy and reconciliation repeated after restart |
| Corporate test cleanup | PASS | exact test containers, network, and four test volumes removed |
| Hosted PR CI | PASS | PR #13 run 31296145054: repository policy, native validators, unit tests, Core runtime/persistence, artifacts, cleanup |
| Historical data erasure | NOT EXECUTED | not required; no owner Evaluation volume was deleted |

## Runtime routing assertions

Every Evaluation routing fixture was present in Tempo. Phoenix contained the
missing-header, header-true, and legacy resource-true fixtures. It did not
contain the header-false or legacy resource-false fixtures. All positive cases
remained queryable after restarting Collector, Prometheus, Loki, Tempo,
PostgreSQL, and Phoenix.

Structured local reports were written to:

- `artifacts/smoke/v0.1.4-evaluation.json`
- `artifacts/smoke/v0.1.4-corporate.json`

The artifacts directory is intentionally ignored; this document records the
release evidence without committing runtime-local details.

## Release sequence

Local implementation, runtime, and initial hosted PR CI gates are closed.
Merge, annotated tag, GitHub Release, Issue/Project read-back, and final
deployment from merged main remain distinct release gates until each occurs.
