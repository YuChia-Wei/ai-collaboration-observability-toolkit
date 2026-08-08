# Initial implementation report

## Scope delivered

Version `0.1.0` implements the first executable baseline from
[`IMPLEMENTATION-BRIEF.md`](IMPLEMENTATION-BRIEF.md):

- Core, evaluation, and corporate Docker Compose modes.
- One host-facing OpenTelemetry Collector ingress.
- Prometheus, Loki, Tempo, Grafana, optional Phoenix, and PostgreSQL with exact image defaults.
- Fail-closed Collector transforms, bounded metric labels, native Loki OTLP ingestion, and explicit
  Phoenix trace selection.
- PostgreSQL 18 persistence mounted at `/var/lib/postgresql`.
- Provisioned Grafana datasources and four initial dashboards.
- Codex configuration examples and Claude Code/Copilot integration notes.
- Version 0.1.1 adds an Antigravity JSON Hooks plugin with metadata-only OTLP/HTTP export.
- Synthetic OTLP fixtures with positive and negative Phoenix routes plus privacy sentinel assertions.
- Cross-platform operations, static policy validation, native-validator hooks, runtime smoke tests,
  and GitHub Actions workflows.
- Architecture, privacy, data-contract, cost-attribution, operations, ADR, and roadmap documentation.

## Validation performed in the generation environment

| Validation | Status | Evidence |
| --- | --- | --- |
| YAML/JSON/TOML parsing and duplicate-key rejection | PASS | `python scripts/toolkit.py validate --mode all --static-only` |
| Repository policy, local Markdown links, schemas, dashboards, fixtures | PASS | Same static validator |
| Python syntax | PASS | `python -m py_compile scripts/toolkit.py` |
| Repository unit tests | PASS | 27 tests through `python -m unittest discover -s tests -v` |
| Bash syntax | PASS | `bash -n scripts/*.sh` |
| Docker Compose merged configuration | NOT EXECUTED | Docker CLI/daemon unavailable in the generation environment |
| Collector native configuration | NOT EXECUTED | Container runtime unavailable locally; CI runs the pinned Collector image |
| Prometheus/Loki/Tempo native configuration | NOT EXECUTED | Container runtime unavailable locally; CI runs their pinned images |
| Core runtime smoke and persistence | NOT EXECUTED | Docker daemon unavailable |
| Corporate runtime smoke and privacy assertions | NOT EXECUTED | Docker daemon unavailable |
| Evaluation/Phoenix routing smoke | NOT EXECUTED | Docker daemon unavailable |
| PowerShell parser/runtime | NOT EXECUTED | PowerShell unavailable in the generation environment |

The external validation report distributed beside the ZIP and Git bundle records the final artifact
hashes and packaging checks.

## Design corrections made during implementation

1. OTTL regular expressions are checked after YAML parsing so escaping cannot silently change their
   meaning.
2. Every privacy transform and the Phoenix selection filter uses `error_mode: propagate`; a transform
   failure stops the affected pipeline rather than bypassing minimization.
3. Prometheus exporter settings suppress scope labels and use a deterministic translation strategy.
4. Loki indexes only four approved low-cardinality resource attributes; all remaining OTLP metadata
   stays structured rather than becoming index labels.
5. PostgreSQL 18 uses the official version-aware volume root `/var/lib/postgresql`.
6. Runtime reports distinguish `PASS`, `FAIL`, and `SKIP`; unavailable checks are never represented as
   successful.

## Version 0.1.1 follow-up

The Antigravity integration is intentionally passive: it uses `PreInvocation`, `PostInvocation`,
`PostToolUse`, and `Stop`, but not `PreToolUse`, because a pre-tool hook must return a permission
decision and could change the user's security behavior. The bridge never reads transcript or tool
payload files and does not claim token or credit telemetry that the hook contract does not expose.

## Known limitations

1. Native AI-client telemetry schemas can change. Codex has committed examples, but the installed
   client version still needs a local end-to-end check.
2. Rich framework-effectiveness dashboards require `ai_context.*` instrumentation from the source
   framework and downstream projects.
3. Phoenix REST smoke verification is coupled to its current project/spans API and must be reviewed
   during Phoenix upgrades.
4. Corporate mode is a technical metadata-minimization baseline, not organizational approval.
5. Official ChatGPT Enterprise credit reconciliation and multi-user authorization are not included.
6. Storage is workstation-oriented filesystem persistence with no automated backup or high availability.
