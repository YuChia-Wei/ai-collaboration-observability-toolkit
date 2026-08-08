# Codex telemetry fixture: CLI 0.146.1

This fixture records the telemetry shape verified for Codex CLI 0.146.1
(rust-v0.146.1, commit 79b4f03d35962b005b007a015113b38930711665).
The emitting app-server identified itself as 0.147.0-alpha.6.5.

The metric names, kinds, labels, log event names, and representative span name
were observed through the local Prometheus, Loki, and Tempo backends on
2026-08-09. Values, timestamps, trace/span IDs, and any identifying values in
the JSON files are synthetic. The codex_fixture_private_sentinel attributes are
deliberate negative-test inputs and must be removed by the Collector.

Codex constructs counters as monotonic OTLP sums and durations/token usage as
OTLP histograms. Its v0.146.1 OTLP metric exporter uses Delta temporality.
Prometheus exposes the accumulated scrape view, including histogram _bucket,
_count, and _sum series. The canonical ai_agent.* copy must retain the original
instrument kind and temporality.

The fixture is intentionally incomplete: it represents the release-blocking
contract surface, not every internal Codex metric. Raw prompts, assistant
responses, command output, tool arguments/results, paths, account identifiers,
and real conversation/session IDs are not captured.

Files:

- metrics.sanitized.json: replayable OTLP/HTTP metrics with histogram, counter,
  and bounded-label examples.
- logs.sanitized.json: replayable metadata log with privacy-negative fields.
- traces.sanitized.json: replayable span with privacy-negative fields.
- mapping.yaml: raw-to-canonical mapping and semantic constraints.
- prometheus-series.md: representative observed Prometheus series.
