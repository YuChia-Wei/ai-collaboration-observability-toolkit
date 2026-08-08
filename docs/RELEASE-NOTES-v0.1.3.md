# v0.1.3 — Observability Baseline Stabilization

## Highlights

- Real, versioned Codex 0.146.1 telemetry fixture and semantics.
- Additive provider-neutral ai_agent.* contract.
- Stronger pre-normalization privacy filtering in every mode.
- Separate native, AI-agent, and framework-evidence dashboards.
- Antigravity alignment with explicit observed/non-billing semantics.
- Compose-first operations and full Evaluation/Corporate runtime evidence.

## Upgrade

1. Preserve the current named volumes.
2. Pull or check out v0.1.3.
3. Review .env and run all merged/native config checks.
4. Start the intended mode with docker compose up -d.
5. Back up the Codex user config, merge only [otel], and set
   log_user_prompt=false.
6. Have the Owner restart Codex.
7. Run the relevant privacy and persistence smoke.

The existing Codex dashboard UID ai-codex-usage is retained; its title becomes
Codex Native Telemetry. The new AI Agent Usage UID is ai-agent-usage.

## Rollback

Check out v0.1.2 and run docker compose up -d without deleting volumes. Restore
the timestamped Codex config backup if necessary, then have the Owner restart
Codex. Do not use down -v. Rollback does not erase historical telemetry.

## Limitations

- Cost is unavailable and is not estimated.
- Claude Code and GitHub Copilot normalization are deferred to Issues #9/#10.
- Existing pre-0.1.3 local data may contain attributes admitted by the older
  policy; deletion requires a separate Owner decision.
