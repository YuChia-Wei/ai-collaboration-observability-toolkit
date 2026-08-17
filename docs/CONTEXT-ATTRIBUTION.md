# Context attribution design

## Architecture boundary

The canonical framework is
[`YuChia-Wei/ai-collaboration-framework`](https://github.com/YuChia-Wei/ai-collaboration-framework).
It is a portable source and governed packaging harness for prompts, context,
skills, and workflows. It does not own Claude/Codex model-call execution, so
this design does not add a framework prompt, runtime emitter, or per-unit load
decision schema.

Observation stays at the runtime boundary:

1. Claude Code emits provider-native request token metrics.
2. Codex native telemetry emits token/tool/MCP/compaction activity where
   available.
3. Codex lifecycle Hooks may emit a content-free byte proxy only when the user
   explicitly selects `size-only`, selects a scope, and exact-allowlists the MCP
   Hook tool name under a safe logical ID.
4. The Collector removes content and identity, normalizes bounded dimensions,
   and Grafana presents evidence without causal claims.

## Question coverage

| Question | Evidence now available | Answerability |
|---|---|---|
| How many tokens did moving a skill out save? | Claude request tokens by `skill_id`, token type, role, and model family | Estimate with a controlled before/after experiment; not a single-run causal fact |
| Did Codebase Memory MCP reduce context loading? | Claude tokens on requests consuming an MCP result; Codex exact-allowlisted MCP response bytes; Codex compaction | Compare matched task cohorts; still a proxy for context pressure, not exact loaded context |
| Is a governance document loaded unnecessarily every time? | No provider-native metric carries a stable document identity | Not answerable with the current standard CLI/Desktop surfaces |

## Experiment contract

For skill or MCP comparisons, keep the task corpus, model, client version,
framework revision, tool configuration, and sample size fixed. Alternate
baseline and treatment runs rather than comparing unrelated work. Compare at
least:

- input, cached-input, cache-write-input, and output token deltas;
- primary versus subagent requests;
- MCP-attributed request tokens or allowlisted response bytes;
- compaction count and task outcome outside this telemetry system.

The dashboard intentionally does not calculate a universal bytes-to-token
ratio. Provider-side system instructions, history, cache state, tool schemas,
and serialization make such a ratio unstable.

## Remaining governance-file gap

Answering the file question requires an execution boundary that sees a real
load operation. Two defensible future options are:

- a runtime/orchestrator such as Orca that owns the terminal/tool execution and
  can emit a safe logical document ID at load time; or
- a client-specific opt-in Hook that exact-matches a configured file path and
  emits only a safe logical document ID plus byte count.

The second option must remain explicit per client and per document. It cannot
be made portable by adding instructions to the framework prompt, and it cannot
cover ChatGPT Desktop or any client surface that exposes no suitable hook.
