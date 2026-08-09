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

## Loki returns HTTP 400 from the Collector

Inspect Collector and Loki logs. Common causes are an invalid Loki OTLP resource-attribute mapping,
oversized structured metadata from a newly introduced sender, or a sender value type that the native
OTLP endpoint cannot map. Keep Loki on `/otlp`; do not reintroduce the deprecated Loki-specific
Collector exporter as a workaround.

## Trace is in Tempo but not Phoenix

Check all of these:

1. evaluation mode is running;
2. the OTLP request does not carry `x-ai-observability-phoenix: false`;
3. the resource does not carry boolean `ai_context.export.phoenix=false`;
4. privacy precedes `attributes/phoenix-routing`, and cleanup follows the filter;
5. Phoenix and PostgreSQL are healthy;
6. Collector exporter queue/failure metrics are not increasing;
7. `openinference.project.name` is present when querying a named Phoenix project.

An explicitly opted-out trace being absent from Phoenix is correct. A missing header is expected to
route in v0.1.4.

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

## Runtime test fails only on Phoenix API shape

Phoenix is version-pinned, but its REST API may evolve during a deliberate upgrade. Verify the
selected route in the UI, read the pinned release's `/v1/projects/{project}/traces` API contract, then
update `scripts/toolkit.py`. Preserve all routing assertions: missing and true present, false absent,
absent, sentinel absent.
