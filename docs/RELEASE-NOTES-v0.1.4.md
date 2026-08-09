# v0.1.4 — Phoenix Routing Compatibility

## Highlights

- Evaluation now forwards already-redacted traces to Phoenix by default.
- `x-ai-observability-phoenix: false` provides a transport-level opt-out for
  clients that support exporter headers.
- The legacy `ai_context.export.phoenix=false` resource opt-out remains
  supported.
- Header-derived routing metadata is temporary and is removed before Phoenix
  persistence.
- Core and Corporate behavior is unchanged; neither has a Phoenix exporter.

## Routing table

| Evaluation input | Tempo | Phoenix |
|---|---|---|
| Header missing, resource missing | Yes | Yes |
| Header `true` | Yes | Yes |
| Header `false` | Yes | No |
| Legacy resource boolean `true` | Yes | Yes |
| Legacy resource boolean `false` | Yes | No |

Privacy transforms run before every Phoenix routing decision. The OTLP header
and temporary routing attribute are not stored in Tempo or Phoenix.

## Upgrade

1. Preserve all existing named volumes.
2. Pull or check out v0.1.4.
3. Run repository, unit, and native configuration validation.
4. Recreate the Evaluation Collector with the merged configuration.
5. Run the Evaluation smoke test and verify all five routing cases.

Do not use `docker compose down -v`; this release requires no data migration or
volume deletion.
