# AI Collaboration Observability Toolkit

一套隱私優先、以 OpenTelemetry Collector 為唯一 host telemetry
入口的本機 AI 協作可觀測性工具。Grafana、Loki、Tempo 與 Prometheus
提供執行與用量證據；Phoenix 在 Evaluation 模式只接收已去識別且具
OpenInference span kind 的 traces，並支援 header 明確退出。

[English](README.en.md)

## 三層證據

- Provider native：經隱私過濾後保留 codex.* 與 antigravity_*，供原生診斷。
- AI-agent canonical：Collector 建立 ai_agent.* 副本，供跨 AI coding agent 的 bounded usage 分析。
- AI Context：ai_context.* 保留給 framework、skill、rule、validation、wait、retry 與 outcome 的顯式 emitter；目前只有 schema／fixture，沒有 production emitter 或 dashboard。

三者不互相代替。Dashboard 不用 fallback 把 provider 訊號冒充 framework
證據。只有 provider-reported token、exact model 與版本化 rate card 都存在
時才顯示公開 API 基礎牌價估算；extension-observed gauges 不會被冒充成
counter 或帳務。

## 架構與模式

    AI tools / applications / AI Context hooks
                       | OTLP gRPC or HTTP
                       v
              OpenTelemetry Collector
              |-- metrics --> Prometheus --+
              |-- logs ----> Loki ---------+--> Grafana
              +-- traces --> Tempo --------+
                           +--> redacted OpenInference spans (default-on) --> Phoenix

| 模式 | 用途 | Phoenix | 資料政策 |
| --- | --- | --- | --- |
| core | 個人本機 LGTM 基線 | 無 | 初始 denylist 加最終 privacy filter |
| evaluation | trace 評註、資料集與實驗 | 有 | 已去識別且含 `openinference.span.kind` 的 span 預設轉送；一般 spans 留在 Tempo，`x-ai-observability-phoenix: false` 可退出 |
| corporate | 公司電腦 metadata-only 基線 | 無 | exact keep_keys allowlist，未知欄位一律丟棄 |

Evaluation 與 Corporate 不可同時啟用。所有 host ports 預設綁定
127.0.0.1；Tempo 與 Phoenix 的 OTLP receivers 不發布到 host。

## Compose-first 快速開始

先建立 .env 並修改範例密碼：

    Copy-Item .env.example .env
    docker compose -f compose.yaml up -d
    docker compose -f compose.yaml ps

Evaluation 完整模式：

    docker compose -f compose.yaml -f compose.evaluation.yaml up -d

Corporate 模式：

    docker compose -f compose.yaml -f compose.corporate.yaml up -d

停止不刪除 named volumes：

    docker compose -f compose.yaml down

不要使用 down -v。資料清除只應在精確確認 Compose project 與 Owner
明示授權後執行。

Python 不是啟動 containers 的必要條件；它是選用的 policy validator、
smoke orchestrator 與報告工具：

    python -m pip install -r requirements.txt
    python scripts/toolkit.py validate --mode all
    python scripts/toolkit.py smoke --mode evaluation --persistence-check

跨平台 thin wrappers 位於 scripts/。

## 本機介面

- Grafana: http://127.0.0.1:3000
- Prometheus: http://127.0.0.1:9090
- Loki: http://127.0.0.1:3100
- Tempo: http://127.0.0.1:3200
- Phoenix（Evaluation）: http://127.0.0.1:6006
- OTLP gRPC / HTTP: 127.0.0.1:4317 / 127.0.0.1:4318

## 已驗證的 provider surfaces

- Codex CLI 0.146.1 / app-server 0.147.0-alpha.6.5：versioned fixture、
  native dashboard、ai_agent.* normalization，以及 exact mapped model 的
  版本化公開 API 牌價估算。
- Codex lifecycle Hooks：[`examples/codex-hooks`](examples/codex-hooks/README.md)
  提供 opt-in、metadata-only 的 `AGENT`／`TOOL` Phoenix trace 實驗；不產生
  LLM/token/cost 或 prompt effectiveness 資料。
- Google Antigravity：direct Hooks 與 CLI status-line extension；usage 為
  observed metadata，非帳務。
