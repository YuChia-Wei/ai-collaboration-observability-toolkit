# Provider support matrix

Support means a versioned fixture, a privacy-reviewed mapping, tests, and a
dashboard contract. Documentation alone is not normalization support.

| Provider/product | Verified surface | Fixture | Native view | \`ai_agent.*\` | Cost estimate | Status |
|---|---|---|---|---|---|---|
| OpenAI Codex CLI 0.146.1 | app-server OTLP logs/metrics/traces; app-server 0.147.0-alpha.6.5 | \`fixtures/codex/0.146.1\` plus role/accounting runtime fixture | Yes | Yes, role-aware v2 accounting | Exact mapped models: separate public API USD and Codex credits estimates | Supported baseline; v0.2 role/credits candidate |
| OpenAI Codex lifecycle Hooks | `UserPromptSubmit`/`Stop` and local `PreToolUse`/`PostToolUse` | `examples/codex-hooks` privacy fixtures | Phoenix/Tempo trace plus explicit size-only metrics | Bounded lifecycle attributes; opt-in user-prompt or exact-allowlisted MCP-response UTF-8 byte histogram | No | Experimental; metadata-only by default, each size source is explicit and personal/Core/Evaluation only |
| Google Antigravity | documented Hooks and CLI status-line extension | repository examples and privacy fixtures | Yes | Yes, observed gauges/lifecycle metadata | No; observations are not counters/billing | Supported, extension-observed |
| Anthropic Claude Code | native OpenTelemetry metrics from CLI/Desktop | `examples/otlp/claude-code-token-metrics.json` | Yes | Token usage by type, role, skill and redacted MCP attribution | No; `model_id=unmapped` | Supported metrics baseline; Core/Evaluation attribution only |
| GitHub Copilot | upstream organization/enterprise usage metrics API and dashboard; no workstation OTLP fixture here | None | No | No | No | Upstream capable; repository integration required |
| AI Context framework | reserved \`ai_context.*\` workflow-evidence contract | schema/example only; framework is not a runtime emitter | Not a provider | Not applicable | Not applicable | Contract reserved; dashboards retired |

The Antigravity status-line values are observations, not a turn-token counter
or billing ledger, and are therefore not priced. Claude Code and Copilot have
upstream telemetry surfaces, but they must not be shown as normalized or priced
by this toolkit until a real, version-pinned privacy-safe fixture and defensible
usage contract are available.

Codex `agent_role` and `model_id` are independent. The current
`codex-auto-review` source value proves `approval_reviewer`, but not the exact
model, so reviewer tokens remain `model_id=unmapped` and unpriced. Cached input
is discounted according to the matching public rate card, not free. The public
Codex credits table has no cache-write-specific rate; that class remains visible
as credits-unpriced.

Provider telemetry can establish usage, timing, tool activity, and trace events.
It cannot independently establish that a prompt-framework rule or governance
file was loaded, followed, or caused an outcome. `ai-collaboration-framework`
is a portable context/skills/workflow source and packaging harness, not an ADK
runtime, so this toolkit does not require it to emit telemetry. Exact load
identity requires an independently observable runtime or an explicit,
privacy-reviewed client hook; prompt self-report is not independent evidence.

The Codex Hooks row is intentionally separate from native app-server support.
It produces partial OpenInference `AGENT`/`TOOL` traces for Phoenix, while
native Codex OTLP remains the source for provider-reported token and usage
metrics. Hosted tools may not be visible to Hooks.

Upstream capability references:

- [OpenAI Codex configuration reference (otel)](https://developers.openai.com/codex/config-reference/#otel)
- [OpenAI Codex Hooks](https://learn.chatgpt.com/codex/hooks)
- [Anthropic Claude Code monitoring and OpenTelemetry](https://code.claude.com/docs/en/monitoring-usage)
- [GitHub Copilot usage metrics](https://docs.github.com/en/copilot/concepts/copilot-usage-metrics/copilot-metrics)
