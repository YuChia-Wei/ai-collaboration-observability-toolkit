# Operations

## Prerequisites

- Docker Engine or Docker Desktop with Docker Compose v2.
- Sufficient local memory and disk for the selected mode.
- Optional: Python 3.11+ with requirements.txt for policy validation, smoke
  orchestration, and evidence reports.
- Optional: Bash or PowerShell for the thin wrappers in scripts/.

Containers do not require a host Python environment.

## Offline session reports

The `session-key`, `session-usage`, and `session-usage-merge` commands use host
Python and run without Docker or network access. They read explicitly selected
local files and write sanitized usage artifacts; they do not modify a running
stack. See [session usage](SESSION-USAGE.md) for commands, private key handling,
company report validation/deduplication, coverage, and pricing assumptions.

## Environment preparation

    Copy-Item .env.example .env

Review host-facing ports and replace sample passwords. The Prometheus, Loki,
and Tempo host port settings apply only with `compose.debug.yaml`. The
untracked .env file may override exact, committed image defaults for controlled tests; an override is
a reviewed change, not an untracked upgrade mechanism.

## Compose-first lifecycle

Core:

    docker compose -f compose.yaml up -d
    docker compose -f compose.yaml ps
    docker compose -f compose.yaml down

Evaluation:

    docker compose -f compose.yaml -f compose.evaluation.yaml up -d
    docker compose -f compose.yaml -f compose.evaluation.yaml ps
    docker compose -f compose.yaml -f compose.evaluation.yaml down

Corporate:

    docker compose -f compose.yaml -f compose.corporate.yaml up -d
    docker compose -f compose.yaml -f compose.corporate.yaml ps
    docker compose -f compose.yaml -f compose.corporate.yaml down

Use exactly one mode override. Evaluation and Corporate are not composable.
Plain down retains named volumes. Never add -v unless the exact Compose project,
backup requirement, and irreversible deletion are explicitly approved.

Default Core and Corporate publish only Collector OTLP gRPC/HTTP and health,
plus Grafana. Evaluation also publishes Phoenix. Prometheus, Loki, Tempo,
and Postgres have no default host ports. Grafana reaches
the three data backends through the private Compose network. Normal `validate`
needs no backend host ports; `smoke` queries them through Grafana's datasource
proxy.

If direct backend API access is needed for local troubleshooting, append the
optional, loopback-only overlay after the selected mode override:

    docker compose -f compose.yaml -f compose.evaluation.yaml -f compose.debug.yaml up -d
    docker compose -f compose.yaml -f compose.evaluation.yaml -f compose.debug.yaml ps

This publishes Prometheus on `127.0.0.1:${PROMETHEUS_PORT:-9090}`, Loki on
`127.0.0.1:${LOKI_PORT:-3100}`, and Tempo on `127.0.0.1:${TEMPO_PORT:-3200}`.
For Core, omit `-f compose.evaluation.yaml`; for Corporate, use
`-f compose.corporate.yaml` in its place. The overlay adds no service or volume.
Remove `-f compose.debug.yaml` from the next `up -d` to return to normal
port publishing; do not use `down -v` for this change.

For an existing Evaluation stack that still has the old backend host ports,
apply the new default during a maintenance window by recreating only the three
backend containers:

    docker compose -f compose.yaml -f compose.evaluation.yaml up -d --no-deps prometheus
    docker compose -f compose.yaml -f compose.evaluation.yaml up -d --no-deps loki
    docker compose -f compose.yaml -f compose.evaluation.yaml up -d --no-deps tempo
    python scripts/toolkit.py wait --mode evaluation
    docker compose -f compose.yaml -f compose.evaluation.yaml ps

The Collector container is not recreated by those commands. Backend export
may briefly retry while Loki or Tempo restarts, so choose a maintenance window
where that short interruption is acceptable. The named volumes are retained.

The shell and PowerShell files in scripts/ are thin wrappers. The optional
Python tool provides the same lifecycle plus structured validation reports:

    python -m pip install -r requirements.txt
    python scripts/toolkit.py up --mode evaluation
    python scripts/toolkit.py smoke --mode evaluation --persistence-check
    python scripts/toolkit.py down --mode evaluation

## Validation tiers

### 1. Static repository validation

    python scripts/toolkit.py validate --mode all --static-only
    python -m unittest discover -s tests -v

This checks structured-file parsing, duplicate YAML keys, pinned images,
loopback ports, mode boundaries, exact Collector processor order, initial and
final privacy policy, canonical mapping parity, Phoenix OpenInference compatibility
plus default-on/opt-out routing, Loki label policy, dashboards, versioned fixtures,
and privacy sentinels.

If Windows exposes bash.exe but the execution sandbox denies WSL startup, shell
syntax is reported as SKIP/not-executed and must be run directly or in CI.

### 2. Native configuration validation

    python scripts/toolkit.py validate --mode all

This runs docker compose config for every mode. When provided through
OTELCOL_BIN, PROMTOOL_BIN, LOKI_BIN, and TEMPO_BIN, it also runs the exact
native validators. Equivalent pinned-container validation is acceptable.
Unavailable checks are SKIP/not-executed, never PASS.

### Token accounting and estimated-cost rules

Prometheus loads legacy `config/prometheus/rules/ai-agent-cost.yml` and v3
`config/prometheus/rules/ai-agent-interval-cost.yml` from read-only Compose
mounts. After changing the mapping or rate card:

1. run `promtool check rules config/prometheus/rules/ai-agent-cost.yml config/prometheus/rules/ai-agent-interval-cost.yml`
   (the pinned Prometheus container is an acceptable validator);
