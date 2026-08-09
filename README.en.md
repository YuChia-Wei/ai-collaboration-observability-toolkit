# AI Collaboration Observability Toolkit

A privacy-first local observability toolkit with the OpenTelemetry Collector as
the only host-facing telemetry ingress. Grafana, Loki, Tempo, and Prometheus
provide execution and usage evidence. Phoenix receives already-redacted traces
by default in Evaluation mode, with an explicit header-based opt-out.

## Evidence layers

- Native provider telemetry: privacy-filtered codex.* and antigravity_* data.
- Canonical AI-agent usage: bounded ai_agent.* copies created by the Collector.
- Framework evidence: ai_context.* skills, rules, validation, waits, retries,
  and outcomes emitted independently by the AI Context framework.

Dashboards never use cross-contract fallback queries. Token, turn, or request
counts are not converted into cost.

## Modes

| Mode | Purpose | Policy |
| --- | --- | --- |
| core | Personal LGTM baseline | Initial denylist plus final privacy filter |
| evaluation | Phoenix annotations/datasets/experiments | Redacted traces reach Phoenix by default; `x-ai-observability-phoenix: false` opts out |
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
  dashboard, and ai_agent.* normalization.
- Google Antigravity: direct Hooks and CLI status-line extension; values are
  observed metadata, not billing.
- Claude Code and GitHub Copilot: documentation only; normalization is not
  claimed without a version-pinned fixture.

See the [provider support matrix](docs/PROVIDER-SUPPORT.md),
[data contract](docs/DATA-CONTRACT.md), and
[privacy policy](docs/PRIVACY.md).

## Dashboards

- Collector 健康狀態 (Collector Health)
- Codex 原生 Telemetry (Codex Native Telemetry)
- AI Agent 用量 (AI Agent Usage)
- Antigravity 用量 (observed, not billing)
- AI 工作流程效率 (AI Workflow Efficiency)
- AI Context 有效性 (Effectiveness)

The provisioned dashboards use zh-TW-first human-facing text while keeping English search terms,
canonical identifiers, UIDs, and queries stable. See the
[zh-TW Phoenix reading guide](docs/PHOENIX-READING-GUIDE.zh-TW.md) and
[telemetry glossary](docs/TELEMETRY-GLOSSARY.zh-TW.md).

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
