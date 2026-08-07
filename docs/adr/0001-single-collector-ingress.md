# ADR 0001: One host-facing OpenTelemetry Collector

- Status: Accepted
- Date: 2026-08-07

## Decision

All AI tools and applications send to one local OpenTelemetry Collector. Backends and Phoenix do not
publish OTLP ingestion ports to the host.

## Rationale

This creates one privacy/routing contract, allows backend replacement without changing every tool,
and prevents inconsistent redaction. An additional backend-bundled Collector may exist internally in
a future experiment, but senders still target this toolkit's Collector.

## Consequences

Collector availability is required for live ingestion. Its configuration becomes security-sensitive
product code and requires sentinel tests.
