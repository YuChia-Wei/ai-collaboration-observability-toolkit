# Implementation report

## Release

- Version: 0.1.4
- Theme: Phoenix Routing Compatibility
- Owner work item: GitHub Issue #12

## Delivered scope

1. Changed Evaluation Phoenix routing from resource-attribute opt-in to
   privacy-safe default-on routing.
2. Added `x-ai-observability-phoenix` OTLP request metadata handling: missing
   and `true` forward; `false` opts out.
3. Preserved `ai_context.export.phoenix=true/false` compatibility for producers
   that can emit custom resource attributes.
4. Kept privacy processors ahead of routing and removed the temporary
   header-derived span attribute before Phoenix export.
5. Updated Antigravity so its default omits the legacy attribute; explicit
   `--phoenix` and `--no-phoenix` remain available.
6. Added deterministic missing-header, header-true, and header-false fixtures,
   static policy assertions, unit coverage, runtime positive/negative checks,
   and operator documentation.

## Boundaries

- The Collector remains the only host-facing OTLP ingress.
- Every minimized trace continues to Tempo, including Phoenix opt-outs.
- Core and Corporate define no Phoenix exporter; a request header cannot
  enable one.
- Logs and metrics are unaffected by the Phoenix routing switch.
- Existing owner Evaluation volumes were preserved.

## Runtime result

Evaluation ran all seven services and passed privacy, dashboard,
native/canonical reconciliation, five-case Phoenix routing, routing-metadata
absence, and restart-persistence checks with all five named volumes retained.

Corporate ran as the isolated project
`ai-collaboration-observability-v014-corporate-test` on alternate loopback
ports. It contained five services, no Phoenix, passed privacy/reconciliation/
persistence checks, and its containers, network, and four test volumes were
then removed.

## Compatibility and limitation

Codex exporter headers are user-level OpenTelemetry configuration; Codex does
not apply `[otel]` from a project-local `.codex/config.toml`. The default-on
route is therefore the compatibility path for Codex/ChatGPT Desktop and other
clients that cannot attach per-project resources or headers. Per-project
opt-out requires a producer surface that can send the header or legacy resource
attribute.