- Claude Code 上游可輸出 OpenTelemetry，GitHub Copilot 上游提供組織／企業 usage metrics；本 repository 目前都只有文件，沒有 versioned fixture，因此不宣稱 normalized support。

詳見 [Provider support matrix](docs/PROVIDER-SUPPORT.md)、
[Codex integration](docs/CODEX-INTEGRATION.md) 與
[Antigravity integration](docs/ANTIGRAVITY-INTEGRATION.md)。

Codex 設定只合併 examples/codex/config.toml.example 的 [otel] 區段，
保留既有 model、sandbox、MCP、skills 與 project 設定；三個 endpoint
必須指向 loopback Collector，且 log_user_prompt=false。變更後由 Owner
重新啟動 Codex。

## Dashboard

- Collector 健康狀態（Collector Health）
- Codex 原生 Telemetry（Codex Native Telemetry）
- AI Agent 用量（AI Agent Usage）
- AI Agent 活動（Metadata 與 Trace）
- Antigravity 用量（觀測值，非帳務）

Codex Native 保留既有 UID ai-codex-usage，並只對同一批 Codex telemetry
使用三個明確的 canonical accounting/rate/cost recording metrics。AI Agent
Usage 僅查詢 ai_agent_*；Activity 從 Loki 查 metadata-only events，並以
trace_id 關聯 Tempo；Antigravity dashboard 維持 provider-native observed
gauges。因目前沒有真實 AI Context emitter，原先兩張 ai_context_* dashboards
已移除，避免把設計中的 contract 呈現成已可觀測能力。

## 閱讀 Phoenix

Phoenix 的 waterfall、span status 與 attributes 可以協助找出慢操作、重複處理、
工具錯誤與長等待，但前提是 sender 產生 OpenInference-compatible spans。一般
Codex internal spans 缺少 LLM kind/model/token/input/output 語意，只保留在 Tempo；
這也是 Phoenix 預設 cost/token/LLM panels 無資料的預期原因。privacy-safe traces
不含 prompt/response 內容，也不能單獨證明答案正確。請依 [Phoenix Trace 閱讀指南](docs/PHOENIX-READING-GUIDE.zh-TW.md)
逐步判讀，並以 [Telemetry 詞彙表](docs/TELEMETRY-GLOSSARY.zh-TW.md) 對照 canonical
英文 identifier。

可先唯讀檢查，再把中文 annotation rubric 套用到一個既有 Phoenix Project：

    python scripts/toolkit.py phoenix-annotations --project "<project-name>"
    python scripts/toolkit.py phoenix-annotations --project "<project-name>" --apply

Synthetic smoke traces 固定使用 `ai-collaboration-observability-fixture` Project
與可辨識的 trace IDs；不需要刪除歷史資料來區分真實 traces。

## 驗證

三個層級都必須明確報告：

1. Static：repository policy、JSON/YAML/TOML、unit tests。
2. Native config：Compose merge 與各 backend/Collector 原生 validator。
3. Runtime：Evaluation 全服務、Corporate 隔離測試、privacy 新時間窗、
   native/canonical reconciliation 與 named-volume persistence。

    python scripts/toolkit.py validate --mode all --static-only
    python -m unittest discover -s tests -v

若某個 validator 或 runtime 不可用，狀態必須是 not-executed，不可寫成 passed。

## 文件

- [Architecture](docs/ARCHITECTURE.md)
- [Data contract](docs/DATA-CONTRACT.md)
- [Privacy](docs/PRIVACY.md)
- [Operations](docs/OPERATIONS.md)
- [Phoenix Trace 閱讀指南（zh-TW）](docs/PHOENIX-READING-GUIDE.zh-TW.md)
- [Telemetry 詞彙表（zh-TW）](docs/TELEMETRY-GLOSSARY.zh-TW.md)
- [Provider support matrix](docs/PROVIDER-SUPPORT.md)
- [Dependencies](docs/DEPENDENCIES.md)
- [Validation report](docs/VALIDATION-REPORT.md)
- [Roadmap](docs/ROADMAP.md)

## 安全邊界

這是本機研究與團隊試行基線，不是可直接暴露到網路的多租戶平台。
0.1.3 policy 僅保證新 ingestion window；升級前已存在於 named volumes
的歷史資料不會被靜默刪除。任何不可逆清除都需要 Owner 明示決策。
