# v0.1.5 — Human-readable Observability

v0.1.5 is the final planned 0.1.x release. It adds a Traditional Chinese human-reading layer while
keeping canonical telemetry identifiers and all privacy/routing boundaries unchanged.

## Highlights

- All six provisioned Grafana dashboards now use zh-TW-first titles, descriptions, explanatory text,
  legends, and applicable value mappings.
- Dashboard UIDs, PromQL expressions, datasource boundaries, units, and telemetry semantics are
  unchanged.
- `docs/PHOENIX-READING-GUIDE.zh-TW.md` explains a consistent reading order and four diagnostic
  scenarios: slow turns, repeated handling, tool/environment failures, and long waits.
- `docs/TELEMETRY-GLOSSARY.zh-TW.md` maps provider-native, `ai_agent.*`, and `ai_context.*` evidence
  without translating canonical keys.
- A five-config Chinese operational annotation rubric can be checked read-only and provisioned
  idempotently through Phoenix 19.19.0's versioned REST API.
- Real traces and synthetic smoke fixtures remain distinguishable through the fixture Project and
  deterministic IDs; no historical owner data is deleted or rewritten.

## Privacy and interpretation boundary

Privacy-safe traces still exclude prompts, responses, tool arguments/results, command output, code,
diffs, credentials, identities, and absolute paths. A span's duration or status can support an
operational diagnosis but cannot prove task completion or answer correctness. Core and Corporate
still expose no Phoenix route.

## Annotation rubric

Use the read-only command first, then apply only to the intended existing Phoenix Project:

```powershell
python scripts/toolkit.py phoenix-annotations --project "<project-name>"
python scripts/toolkit.py phoenix-annotations --project "<project-name>" --apply
```

The command creates or updates only the five version-controlled configs and assigns them
idempotently. It performs no deletion.

## Upgrade

1. Preserve all five Evaluation named volumes and do not use `down -v`.
2. Pull or check out `v0.1.5`.
3. Run repository, unit, and pinned native configuration validation.
4. Recreate the existing stack without deleting volumes so Grafana reloads the dashboards.
5. Run Evaluation smoke and persistence checks.
6. Read the Phoenix guide before applying annotations to a real project.

## Next line

After v0.1.5, planning moves to v0.2.0: the AI Collaboration Improvement Loop. Semantic span
normalization, datasets, evaluators, experiments, and LLM-as-a-judge automation require a separate
owner planning and authorization pass.