2. run `docker compose ... up -d` without `-v` so named volumes are retained;
3. confirm both `ai-agent-token-accounting-and-estimates` (legacy v2) and
   `ai-agent-interval-estimates-v3` are healthy; the v3 interval must be
   exactly 30 seconds because its dashboard integrals use that fixed step;
4. query `ai_agent_token_usage_total`,
   `ai_agent_token_price_usd_per_million`, and
   `ai_agent_estimated_cost_usd_total`, then separately query
   `ai_agent_token_credit_per_million`,
   `ai_agent_estimated_credit_usage_total`, and both `ai_agent_unpriced_*`
   token metrics for the legacy view. Separately query v3
   `ai_agent_token_usage_per_second`,
   `ai_agent_active_token_price_usd_per_million`,
   `ai_agent_active_token_credit_per_million`,
   `ai_agent_estimated_cost_usd_per_second`,
   `ai_agent_estimated_credit_usage_per_second`, and
   `ai_agent_accounting_sample_available`;
5. confirm v3 series carry `accounting_schema="v3"`, bounded `agent_role`,
   `billing_category`, and `service_namespace`, plus applicable card/policy
   provenance. Only exact trusted approval-operation evidence should create
   non-billable credit samples; API-unknown reviewer coverage stays visible;
6. confirm dashboard queries exclude
   `^ai-collaboration(-cost|-role)?-fixture$`, while unknown real models and
   unpublished credits classes appear as unpriced usage rather than disappearing.

Keep v2 cards/rules immutable and retain named volumes; v3 does not backfill or
rewrite history. Update future rates or policy with new versions after reading
the exact official table and scope. A review date does not establish an
official effective date. V3 totals integrate stored rate gauges at 30 seconds;
do not change that interval without changing the contract and its queries.
Verify sample availability and the latest
`up{job="otel-collector-exported"}` result. A failed/absent latest Collector
scrape suppresses new integral samples. This does not verify upstream provider
completeness; after restoration, `rate()` can bridge short gaps within its
two-minute window. Allow that window around deployment, new-counter warmup,
scrape restoration, and price transitions before interpreting stable estimates.
Missing evaluations are not fabricated as zeros. Corporate's 7-day/1GB retention can remove older
estimate samples. See [the pricing review](PRICING-REVIEW-2026-10-07.md) for
the scope and historical risks. API USD and Codex credits remain separate
estimates; neither is an official subscription allowance, debit, Enterprise
contract, or invoice. A static/native validator pass alone is not a runtime
deployment or observed smoke pass.

### 3. Runtime smoke and persistence

    python scripts/toolkit.py smoke --mode evaluation --persistence-check


## Human trace review and annotations

Use [Phoenix Trace 閱讀指南](PHOENIX-READING-GUIDE.zh-TW.md) before treating low-level spans as
task outcomes. The [Telemetry 詞彙表](TELEMETRY-GLOSSARY.zh-TW.md) maps canonical English
identifiers to stable zh-TW explanations without changing query keys.

Use Grafana's AI Agent Activity dashboard for native prompt/tool/API/sandbox
metadata and Tempo trace correlation. Phoenix is appropriate only when a trace
already carries OpenInference semantics needed for annotation or evaluation.

Check the five-config rubric without mutation, then explicitly provision it for one existing Phoenix
Project when desired:

    python scripts/toolkit.py phoenix-annotations --project "<project-name>"
    python scripts/toolkit.py phoenix-annotations --project "<project-name>" --apply

The apply path uses idempotent create/update/assignment requests. It never removes owner data.
Synthetic smoke traces remain distinguishable by their fixed Project and trace IDs.

## Codex configuration

Before changing the user-level Codex config:

1. create a same-directory timestamped backup;
2. change only [otel];
3. keep logs/traces/metrics endpoints on 127.0.0.1 Collector ports;
4. set log_user_prompt=false;
5. do not terminate the current Codex process; the Owner restarts it afterward.

## Persistence, backup, and rollback

The named volumes are:

- grafana-data
- loki-data
- prometheus-data
- tempo-data
- phoenix-postgres-data in Evaluation

PostgreSQL 18 must mount phoenix-postgres-data at /var/lib/postgresql, not the
legacy /var/lib/postgresql/data path.

Before destructive work, back up or export only the redacted evidence that
must survive. To roll back application/config changes:

1. check out tag v0.1.2 or restore its exact Compose/config files;
2. run merged Compose and native config validation;
3. run docker compose up -d without -v so existing named volumes remain;
4. restore the Codex config backup if required and have the Owner restart Codex;
5. record that legacy stored data was not retroactively removed.

The toolkit has no automated backup and never silently deletes pre-0.1.3 data.

## Removed source archive

v0.2.0 no longer runs the source archive or initializer in any mode. Existing
`collector-source-data` volumes are retained but receive no new records after
old archive containers stop. Export any needed old records using the old
checkout before removal; never delete volumes as part of this upgrade.

## Resource snapshot

    python scripts/toolkit.py snapshot --mode evaluation

Capture idle, representative ingestion/query, and post-workflow snapshots.
Compare steady-state and pressure behavior; database caches need not return to
their initial RSS.

## Upgrade procedure

1. Update one exact image default and matching .env.example value.
2. Update the dependency inventory and validator expectations.
3. Record a versioned provider fixture before changing normalization.
4. Run all three validation tiers.
5. Verify privacy, native/canonical reconciliation, dashboard UIDs, and
   persistence.
6. Record exact results and all not-executed gates in the release report.
