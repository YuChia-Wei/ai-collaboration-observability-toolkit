# Provider support matrix

Support means a versioned fixture, a privacy-reviewed mapping, tests, and a
dashboard contract. Documentation alone is not normalization support.

| Provider/product | Verified surface | Fixture | Native view | \`ai_agent.*\` | Cost estimate | Status |
|---|---|---|---|---|---|---|
| OpenAI Codex CLI 0.146.1 | app-server OTLP logs/metrics/traces; app-server 0.147.0-alpha.6.5 | \`fixtures/codex/0.146.1\` | Yes | Yes | Exact mapped models, public API base rates | Supported in 0.1.3 |
| Google Antigravity | documented Hooks and CLI status-line extension | repository examples and privacy fixtures | Yes | Yes, observed gauges/lifecycle metadata | No; observations are not counters/billing | Supported, extension-observed |
| Anthropic Claude Code | documentation only | None | No | No | No | Follow-up required |
| GitHub Copilot | documentation only | None | No | No | No | Follow-up required |
| AI Context framework | framework-owned \`ai_context.*\` contract | schema/example only | Not a provider | Not applicable | Not applicable | Planned for 0.2.0 |

The Antigravity status-line values are observations, not a turn-token counter
or billing ledger, and are therefore not priced. Claude Code and Copilot must
not be shown as normalized or priced until a real, version-pinned privacy-safe
fixture and defensible usage contract are available.
