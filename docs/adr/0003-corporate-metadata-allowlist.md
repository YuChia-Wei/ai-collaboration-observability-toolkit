# ADR 0003: Corporate mode is metadata allowlist, not expanded denylist

- Status: Accepted
- Date: 2026-08-07

## Decision

Corporate mode applies a strict `keep_keys` allowlist after baseline privacy transforms and replaces
log bodies with a constant marker.

## Rationale

AI clients evolve and can add unknown content-bearing attributes. A denylist cannot safely anticipate
all future fields in a regulated environment.

## Consequences

Some diagnostics available in personal mode are intentionally unavailable. Contract additions need
privacy review and explicit allowlist changes. Unknown fields disappear rather than silently leaving
the workstation.
