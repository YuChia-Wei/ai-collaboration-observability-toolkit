# Representative observed Prometheus series

Observed from the local Collector/Prometheus path on 2026-08-09:

- codex_turn_token_usage_bucket, _count, _sum
- codex_turn_e2e_duration_ms_bucket, _count, _sum
- codex_turn_ttft_duration_ms_bucket, _count, _sum
- codex_turn_ttfm_duration_ms_bucket, _count, _sum
- codex_tool_call
- codex_tool_call_duration_ms_bucket, _count, _sum
- codex_mcp_call
- codex_mcp_call_duration_ms_bucket, _count, _sum
- codex_mcp_error
- codex_responses_api_inference_time_duration_ms_bucket, _count, _sum
- codex_responses_api_overhead_duration_ms_bucket, _count, _sum
- codex_task_compact
- codex_skill_injected
- codex_thread_started

Observed bounded dimensions included model, token_type, status, source, outcome,
and success. The canonical copy removes raw model, tool, tool_name, and skill
dimensions after deriving bounded model_family, tool_category, operation, and
evidence_class values.

This inventory contains names only. No local series values or identifying label
values are committed.
