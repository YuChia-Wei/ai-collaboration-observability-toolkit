# Operations

## Prerequisites

- Docker Engine or Docker Desktop with Compose v2.
- Python 3.11 or newer.
- Bash for `scripts/*.sh`, or PowerShell 7/Windows PowerShell for `scripts/*.ps1`.
- Sufficient local memory and disk for the selected mode. Do not treat a generic estimate as a
  workstation guarantee; use the resource-baseline procedure.

Install the pinned Python dependencies in a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement requirements.txt
```

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --requirement requirements.txt
```

## Environment preparation

```bash
cp .env.example .env
```

Review every port and replace example passwords. `.env` is ignored by Git. Each Compose image
expression contains an exact committed default and `.env.example` mirrors the same value. Overrides
are supported for controlled testing, but an override is a reviewed configuration change—not an
untracked upgrade mechanism.

## Start, inspect, and stop

Bash wrappers accept the mode as the first positional argument:

```bash
./scripts/up.sh core
./scripts/status.sh core
./scripts/smoke-test.sh core
./scripts/down.sh core
```

PowerShell:

```powershell
.\scripts\up.ps1 -Mode core
.\scripts\status.ps1 -Mode core
.\scripts\smoke-test.ps1 -Mode core
.\scripts\down.ps1 -Mode core
```

The canonical Python form is also available:

```bash
python scripts/toolkit.py up --mode evaluation
python scripts/toolkit.py smoke --mode evaluation
python scripts/toolkit.py down --mode evaluation
```

Use exactly one of `core`, `evaluation`, or `corporate`. Mode overrides are not composable with each
other.

## Validation tiers

### Static repository validation

```bash
python scripts/toolkit.py validate --mode all --static-only
python -m unittest discover -s tests -v
```

This checks YAML/JSON/TOML parsing, duplicate YAML keys, exact image defaults and matching override
variables, loopback ports, Compose mode boundaries, Collector pipeline references/order, OTTL
allowlists, Phoenix opt-in routing, corporate fail-closed rules, Loki label cardinality, Tempo
retention shape, JSON Schema instances, shell syntax, dashboards, fixtures, and sentinel placement.

### Native configuration validation

```bash
python scripts/toolkit.py validate --mode all
```

When available, this additionally runs:

- `docker compose config --quiet` for every merged mode;
- `otelcol-contrib validate` when `OTELCOL_BIN` points to the pinned binary;
- `promtool check config` when `PROMTOOL_BIN` points to the pinned binary;
- Loki `-verify-config=true` when `LOKI_BIN` points to the pinned binary;
- Tempo `-config.verify` when `TEMPO_BIN` points to the pinned binary.

Unavailable executables are printed as `SKIP`. GitHub Actions uses the exact pinned validators or
container image, so pull requests receive native Collector, Prometheus, Loki, Tempo, and merged Compose
checks even when a workstation does not have those binaries installed.

### Runtime smoke and persistence

```bash
./scripts/up.sh core
./scripts/smoke-test.sh core
```

The smoke test waits for services, sends synthetic logs/metrics/traces, queries Prometheus/Loki/Tempo,
checks Grafana and datasource health, and verifies prohibited sentinel data is absent. Evaluation mode
also sends selected/rejected Phoenix traces and checks the positive and negative routes through the
Phoenix REST API.

The default smoke run is intentionally non-disruptive and does not restart the stack. Add
`--persistence-check` when named-volume durability must be verified; this restarts the applicable
services and repeats the backend assertions. A non-executed persistence assertion is recorded as
`SKIP`, never `PASS`. `--skip-persistence` remains as an explicit compatibility flag. Smoke reports
are written under `artifacts/smoke/` unless `--report <path>` is supplied.

## Resource snapshot

```bash
./scripts/resource-snapshot.sh evaluation
```

The command writes Compose process state and `docker stats --no-stream` output to an `artifacts/`
JSON file. Capture at least idle, representative ingestion, representative query, and post-workflow
states. Databases retain caches; compare steady-state and pressure behavior rather than expecting RSS
to return to the initial value.

## Non-destructive stop versus destructive reset

`down` retains data volumes:

```bash
./scripts/down.sh core
```

`reset` destroys all mode volumes and therefore requires the exact Compose project name:

```bash
./scripts/reset-data.sh core ai-collaboration-observability
```

Equivalent canonical form:

```bash
python scripts/toolkit.py reset \
  --mode core \
  --confirm ai-collaboration-observability
```

Do not automate reset against a non-disposable workstation without first exporting any redacted
findings that must be retained.

## PostgreSQL 18 persistence note

The evaluation profile mounts `phoenix-postgres-data` at `/var/lib/postgresql`. PostgreSQL 18 changed
the official image's volume root and version-specific `PGDATA`; do not change this back to
`/var/lib/postgresql/data`, or Phoenix data can be written outside the intended named volume.

## Backup

This is a laboratory toolkit. No automated backup is included. Before a destructive upgrade, archive
named volumes or export only the redacted, durable findings needed for framework improvement. Do not
copy raw personal traces into a corporate or public repository.

## Upgrade procedure

1. Update one exact default image in Compose and the matching value in `.env.example`.
2. Update `scripts/toolkit.py::EXACT_IMAGES`, `docs/DEPENDENCIES.md`, and affected tests.
3. Read component migration notes.
4. Run static/native checks.
5. Run core smoke with persistence.
6. Run corporate and evaluation smoke workflows.
7. Capture resource snapshots and verify dashboards/retention.
8. Record exact evidence and any `NOT EXECUTED` items in an implementation or release report.
