# v0.2.0 — Privacy-first agent usage and source evidence

Status: prepared candidate, not tagged or published. Publication date: unassigned.
Baseline: v0.1.5. See [readiness](RELEASE-READINESS-v0.2.0.md) for open gates.

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
  Exact-client capture provenance is still tracked by Issue #9; bounded
  skill/MCP label acceptance remains open in Issue #24.
- Core/Evaluation preserve privacy-filtered source-shaped OTLP JSON in an
  internal archive, separately from analytical mappings. Safe unknown fields,
  histogram semantics, exemplars, span events, and links can be exported.
- Evaluation uses pinned Phoenix 20.0.0 nonroot. Only redacted spans declaring
  an OpenInference kind reach Phoenix; generic traces stay in Tempo.
- Default host ports belong only to Collector, Grafana, and Evaluation Phoenix.
  Backend readiness and smoke queries use Grafana's datasource proxy. Direct
  Prometheus/Loki/Tempo access requires `compose.debug.yaml`.

## Upgrade from v0.1.5

1. Back up the existing deployment configuration and persistent data. Preserve
   named volumes; never use `down -v` as an upgrade step.
2. Once published, check out the approved v0.2.0 tag. Until then, use an explicitly
   selected candidate commit; this document does not imply that the tag exists.
3. Review `.env` against `.env.example`, retaining local credentials. Check the
   pinned images in [Dependencies](DEPENDENCIES.md); do not silently replace
   them with floating tags. Review Phoenix/PostgreSQL backup and rollback needs.
4. Run repository, unit, and pinned native configuration checks. In a maintenance
   window, apply the selected Compose mode without deleting volumes. The new
   source archive requires its internal service and named volume in Core/Evaluation.
5. Update clients that directly query backend host ports. Prefer Grafana;
   explicitly append `compose.debug.yaml` if direct loopback APIs are required.
   Verify the actual container port mappings after applying the configuration.
6. Run the selected-mode smoke with `--persistence-check`. For Core/Evaluation,
   also run `python scripts/source_archive_smoke.py --mode <mode> --persistence-check`.
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
route. Source archive retention/export requires disk-capacity planning and
the same privacy boundary as ingestion; it cannot recover previously dropped data.

The toolkit does not claim causal skill savings, prompt effectiveness, task
correctness, complete hosted-tool visibility, or Copilot normalization.

## Rollback

Preserve all volumes and a verified pre-upgrade backup. Reverting repository
configuration does not undo database migrations or delete newer telemetry.
Do not downgrade Phoenix against a migrated database without a compatible,
tested restore plan. A code/configuration rollback may also restore old backend
host ports; review that exposure explicitly. Keep the source archive volume
even if rolling back to a version that does not read it.

## After v0.2.0

Prioritize version-pinned Claude capture/reconciliation (#9), then a bounded
Copilot data adapter feasibility slice (#10). Company showback (#6) and backend
comparison (#7) remain conditional proposals without reserved versions.
The old framework-emitter/evaluator plans (#4/#5) may reopen only with a real
producer, a bounded use case, privacy rules, and explicit experiment ownership.
