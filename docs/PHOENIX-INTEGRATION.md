# Phoenix evaluation integration

## Role

Phoenix is not the primary telemetry store. Tempo keeps the complete minimized trace history for the
running mode; Phoenix receives a deliberate subset for annotations, evaluators, datasets, and
experiments.

## Selection contract

Set this **resource attribute** on the trace to opt in:

```text
ai_context.export.phoenix = true
```

The evaluation Collector applies the privacy transform first, then drops spans whose resource does
not contain boolean true. The smoke fixture sends:

- trace `2222…2222`: selected; expected in Tempo and Phoenix;
- trace `3333…3333`: rejected; expected in Tempo only;
- trace `1111…1111`: normal core fixture; expected in Tempo.

The selected and rejected fixtures use:

```text
openinference.project.name = ai-collaboration-observability-fixture
openinference.span.kind = CHAIN
```

The runtime test queries `GET /v1/projects/{project}/traces?include_spans=true` and searches the
returned trace IDs. The negative assertion prevents a future configuration merge from exporting every
trace by accident.

## Project naming

A suitable project separates framework-source evolution, a public downstream lab, and deliberately
redacted corporate experiments. Do not encode internal repository names into corporate telemetry.
Corporate mode has no Phoenix exporter.

## Initial evaluator backlog

Prefer deterministic code evaluators before LLM-as-a-judge:

1. **duplicate-validation** — same fingerprint rerun without invalidation.
2. **late-environment-preflight** — runtime/shell/temp failure after expensive work begins.
3. **unattributed-wait** — long gap without owner, tool, hosted-check, pause, or sleep state.
4. **context-route-budget** — loaded bytes/files/tokens versus successful outcome.
5. **subagent-overlap** — duplicated files, checks, or findings without review rationale.
6. **outcome-truthfulness** — blocked/skipped/deferred never reclassified as passed/completed.

## Experiments

A valid framework simplification experiment controls:

- fixed Git commit or disposable worktree;
- identical task and acceptance criteria;
- model/tool/reasoning settings;
- environment and dependency versions;
- framework version/rule-set hash;
- repeat count and evaluator set.

At minimum compare current framework/current model and simplified framework/current model. Repeat the
pair when changing the model; otherwise model improvement and context simplification cannot be
separated.

## Storage and privacy

Phoenix uses PostgreSQL in evaluation mode. Its UI is loopback-bound and authentication is not enabled
by this local Compose. Do not expose it to the network. Selected traces must already be minimized;
Phoenix selection is not a substitute for privacy processing.
