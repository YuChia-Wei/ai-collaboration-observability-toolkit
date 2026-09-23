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

Prometheus loads `config/prometheus/rules/ai-agent-cost.yml` from a read-only
Compose mount. After changing the mapping or rate card:

1. run `promtool check rules config/prometheus/rules/ai-agent-cost.yml` (the
   pinned Prometheus container is an acceptable validator);
2. run `docker compose ... up -d` without `-v` so named volumes are retained;
3. confirm the `ai-agent-token-accounting-and-estimates` rule group is healthy;
4. query `ai_agent_token_usage_total`,
   `ai_agent_token_price_usd_per_million`, and
   `ai_agent_estimated_cost_usd_total`, then separately query
   `ai_agent_token_credit_per_million`,
   `ai_agent_estimated_credit_usage_total`, and both `ai_agent_unpriced_*`
   token metrics;
5. confirm new accounting/estimate series carry `accounting_schema="v2"`, a
   bounded `agent_role`, and their bounded `service_namespace`;
6. confirm dashboard queries exclude
   `^ai-collaboration(-cost|-role)?-fixture$`, while unknown real models and
   unpublished credits classes appear as unpriced usage rather than disappearing.

The v2 rules apply only to newly mapped data and do not rewrite existing stored
series. API USD and Codex credits are separate estimates. Neither is an official
subscription allowance, debit, Enterprise contract, or invoice.

### 3. Runtime smoke and persistence

    python scripts/toolkit.py smoke --mode evaluation --persistence-check

Verify the source archive's independent privacy and retention path as well:

    python scripts/source_archive_smoke.py --mode evaluation --persistence-check

This sends synthetic logs, traces, and histogram streams with unknown safe
dimensions and sensitive canaries, reads the source files, restarts both the
archive service and Collector, and sends another fixture. It verifies that old
file bytes survive and new records append. Use `--mode core` when
verifying Core. Reports are written under `artifacts/source-smoke-<marker>`.

Runtime smoke:

- sends legacy compatibility fixtures plus the versioned Codex metrics/logs/
  traces fixture;
- sends synthetic exact-model and role-accounting data and proves the four
  non-overlapping token classes, bounded `primary`/`approval_reviewer`/`subagent`
  roles, 12 API rate series, 9 published Codex credits rate series, separate USD
  and credits estimates, and explicit unpriced cache-write/reviewer boundaries;
  the fixtures use `ai-collaboration-cost-fixture` and
  `ai-collaboration-role-fixture`;
- executes the Antigravity status-line exporter against its privacy fixture,
  under `service_namespace=ai-collaboration-fixture`,
  reconciles native/canonical observed gauges, and proves Google observations
  do not produce an estimated-cost series;
- proves the synthetic privacy fields are absent in the new Prometheus, Loki,
  Tempo, and selected Phoenix window;
- reconciles native and canonical Codex histogram values;
- checks Grafana datasources and provisioned dashboard availability;
- verifies Phoenix missing-header default, header true/false, and legacy resource
  routing for compatible spans in Evaluation, and proves a generic span remains
  in Tempo without entering Phoenix;
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
- collector-source-data for the Core/Evaluation source archive
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

## Source archive export and maintenance

Core and Evaluation automatically retain privacy-filtered source logs, metrics,
and traces in `collector-source-data`, mounted at `/var/lib/otelcol/source` in
the internal `source-archive` service. The three files are `logs.jsonl`,
`metrics.jsonl`, and `traces.jsonl`. They receive data before provider normalization, backend label
allowlists, Prometheus conversion, and Phoenix filtering. Safe unknown fields
and unmapped metrics therefore remain available for later analysis.

Compose first runs `source-storage-init` once to set the volume directory owner
to UID/GID `10001:10001` with mode `0700`. This uses the existing pinned Grafana
image, no network, and root only for directory ownership and permissions; the
source service runs as UID/GID `10001:10001`, and the Collector continues to run
as its image's non-root user. `Exited (0)` is the
expected init-service state. It does not clear archive files or change their
contents, and the source service waits for successful initialization before startup.

The service uses the Python standard library in
`scripts/source_archive_server.py`. The Collector sends JSON to it over
the private Compose network; it recursively redacts, appends, and syncs the
per-signal file. It publishes no host port. Senders keep using the Collector's
4317/4318 endpoints.

Export the archive to a new local directory:

    python scripts/toolkit.py source-export --mode evaluation --output artifacts/source-export-2026-09-20

Use `--mode core` for Core. Corporate has no source export route and this command
is unavailable for that mode. The shared Compose service may remain idle;
switching to Corporate does not erase existing personal archive data. The command copies
the source directory, including all three signal files and any recovered partial
records, and writes a metadata manifest with byte sizes without
printing their contents or deleting source data. The output directory must be
new; omitting `--output` creates `artifacts/source-export-<UTC timestamp>`.
This is an export of stored source records, not a backfill from Loki, Tempo,
Prometheus, Phoenix, or the provider. Records previously discarded or never sent
to the updated Collector cannot be recovered.

Read the exported OTLP JSONL locally with Python, for example to count metrics
without printing attribute values:

```python
import json
from pathlib import Path

archive = Path("artifacts/source-export-2026-09-20/metrics.jsonl")
metric_count = 0
with archive.open(encoding="utf-8") as stream:
    for line in stream:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            # A live copy may end halfway through the last written record.
            if not line.endswith("\n") and not stream.read(1):
                print("Skipped incomplete final line from live export")
                break
            raise
        metric_count += sum(
            len(scope.get("metrics", []))
            for resource in request.get("resourceMetrics", [])
            for scope in resource.get("scopeMetrics", [])
        )
print(f"Archived metric records: {metric_count}")
```

Each line is an OTLP export request and can contain multiple records. JSON
decoding does not imply that a metric has reviewed accounting semantics; use
the [data contract](DATA-CONTRACT.md) before deriving token or cost totals.
Ignore only an incomplete final line from a live copy; malformed complete lines
or corruption in the middle of a file require investigation.

The archive service appends on restart and deliberately performs no rotation,
expiration, or automatic deletion. Backend 14-day retention does not apply to
this archive. Check free disk space and Collector export failures regularly;
the volume can grow until the disk is full. Privacy filtering is still required
and does not constitute universal DLP for arbitrary future fields. Exported
files and backups need the same local access controls as the live volume.

Treat this as a local analysis format, not an exactly-once durable queue. The
archive checks for an unfinished final record at startup. Before continuing it
durably preserves those already-redacted bytes in a uniquely named
`recovered-<signal>-<id>.partial` file, then restores the signal file to its last
complete line. If preservation fails, startup fails without removing the tail.
Recovery files are included in `source-export`; they are incomplete fragments,
not valid OTLP requests. A retry after an uncertain acknowledgement may also
produce duplicate complete records.

The
Collector source export has no sending queue, so unredacted data is not spooled
to disk. An export from a running archive service is not an atomic snapshot
across all three signals; ongoing ingestion may append records while files are
copied. Stop the source archive service for a quiescent copy when needed and
account for sender and Collector retry/loss during the
pause. Before any manual archive truncation or volume deletion, confirm the
exact Compose project and volume, export and verify the records to retain, and
obtain explicit deletion authorization. Ordinary `down` keeps the archive.

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
