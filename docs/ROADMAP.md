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

## v0.2.0 — AI Collaboration Improvement Loop

- Issue #4 requires re-scoping around a deterministic runtime-owned emitter,
  orchestrator, or client hook. The framework harness itself is not expected to
  observe model execution. Provider-native telemetry and prompt self-reports do not satisfy the
  effectiveness evidence contract; no AI Context dashboard is provisioned until
  a real emitter is available.
- Issue #5 remains downstream of compatible application/framework traces and
  meaningful outputs. Phoenix receives only already-redacted spans with an
  OpenInference span kind; generic agent-internal traces remain in Tempo.

## Issue #18 — Actionable usage and activity views

- Retire the two no-source AI Context dashboards while preserving the reserved
  schema/fixture contract.
- Make AI Agent Usage lead with telemetry freshness and selected-range
  token/cost/turn/coverage/cache evidence.
- Add an AI Agent Activity dashboard for metadata-only prompt/tool/API/sandbox
  logs and Tempo trace correlation.
- Filter generic non-OpenInference spans out of Phoenix without deleting
  historical PostgreSQL/Phoenix data.

## Unassigned and later horizons

- Issue #6 remains unassigned until an Owner allocates it.
- Issue #7 remains a deferred proposal.
- Claude Code has a privacy-reviewed native metrics baseline. GitHub Copilot
  normalization still requires a separate version-pinned fixture and follow-up
  Issue; documentation does not count as support.
- Company showback, billing reconciliation, and task-level cost attribution
  remain later horizons and require authoritative inputs.
