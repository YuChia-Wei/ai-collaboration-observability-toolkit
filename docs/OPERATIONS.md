# Operations

## Prerequisites

- Docker Engine or Docker Desktop with Docker Compose v2.
- Sufficient local memory and disk for the selected mode.
- Optional: Python 3.11+ with requirements.txt for policy validation, smoke
  orchestration, and evidence reports.
- Optional: Bash or PowerShell for the thin wrappers in scripts/.

Containers do not require a host Python environment.

## Environment preparation

    Copy-Item .env.example .env

Review every port and replace sample passwords. The untracked .env file may
override exact, committed image defaults for controlled tests; an override is
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
final privacy policy, canonical mapping parity, Phoenix default-on/opt-out routing, Loki
label policy, dashboards, versioned fixtures, and privacy sentinels.

If Windows exposes bash.exe but the execution sandbox denies WSL startup, shell
syntax is reported as SKIP/not-executed and must be run directly or in CI.

### 2. Native configuration validation

    python scripts/toolkit.py validate --mode all

This runs docker compose config for every mode. When provided through
OTELCOL_BIN, PROMTOOL_BIN, LOKI_BIN, and TEMPO_BIN, it also runs the exact
native validators. Equivalent pinned-container validation is acceptable.
Unavailable checks are SKIP/not-executed, never PASS.

### Token accounting and estimated-cost rules

Prometheus loads `config/prometheus/rules/ai-agent-cost.yml` from a read-only
Compose mount. After changing the mapping or rate card:

1. run `promtool check rules config/prometheus/rules/ai-agent-cost.yml` (the
   pinned Prometheus container is an acceptable validator);
2. run `docker compose ... up -d` without `-v` so named volumes are retained;
3. confirm the `ai-agent-token-accounting-and-cost` rule group is healthy;
4. query `ai_agent_token_usage_total`,
   `ai_agent_token_price_usd_per_million`, and
   `ai_agent_estimated_cost_usd_total`;
5. confirm new accounting/cost series carry `accounting_schema="v1"` and retain
   their bounded `service_namespace`;
6. confirm dashboard queries exclude
   `^ai-collaboration(-cost)?-fixture$`, while unknown real models appear as
   unpriced usage rather than disappearing.

The rate card applies only to newly mapped data and does not rewrite existing
stored series. Its cost is a public API base-price estimate, not a subscription
or invoice.

### 3. Runtime smoke and persistence

    python scripts/toolkit.py smoke --mode evaluation --persistence-check

Runtime smoke:

- sends legacy compatibility fixtures plus the versioned Codex metrics/logs/
  traces fixture;
- sends a synthetic exact-model accounting fixture and proves the four
  non-overlapping token classes, 12 versioned rate series, an estimated cost,
  and the absence of a price for `codex-auto-review`; this fixture uses
  `service_namespace=ai-collaboration-cost-fixture`;
- executes the Antigravity status-line exporter against its privacy fixture,
  under `service_namespace=ai-collaboration-fixture`,
  reconciles native/canonical observed gauges, and proves Google observations
  do not produce an estimated-cost series;
- proves the synthetic privacy fields are absent in the new Prometheus, Loki,
  Tempo, and selected Phoenix window;
- reconciles native and canonical Codex histogram values;
- checks Grafana datasources and provisioned dashboard availability;
- verifies Phoenix missing-header default, header true/false, and legacy resource routing in Evaluation;
- restarts services and proves named-volume data remains queryable when
  persistence-check is selected.

Corporate must be tested as an isolated Compose project with alternate
loopback ports. It must contain no Phoenix service/exporter and must use the
exact allowlist. Test-project cleanup may delete only volumes whose Compose
project label matches the reviewed isolated test project.

Smoke reports are written under artifacts/smoke unless an explicit report path
is supplied.

## Human trace review and annotations

Use [Phoenix Trace 閱讀指南](PHOENIX-READING-GUIDE.zh-TW.md) before treating low-level spans as
task outcomes. The [Telemetry 詞彙表](TELEMETRY-GLOSSARY.zh-TW.md) maps canonical English
identifiers to stable zh-TW explanations without changing query keys.

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
