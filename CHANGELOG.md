# Changelog

All notable changes to this project will be documented here.

## [0.1.4] - 2026-08-09

### Changed

- Made already-redacted Evaluation traces route to Phoenix by default so
  clients without custom resource attributes still produce useful evaluation
  data.
- Added `x-ai-observability-phoenix` OTLP request-header routing: missing or
  `true` forwards, while `false` opts out.
- Preserved the legacy boolean `ai_context.export.phoenix` resource contract;
  explicit `false` remains an opt-out.
- Changed the Antigravity exporter to omit the legacy attribute by default and
  retain `--phoenix`/`--no-phoenix` as explicit overrides.

### Privacy and validation

- Kept privacy transforms ahead of Phoenix routing and deleted temporary
  header-derived routing metadata before export.
- Added deterministic runtime fixtures for missing-header, header-true, and
  header-false behavior, including Tempo continuity and Phoenix positive/
  negative assertions.
- Core and Corporate remain unchanged and expose no Phoenix route.

## [0.1.3] - 2026-08-09

### Added

- Versioned Codex CLI 0.146.1/app-server 0.147.0-alpha.6.5 privacy-safe
  metrics, logs, and traces fixture with raw-to-canonical mapping.
- Provider support matrix and canonical AI Agent Usage dashboard.
- Initial privacy denylist before normalization in Core, Evaluation, and
  Corporate Collector pipelines.
- Runtime smoke assertions for Codex privacy and native/canonical histogram
  reconciliation.

### Changed

- Added the ai_agent.* provider-neutral contract while retaining
  privacy-filtered codex.* and antigravity_* native telemetry.
- Aligned Antigravity Hooks/status-line resources and metadata to the
  AI-agent contract; observed gauges remain explicitly non-billing.
- Renamed the existing UID ai-codex-usage dashboard to Codex Native Telemetry
  and restricted it to native Codex queries.
- Removed provider-native fallback queries from both AI Context dashboards.
- Made Docker Compose the primary documented runtime path; Python is optional
  for validation, orchestration, and reports.

### Privacy

- Added explicit underscore-form Codex content/identifier/path deletion and
  bounded canonical labels.
- Documented that pre-0.1.3 persistent data is not retroactively erased and
  requires an explicit Owner decision for irreversible cleanup.

### Compatibility

- ai_context.environment.profile remains a deprecated 0.1.x alias for
  ai_observability.profile.
- Deprecated provider-usage ai_context metrics remain bounded compatibility
  data but are not copied into ai_agent.*; new integrations use ai_agent.*.

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
