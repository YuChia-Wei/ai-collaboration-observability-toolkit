# Codex OpenTelemetry setup

1. Start `core` or `corporate` mode.
2. Merge one example `[otel]` table into the user-level Codex configuration. Do not overwrite unrelated model, sandbox, MCP, skill, or project settings.
3. Restart Codex and run a small task.
4. Inspect Collector health first, then the Codex usage and raw metric inventory in Grafana/Prometheus.

`log_user_prompt = false` disables explicit prompt logging at the client, but it is not the only privacy control. Collector processors remove known content-bearing and credential-bearing attributes before export. Corporate mode keeps only an exact metadata allowlist.

Vendor event and metric names can change with Codex versions. Do not rename an unobserved metric into the normalized `ai_context_*` contract merely to make a dashboard non-empty.
