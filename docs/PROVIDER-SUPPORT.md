# Provider support matrix

Support means a versioned fixture, a privacy-reviewed mapping, tests, and a
dashboard contract. Documentation alone is not normalization support.

| Provider/product | Verified surface | Fixture | Native view | \`ai_agent.*\` | Cost estimate | Status |
|---|---|---|---|---|---|---|
| OpenAI Codex CLI 0.146.1 | app-server OTLP logs/metrics/traces; app-server 0.147.0-alpha.6.5 | \`fixtures/codex/0.146.1\` | Yes | Yes | Exact mapped models, public API base rates | Supported in 0.1.3 |
| OpenAI Codex lifecycle Hooks | `UserPromptSubmit`/`Stop` and local `PreToolUse`/`PostToolUse` | `examples/codex-hooks` privacy fixtures | Phoenix/Tempo trace only | Bounded lifecycle attributes; no usage metrics | No | Experimental, metadata-only |
| Google Antigravity | documented Hooks and CLI status-line extension | repository examples and privacy fixtures | Yes | Yes, observed gauges/lifecycle metadata | No; observations are not counters/billing | Supported, extension-observed |
| Anthropic Claude Code | upstream OpenTelemetry metrics/events and optional traces; repository documentation only | None | No | No | No | Upstream capable; repository integration required |
| GitHub Copilot | upstream organization/enterprise usage metrics API and dashboard; no workstation OTLP fixture here | None | No | No | No | Upstream capable; repository integration required |
| AI Context framework | framework-owned \`ai_context.*\` contract | schema/example only; no runtime emitter | Not a provider | Not applicable | Not applicable | Contract reserved; dashboards retired |

The Antigravity status-line values are observations, not a turn-token counter
or billing ledger, and are therefore not priced. Claude Code and Copilot have
upstream telemetry surfaces, but they must not be shown as normalized or priced
by this toolkit until a real, version-pinned privacy-safe fixture and defensible
usage contract are available.

Provider telemetry can establish usage, timing, tool activity, and trace events.
It cannot independently establish that a prompt-framework rule was loaded,
followed, or caused an outcome. That requires deterministic framework-owned
instrumentation or hooks; a prompt self-report is not independent evidence.

The Codex Hooks row is intentionally separate from native app-server support.
It produces partial OpenInference `AGENT`/`TOOL` traces for Phoenix, while
native Codex OTLP remains the source for provider-reported token and usage
metrics. Hosted tools may not be visible to Hooks.

Upstream capability references:

- [OpenAI Codex configuration reference (otel)](https://developers.openai.com/codex/config-reference/#otel)
- [OpenAI Codex Hooks](https://learn.chatgpt.com/codex/hooks)
- [Anthropic Claude Code monitoring and OpenTelemetry](https://code.claude.com/docs/en/monitoring-usage)
- [GitHub Copilot usage metrics](https://docs.github.com/en/copilot/concepts/copilot-usage-metrics/copilot-metrics)
