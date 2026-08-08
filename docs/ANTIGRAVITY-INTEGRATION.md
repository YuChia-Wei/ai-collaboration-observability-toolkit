# Google Antigravity integration

## Canonical contract in 0.1.3

The exporter emits ai_agent.provider=google,
ai_agent.product=antigravity, and a bounded ai_agent.surface of hooks or
status-line. Lifecycle metadata uses bounded AI-agent operation/model/tool/
evidence fields. The Collector retains the native antigravity_* gauges and
creates ai_agent.observed.* gauge copies.

These values are extension observations, not provider billing records. They do
not satisfy the AI Context framework evidence contract and are not used as a
fallback on AI Context dashboards.

## Decision

The toolkit integrates with Google Antigravity through two documented local extension surfaces:

1. **Antigravity Hooks** for invocation, completed tool step, and execution lifecycle signals.
2. **Antigravity CLI custom status line** for observed model, token/context, quota, task, artifact, and
   agent-state signals.

The account-level **Enable Telemetry** setting is not treated as a local OpenTelemetry integration. It
controls product telemetry and does not document a user-selected OTLP Collector endpoint.

Official references used by this example:

- <https://antigravity.google/docs/hooks>
- <https://antigravity.google/docs/cli/statusline>
- <https://antigravity.google/docs/settings>

## Supplied artifacts

- `examples/antigravity/antigravity_otel_exporter.py`: one canonical, standard-library-only exporter.
- `examples/antigravity/config/hooks.*.json.example`: project/user direct Hooks for personal/corporate
  and POSIX/Windows.
- `examples/antigravity/config/settings.statusline.*.json.fragment.example`: CLI status-line fragments.
- `examples/antigravity/fixtures/`: sanitized examples of documented callback contracts.
- `config/grafana/dashboards/antigravity-usage.json`: provisioned observed-usage dashboard.

The repository intentionally does not ship a second Plugin Hooks package. Running the same exporter
from both direct Hooks and a plugin would duplicate lifecycle events and create ambiguous ownership.

## Data flow

```text
Antigravity direct Hooks ───────────────┐
                                        ├─▶ privacy-first exporter ─▶ 127.0.0.1:4318
Antigravity CLI custom status line ─────┘                            │
                                                                     ▼
                                                          OpenTelemetry Collector
                                                             ├─▶ Loki
                                                             ├─▶ Tempo
                                                             ├─▶ Prometheus
                                                             └─▶ Phoenix (explicit opt-in only)
```

The client exporter applies a strict allowlist. The Collector remains the canonical privacy, routing,
and environment boundary before any backend fan-out.

## Hooks configuration locations

Antigravity documents project and user-level Hook configuration:

```text
<workspace>/.agents/hooks.json
~/.gemini/config/hooks.json
```

The provided project examples execute:

```text
.agents/observability/antigravity_otel_exporter.py
```

A user-level Hook command should use an absolute exporter path because its working directory cannot be
assumed. Do not activate identical Hooks at both scopes.

## Hook events and emitted signals

| Hook | Exported signal | Safe evidence |
| --- | --- | --- |
| `PreInvocation` | log | invocation started, model, invocation number, initial step count |
| `PostInvocation` | log + root span | invocation completed, duration, outcome |
| `PostToolUse` | log | bounded operation category, step index, boolean error outcome |
| `Stop` | log + root span | execution duration, termination category, idle/background state |

The Hooks documentation exposes common lifecycle fields including `conversationId`, `workspacePaths`,
`transcriptPath`, `artifactDirectoryPath`, and `modelName`. `PostToolUse` also exposes `toolCall` and
`error`. This example uses only `conversationId` as HMAC input, `modelName`, bounded numeric/status
fields, and the presence of an error. It does not serialize paths, transcript/artifact locations,
`toolCall`, or raw error text.

## Why `PreToolUse` is absent

`PreToolUse` participates in permission decisions. A passive observability extension must not approve,
deny, repeat, or prolong an action. The example therefore starts observing a tool only after
`PostToolUse` and always returns non-interfering callback responses:

```json
PreInvocation  -> {"injectSteps": []}
PostInvocation -> {"injectSteps": [], "terminationBehavior": ""}
PostToolUse     -> {}
Stop            -> {"decision": ""}
```

## Tool classification

A `PostToolUse` callback contains a `toolCall` object, but arguments can include commands, source paths,
queries, internal identifiers, or secrets. The Hooks configuration already knows which matcher fired,
so it passes one low-cardinality category instead of raw tool metadata:

```text
file-operation
search-operation
execution-operation
agent-collaboration
interaction-operation
```

Unknown future tool names are not exported until the matcher list is deliberately reviewed. The
exporter contains a defensive `other-tool` value but committed configurations do not use a wildcard.

