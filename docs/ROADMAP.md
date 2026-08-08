# Roadmap

## Implemented baseline

- Core LGTM mode with a host-facing OpenTelemetry Collector.
- Evaluation mode with selected redacted traces to Phoenix/PostgreSQL.
- Corporate metadata-only allowlist mode.
- Codex configuration example.
- Provisioned Grafana datasources and initial dashboards.
- Deterministic OTLP fixtures and end-to-end privacy/routing smoke test.
- Bash/PowerShell operations and CI configuration validation.

## Next: AI Context instrumentation

1. Define a small hook/CLI that emits workflow, state, validation, wait, Git, and outcome spans.
2. Add validation fingerprints and evidence-reuse decisions.
3. Add sleep/resume and heartbeat/checkpoint events.
4. Emit context manifest hashes, loaded file/byte counts, and rule-effect states.
5. Keep the emitter technology-neutral; consider Rust/Go/.NET AOT only after command/runtime needs are
   measured.

## Next: Phoenix improvement loop

1. Import the v0.8.0 release incident as the first curated trace/dataset.
2. Implement deterministic evaluators from `PHOENIX-INTEGRATION.md`.
3. Establish disposable Git worktree fixtures for framework-version experiments.
4. Compare current/simplified frameworks under fixed model and task conditions.
5. Feed accepted findings into governed backlog items rather than auto-editing rules.

## Next: company usage showback

1. Define a versioned, redacted `ai-context-feedback-bundle.json` schema.
2. Add local aggregation/export without raw content.
3. Design a PostgreSQL official usage ledger and reconciliation jobs.
4. Pilot CSV import before Admin API automation.
5. Add per-user access control and anonymous team aggregates.
6. Create “my AI usage,” “task cost effectiveness,” “workflow waste,” and “official reconciliation”
   dashboards.

## Deferred platform comparisons

After the telemetry contract is stable, use Collector fan-out and identical fixture/query workloads
to compare ClickStack/HyperDX, SigNoz, or OpenObserve. Do not migrate merely because a backend has an
AI-labelled dashboard.

## Explicitly deferred

- Kubernetes/Helm and high availability.
- Internet exposure and authentication gateway.
- OpenAI Enterprise Admin/Spend Controls write automation.
- Automated employee productivity ranking.
- Raw prompt/code collection.
- Automatic rule deletion based only on usage frequency.

## Antigravity native usage follow-up

- Replace or complement the JSON Hooks bridge if Antigravity publishes a native OTLP exporter.
- Add token/credit reconciliation only when an official, documented data source is available.
- Reassess tool-name and duration capture if PostToolUse gains passive start/end metadata.
