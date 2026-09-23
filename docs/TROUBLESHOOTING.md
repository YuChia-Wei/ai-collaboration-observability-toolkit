# Troubleshooting

## Collector does not start

Run the exact profile through the pinned image's native validator:

```bash
docker run --rm \
  -v "$PWD/config/otel-collector/core.yaml:/etc/otelcol/config.yaml:ro" \
  otel/opentelemetry-collector-contrib:0.158.0 \
  validate --config=/etc/otelcol/config.yaml
```

OTTL parser errors normally identify the statement/context. Confirm every `keep_keys` list contains
quoted string literals and keep resource, span, span-event, log, metric, datapoint, and exemplar
statements in compatible context groups. Privacy transforms intentionally use
`error_mode: propagate`; a newly incompatible sender/configuration is dropped rather than routed
without minimization.

## Codex sends logs but no metrics

Codex has independent exporters. Confirm `metrics_exporter` points to `/v1/metrics`; do not assume the
log exporter routes every signal. Restart the Codex process after editing the user-level config.

## Prometheus metric exists but useful dimensions are missing

The cardinality processor intentionally removes session, request, trace, prompt, path, user, workflow
UUID, validation fingerprint, and commit dimensions. Inspect traces or Loki structured metadata
instead of restoring them as metric labels. Add only bounded dimensions to the documented contract.

For safe source dimensions that are not in the backend allowlist, export the
Core/Evaluation source archive with
`python scripts/toolkit.py source-export --mode evaluation --output artifacts/source-export-2026-09-20`
and inspect `metrics.jsonl` locally. It retains non-sensitive source attributes
before canonical mapping and Prometheus label reduction. Sensitive identifiers
and content remain redacted there too.

## Unknown telemetry or a histogram is absent from Prometheus

A backend metric name or dashboard mapping is not the source retention boundary.
Core/Evaluation source pipelines archive all three received signal types before
Prometheus conversion. For example, `Dropped misaligned histogram datapoint`
can mean that a histogram projection cannot be accumulated by Prometheus; the
original privacy-filtered datapoint remains in `metrics.jsonl` if the source
export succeeded. Review its bounds, count, sum, and temporality before adding a
canonical mapping. Do not guess semantics from the metric name.

If the record is absent from the archive too, check the running mode and
Collector configuration, source archive service health, source-export errors, available disk space, and
whether the sender sent that signal after source archiving was deployed.
Corporate intentionally has no source archive route. This feature cannot recover
earlier discarded records, sender-side omissions, or transport failures.

## Source archive grows or export fails

For startup permission errors under `/var/lib/otelcol/source`, inspect
`source-storage-init` first. Its expected state is `Exited (0)` after setting the
volume directory owner and permissions. The Collector waits for that successful
exit indirectly through the source service, which runs as UID/GID `10001:10001`;
do not work around directory permissions by running either service as root.

Check both Collector and `source-archive` logs for ingestion errors. The source
service has no published host port; senders must use the Collector endpoint,
which forwards this copy over the private Compose network.

The `collector-source-data` volume has no TTL or automatic rotation/deletion.
Backend retention settings do not prune it. Disk exhaustion and file-write
errors can prevent new source records from being stored. Check disk capacity
and Collector errors, export records that must survive, and follow the explicit
maintenance procedure in [Operations](OPERATIONS.md). Do not use `down -v` to
solve a full disk without exact project verification and deletion authorization.

## Loki returns HTTP 400 from the Collector

Inspect Collector and Loki logs. Common causes are an invalid Loki OTLP resource-attribute mapping,
oversized structured metadata from a newly introduced sender, or a sender value type that the native
OTLP endpoint cannot map. Keep Loki on `/otlp`; do not reintroduce the deprecated Loki-specific
Collector exporter as a workaround.

## Trace is in Tempo but not Phoenix

Check all of these:

1. evaluation mode is running;
2. the span declares `openinference.span.kind`; a generic span is expected only in Tempo;
3. the OTLP request does not carry `x-ai-observability-phoenix: false`;
4. the resource does not carry boolean `ai_context.export.phoenix=false`;
5. privacy precedes `filter/phoenix-openinference`, then routing and cleanup;
6. Phoenix and PostgreSQL are healthy;
7. Collector exporter queue/failure metrics are not increasing;
8. `openinference.project.name` is present when querying a named Phoenix project.

An explicitly opted-out or generic trace being absent from Phoenix is correct. A
missing header routes only after the OpenInference compatibility check.

## Phoenix dashboard has traces but cost/token/LLM panels are empty

This is expected when the stored spans lack OpenInference LLM kind, model, token,
cost, input, or output attributes. Project selection can reveal an existing
project, but it cannot add missing semantics. Use AI Agent 活動 and Tempo for
native Codex metadata/internal traces. Use Phoenix only for compatible traces
that were instrumented for evaluation; privacy policy still removes raw
prompt/response content.

## Grafana datasource health fails

Use the direct endpoints first:

```text
Prometheus  http://127.0.0.1:9090/-/ready
Loki        http://127.0.0.1:3100/ready
Tempo       http://127.0.0.1:3200/ready
Grafana     http://127.0.0.1:3000/api/health
```

Then inspect provisioned URLs inside the Docker network. `localhost` inside Grafana would point to the
Grafana container; the correct datasource URLs use Compose service names.

## Docker Desktop / WSL path problems

Run Compose and scripts consistently from one environment. Mounting a Windows path through a WSL
Docker client can introduce permission or path-translation issues. The Repository uses relative
read-only configuration mounts and named data volumes to minimize this risk.

## Port already allocated

Change the corresponding host port in `.env`; do not change backend container ports or publish Tempo
or Phoenix OTLP ports. AI tools must use the updated Collector host port.

## Smoke test keeps finding an old rejected Phoenix trace

The synthetic trace IDs are deterministic. A previous unsafe configuration may have persisted the
rejected trace. Preserve the failed report as evidence, then intentionally reset the disposable
laboratory volumes and rerun with the corrected configuration. Do not weaken the negative assertion.
For an owner stack, do not delete history merely to make the UI cleaner. Filter the fixed
`ai-collaboration-observability-fixture` Project and IDs described in the
[Phoenix Trace 閱讀指南](PHOENIX-READING-GUIDE.zh-TW.md).

## Runtime test fails only on Phoenix API shape

Phoenix is version-pinned, but its REST API may evolve during a deliberate upgrade. Verify the
selected route in the UI, read the pinned release's `/v1/projects/{project}/traces` API contract, then
update `scripts/toolkit.py`. Preserve all routing assertions: missing and true present, false absent,
absent, sentinel absent.
