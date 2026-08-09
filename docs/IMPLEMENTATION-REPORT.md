# Implementation report

## Release

- Version: 0.1.5
- Theme: Human-readable Observability
- Owner work item: GitHub Issue #14
- Release boundary: final planned 0.1.x release

## Delivered scope

1. Made all six provisioned Grafana dashboards zh-TW-first across dashboard titles, panel titles,
   descriptions, legends, explanatory text, and applicable value mappings.
2. Preserved all dashboard UIDs, 44 PromQL expressions, datasource boundaries, units, and canonical
   telemetry identifiers.
3. Added `docs/PHOENIX-READING-GUIDE.zh-TW.md` with a consistent reading order, operational
   interpretation limits, four diagnostic scenarios, deterministic fixture identification, and the
   v0.2 handoff boundary.
4. Added `docs/TELEMETRY-GLOSSARY.zh-TW.md` to map provider-native, `ai_agent.*`, and `ai_context.*`
   evidence without translating canonical keys.
5. Added a version-controlled five-config Chinese annotation rubric for execution outcome, problem
   type, case retention, human reason, and follow-up action.
6. Added `phoenix-annotations`, which checks drift without mutation by default and performs explicit,
   idempotent create/update/project-assignment requests only with `--apply`.
7. Updated version, fixtures, Antigravity instrumentation scope, README discoverability, operations,
   integration, troubleshooting, roadmap, changelog, tests, and release notes for v0.1.5.

## Boundaries

- The Collector remains the only host-facing OTLP ingress.
- Core and Corporate still define no Phoenix route.
- Evaluation Phoenix routing remains privacy-safe default-on with explicit header/resource opt-out.
- No prompt, response, tool argument/result, command output, code, diff, credential, identity, or
  absolute path was re-enabled.
- No evaluator, dataset, experiment, LLM-as-a-judge, or semantic normalization work was added.
- No trace, annotation, project, PostgreSQL row, named volume, or other owner data was deleted.

## Local validation result

- Repository policy and all three merged Compose modes passed.
- 36 unit tests were discovered: 35 passed and one Windows-only POSIX executable-bit check was
  skipped as expected.
- Collector 0.158.0 validated Core, Evaluation, and Corporate configs.
- Prometheus 3.13.2, Loki 3.7.6, and Tempo 3.0.2 native validators passed.
- Evaluation ran all seven services and passed privacy, raw/canonical reconciliation, all six
  provisioned zh-TW dashboards, five-case Phoenix routing, and restart-persistence checks.
- The five owner named volumes remained present and queryable after restart.
- The annotation rubric was provisioned to `ai-collaboration-observability-fixture` and passed a
  read-only check after Phoenix restart.
- Browser-based Grafana QA loaded every panel heading across all six dashboards; no browser console
  error was observed.

## Human interpretation boundary

Low-level provider spans can show operation order, duration, status, and bounded metadata. They do
not independently prove task completion, answer correctness, context causality, or cost. The new
guide and rubric preserve this evidence-versus-inference distinction.
