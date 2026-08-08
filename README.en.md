# AI Collaboration Observability Toolkit

A privacy-first local observability toolkit for AI-assisted software development. The
OpenTelemetry Collector is the only host-facing telemetry ingress. Grafana, Loki, Tempo, and
Prometheus provide the execution/usage evidence layer; an optional Phoenix profile receives only
explicitly selected and minimized traces for evaluation.

The toolkit is intended to answer where tokens, time, retries, validation, and context cost are
spent—without treating raw conversation or source content as the primary data product.

## Modes

| Mode | Purpose | Data policy |
| --- | --- | --- |
| `core` | Personal LGTM baseline | Known content fields removed, constant log body, bounded metric labels |
| `evaluation` | Phoenix annotations/datasets/experiments | Core policy plus explicit `ai_context.export.phoenix=true` routing |
| `corporate` | Company workstation metadata baseline | Strict `keep_keys` allowlist; unknown fields are dropped; no Phoenix |

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Change the sample local passwords.
./scripts/up.sh core
./scripts/smoke-test.sh core
```

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\scripts\up.ps1 -Mode core
.\scripts\smoke-test.ps1 core
```

All published ports are loopback-bound. AI tools send OTLP only to the Collector on ports 4317/4318;
backend OTLP receivers are not published to the host.


## Google Antigravity

The committed Antigravity example uses JSON Hooks rather than assuming a native OTLP exporter. Copy
`examples/antigravity/plugin` into `.agents/plugins/ai-collaboration-observability` or the global
`~/.gemini/config/plugins/` directory. It exports metadata-only model/session traces and bounded tool
outcome logs without reading transcripts, prompts, tool payloads, workspace paths, raw errors, or raw
conversation IDs. See [the integration guide](docs/ANTIGRAVITY-INTEGRATION.md).

## Validation

```bash
python scripts/toolkit.py validate --mode all --static-only
python -m unittest discover -s tests -v
```

With Docker available, run `python scripts/toolkit.py validate --mode all` and the relevant runtime
smoke mode.

Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/PRIVACY.md`, and
`docs/DATA-CONTRACT.md` before changing telemetry policy.

## Reports

- [Implementation report](docs/IMPLEMENTATION-REPORT.md)
- [Validation report](docs/VALIDATION-REPORT.md)
