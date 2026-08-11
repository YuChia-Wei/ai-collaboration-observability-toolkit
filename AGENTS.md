# Repository collaboration contract

This repository provides a local, privacy-first OpenTelemetry observability toolkit for AI-assisted software development.

## Fixed architecture decisions

1. `otel-collector` is the only host-facing telemetry ingress. Do not add a second public OTLP endpoint.
2. The core backend is Grafana + Loki + Tempo + Prometheus.
3. Phoenix is optional and, in Evaluation mode, receives already-redacted OpenInference-compatible spans by default. A span without `openinference.span.kind` remains in Tempo only. The `x-ai-observability-phoenix: false` OTLP header or legacy boolean resource attribute `ai_context.export.phoenix=false` opts a compatible trace out. Core and Corporate expose no Phoenix route.
4. Corporate mode is fail-closed: only its exact allowlist may leave the Collector pipelines.
5. Raw prompts, assistant responses, tool arguments/results, command output, source code, diffs, credentials, email addresses, account identifiers, and absolute paths are disabled or removed by default.
6. Never place session, prompt, conversation, task UUID, validation fingerprint, commit SHA, branch, path, or user identity in Prometheus labels or Loki index labels.
7. Do not use floating container tags such as `latest`.
8. Do not claim a runtime test passed unless the containers actually ran and the assertion was observed.

## Canonical files

- Compose topology: `compose.yaml` plus its mode override.
- Collector policy: `config/otel-collector/*.yaml`.
- Telemetry contract: `docs/DATA-CONTRACT.md` and `schemas/`.
- Privacy boundary: `docs/PRIVACY.md`.
- Operations: `scripts/toolkit.py`; shell files are thin wrappers.

## GitHub tool routing

1. Use the GitHub connector first for GitHub-hosted semantic or API operations, including repository, Issue, pull request, comment, label, release, and workflow metadata when the connector exposes the required capability.
2. Use `gh` only when the GitHub connector cannot perform the required operation. Run every `gh` command outside the sandbox from the first attempt because the sandbox has known permission and credential-boundary problems that can make GitHub CLI authentication unavailable.
3. Never treat a sandboxed `gh auth` failure as evidence that host authentication is invalid. Verify through the GitHub connector or rerun the minimum required `gh` command outside the sandbox without reading or printing token values.
4. Continue to use local `git` for local branch, commit, merge, fetch, and ordinary push operations; the connector-first rule applies to GitHub-hosted semantics and API workflows.

## Required validation after changes

```bash
python3 scripts/toolkit.py validate --mode all
python3 -m unittest discover -s tests -v
```

When Docker is available, also run the relevant mode and smoke test. Report `not-executed` rather than `passed` for unavailable checks.
