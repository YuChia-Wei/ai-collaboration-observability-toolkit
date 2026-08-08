# Google Antigravity observability example

This example uses Antigravity JSON Hooks to export metadata-only OTLP/HTTP logs and traces to the toolkit Collector. It does not read transcripts, prompts, model responses, tool arguments/results, workspace paths, raw errors, or raw conversation IDs.

Install as a workspace plugin:

```bash
mkdir -p .agents/plugins
cp -R examples/antigravity/plugin \
  .agents/plugins/ai-collaboration-observability
```

Or install globally under `~/.gemini/config/plugins/ai-collaboration-observability`.

Start `core` or `corporate` mode, restart Antigravity, and run a small task. The bridge defaults to `http://127.0.0.1:4318` and can be changed with `AI_OBSERVABILITY_OTLP_HTTP_ENDPOINT`.

The safe default deliberately avoids `PreToolUse`, because that hook must return a permission decision and a passive observer must not silently allow, deny, or add approval prompts. `PostToolUse` matchers record only bounded tool categories. Model invocation and session durations are emitted as traces.

Antigravity hook payloads do not currently expose token or credit usage. This example therefore complements rather than replaces `/credits` or official usage data.

See [the detailed integration guide](../../docs/ANTIGRAVITY-INTEGRATION.md) and the [Traditional Chinese guide](README.md).
