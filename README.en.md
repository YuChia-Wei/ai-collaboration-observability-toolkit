# AI Collaboration Observability Toolkit

A privacy-first local observability toolkit with the OpenTelemetry Collector as
the only host-facing telemetry ingress. Grafana, Loki, Tempo, and Prometheus
provide execution and usage evidence. In Evaluation mode, Phoenix receives only
already-redacted spans that declare an OpenInference span kind, with an explicit
header-based opt-out.

## Evidence layers

- Native provider telemetry: privacy-filtered codex.* and antigravity_* data.
- Canonical AI-agent usage: bounded ai_agent.* copies created by the Collector.
- Framework evidence: ai_context.* is reserved for independently emitted skills,
  rules, validation, waits, retries, and outcomes. The repository currently has
  schema/fixtures only, not a production emitter or dashboard.

Dashboards never use cross-contract fallback queries. A public API base-price
estimate is produced only when provider-reported tokens, an exact model, and a
versioned rate card all exist. Extension-observed gauges are never presented as
counters or billing.

## Modes

| Mode | Purpose | Policy |
| --- | --- | --- |
| core | Personal LGTM baseline | Initial denylist plus final privacy filter |
| evaluation | Phoenix annotations/datasets/experiments | Redacted OpenInference-compatible spans reach Phoenix by default; generic spans remain in Tempo; `x-ai-observability-phoenix: false` opts out |
| corporate | Company workstation metadata baseline | Exact allowlist, unknown fields dropped, no Phoenix |

## Compose-first quick start

    Copy-Item .env.example .env
    docker compose -f compose.yaml up -d

Evaluation:

    docker compose -f compose.yaml -f compose.evaluation.yaml up -d

Corporate:

    docker compose -f compose.yaml -f compose.corporate.yaml up -d

Stopping with docker compose down retains named volumes. Do not use down -v
without explicit authorization and exact project verification.

Python is optional for starting the stack. It provides policy validation,
smoke orchestration, and evidence reports:

    python -m pip install -r requirements.txt
    python scripts/toolkit.py validate --mode all
    python scripts/toolkit.py smoke --mode evaluation --persistence-check

All published ports are loopback-bound. AI tools send OTLP only to the
Collector on 4317/4318.

## Verified provider surfaces

- Codex CLI 0.146.1 / app-server 0.147.0-alpha.6.5: versioned fixture, native
  dashboard, role-aware ai_agent.* normalization, and separate versioned public
  API USD and Codex credits estimates for exact mapped models.
- Codex lifecycle Hooks: [`examples/codex-hooks`](examples/codex-hooks/README.en.md)
  provides an opt-in metadata-only `AGENT`/`TOOL` Phoenix trace experiment. It
  does not synthesize LLM, token/cost, or prompt-effectiveness data.
- Google Antigravity: direct Hooks and CLI status-line extension; values are
  observed metadata, not billing.
- Claude Code has upstream OpenTelemetry support and GitHub Copilot has upstream
  organization/enterprise usage metrics. This repository has documentation only;
  normalization is not claimed without a version-pinned fixture.

See the [provider support matrix](docs/PROVIDER-SUPPORT.md),
[data contract](docs/DATA-CONTRACT.md), and
[privacy policy](docs/PRIVACY.md).

## Dashboards

- Collector 健康狀態 (Collector Health)
- Codex 原生 Telemetry (Codex Native Telemetry)
- Codex Auto-review 用量 (Approval Reviewer)
- AI Agent 用量 (AI Agent Usage)
- AI Agent 活動 (Metadata and Trace)
- Antigravity 用量 (observed, not billing)

The provisioned dashboards use zh-TW-first human-facing text while keeping English search terms,
canonical identifiers, UIDs, and queries stable. See the
[zh-TW Phoenix reading guide](docs/PHOENIX-READING-GUIDE.zh-TW.md) and
[telemetry glossary](docs/TELEMETRY-GLOSSARY.zh-TW.md).

The former AI Context effectiveness/workflow dashboards were retired because no
production framework emitter exists. Prompts alone cannot independently prove
that a rule was loaded, applied, or caused a better outcome. The contract remains
available for a future explicit emitter.

API USD and Codex public-credit equivalents are separate estimates; neither is
the official remaining subscription allowance, enterprise contract, debit, or
invoice. Cached input is discounted rather than free. Current Auto-review
telemetry proves the approval-reviewer role but not the exact model, so those
tokens remain unmapped and unpriced. Antigravity status-line
token/context/quota values remain unpriced observed snapshots. Claude and
Copilot remain unnormalized and unpriced until version-pinned fixtures are
available.

## Validation

Validation has three explicit tiers: static repository/unit checks, native
Compose/backend configuration checks, and runtime Evaluation/Corporate privacy,
reconciliation, and persistence checks.

    python scripts/toolkit.py validate --mode all --static-only
    python -m unittest discover -s tests -v

Unavailable checks are reported as not-executed, never passed.

The 0.1.3 policy protects the new ingestion window. It does not silently erase
legacy data in persistent volumes; irreversible cleanup requires an explicit
Owner decision.
