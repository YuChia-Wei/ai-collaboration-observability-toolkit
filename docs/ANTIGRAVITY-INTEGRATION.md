# Google Antigravity integration

## Canonical contract in 0.1.3

The exporter emits ai_agent.provider=google,
ai_agent.product=antigravity, and a bounded ai_agent.surface of hooks or
status-line. Lifecycle metadata uses bounded AI-agent operation/model/tool/
evidence fields. The Collector retains the native antigravity_* gauges and
creates ai_agent.observed.* gauge copies.

These values are extension observations, not provider billing records. They do
not satisfy the AI Context framework evidence contract. AI Context dashboards
are not provisioned until an independent framework emitter exists.

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
- `scripts/install_antigravity.py`: repeatable user-level Hooks and CLI status-line setup.

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
                                                             └─▶ Phoenix (Evaluation, OpenInference-compatible only)
```

The client exporter applies a strict allowlist. The Collector remains the canonical privacy, routing,
and environment boundary before any backend fan-out.

The exporter defaults `--service-namespace` to `ai-collaboration`. Runtime
smoke passes `ai-collaboration-fixture` explicitly, and the provisioned usage
dashboards exclude fixture namespaces so verification snapshots cannot appear
as owner usage.

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

## Install the local bridge

Running the Compose stack does not enable Antigravity callbacks. Install the
bridge separately for the OS user that runs Antigravity. From this repository,
preview the two configuration changes, then apply them:

```bash
python scripts/install_antigravity.py
python scripts/install_antigravity.py --apply
```

The installer merges the `ai-observability` Hook group into
`~/.gemini/config/hooks.json` and the CLI `statusLine` into
`~/.gemini/antigravity-cli/settings.json`. Commands use the current Python
interpreter and this repository's canonical exporter as absolute paths. On
Windows, both paths must contain no spaces or shell metacharacters: Antigravity
CLI 1.4.5's `cmd.exe /c` callback transport cannot launch quoted executable
paths. The installer refuses unsupported paths before writing configuration.
Keep both paths available; moving Python requires rerunning the installer,
and moving the repository also requires explicitly replacing the old status
line with `--replace-statusline`. Existing unrelated settings are preserved and changed existing
files are backed up beside the original. Repeating the install is a no-op
when the managed configuration already matches.

For Corporate, pass `--profile corporate-local-redacted`. An existing custom
status line is a conflict: inspect the preview before deliberately replacing
it with `--replace-statusline --apply`. Do not also activate the project-level
examples or a second plugin that runs this exporter.

Start a new Antigravity session after installation. In CLI, use `/hooks` to
confirm `ai-observability` is loaded and enabled. In App/IDE, inspect
Customizations > Hooks. Configuration files alone do not prove that the
already-running process has reloaded them or that OTLP reached the backends.

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
They remain gauges in the canonical `ai_agent.observed.*` lane: the toolkit does
not apply `increase()`, convert them to turn-token accounting, or attach a rate
card. A future Antigravity estimate requires a version-pinned usage fixture and
an independently verified pricing contract; current data is deliberately not
guessed.

## Official account quota snapshots

Account quota can be read independently of CLI conversation status lines with
the official, zero-turn `agy -p /usage --output-format json` command (CLI 1.1.11
or newer). The toolkit exposes a guarded reader:

```powershell
python scripts/toolkit.py antigravity-quota --scratch-root F:\codex-tmp\antigravity-quota
python scripts/toolkit.py antigravity-quota --export --scratch-root F:\codex-tmp\antigravity-quota
python scripts/toolkit.py antigravity-quota --export --watch --interval-seconds 120 --scratch-root F:\codex-tmp\antigravity-quota
```

The first command reads a sanitized snapshot without exporting. `--export`
sends only quota metrics to the existing loopback Collector. `--watch` polls
while that process runs; it does not register a startup task or run model
prompts. Select a disposable scratch parent appropriate to the machine; the
F: example assumes a separately verified RAM disk. `--output` writes a sanitized
local JSON result. Corporate uses `--profile corporate-local-redacted` with
the Corporate Collector mode.

The Windows reader requires an already signed-in CLI and running desktop app.
It reads only the fixed Antigravity Credential Manager entry, compares its
native ID-token email to the desktop's read-only `GetUserStatus` response, and
rechecks both bindings around the report. Credential material, email, subject,
and comparison fingerprints stay in memory. This is local native-login binding
verification, not JWT signature verification or remote identity attestation.
An expired, unavailable, mismatching, or changed binding prevents quota export.
For an expired but otherwise matching native binding, the reader may run one
official passive `/usage` refresh probe and discard its response. It requires
the same account subject/email before and after that probe, then collects a
separate report with current, stable bindings. A failed refresh still closes
the export gate. Both ordinary reads and refresh probes accept only the native
installation under `LOCALAPPDATA/agy/bin/agy.exe`; `--agy-bin` can explicitly
select that same installation when it is absent from PATH.
The desktop metadata connection is limited to the same OS user, exact installed
desktop executable, matching PID/start time, owned loopback listener, pinned
local TLS certificate, and a fixed read-method allowlist. It uses no HTTP proxy
or redirects and never exports the identity response.

The parser accepts only a successful `usage` command with `num_turns=0`, and
currently recognizes five version-reviewed buckets: `gemini-weekly`,
`gemini-5h`, `3p-weekly`, `3p-5h`, and `gemini-argon-wtu-weekly`.
Unknown buckets are reported as skipped; absent, invalid, or non-finite
measurements are omitted, not replaced by zero. Account scope does not attribute
quota changes to a conversation, surface, token count, or charge.

The independent metrics are:

```text
antigravity_account_quota_remaining_ratio
antigravity_account_quota_reset_timestamp_seconds
antigravity_account_quota_snapshot_timestamp_seconds
antigravity_account_quota_identity_match
```

Bounded dimensions retain source, account scope, quota group, bucket, and
window. They contain no account identifier or hash. On a failed read, the
watcher sends only `identity_match=0`; it does not refresh the quota timestamp
or fabricate zero quota. Dashboard account quota tables require a confirmed
binding and a snapshot no older than 180 seconds. An old snapshot turns the age
indicator red and stops displaying quota values. Each bucket's source timestamp
must also match that snapshot within Prometheus's 1 ms timestamp precision; a
bucket or reset omitted from the latest report cannot reuse a retained old point.
Freshness and identity gates match the same service, namespace, profile, source,
and scope. The Collector sets the canonical profile to its selected runtime mode.
These panels remain separate
from CLI status-line observations and exclude fixture namespaces.

The optional reader currently verifies Windows native-login bindings. Other
platforms fail with `windows_required` until their native binding sources have
an independently verified adapter.

Official command semantics: <https://antigravity.google/docs/changelog>.

## Desktop token and context read verification

The Windows desktop adapter is a local, bounded verification reader for the
reviewed **2.25.0** schema. It is an internal version-specific adapter, not a
documented Google telemetry API. An unreviewed installed version stops the read
with `desktop_version_review_required` rather than assuming wire compatibility.

```powershell
python scripts/toolkit.py antigravity-desktop-usage --output artifacts/desktop-usage.json
python scripts/toolkit.py antigravity-desktop-usage --max-conversations 1 --max-rows 128
```

This command has no export or watch option. `observed` exits zero; `partial` or
`unavailable` exits one and still returns a sanitized report with coverage and
unknown fields. A partial report can contain valid numeric observations without
establishing complete or current usage. Conversation selectors and provider
responses never enter the report.

- **Tokens:** up to three recent desktop SQLite databases, at most 512
  `gen_metadata` rows per database by default. A WAL-aware, query-only read
  transaction reads only this metadata table. The numeric protobuf parser skips
  strings and unknown fields without decoding them, and does not read `steps`
  or legacy `.pb` files. Record size, total bytes and query time are bounded.
  The reviewed `ModelUsageStats` fields are uncached input, total output, cache
  write/read, thinking output and response output. Total output already includes
  thinking; its diagnostic subsets are not added again. Each sampled sum retains
  present/absent record counts. Missing fields remain unknown. Model attribution
  and response deduplication are unverified, so these sums are historical
  metadata samples rather than a complete usage counter or a billing ledger.
- **Context:** the same-user local language server's read-only
  `GetCascadeTrajectoryGeneratorMetadata` method is restricted to a UUID selector,
  a bounded numeric offset, and `includeMessages=false`. The installed server's
  protobuf descriptors establish the path `chatModel.chatStartMetadata.contextWindowMetadata`.
  The reader uses the server's `estimatedTokensUsed`, `maxContextTokens`, and
  numeric breakdown total directly. It does not infer occupancy from accumulated
  usage or look up a model capacity table. Only a recent suffix of persisted
  generator metadata is requested, after the native CLI/desktop binding check.

Selection uses database/existing WAL storage modification times; it does not
identify the currently active UI conversation. A language-server metadata read
can itself cause persistence or flushing, so file age must not be treated as
generation age or proof of new model activity. The source generation timestamp
is reported only if actually present; otherwise source freshness stays unknown.
The token and context sources are separate observations, not an atomic snapshot
of one identified conversation. Historical local files are not attributed to
the currently signed-in account's charges.

The diagnostic command does not export or deduplicate a persistent history. The
separate observer below adds native generation identity and source-time checks.
Neither lane is merged into CLI status-line or official account quota metrics.

## Desktop metadata observer

```powershell
python scripts/toolkit.py antigravity-desktop-observe --output artifacts/desktop-observation.json
python scripts/toolkit.py antigravity-desktop-observe --export --watch --interval-seconds 60 --output artifacts/desktop-observation.json
```

The observer is a reviewed **Windows desktop 2.25.0** adapter. It reads bounded
`gen_metadata` plus only the referenced `steps.metadata` fields. Step bodies,
tool arguments/results, source code and unknown strings are not decoded. Raw
conversation selectors and native response IDs remain in memory.

The native response ID (`ModelUsageStats.response_id`, field 11) is the stable
deduplication key. The private local SQLite ledger stores an HMAC of this key,
reviewed numeric token fields and generation source times. Its default directory
is `%LOCALAPPDATA%/ai-collaboration-observability/antigravity-desktop`; `--state-dir`
selects another durable location. Keep this state across restarts. Re-reading,
reordering or copying records with the same native ID does not add usage again.
Later positive numeric refinements add only the difference. Conflicting times or
decreasing values are rejected, not subtracted or counted as a new generation.
A publication lock covers collection, ledger update and OTLP export; transport
retries resend cumulative values with the same ledger start time. Missing or
corrupt ledger metadata fails closed instead of silently generating a new key.
The 100,000-generation bound stops admission rather than pruning deduplication
keys and accidentally recounting history.

Source time comes from `ChatStartMetadata.created_at`, or, when absent, the first
referenced step's `CortexStepMetadata.created_at`. The latter is explicitly
labelled `first-referenced-step-created-at`; it is not a claimed request start
or completion time. Completed/finished-generating timestamps are separate fields.
Missing identity or source time cannot become a trusted token counter.

Context scope is **latest observed generation**, selected by these source times
within the bounded sample. Its RPC response must match the native response ID
or the exact referenced step indices of that generation; a raced or unmatched
response closes the context gate. Its estimate and capacity come directly from
the language server. The metric sample timestamp records when the saved metadata
snapshot was observed; the separate source-timestamp gauge preserves the native
generation time. This lets an idle conversation's last known estimate remain
visible with its actual age. Polls do not make old generations into new activity.
Dashboard values require a successful read, generation alignment, matching
per-field availability and the current observation cohort. A producer read older
than 180 seconds is hidden. Unknown fields stay absent rather than becoming zero.

**Active conversation is deferred.** The observer does not identify the UI's
selected pane or an executing conversation. The reviewed desktop UI keeps its
selection in each renderer's router state; the similarly named
`GetBrowserOpenConversation` is a browser-tab return hint and is not a reliable
selection source. No selector bridge or additional RPC was enabled for it.

Desktop counters use `antigravity_desktop_generation_observed_tokens_total`
(`token_type` is one of the six reviewed numeric fields) and
`antigravity_desktop_generation_records_total`. They count discovered,
deduplicated metadata since the ledger began, including initially discovered
history. They are not a complete provider ledger, a current-conversation total,
or a charge. Thinking and response output are subsets of total output and must
not be added to it. The dashboard displays totals, not an activity rate derived
from historical imports. Read limits and source coverage remain visible.

The observer uses the existing loopback Collector only. All three modes retain
desktop dimensions only for the exact twelve reviewed metric names. No UUID,
response ID, HMAC, account value, path or identity is used as a metric label.
`--watch` runs while the process exists and does not register a startup task.
Exit zero means collection/export ran (the safe report may still be partial);
an unavailable collection or busy publisher exits one. No model turn is started.

## Session correlation

Personal mode can add `ai_context.session.id`, generated as the first 24 hexadecimal characters of an
HMAC-SHA256 digest. The key is either:

- provided through `AI_OBSERVABILITY_SESSION_SALT`; or
- generated and stored in the user-local state directory with restrictive permissions when possible.

This is a pseudonym, not anonymization. Corporate examples pass `--no-include-session-hash`, and the
Corporate Collector allowlist removes session identities as a second control.

## Phoenix route

Evaluation Phoenix routing is default-on only for spans that already declare
`openinference.span.kind`. Generic Antigravity spans remain in Tempo. With no
Phoenix flag, the exporter omits the legacy resource attribute and lets the
Collector apply its compatibility filter and default. Adding `--no-phoenix` sets:

```text
ai_context.export.phoenix = false
```

Adding `--phoenix` explicitly sets the legacy attribute to true, but does not
manufacture missing OpenInference semantics. Only Evaluation mode has a Phoenix
exporter, and Collector privacy transforms execute before the compatibility and
routing filters. Corporate mode has no Phoenix pipeline, regardless of this
producer-side flag.

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

## Diagnose missing activity

1. Check that the active user's global Hooks file exists and that Antigravity
   reports a loaded, enabled `ai-observability` Hook group. A CLI log entry
   `loaded 0 named hooks from 0 hooks.json file(s)` means that session did not
   load any file-based Hooks. Product activity alone cannot reach the Collector.
2. Check that the configured absolute Python and exporter paths still exist.
   Re-run the installer preview to detect an outdated managed command.
3. Check Collector health at `http://127.0.0.1:13133/`, then use a sanitized
   fixture and `--service-namespace ai-collaboration-fixture --debug` to test
   the exporter separately. Inspect backend receipt; exit code zero is also
   the exporter's intentional fail-open response on a transport failure.
4. Trigger a fresh, harmless Antigravity action and confirm a new lifecycle
   event in Loki and a completed invocation/Stop trace in Tempo. Fixture
   events are excluded from usage dashboards and do not prove live callback
   activation. Phoenix requires OpenInference-compatible spans; generic
   Antigravity lifecycle traces remain in Tempo.
5. For CLI token/context/quota gauges, also verify the CLI `statusLine`
   configuration and trigger an interactive state change. App/IDE Hooks
   supply activity logs/traces; they do not supply status-line gauges.

The bridge observes future callbacks. It does not backfill missed work from
private conversation files or reconstruct historical token usage.
