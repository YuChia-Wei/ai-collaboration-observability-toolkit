# Codex Hooks lifecycle trace experiment

This opt-in example converts Codex lifecycle Hooks into metadata-only OTLP traces and sends them to
the existing loopback OpenTelemetry Collector. Evaluation mode retains compatible spans in Tempo and
forwards them to Phoenix.

- `UserPromptSubmit` to `Stop` produces one OpenInference `AGENT` span.
- `PreToolUse` to `PostToolUse` produces a child `TOOL` span with a bounded tool category.
- No `LLM` span, token/cost value, prompt effectiveness, or correctness claim is synthesized.

The exporter never reads or stores prompt text, assistant messages, tool input/output, the working
directory, or transcript paths. Raw session, turn, and tool IDs are used only to hash local state
paths; exported trace/span IDs are random. Tool names are reduced to fixed categories.

Run `python examples/codex-hooks/install_hooks.py` to generate `.codex/hooks.json` with direct
absolute Python/exporter paths, then restart Codex and use `/hooks` to review and trust the exact
definition. The installer refuses to overwrite an existing hook file; merge it manually or inspect
`--print` output. Do not enable a duplicate user-level copy. Remove the generated file or disable it
in `/hooks` to roll back.

Exporter failures are fail-open and cannot change tool permissions. Hosted and specialized tool paths
may bypass tool hooks, so this is a useful lifecycle view rather than a complete accounting or
enforcement boundary. See [Codex Hooks](https://learn.chatgpt.com/codex/hooks) and the
[OpenInference semantic conventions](https://arize-ai.github.io/openinference/spec/semantic_conventions.html).