## CLI status line

Antigravity CLI reads its custom status line from:

```text
~/.gemini/antigravity-cli/settings.json
```

The callback receives a JSON payload over standard input. The example reads only:

- model ID/display name;
- total and current input/output/cache token counts;
- context used percentage;
- quota remaining fraction by bounded quota type;
- agent state and execution mode;
- task and artifact counts;
- `exceeds_200k_tokens`;
- pending input count;
- tool confirmation pending flag;
- product/version and terminal width.

It deliberately ignores:

- `cwd`, workspace directories, and transcript path;
- email and plan tier;
- VCS branch and dirty state;
- quota reset timestamps;
- raw session/conversation identifiers beyond local HMAC input.

The status command prints a compact local display line and exports logs/metrics. Unchanged safe
snapshots are deduplicated, with a configurable heartbeat to prove liveness.

## Emitted metric names

```text
antigravity_session_tokens
antigravity_context_tokens
antigravity_context_used_ratio
antigravity_quota_remaining_ratio
antigravity_background_task_count
antigravity_artifact_count
antigravity_context_exceeds_200k
antigravity_pending_input_count
antigravity_tool_confirmation_pending
```

Metric labels are intentionally bounded to fields such as `tool`, `model_family`, `token_type`, quota
`type`, and agent `state`. Session, task, path, branch, conversation, and artifact IDs are not metric
labels.

These metrics are observed status data, **not official credit, price, invoice, or billing records**.

## Session correlation

Personal mode can add `ai_context.session.id`, generated as the first 24 hexadecimal characters of an
HMAC-SHA256 digest. The key is either:

- provided through `AI_OBSERVABILITY_SESSION_SALT`; or
- generated and stored in the user-local state directory with restrictive permissions when possible.

This is a pseudonym, not anonymization. Corporate examples pass `--no-include-session-hash`, and the
Corporate Collector allowlist removes session identities as a second control.

## Phoenix route

Phoenix is opt-in. Adding `--phoenix` sets:

```text
ai_context.export.phoenix = true
```

Only Evaluation mode has a Phoenix exporter, and Collector privacy transforms execute before that
route. Corporate examples must not add `--phoenix`.

## Failure semantics

Exporter failure is fail-open for Antigravity execution:

- local HTTP timeout defaults to 350 ms;
- exceptions are swallowed after an optional error-category-only debug message;
- required Hook response JSON is still written;
- prompt/tool/error payloads are never written to debug output.

Collector privacy processing remains fail-closed: unsafe attributes are removed before fan-out, and the
Corporate profile exposes no Phoenix route.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AI_OBSERVABILITY_OTLP_HTTP_ENDPOINT` | `http://127.0.0.1:4318` | Collector base URL |
| `AI_OBSERVABILITY_SESSION_SALT` | empty | Optional HMAC key material |
| `AI_OBSERVABILITY_STATE_DIR` | user-local cache/state | Dedup/timing state and local HMAC key only |
| `AI_OBSERVABILITY_HTTP_TIMEOUT_SECONDS` | `0.35` | Local OTLP request timeout |
| `AI_OBSERVABILITY_STATUS_HEARTBEAT_SECONDS` | `60` | Re-export interval for unchanged safe status |
| `AI_OBSERVABILITY_PHOENIX` | `false` | Explicit trace evaluation opt-in |
| `AI_OBSERVABILITY_DEBUG` | `false` | Failure type only; never payload content |

CLI arguments override these defaults.

## Verification

The committed tests assert:

- all four Hook variants parse and omit `PreToolUse`;
- matchers map to exactly five bounded categories and use no wildcard;
- personal/corporate and Windows/POSIX status fragments parse;
- corporate variants disable session pseudonyms;
- Hook contract responses are non-interfering;
- documented `modelName` is preserved while `toolCall` and raw errors are excluded;
- status metrics are emitted and unchanged payloads deduplicate;
- a local HTTP receiver sees only `/v1/logs`, `/v1/metrics`, and `/v1/traces` with no fixture secrets;
- the Grafana dashboard queries only metrics emitted by the exporter.

Run:

```bash
python3 -m unittest tests.test_antigravity_example -v
python3 scripts/toolkit.py validate --mode all --static-only
```

## Limitations

- The integration does not intercept model APIs or read transcript content, so it cannot reconstruct
  exact per-request prompt composition.
- Hooks and status-line callbacks are independent; personal mode offers pseudonymous correlation, while
  corporate no-session mode supports aggregate analysis only.
- Matchers and payload schemas may change with Antigravity. Revalidate against official documentation
  after upgrades.
- A passing local fixture test does not prove the live installed Antigravity version invoked every
  callback; perform a first-machine smoke test and inspect Collector logs.
