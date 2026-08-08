# Validation report

## Metadata

- Repository: `ai-collaboration-observability-toolkit`
- Version: `0.1.2`
- Validation date: `2026-08-08`
- Generation environment: Linux, Python `3.13.5`
- Validation principle: unavailable checks are recorded as **NOT EXECUTED**, never inferred as passed.

## Result summary

| Validation surface | Status | Evidence |
| --- | --- | --- |
| Repository static policy validator | PASS | `python3 scripts/toolkit.py validate --mode all --static-only` |
| Python unit tests | PASS | `31` tests passed |
| Python syntax/bytecode compilation | PASS | `python3 -m compileall -q scripts tests examples/antigravity` |
| Bash syntax | PASS | `bash -n scripts/*.sh` |
| YAML, JSON, TOML parsing | PASS | Included in the static policy validator |
| Duplicate YAML key rejection | PASS | Included in validator and unit tests |
| JSON Schema examples | PASS | AI Context event and feedback bundle validated |
| Antigravity direct Hooks examples | PASS | Four OS/profile variants parse; no `PreToolUse`; five explicit bounded matchers |
| Antigravity status-line examples | PASS | Four OS/profile fragments parse; corporate variants disable session pseudonyms |
| Antigravity privacy tests | PASS | Documented `modelName` retained; `toolCall`, paths, IDs, e-mail, commands and raw errors excluded |
| Local OTLP/HTTP wire test | PASS | Logs/traces delivered to an ephemeral loopback receiver without fixture secrets |
| Grafana Antigravity dashboard | PASS (static) | Queries all nine exporter metrics and labels observations as non-billing |
| Local Markdown link targets | PASS | Included in the static policy validator |
| Compose policy and mode boundaries | PASS (static) | Exact image defaults, loopback ports, no `container_name`, mutually exclusive modes |
| Collector processor ordering | PASS (static) | Minimization precedes batching and Phoenix routing |
| Corporate metadata allowlist | PASS (static) | Strict `keep_keys`, fixed bodies/names, no Phoenix exporter |
| Loki index-label policy | PASS (static) | Exact approved low-cardinality label set |
| Tempo retention/configuration shape | PASS (static) | Local monolithic storage and scoped `336h` retention |
| Docker Compose merged configuration | NOT EXECUTED locally | Docker/Compose executable unavailable; CI workflow exists |
| OpenTelemetry Collector native validation | NOT EXECUTED locally | `OTELCOL_BIN` unavailable; pinned validator configured in CI |
| Prometheus native validation | NOT EXECUTED locally | `PROMTOOL_BIN` unavailable; pinned validator configured in CI |
| Loki native `-verify-config` | NOT EXECUTED locally | Container/runtime unavailable; pinned image check configured in CI |
| Tempo native `-config.verify` | NOT EXECUTED locally | Container/runtime unavailable; pinned image check configured in CI |
| PowerShell parser/execution | NOT EXECUTED locally | `pwsh` unavailable |
| Core/Corporate/Evaluation runtime smoke and persistence | NOT EXECUTED locally | Docker daemon unavailable |
| Live installed Antigravity invocation | NOT EXECUTED locally | Requires Antigravity and a running Collector on the target workstation |
| Grafana live browser rendering | NOT EXECUTED locally | Requires a running stack and browser review |

## Antigravity assertions

The committed validator and tests prove the following about the example itself:

1. The Repository ships one canonical exporter and one direct-Hooks route; no second Plugin Hooks
   package is present.
2. Project/user Hooks cover `PreInvocation`, `PostInvocation`, `PostToolUse`, and `Stop`.
3. `PreToolUse` is absent, so passive telemetry cannot alter permission decisions.
4. Tool matchers use no wildcard and pass exactly five low-cardinality operation categories.
5. Lifecycle Hooks consume documented `modelName`; CLI status consumes its documented `model` object.
6. The exporter deliberately does not read `toolCall` even though the privacy fixture contains a tool
   name, command, working directory, and sentinel.
7. Prompt/response/transcript/artifact/code content, paths, branch, e-mail, plan tier, raw errors, reset
   timestamps, and raw session/conversation IDs are not emitted.
8. Personal mode may add an HMAC session pseudonym; corporate variants disable it.
9. Hook callbacks always return non-interfering contract JSON, including when OTLP export fails.
10. Unchanged status payloads are deduplicated until the configured heartbeat.
11. The exporter sends only OTLP/HTTP `/v1/logs`, `/v1/metrics`, and `/v1/traces` to loopback by
    default.
12. Dashboard metrics are observations and are not represented as official credits or billing.

## Commands executed

```text
python3 scripts/toolkit.py validate --mode all --static-only
PASS: repository configuration and policy validation

python3 -m unittest discover -s tests -v
Ran 31 tests
OK

python3 -m compileall -q scripts tests examples/antigravity
(exit code 0)

bash -n scripts/*.sh
(exit code 0)

python3 scripts/toolkit.py validate --mode all
SKIP: Docker Compose v2+ executable not available
SKIP: OTELCOL_BIN not set; native Collector validation is performed in CI
SKIP: PROMTOOL_BIN not set; native Prometheus validation is performed in CI
SKIP: LOKI_BIN not set; native Loki validation is performed in CI
SKIP: TEMPO_BIN not set; native Tempo validation is performed in CI
SKIP: pwsh not available; PowerShell parsing is performed in CI
PASS: repository configuration and policy validation
```

## Required first-machine acceptance

On the target Windows/WSL workstation:

```bash
cp .env.example .env
python3 scripts/toolkit.py validate --mode all
python3 scripts/toolkit.py up --mode core
python3 scripts/toolkit.py smoke --mode core --persistence-check --report artifacts/smoke-core.json
python3 -m unittest tests.test_antigravity_example -v
```

Install the matching Antigravity Hook and status-line examples, execute a small non-sensitive task, then
verify Collector logs, the **Antigravity Usage (observed, not billing)** dashboard, and absence of
sensitive fields. Corporate and Evaluation modes must be tested separately. A skipped native/runtime
check must not be relabeled as passed.
