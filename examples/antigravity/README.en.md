# Google Antigravity observability example

This example converts documented Google Antigravity **Hooks** and the **Antigravity CLI custom status
line** into metadata-only OTLP/HTTP sent to the toolkit's local OpenTelemetry Collector.

It does not assume Antigravity exposes a user-configurable native OTLP endpoint. Product `Enable
Telemetry` is not equivalent to exporting to `127.0.0.1:4318`.

## Data surfaces

| Source | Signal | Safe evidence |
| --- | --- | --- |
| `PreInvocation` / `PostInvocation` | logs, traces | invocation, model, duration, completion |
| `PostToolUse` | logs | bounded tool category, step index, success/failure |
| `Stop` | logs, traces | execution duration, termination and idle state |
| CLI status line | logs, metrics | tokens, context, quota, tasks, artifacts, pending input/approval |

Status-line token and quota values are observations, not official billing or credits.

The exporter does not read prompts, responses, transcripts, artifacts, code, workspace paths, branches,
email, `toolCall`, tool arguments/results, raw errors, or raw conversation IDs. Personal mode may emit a
local HMAC session pseudonym; corporate examples disable it and the Corporate Collector profile applies
another allowlist.

`PreToolUse` is intentionally absent so passive telemetry cannot participate in permission decisions.
The repository ships one direct-Hooks route only; do not add a second plugin running the same exporter.

## Start the Collector

```bash
cp .env.example .env
# Replace example passwords
docker compose up -d
```

The exporter defaults to `http://127.0.0.1:4318` and appends the OTLP signal path.

## Project Hooks on POSIX/WSL

```bash
mkdir -p .agents/observability
cp /path/to/toolkit/examples/antigravity/antigravity_otel_exporter.py \
  .agents/observability/
cp /path/to/toolkit/examples/antigravity/config/hooks.personal.posix.json.example \
  .agents/hooks.json
chmod +x .agents/observability/antigravity_otel_exporter.py
```

Use `hooks.corporate.posix.json.example` for corporate mode.

## Project Hooks on Windows

```powershell
New-Item -ItemType Directory -Force .agents\observability | Out-Null
Copy-Item C:\path\to\toolkit\examples\antigravity\antigravity_otel_exporter.py `
  .agents\observability\
Copy-Item C:\path\to\toolkit\examples\antigravity\config\hooks.personal.windows.json.example `
  .agents\hooks.json
```

Use `hooks.corporate.windows.json.example` for corporate mode. Change `python` to `py -3` or an
absolute interpreter path when required.

User Hooks may be placed in `~/.gemini/config/hooks.json`; use an absolute exporter path and do not
activate the same Hooks at project and user scope.

## CLI status line

Merge the matching `settings.statusline.*.json.fragment.example` into:

```text
~/.gemini/antigravity-cli/settings.json
```

Replace the placeholder exporter path and restart Antigravity CLI. The status line can run with direct
lifecycle Hooks because it covers a different data surface.

## Privacy test

```bash
python3 examples/antigravity/antigravity_otel_exporter.py statusline \
  --profile personal-local \
  --product antigravity \
  --dry-run \
  --capture-dir artifacts/antigravity-example \
  --state-dir artifacts/antigravity-state \
  < examples/antigravity/fixtures/statusline.json

python3 -m unittest tests.test_antigravity_example -v
```

See [`../../docs/ANTIGRAVITY-INTEGRATION.md`](../../docs/ANTIGRAVITY-INTEGRATION.md) for field policy,
Phoenix opt-in, environment variables, and limitations.
