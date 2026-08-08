# Implementation report

## Release

- Version: 0.1.3
- Theme: Observability Baseline Stabilization
- Owner work items: Issues #1, #2, and #3
- Next release: Issues #4 and #5 remain planned for 0.2.0
- Unallocated/deferred: Issues #6 and #7 retain their Owner state

## Delivered scope

1. Captured a privacy-safe, versioned Codex CLI 0.146.1/app-server
   0.147.0-alpha.6.5 fixture with official source and local backend evidence.
2. Added an initial denylist before normalization in all three Collector modes,
   followed by the existing final privacy filter or Corporate allowlist.
3. Added provider-neutral ai_agent.* copies while preserving privacy-filtered
   native metrics and their original instrument semantics.
4. Aligned Antigravity Hooks/status-line telemetry to the same resource
   contract and mapped its status values only as observed gauges.
5. Split dashboards into Codex Native Telemetry, AI Agent Usage, and genuine
   AI Context evidence without cross-contract fallbacks or invented cost.
6. Made Docker Compose the primary documented runtime path and retained Python
   as an optional validator/orchestrator.
7. Added truthful provider support documentation and created follow-up Issues
   #9 and #10 for Claude Code and GitHub Copilot fixtures.
8. Corrected the Tempo 3.0.2 native validation flag to config.verify=true.

## Privacy result

The 0.1.3 runtime fixture deliberately injects synthetic sensitive attributes
into metrics, logs, and traces. Evaluation and isolated Corporate smoke both
proved those fields absent in the new Prometheus/Loki/Tempo time window.
Evaluation also proved selected traces reach Phoenix only after redaction and
rejected traces do not reach Phoenix.

Persistent data written before 0.1.3 was not deleted. The release makes no
retroactive-erasure claim. Irreversible cleanup remains an Owner decision.

## Runtime result

Evaluation ran all seven services and passed privacy, dashboard, Phoenix,
native/canonical reconciliation, and restart-persistence checks with all five
named volumes retained.

Corporate ran as the isolated project
ai-collaboration-observability-v013-corporate-test on alternate loopback ports.
It contained five services, no Phoenix, passed privacy/reconciliation/
persistence checks, and its containers/network/test volumes were then removed.

The primary Evaluation project and its volumes remained intact.

## Codex configuration

A same-directory timestamped backup was created before changing the user
configuration. Only log_user_prompt changed from true to false. All three
OTLP/HTTP endpoints remain on 127.0.0.1:4318 with the correct signal paths.
The active Codex process was not terminated; the Owner must restart Codex for
the sender-side setting to take effect.

## Compatibility

- Dashboard UID ai-codex-usage is preserved.
- Privacy-filtered native provider telemetry remains queryable.
- ai_agent.* is additive.
- Legacy ai_context provider-usage metrics remain queryable but are not copied
  into ai_agent.*.
- ai_context.environment.profile remains a deprecated 0.1.x alias for
  ai_observability.profile.

## Known limitations

- Claude Code and GitHub Copilot have no versioned fixtures, so normalization
  is not claimed.
- Antigravity values come from local documented extension surfaces and are not
  authoritative billing records.
- Cost remains unavailable until an explicit versioned provider billing/rate
  source is implemented.
- Historical local volume data may predate the strengthened policy.
