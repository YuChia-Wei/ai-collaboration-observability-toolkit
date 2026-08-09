# Phoenix evaluation integration

## Role

Phoenix is not the primary telemetry store. Tempo keeps the complete minimized trace history for the
running mode; Phoenix receives Evaluation traces for annotations, evaluators, datasets, and
experiments after the Collector privacy boundary.

## v0.1.4 hybrid routing contract

Evaluation routing is default-on:

- missing `x-ai-observability-phoenix` header: forward;
- `x-ai-observability-phoenix: true`: forward;
- `x-ai-observability-phoenix: false`: do not forward.

The legacy boolean resource attribute remains supported. `ai_context.export.phoenix=false` opts out;
`true` forwards. The header cannot enable Phoenix in Core or Corporate because those profiles define
no Phoenix pipeline or exporter.

The Evaluation OTLP receiver reads request metadata only for routing. The Collector performs privacy
processing first, copies the header into a temporary
`ai_observability.routing.phoenix` attribute, filters explicit opt-outs, then deletes the temporary
attribute before export. Neither the transport header nor the temporary attribute is stored in Tempo
or Phoenix.

Codex supports exporter headers in the user-level `~/.codex/config.toml`. For a global opt-out, add a
header to the trace exporter:

```toml
trace_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/traces", protocol = "binary", headers = { "x-ai-observability-phoenix" = "false" } } }
```

Codex does not apply project-local `.codex/config.toml` overrides to the `[otel]` configuration. The
default-on behavior therefore provides useful Phoenix data for Codex and ChatGPT Desktop even when a
tool cannot attach custom resources or headers.

The smoke fixture sends:

- trace `2222…2222`: legacy resource true; expected in Tempo and Phoenix;
- trace `3333…3333`: legacy resource false; expected in Tempo only;
- trace `5555…5555`: header missing; expected in Tempo and Phoenix;
- trace `6666…6666`: header true; expected in Tempo and Phoenix;
- trace `8888…8888`: header false; expected in Tempo only;
- trace `1111…1111`: normal core fixture; expected in Tempo.

The fixtures use:

```text
openinference.project.name = ai-collaboration-observability-fixture
openinference.span.kind = CHAIN
```

The runtime test queries Phoenix's project span API and searches the returned trace IDs. Positive and
negative assertions prevent future configuration changes from losing the default route or ignoring
an explicit opt-out.

For Traditional Chinese trace-reading order, operational caveats, deterministic fixture
identification, and the annotation rubric, see
[Phoenix Trace 閱讀指南](PHOENIX-READING-GUIDE.zh-TW.md) and
[Telemetry 詞彙表](TELEMETRY-GLOSSARY.zh-TW.md).

Phoenix 19.19.0 exposes versioned annotation-config REST endpoints. The toolkit checks the rubric in
read-only mode unless `--apply` is explicit, then idempotently creates or updates the five configs and
assigns them to the named existing project:

```powershell
python scripts/toolkit.py phoenix-annotations --project "<project-name>"
python scripts/toolkit.py phoenix-annotations --project "<project-name>" --apply
```

This operation does not delete annotations, traces, projects, or PostgreSQL owner data.

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
by this local Compose. Do not expose it to the network. Forwarded traces must already be minimized;
Phoenix routing is not a substitute for privacy processing.
