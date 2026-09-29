# Roadmap

## v0.1.3 — Observability Baseline Stabilization

- Versioned Codex 0.146.1 telemetry fixture and semantic mapping.
- Initial privacy denylist plus final mode-specific policy.
- Additive ai_agent.* normalization with native telemetry retained.
- Antigravity canonical alignment and truthful provider support matrix.
- Separate Codex Native, AI Agent Usage, and AI Context dashboards.
- Docker Compose as the primary runtime; Python remains an optional validation
  and operations convenience.

## v0.1.4 — Phoenix Routing Compatibility

- Evaluation forwards already-redacted traces to Phoenix by default.
- OTLP header and legacy resource-attribute opt-outs remain explicit and tested.
- Header-derived routing metadata is removed before persistence.

## v0.1.5 — Human-readable Observability

- Make all six Grafana dashboards zh-TW-first without changing UIDs, PromQL, or telemetry contracts.
- Add a Traditional Chinese Phoenix reading guide and bilingual telemetry glossary.
- Provision an idempotent Chinese operational annotation rubric through the pinned Phoenix REST API.
- Close the planned 0.1.x line; subsequent feature planning targets v0.2.0.

## v0.2.0 — Privacy-first agent usage for constrained workstations

- Candidate scope: role-aware token accounting, separate API USD/Codex credits,
  GPT-6 mappings, usage/activity/context views, optional metadata-only Hooks,
  explicit size-only proxies, and a bounded five-service company profile.
- Source archive services and pipelines are removed; old volumes are retained.
- Default backend APIs remain internal; normal operations use Grafana proxy,
  with an explicit loopback-only debug overlay.
- Phoenix 20.0.0 remains Evaluation-only and receives redacted OpenInference
  spans; generic agent-internal traces remain in Tempo.
- See [release notes](RELEASE-NOTES-v0.2.0.md)
  and [readiness / issue review](RELEASE-READINESS-v0.2.0.md).
- #8 tracks release closeout; #22 real-data observation and #24 attribution
  bounds are recorded in the readiness report with their evidence limitations.
- Old #4/#5 improvement-loop scopes are closed as not planned, not completed.
  Reopening requires a real producer, bounded workflow/dataset, deterministic
  evaluator, privacy review, and experiment ownership/budget.

## Delivered baseline: Issue #18 — Actionable usage and activity views

- Retire the two no-source AI Context dashboards while preserving the reserved
  schema/fixture contract.
- Make AI Agent Usage lead with telemetry freshness and selected-range
  token/cost/turn/coverage/cache evidence.
- Add an AI Agent Activity dashboard for metadata-only prompt/tool/API/sandbox
  logs and Tempo trace correlation.
- Filter generic non-OpenInference spans out of Phoenix without deleting
  historical PostgreSQL/Phoenix data.

## After v0.2.0: follow-up priorities

- First, #9: strengthen the implemented Claude metrics baseline with exact
  CLI/Desktop client versions, sanitized real-capture provenance, and
  native/canonical reconciliation. Existing deterministic fixtures are not
  proof of version-pinned production capture.
- Next, #10: choose an authorized Copilot telemetry/API surface and obtain a
  reproducible fixture before implementing an adapter.
- #6 remains conditional: begin with bounded aggregate feedback export or
  authorized official CSV reconciliation, not the entire company platform.
- #7 remains a deferred comparison proposal, justified only by measured pain
  and an approved workload/budget. Keeping LGTM is an acceptable outcome.
- No patch/minor versions are reserved. New mapping, fixture, and rate-card
  maintenance should follow observed evidence and preserve privacy boundaries.
- Company showback, billing reconciliation, and task-level cost attribution
  remain later horizons and require authoritative inputs.
