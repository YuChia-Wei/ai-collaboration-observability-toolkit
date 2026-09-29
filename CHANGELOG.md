# Changelog

All notable changes to this project will be documented here.

## [Unreleased]

## [0.2.0] - 2026-09-29

Privacy-first agent usage with a bounded company workstation profile.
See [release notes](docs/RELEASE-NOTES-v0.2.0.md) and
[readiness and issue review](docs/RELEASE-READINESS-v0.2.0.md).

### Added

- Provider-neutral token accounting with disjoint uncached input, cached input,
  cache-write input, and output classes; unknown models/rates remain unpriced.

- Added provider-neutral `agent_role` attribution (`primary`,
  `approval_reviewer`, `subagent`, `unknown`) without conflating roles with
  exact models; current Codex Auto-review remains `model_id=unmapped`.
- Added accounting schema v2 for new data only, with API-unpriced and
  Codex-credits-unpriced token series.
- Separated OpenAI API USD estimates from public Codex token-based credits
  estimates. Cached input is discounted rather than free; cache-write remains
  credits-unpriced because the public Codex table has no dedicated rate.
- Added the `ai-codex-auto-review` dashboard and role/model filters plus credits
  panels to the provider-neutral AI Agent Usage dashboard.
- Added exact-model, approval-reviewer, and producer-supplied subagent runtime
  fixture coverage. Existing data is not backfilled or rewritten.

- Exact reviewed GPT-6 Astra/Sol/Luna mappings and versioned rate cards, with
  fixture reconciliation and unknown-model coverage.
- Experimental metadata-only Codex lifecycle Hooks producing OpenInference
  AGENT/TOOL traces, plus separately enabled prompt-size and allowlisted MCP
  response-size byte metrics. Bytes are not tokens or full model context.
- Claude Code CLI/Desktop native token mapping, skill/MCP attribution, and
  context-attribution dashboards; exact-client capture evidence remains a
  follow-up. Arbitrary skill/MCP names become bounded other/custom values before
  native/canonical export; Corporate removes attribution dimensions.
- Optional loopback-only `compose.debug.yaml` for direct backend API access.

### Changed

- Usage dashboards lead with freshness, selected-range usage, estimate
  coverage, and activity. Added AI Agent Activity and context-attribution views.
- Retired the two AI Context dashboards without a real producer; the reserved
  schema/fixtures do not establish framework effectiveness.
- Evaluation sends only redacted OpenInference-compatible spans to Phoenix;
  generic spans stay in Tempo. Header/resource opt-outs remain supported.
- Pinned Evaluation Phoenix to `version-20.0.0-nonroot`, with its persistent
  agent disabled and existing PostgreSQL data retained.
- Default host interfaces are Collector, Grafana, and Evaluation Phoenix.
  Prometheus/Loki/Tempo remain internal; operational queries use Grafana proxy.
- Corporate uses five services capped at 1664 MiB aggregate container memory,
  30-second scrape/rule evaluation, reduced query concurrency, 7-day/1GB
  Prometheus block retention, and 72-hour log/trace retention. Container logs rotate.
- Patched Grafana to 13.1.7, Prometheus to 3.13.3, Loki to 3.7.8, Tempo to 3.0.3,
  and optional PostgreSQL to 18.6-alpine3.24. Collector/Phoenix feature upgrades
  remain separate from this resource-focused release.

### Removed

- Removed the unreleased source archive service, initializer, independent
  Collector pipelines, export CLI and dedicated implementation/tests. No
  duplicate OTLP JSONL storage runs in any mode. Existing archive volumes are
  retained until separately reviewed for export/deletion.

### Fixed

- Selected-range estimated costs use counter increases instead of a last
  cumulative value that can misleadingly appear frozen.

### Compatibility and release boundary

- Existing backend host-port consumers must opt into the debug overlay or use
  Grafana. Apply topology changes during a maintenance window.
- Accounting v2 and privacy rules apply to new ingestion. Historical data is
  neither backfilled nor erased, and estimates are not invoices or allowances.
- The complete AI Collaboration Improvement Loop is excluded. Issues #4/#5
  are retired planning scopes, not delivered capabilities.
- Corporate caps are a resource budget, not a throughput or disk-capacity
  guarantee. Retention can remove older data after deployment; back up before
  changing an existing personal stack to the short-retention company profile.

## [0.1.5] - 2026-08-09

### Added

- Added a Traditional Chinese Phoenix trace-reading guide covering projects, traces, spans,
  waterfalls, status, attributes, events, annotations, datasets, experiments, and four operational
  diagnostic scenarios.
- Added a bilingual telemetry glossary that preserves canonical English identifiers.
- Added a five-config zh-TW operational annotation rubric with read-only drift detection and
  explicit, idempotent Phoenix REST provisioning for a selected project.

### Changed

- Made all six Grafana dashboards zh-TW-first while preserving dashboard UIDs, PromQL, datasource
  boundaries, units, and telemetry semantics.
- Corrected AI Context legend templates to use labels actually produced by their unchanged queries.
- Documented deterministic smoke-fixture identification without deleting historical owner data.

### Release boundary

- v0.1.5 closes the planned 0.1.x line. Semantic normalization, evaluators, datasets, experiments,
  and the AI Collaboration Improvement Loop remain v0.2.0 planning work.

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
