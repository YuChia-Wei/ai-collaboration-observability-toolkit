# Claude Code integration notes

Point Claude Code OpenTelemetry logs, metrics, and traces to `http://127.0.0.1:4318` (OTLP/HTTP) or `127.0.0.1:4317` (OTLP/gRPC), following the settings supported by the installed Claude Code release.

Disable prompt/content export and high-cardinality metric dimensions at the client where possible. The Collector remains the enforcement boundary. Before production or company use, capture one synthetic session, inventory its actual attributes, and update only the documented normalization mapping.
