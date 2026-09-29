# v0.2.0 — Privacy-first agent usage for constrained workstations

Release date: 2026-09-29. Baseline: v0.1.5.
See [readiness](RELEASE-READINESS-v0.2.0.md) for validation scope and limitations.

## Highlights

- Provider-neutral usage separates agent role, exact model, and disjoint token
  classes. Public API USD and Codex credits estimates use separate versioned
  rules; unknown models and missing rates stay visibly unpriced. Reviewed GPT-6
  Astra/Sol/Luna mappings are included.
- Grafana adds role/Auto-review, activity, and context-attribution views. Costs
  represent the selected range. Empty AI Context effectiveness/workflow
  dashboards are retired until independently observable producers exist.
- Optional Codex Hooks emit content-free AGENT/TOOL lifecycle traces. Prompt
  bytes and allowlisted MCP response bytes require separate size-only opt-in.
  Hook coverage is partial, and bytes do not measure tokens or total context.
- Claude Code CLI/Desktop token normalization is implemented and fixture-tested.
  Exact-client capture provenance is still tracked by Issue #9. Arbitrary
  skill/MCP names are mapped to other/custom before native/canonical export.
- Company mode runs five services with 1664 MiB aggregate memory limits,
  reduced query concurrency, 7-day/1GB metrics block retention and 72-hour
  logs/traces. These limits exclude Docker/WSL overhead and are not disk quotas.
- Source archive and its initializer/pipelines/CLI are removed from every mode;
  analytical LGTM data remains. Old archive volumes are preserved.
- Evaluation uses pinned Phoenix 20.0.0 nonroot. Only redacted spans declaring
  an OpenInference kind reach Phoenix; generic traces stay in Tempo.
- Default host ports belong only to Collector, Grafana, and Evaluation Phoenix.
  Backend readiness and smoke queries use Grafana's datasource proxy. Direct
  Prometheus/Loki/Tempo access requires `compose.debug.yaml`.
- Same-line patches: Grafana 13.1.7, Prometheus 3.13.3, Loki 3.7.8, Tempo 3.0.3,
  PostgreSQL 18.6 Alpine (Evaluation only). See [dependency review](DEPENDENCY-REVIEW-v0.2.0.md).

## Upgrade from v0.1.5

1. Back up the existing deployment configuration and persistent data. Preserve
   named volumes; never use `down -v` as an upgrade step.
2. Check out the approved v0.2.0 tag and compare `.env` image overrides with the
   updated defaults; old overrides otherwise continue to select old images.
3. Review `.env` against `.env.example`, retaining local credentials. Check the
   pinned images in [Dependencies](DEPENDENCIES.md); do not silently replace
   them with floating tags. Review Phoenix/PostgreSQL backup and rollback needs.
4. Run repository, unit, and pinned native configuration checks. In a maintenance
   window, stop the old mode and apply the selected Compose mode without deleting
   volumes. Remove old orphan archive/Phoenix containers when switching to
   Corporate. Review [company setup](COMPANY-LOW-RESOURCE.md) before shortening
   retention on existing data.
5. Update clients that directly query backend host ports. Prefer Grafana;
   explicitly append `compose.debug.yaml` if direct loopback APIs are required.
   Verify the actual container port mappings after applying the configuration.
6. Run the selected-mode smoke with `--persistence-check`, then
   `python scripts/check_attribution_bounds.py --mode <mode>`.
   Persistence checks restart services; schedule them accordingly.

See [Operations](OPERATIONS.md) for exact mode and maintenance commands.

## Data and interpretation boundaries

No historical backfill, deletion, or retroactive privacy cleanup is performed.
Accounting v2 applies to new data. Auto-review source names establish a role,
not an exact model; Antigravity gauges remain observed and unpriced. Neither
API USD nor public credit equivalents are invoices, subscription balances, or
enterprise contract charges. Standard reviewed rates do not infer Fast or
long-context pricing from aggregate telemetry.

Metadata-only is the default. Size-only options export numeric measurements,
not content. Corporate remains fail-closed and has no Phoenix/source-archive
route. Source JSONL is no longer captured. Analytical retention cannot recreate
unknown fields that were dropped during privacy filtering or normalization.

The toolkit does not claim causal skill savings, prompt effectiveness, task
correctness, complete hosted-tool visibility, or Copilot normalization.

## Rollback

Preserve all volumes and a verified pre-upgrade backup. Reverting repository
configuration does not undo database migrations or delete newer telemetry.
Do not downgrade Phoenix against a migrated database without a compatible,
tested restore plan. PostgreSQL 18.6 release notes identify extension/index and
logical-decoding cases to review; isolated tests do not prove all existing
database migrations. A code/configuration rollback may also restore old backend
host ports; review that exposure explicitly. Keep the source archive volume
even if rolling back to a version that does not read it.

## After v0.2.0

Prioritize version-pinned Claude capture/reconciliation (#9), then a bounded
Copilot data adapter feasibility slice (#10). Company showback (#6) and backend
comparison (#7) remain conditional proposals without reserved versions.
The old framework-emitter/evaluator plans (#4/#5) may reopen only with a real
producer, a bounded use case, privacy rules, and explicit experiment ownership.
