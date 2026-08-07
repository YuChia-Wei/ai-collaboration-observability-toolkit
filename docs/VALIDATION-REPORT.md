# Validation report

## Metadata

- Repository: `ai-collaboration-observability-toolkit`
- Version: `0.1.0`
- Validation date: `2026-08-07`
- Generation environment: Linux, Python 3.13.5
- Validation principle: unavailable checks are recorded as **NOT EXECUTED**, never inferred as passed.

## Result summary

| Validation surface | Status | Evidence |
| --- | --- | --- |
| Repository static policy validator | PASS | `python3 scripts/toolkit.py validate --mode all --static-only` |
| Python unit tests | PASS | `25` tests passed |
| Python syntax/bytecode compilation | PASS | `python3 -m compileall -q scripts tests` |
| Bash syntax | PASS | `bash -n scripts/*.sh` |
| YAML, JSON, TOML parsing | PASS | Included in the static policy validator |
| Duplicate YAML key rejection | PASS | Included in validator and unit tests |
| JSON Schema examples | PASS | AI Context event and feedback bundle both validated |
| Local Markdown link targets | PASS | Included in the static policy validator |
| Compose policy and mode boundaries | PASS (static) | Exact image defaults, matching override variables, loopback ports, no `container_name`, mutually exclusive modes |
| Collector component references and processor ordering | PASS (static) | All pipeline references resolve; minimization precedes batching and Phoenix routing |
| Corporate metadata allowlist | PASS (static) | Strict `keep_keys`, fixed log body, cleared status/trace state/metric description, no Phoenix exporter |
| Loki index-label policy | PASS (static) | Exact approved low-cardinality label set |
| Tempo retention/configuration shape | PASS (static) | Local monolithic storage, scoped `336h` block retention, no legacy top-level compactor block |
| Docker Compose merged configuration | NOT EXECUTED locally | Docker/Compose executable was unavailable; configured in GitHub Actions |
| OpenTelemetry Collector native validation | NOT EXECUTED locally | `OTELCOL_BIN` was unavailable; pinned validator configured in GitHub Actions |
| Prometheus native validation | NOT EXECUTED locally | `PROMTOOL_BIN` was unavailable; pinned validator configured in GitHub Actions |
| Loki native `-verify-config` | NOT EXECUTED locally | Loki binary/container runtime was unavailable; pinned image check configured in GitHub Actions |
| Tempo native `-config.verify` | NOT EXECUTED locally | Tempo binary/container runtime was unavailable; pinned image check configured in GitHub Actions |
| PowerShell parser/execution | NOT EXECUTED locally | `pwsh` was unavailable; parser check runs when available |
| Core Docker runtime smoke/persistence | NOT EXECUTED locally | Docker daemon was unavailable |
| Corporate Docker runtime smoke/persistence | NOT EXECUTED locally | Docker daemon was unavailable; manual GitHub workflow is included |
| Evaluation/Phoenix routing smoke/persistence | NOT EXECUTED locally | Docker daemon was unavailable; manual GitHub workflow is included |
| Grafana UI rendering in a live browser | NOT EXECUTED locally | Requires a running stack and browser review |

## Static assertions completed

The repository validator and tests verify the following invariants:

1. `core`, `evaluation`, and `corporate` resolve to explicit, non-composable Compose file sets.
2. Every image expression uses `${VARIABLE:-exact/image:tag}` and matches `.env.example` plus the canonical version map.
3. All published ports bind to `127.0.0.1`; Tempo and Phoenix OTLP receivers are not host-published.
4. Prometheus is a scrape target for Collector-exported metrics, not an unrestricted OTLP or remote-write receiver.
5. Collector pipelines reference declared receivers, processors, and exporters.
6. Prompt, response, tool payload, source code, path, credential, identity, and other free-text fields are minimized before fan-out.
7. Log bodies are replaced by a constant metadata-only value.
8. Metric resource/datapoint attributes use bounded allowlists and exclude session/task/path identities.
9. Corporate mode uses a stricter allowlist, generic span/event names, cleared status and trace state, and no Phoenix route.
10. Phoenix receives only `ai_context.export.phoenix=true` traces after privacy processing; the negative fixture is explicitly false.
11. Loki indexes only `service.name`, `service.namespace`, `deployment.environment.name`, and `ai_context.environment.profile`.
12. Synthetic OTLP fixtures render to valid JSON and contain deterministic trace IDs for runtime assertions.
13. Grafana dashboard/provisioning JSON/YAML parses and datasource UIDs are internally consistent.
14. Codex examples export logs, traces, and metrics to loopback OTLP/HTTP endpoints with `log_user_prompt=false`.
15. Destructive reset refuses to run without the exact Compose project confirmation.

## Commands executed

```text
python3 scripts/toolkit.py validate --mode all --static-only
PASS: repository configuration and policy validation

python3 -m unittest discover -s tests -v
Ran 25 tests
OK

python3 -m compileall -q scripts tests
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

Before treating the toolkit as runtime-validated on a Windows/WSL workstation, execute:

```bash
cp .env.example .env
python3 scripts/toolkit.py validate --mode all
python3 scripts/toolkit.py up --mode core
python3 scripts/toolkit.py smoke --mode core --persistence-check --report artifacts/smoke-core.json
python3 scripts/toolkit.py snapshot --mode core --output artifacts/resource-core.json
python3 scripts/toolkit.py down --mode core
```

Then run `corporate` and `evaluation` separately. Review Collector/container logs and every dashboard.
Do not relabel a skipped or unavailable native/runtime check as passed.

## Repository inventory at packaging

The distribution-level validation report shipped beside the ZIP and Git bundle records the final
file count, source-tree size, commit SHA, tag, artifact hashes, archive verification, and clean-clone
revalidation. Keeping those values outside the tracked tree avoids a self-referential byte count.
