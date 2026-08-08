# Changelog

All notable changes to this project will be documented here.

## [0.1.2] - 2026-08-08

### Added

- Personal and corporate direct-Hooks examples for Windows and POSIX.
- Antigravity CLI custom status-line fragments for observed model, token/context, quota, task,
  artifact, pending-input, approval, and agent-state metadata.
- One standard-library OTLP/HTTP exporter with local HMAC session pseudonyms, corporate no-session
  mode, non-interfering Hook responses, status deduplication, and offline capture.
- Sanitized documented Hook/status fixtures, privacy tests, a local OTLP wire test, and the
  **Antigravity Usage (observed, not billing)** Grafana dashboard.

### Changed

- Antigravity integration uses one direct-Hooks route only; a second packaged Plugin Hooks route is
  intentionally excluded to prevent duplicate lifecycle events.
- `PostToolUse` classification comes from explicit matchers. The exporter never reads `toolCall` and
  uses raw errors only as a boolean outcome.
- Lifecycle model metadata uses documented Hook `modelName`; CLI status uses its documented `model`
  object.
- Static validation checks direct Hook/status variants, dashboard queries, exporter syntax, and
  sensitive-field exclusion.
- Dashboard inventory increased from four to five.

## [0.1.1] - 2026-08-08

### Added

- Initial metadata-only Antigravity Hooks proof of concept.

## [0.1.0] - 2026-08-07

### Added

- Core Grafana/Loki/Tempo/Prometheus mode behind one OpenTelemetry Collector ingress.
- Optional Phoenix/PostgreSQL evaluation mode with explicit trace opt-in.
- Corporate metadata allowlist mode with no Phoenix or external exporter.
- Codex, Claude Code, and GitHub Copilot integration guidance.
- Provisioned Grafana datasources and initial AI usage/workflow dashboards.
- Synthetic OTLP fixtures, sentinel privacy assertions, and persistence checks.
- Cross-platform Python operations with Bash/PowerShell wrappers.
- Static/native/runtime GitHub Actions validation design.
- Architecture, privacy, data-contract, cost-attribution, operations, ADR, and roadmap documentation.
