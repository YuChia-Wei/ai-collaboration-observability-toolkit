# AI collaboration telemetry data contract

## Principles

1. Vendor-native attributes are preserved only when privacy and cardinality policies permit them.
2. Cross-tool analysis uses the `ai_context.*` namespace.
3. “Loaded” does not mean “used,” and elapsed time does not mean active model reasoning.
4. Cost figures always carry a source, unit, rate-card version when estimated, and attribution confidence.
5. Unsupported or unmeasured evidence is represented as unknown, not inferred as success.
6. Raw content is not part of the normalized event contract.

The contract is versioned independently of Collector implementation. New fields require a privacy
classification and expected cardinality before they are emitted. The content-free JSON envelope is
specified by `schemas/ai-context-telemetry.schema.json`; OTLP senders map the same semantics into
resource/span/log/metric attributes.

## Resource attributes

Resource attributes describe the sender, framework, and environment and should remain stable for a
process or workflow batch.

| Field | Type | Cardinality | Purpose |
| --- | --- | ---: | --- |
| `service.name` | string | low | Sender surface, e.g. `codex-cli` |
| `service.namespace` | string | low | Logical product/team grouping |
| `service.version` | string | low | Sender version |
| `deployment.environment.name` | string | low | `personal-local`, `corporate-local`, CI, etc. |
| `ai_context.environment.profile` | string | low | `core`, `evaluation`, `corporate-redacted` |
| `ai_context.framework.name` | string | low | Framework product name |
| `ai_context.framework.version` | string | low | Released framework version |
| `ai_context.framework.commit_hash` | string | high | Exact framework revision; personal traces only |
| `ai_context.workflow.id` | string | high | Durable local workflow/run identifier; traces only |
| `ai_context.workflow.type` | string | low | Release, implementation, review, audit, etc. |
| `ai_context.workflow.stage` | string | bounded | Workflow stage |
| `ai_context.task.type` | string | low | Task classification rather than ticket content |
| `ai_context.skill.id` | string | bounded | Canonical skill identifier |
| `ai_context.rule.id` | string | bounded | Stable governance-rule identifier |
| `ai_context.context.manifest_hash` | string | high | Hash of loaded-context manifest, not file content |
| `ai_context.tool.category` | string | low | Codex, Claude Code, Copilot, wrapper, etc. |
| `ai_context.model.family` | string | bounded | Normalized model family |
| `ai_context.user.pseudonym` | string | high | Optional HMAC-derived internal pseudonym |
| `ai_context.export.phoenix` | bool | low | Explicit evaluation-mode trace selection |

`ai_context.export.phoenix` should be a resource attribute so every span in a selected trace is routed
consistently. A span-local flag can produce partial traces and is not the recommended contract.

## Span and event attributes

| Field | Type | Purpose |
| --- | --- | --- |
| `ai_context.operation.type` | string | model, tool, validation, wait, Git, review, handoff, workflow |
| `ai_context.state` | string | active, wait, blocked, paused, sleep, resumed, completed |
| `ai_context.outcome` | string | success/passed, failed, blocked-by-environment, skipped, not-applicable, deferred, unknown |
| `ai_context.evidence.class` | string | repository-record, git-fact, provider-readback, conversation-observation, derived-interval, manual-annotation |
| `ai_context.validation.type` | string | preflight, build, test, package, hosted-readback, etc. |
| `ai_context.validation.tier` | string | targeted, quick, critical, full, etc. |
| `ai_context.validation.fingerprint` | string | Personal trace-only hash of inputs and validation definition |
| `ai_context.validation.fingerprint_hash` | string | Export-safe non-reversible fingerprint |
| `ai_context.validation.reused` | bool | Whether valid prior evidence was reused |
| `ai_context.validation.invalidation_reason` | string | Normalized reason evidence could not be reused |
| `ai_context.retry.count` | int | Bounded retry number |
| `ai_context.retry.reason` | string | Normalized reason, never raw output |
| `ai_context.wait.reason` | string | owner, approval, hosted-check, process, queue, sleep, unknown |
| `ai_context.token.type` | string | input, cached_input, output, reasoning, cache_write |
| `ai_context.token.count` | int | Vendor-reported count when available |
| `ai_context.cost.value` | double | Cost/credit figure |
| `ai_context.cost.unit` | string | credits, USD, internal_unit, unknown |
| `ai_context.cost.source` | string | official, vendor_reported, estimated, allocated, unknown |
| `ai_context.cost.rate_card.version` | string | Effective rate-card identifier for estimates |
| `ai_context.cost.attribution.confidence` | string | exact, bounded, proportional, manual, unattributed |

## Rule-effect states

A rule or document should not be labeled useful merely because it was present. Instrumentation records
the strongest proven state:

| State | Meaning |
| --- | --- |
| `declared` | Included by the workflow/profile |
| `loaded` | File or rule was loaded into tool context |
| `evaluated` | A workflow check considered the rule |
| `triggered` | Its condition was true |
| `affected_action` | It changed a decision or action |

Framework simplification should compare outcomes against these states and representative workloads
rather than deleting every rule with a low trigger count.

## Cost attribution

Official credits and local evidence often lack a shared task ID. Allocation records must use:

```text
attribution.confidence = exact | bounded | proportional | manual | unattributed
```

- `exact`: a durable provider/run ID provides a direct join.
- `bounded`: one eligible local task exists in the official usage window.
- `proportional`: usage is allocated by a documented local token/activity proportion.
- `manual`: a user explicitly assigns a usage record.
- `unattributed`: no defensible allocation exists.

Never silently convert `unattributed` usage to a precise-looking task cost.

## Metric label allowlist

Metrics may use only bounded dimensions such as:

```text
tool, model_family, operation, outcome, token_type, task_type,
workflow_type, stage, validation_type, validation_tier, reused,
wait_reason, environment_profile, cost_unit, cost_source
```

They must not use workflow/session/prompt/request/trace/span/tool-call IDs, raw validation
fingerprints, commit hashes, branches, paths, ticket text, emails, or user pseudonyms.

## Initial normalized metric names

The synthetic fixtures and provisioned dashboards use these names as a stable toolkit contract:

```text
ai_context_token_usage_total
ai_context_cost_value_total
ai_context_tool_calls_total
ai_context_validation_runs_total
ai_context_validation_duplicate_total
ai_context_retry_total
ai_context_task_outcome_total
ai_context_manual_correction_total
ai_context_loaded_bytes_total
ai_context_estimated_context_tokens_total
ai_context_rule_state_total
```

Future workflow hooks may add histograms such as:

```text
ai_context_workflow_duration_seconds
ai_context_wait_duration_seconds
```

Vendor-native metrics are not silently renamed merely to populate a dashboard. A normalization layer
must be based on observed sender schemas and covered by fixtures/tests.
