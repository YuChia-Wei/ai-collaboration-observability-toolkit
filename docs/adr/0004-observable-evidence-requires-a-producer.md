# ADR 0004: Observable evidence requires a real producer

## Status

Accepted by Issue #18.

## Decision

The toolkit provisions dashboards only when a supported runtime produces the
queried evidence. The two AI Context effectiveness/workflow dashboards are
retired while `ai_context.*` remains a reserved schema and fixture contract.
They may return only after a deterministic runtime-owned emitter, orchestrator,
or client hook is implemented and validated against a real workflow. The
portable framework harness is not expected to observe model execution.

Provider-native telemetry may establish usage, timing, tool activity, and trace
events. It must not be used to infer that a prompt rule was loaded, followed, or
caused an outcome. A prompt's own declaration is not independent evidence.

Grafana remains the primary native/canonical usage and activity surface. The AI
Agent Activity dashboard reads metadata-only Loki events and correlates them to
Tempo. Raw prompt, response, tool payload, command output, code, and paths remain
outside the persistence contract.

Phoenix remains optional in Evaluation mode. After privacy processing, its
branch retains only spans declaring `openinference.span.kind`; compatible spans
remain default-on with explicit header/resource opt-out. Generic spans remain in
Tempo. Existing Phoenix/PostgreSQL data is preserved and is not rewritten or
deleted by this decision.

## Consequences

- Empty dashboards cannot imply an instrumentation capability that does not
  exist.
- Native Codex events are immediately useful in Grafana/Loki/Tempo without being
  mislabeled as framework effectiveness evidence.
- Phoenix default panels receive fewer but semantically meaningful spans; model,
  token, cost, input, and output panels still require those attributes from a
  compatible producer.
- Issues #4 and #5 require re-scoping or prerequisite implementation rather than
  being pulled unchanged as dashboard work.
