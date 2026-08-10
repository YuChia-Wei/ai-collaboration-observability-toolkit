# `ai-collaboration-observability-toolkit` 建置工作規格

> 文件狀態：Implementation-ready
> 文件版本：0.1.0
> 建立日期：2026-08-07
> 目標 Repository：`YuChia-Wei/ai-collaboration-observability-toolkit`
> 主要執行工具：Google Antigravity
> 建議主執行模型：Gemini 3.6 Flash（High）
> 文件語言：臺灣繁體中文；程式識別字、設定鍵與官方產品名稱維持英文
> 本文件的規範性關鍵字 `MUST`、`MUST NOT`、`SHOULD`、`MAY` 分別表示必須、禁止、建議與選用。

---

## 0. 給實作 Agent 的執行指令

本文件是本次建置的**權威工作規格（authoritative implementation specification）**。請先完整閱讀，再檢查目前 Repository 狀態，接著直接規劃、實作、驗證並留下可重現的證據。

### 0.1 執行原則

1. 不要在尚未閱讀完整文件前開始建立 Docker Compose 或複製網路範例。
2. 不要再詢問已由本文件決定的架構選項；若遇到官方文件或目前版本造成的衝突，採用最新官方文件，並在 `docs/IMPLEMENTATION-REPORT.md` 記錄差異與理由。
3. 所有 Docker image MUST 使用明確版本，禁止 `latest`、`main`、僅 major 版本或其他浮動標籤。
4. 不要將密碼、Token、API key、內部路徑或實際使用者識別資料提交到 Git。
5. 不要建立或推送遠端 Repository、branch、tag、Release 或 Pull Request，除非 Owner 另外明確指示。
6. 不要擴張到本文件列為 Out of Scope 的功能。
7. 每一個宣稱完成的功能都必須有對應的機械式驗證或清楚標示為人工驗證。
8. 所有 YAML、TOML、JSON、Markdown 與 shell script MUST 使用 UTF-8，避免 BOM；shell script MUST 使用 LF。
9. README 與操作文件使用臺灣繁體中文；避免中國用語。初次出現專有名詞時附英文。
10. 若 Repository 已經套用可攜式 AI Collaboration Context，必須遵循其既有 `AGENTS.md`、skills 與治理流程；若尚未套用，不要從來源 Repository 任意複製整套 `.ai` 或 `.dev`。

### 0.2 開始實作前必須產生的規劃

在修改檔案前，先產生一份可追蹤的實作計畫，至少包含：

- 現有 Repository 狀態與缺少項目。
- 所有選定 image 版本、官方來源及相容性判斷。
- 預計新增／修改檔案清單。
- 實作階段與各階段驗證方式。
- 已知風險：Windows／WSL2、Docker Compose、OTLP、Loki OTLP、Phoenix、資料去機敏。
- 任何偏離本規格的必要理由。

計畫核對完成後直接執行，不需要等待 Owner 逐項確認；只有遇到無法安全推定的權限、法律授權或外部憑證問題才停止。

---

# 1. 專案背景

## 1.1 上游管理專案

`ai-collaboration-prompts-dotnet-backend` 是一套可攜式 AI 協作框架來源庫，管理：

- Agent-facing context。
- skills 與 sub-agent prompts。
- 軟體開發 workflow。
- 規範、驗證方式與治理證據。
- .NET backend 專門能力。
- 下游專案的套用與升級流程。

參考：

- <https://github.com/YuChia-Wei/ai-collaboration-prompts-dotnet-backend>
- <https://github.com/YuChia-Wei/ai-collaboration-prompts-dotnet-backend/blob/main/README.md>

本 Toolkit 是一個**獨立支援專案**，不得成為上游可攜式 payload 的隱性依賴，也不得將上游來源庫的 repo-only governance 直接打包到下游專案。

## 1.2 主要問題證據

上游專案的 `ASM-20260803-003` 已指出：

- 發布工作流結果具有良好治理與證據，但執行路徑缺少成本治理與可觀測性。
- 一次工作流總 wall time 為 `10:47:46`，其中 `5:42:29` 無法區分 active work、等待、工具排隊、核准或電腦休眠。
- 三次廣泛本機驗證合計 `1,495.5` 秒，其中一次因 WSL runtime 選錯而在 573.5 秒後才失敗。
- 沒有 input、cached input、reasoning、output token 的完整歸因。
- 沒有 validation fingerprint、reuse、invalidation reason。
- 沒有 sub-agent 的時間、Token、重疊與停止預算。
- 沒有 sleep／resume 與 no-output heartbeat 證據。

參考：

- <https://github.com/YuChia-Wei/ai-collaboration-prompts-dotnet-backend/blob/main/.dev/assessments/ASM-20260803-003/report.md>

本 Toolkit 的目的不是單純顯示漂亮圖表，而是讓這些問題能被**持續量測、標記、比較、回歸驗證與改善**。

## 1.3 第一個下游實驗專案

第一個可用於觀察下游採用狀況的專案：

- <https://github.com/YuChia-Wei/dotnet-distributed-architecture-lab>

它是實驗性專案，資料只能視為早期樣本，不應直接外推為所有團隊或正式產品的行為。

## 1.4 公司情境

公司環境可能：

- 使用 ChatGPT Enterprise credit 配額。
- 電腦資源有限。
- 禁止原始 prompt、回應、程式碼、路徑或內部 Repository 資料外流。
- 部分電腦無法使用 Docker。
- 只能在本機收集後產生去機敏、彙總的 feedback bundle。

因此本次 Docker Compose 是**個人與允許使用 Docker 的公司電腦 POC**。無 Docker 的 agent／bundle 模式列入後續 Roadmap，不在本次實作。

---

# 2. 專案目標

## 2.1 主要目標

建立一套本機優先（local-first）、OpenTelemetry 原生（OpenTelemetry-native）的觀測 Toolkit，能：

1. 接收 Codex CLI 與後續其他 AI 工具的 OTLP logs、metrics、traces。
2. 使用 Grafana 生態系分析：
   - Token 用量與類型。
   - 模型、turn、tool、MCP、skill 與 sub-agent 活動。
   - latency、TTFT、重試、錯誤、compaction。
   - 重複驗證、等待、環境阻塞、工作流階段。
3. 使用 Phoenix 分析經過挑選的 AI workflow traces，為後續：
   - 人工評註。
   - evaluator。
   - dataset。
   - framework 版本 experiment。
   提供基礎。
4. 建立可重複的隱私與去機敏測試。
5. 提供 Windows PowerShell 與 Bash 操作腳本。
6. 能作為未來公司個人使用量與團隊 showback 的基礎，但不冒充官方 credit 帳務系統。

## 2.2 成功標準

完成後，一位新使用者應能：

1. Clone Repository。
2. 複製 `.env.example`。
3. 執行一個啟動腳本。
4. 修改 `~/.codex/config.toml` 的 `[otel]`。
5. 執行一次短 Codex 工作階段。
6. 在 Grafana 看見 logs、metrics、traces。
7. 啟動 evaluation mode 後，將明確標記的 trace 送入 Phoenix。
8. 執行 smoke test，獲得可判讀的 pass／fail 報告。
9. 不需要手動進入容器修改設定。

---

# 3. 固定架構決策

## 3.1 採用元件

### 核心模式（Core mode）

- OpenTelemetry Collector Contrib
- Prometheus
- Loki
- Tempo
- Grafana

### 評估模式（Evaluation mode）

在 Core mode 上增加：

- Phoenix
- PostgreSQL（僅供 Phoenix；未來 usage ledger 必須使用獨立 database／schema）

## 3.2 暫不採用

MVP MUST NOT 加入：

- ClickHouse
- SigNoz
- OpenObserve
- Elasticsearch／Logstash／Kibana
- Jaeger 作為額外 trace backend
- 自訂 Web UI
- Kafka／RabbitMQ
- Kubernetes manifests
- Grafana Cloud、Phoenix Cloud 或其他 SaaS export

## 3.3 元件責任

| 元件 | 責任 | 非責任 |
|---|---|---|
| OpenTelemetry Collector | 唯一 OTLP 入口、正規化、去機敏、分流、批次、重試 | 不做長期查詢與人工作業 UI |
| Prometheus | 低基數 metrics 與趨勢 | 不保存 session／prompt 級高基數事件 |
| Loki | 結構化 logs／events | 不把高基數欄位全部做成 labels |
| Tempo | 原始執行 traces 的主要來源 | 不負責 evaluator／dataset |
| Grafana | 日常 dashboard、查詢、關聯與成本趨勢 | 不取代正式帳務或 AI experiment 系統 |
| Phoenix | 經篩選 AI traces、評註與未來 experiments | 不接收所有原始 logs／metrics，不取代 LGTM |
| PostgreSQL | Phoenix persistence | MVP 不建立未使用的 usage ledger |

## 3.4 核心原則

```text
AI tools / applications
          │
          │ OTLP gRPC or HTTP
          ▼
OpenTelemetry Collector
          │
          ├── metrics ───────────────▶ Prometheus ─┐
          ├── logs ──────────────────▶ Loki ───────┼──▶ Grafana
          ├── all traces ────────────▶ Tempo ──────┘
          └── curated traces only ───▶ Phoenix ────▶ Phoenix UI
```

- Collector 是唯一 host-facing OTLP endpoint。
- AI 工具不直接認識 Tempo、Loki、Prometheus 或 Phoenix。
- Tempo 保存接近來源的完整 trace 證據。
- Phoenix 只接收明確選取、已正規化、已去機敏的 traces。
- 後端替換不得要求每個 AI 工具改設定。

---

# 4. 執行環境與相容性

## 4.1 必須支援

- Docker Engine + Docker Compose v2（Linux）。
- Windows 11 + Docker Desktop。
- Windows 11 + WSL2 內的 Docker Engine，只要 Docker Compose v2 可用。
- PowerShell 7。
- Bash。

## 4.2 Docker 規則

1. 使用現代 Compose Specification，禁止頂層 `version:`。
2. 不要使用固定 `container_name`，避免多個 worktree／project 發生名稱衝突。
3. 使用 `COMPOSE_PROJECT_NAME` 控制 project 名稱。
4. 所有 host-facing ports 預設只綁定 `127.0.0.1`。
5. 所有資料使用 named volumes，不把高 IO 資料直接寫入 Windows bind mount。
6. 設定檔以 read-only bind mount 掛入容器。
7. 容器內互連使用 Compose service name，不使用 `localhost`。
8. 不依賴 `host.docker.internal` 作為核心路由。
9. 加入合理的 restart policy 與 health check；若官方 image 沒有可靠內建 health command，必須由外部 smoke test 補足並在文件說明。
10. 不為了通過健康檢查安裝未固定版本的套件。

## 4.3 可設定 host ports

`.env.example` 至少提供：

```dotenv
COMPOSE_PROJECT_NAME=ai-collaboration-observability

OTLP_GRPC_PORT=4317
OTLP_HTTP_PORT=4318
GRAFANA_PORT=3000
PROMETHEUS_PORT=9090
LOKI_PORT=3100
TEMPO_PORT=3200
PHOENIX_PORT=6006

GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=change-me-local-only
POSTGRES_USER=phoenix
POSTGRES_PASSWORD=change-me-local-only
POSTGRES_DB=phoenix
```

啟動腳本 SHOULD 在偵測到預設密碼時提出清楚警告；不得將實際密碼寫回 tracked file。

---

# 5. Compose 模式設計

## 5.1 核心模式

```bash
docker compose up -d
```

啟動：

- `otel-collector`
- `prometheus`
- `loki`
- `tempo`
- `grafana`

## 5.2 評估模式

不要只靠 Compose profile 切換 Phoenix exporter，因為 Collector pipeline 仍可能持續嘗試連線到未啟動的 Phoenix。

採用 Compose override 與獨立 Collector 設定：

```bash
docker compose \
  -f compose.yaml \
  -f compose.evaluation.yaml \
  up -d
```

PowerShell 使用等效參數。

Evaluation mode 增加：

- `postgres`
- `phoenix`

並將 Collector 設定改為 evaluation 版本，新增 curated trace pipeline。

## 5.3 公司去機敏模式

```bash
docker compose \
  -f compose.yaml \
  -f compose.corporate.yaml \
  up -d
```

Corporate mode：

- 使用嚴格 metadata-only Collector 設定。
- 不啟動 Phoenix。
- 不允許與 `compose.evaluation.yaml` 同時使用。
- 啟動腳本 MUST 阻止不支援的 mode 組合。
- 不自動輸出到任何公司外部 endpoint。

---

# 6. 建議 Repository 結構

實作 Agent 可以做小幅調整，但責任邊界不得改變。

```text
ai-collaboration-observability-toolkit/
├─ README.md
├─ AGENTS.md
├─ .editorconfig
├─ .gitattributes
├─ .gitignore
├─ .env.example
├─ compose.yaml
├─ compose.evaluation.yaml
├─ compose.corporate.yaml
│
├─ config/
│  ├─ otel-collector/
│  │  ├─ core.yaml
│  │  ├─ evaluation.yaml
│  │  └─ corporate.yaml
│  ├─ prometheus/
│  │  └─ prometheus.yml
│  ├─ loki/
│  │  └─ loki.yml
│  ├─ tempo/
│  │  └─ tempo.yml
│  └─ grafana/
│     ├─ provisioning/
│     │  ├─ datasources/
│     │  │  └─ datasources.yml
│     │  └─ dashboards/
│     │     └─ dashboards.yml
│     └─ dashboards/
│        ├─ collector-health.json
│        ├─ codex-usage.json
│        ├─ ai-agent-usage.json
│        ├─ ai-agent-activity.json
│        └─ antigravity-usage.json
│
├─ examples/
│  ├─ codex/
│  │  ├─ config.toml.example
│  │  └─ README.md
│  └─ otlp/
│     ├─ logs.json
│     ├─ metrics.json
│     ├─ traces.json
│     ├─ phoenix-selected-trace.json
│     └─ phoenix-rejected-trace.json
│
├─ scripts/
│  ├─ up.ps1
│  ├─ up.sh
│  ├─ down.ps1
│  ├─ down.sh
│  ├─ status.ps1
│  ├─ status.sh
│  ├─ validate-config.ps1
│  ├─ validate-config.sh
│  ├─ smoke-test.ps1
│  ├─ smoke-test.sh
│  ├─ resource-snapshot.ps1
│  ├─ resource-snapshot.sh
│  ├─ reset-data.ps1
│  └─ reset-data.sh
│
├─ docs/
│  ├─ ARCHITECTURE.md
│  ├─ DATA-CONTRACT.md
│  ├─ PRIVACY.md
│  ├─ OPERATIONS.md
│  ├─ TROUBLESHOOTING.md
│  ├─ CODEX-INTEGRATION.md
│  ├─ PHOENIX-INTEGRATION.md
│  ├─ COST-ATTRIBUTION.md
│  ├─ RESOURCE-BASELINE.md
│  ├─ DEPENDENCIES.md
│  ├─ ROADMAP.md
│  └─ IMPLEMENTATION-REPORT.md
│
└─ .github/
   └─ workflows/
      ├─ validate.yml
      └─ evaluation-smoke.yml
```

### 6.1 不應建立的內容

- 不要複製上游完整 `.dev` 歷史。
- 不要放入真實 telemetry data。
- 不要提交 `.env`。
- 不要提交 Grafana、Loki、Tempo、Prometheus、PostgreSQL data directories。
- 不要提交 Phoenix database。
- 不要建立未被使用的 application service 或 API。
- 不要用自製 Docker image 包裝所有官方元件，除非官方 image 無法達成必要設定且有明確證據。

---

# 7. OpenTelemetry Collector 規格

## 7.1 Receiver

對外提供：

- OTLP/gRPC：container `4317`
- OTLP/HTTP：container `4318`

Host 預設：

- `127.0.0.1:${OTLP_GRPC_PORT}:4317`
- `127.0.0.1:${OTLP_HTTP_PORT}:4318`

## 7.2 必要 processors

每個 pipeline 根據訊號需求組合，但至少包含：

1. `memory_limiter`
2. 資源／屬性正規化 processor
3. 隱私去除／轉換 processor
4. `batch`

Evaluation trace pipeline 額外包含：

5. request-metadata routing：缺少 `x-ai-observability-phoenix` 或值為 `true` 時轉送，值為 `false` 時退出。
6. legacy resource routing：`ai_context.export.phoenix == false` 時退出，`true` 時轉送。
7. routing metadata cleanup：Phoenix export 前刪除暫存 header attribute。

Processor 順序 MUST 先去機敏，再 fan-out 到任何後端。

## 7.3 Exporters

### Logs

使用 Loki 的原生 OTLP/HTTP ingestion。Collector 使用 `otlphttp` exporter，base endpoint 應指向：

```text
http://loki:3100/otlp
```

請依目前 Loki 與 OTel Collector 官方文件確認是否由 exporter 自動附加 `/v1/logs`，並以 smoke test 證明。

禁止使用已棄用的 Loki-specific Collector exporter。

### Metrics

使用 Collector Prometheus exporter 暴露內部 scrape endpoint，由 Prometheus 主動 scrape。

要求：

- 正確處理 resource attributes。
- 不把高基數 session、conversation、prompt、task、path、commit 等欄位轉成 Prometheus labels。
- 同時收集 Collector 自身健康、queue、dropped、export failure 等 internal metrics。

### Traces → Tempo

使用 OTLP/gRPC exporter：

```text
tempo:4317
```

容器內允許 insecure transport；不得暴露成遠端網路服務。

### Curated traces → Phoenix

只在 evaluation Collector 設定啟用。

使用 Phoenix 官方支援的 OTLP endpoint，優先選 OTLP/gRPC：

```text
phoenix:4317
```

若當前 Phoenix image 的官方建議不同，採官方方式並記錄。

## 7.4 Extensions

至少評估並合理使用：

- `health_check`
- Collector 自身 telemetry
- 必要時 `zpages`，但預設不得暴露到 host

## 7.5 Queue、Retry 與資料遺失

- 使用官方 exporter 預設 retry 或明確設定 bounded retry。
- 不建立無界 queue。
- 本機 MVP 不要求 persistent queue；若未啟用，必須在 `OPERATIONS.md` 說明 Collector／後端關閉期間可能遺失資料。
- 任何 exporter 長期失敗都應能從 Collector health dashboard 看見。

---

# 8. 資料去機敏與隱私

## 8.1 預設原則

預設 profile 是 metadata-first，而不是 content-first。

MUST NOT 預設保存：

- 使用者 prompt 內容。
- Assistant 完整回應。
- tool arguments。
- tool result／output snippet。
- shell command 完整字串。
- 程式碼、diff 或檔案內容。
- 絕對路徑。
- email、真實姓名、account ID、organization ID。
- Authorization、Cookie、API key、Token、secret 類 headers。
- 公司內部 Repository、ticket、PR 內容。

## 8.2 Codex 特別要求

Codex 設定 MUST：

```toml
log_user_prompt = false
```

Collector 還要刪除已知可能含內容的 event attributes，因為 `log_user_prompt=false` 不代表所有 tool output 都自動安全。

## 8.3 Personal core 去除規則

Personal core 可以保留：

- tool 名稱。
- model 名稱。
- token counts。
- duration。
- success／failure。
- event type。
- conversation／session 的本機 opaque ID。
- framework／workflow／skill ID。
- validation fingerprint。
- Git diff 數量統計，但不含內容。

Personal core 仍必須刪除內容欄位與 secret-like attributes。

## 8.4 Corporate metadata-only 規則

Corporate mode 採 allowlist 思維，只保留：

- pseudonymous user ID。
- environment profile。
- framework version。
- workflow／stage／skill／rule ID。
- tool category。
- model family。
- token counts。
- durations 與 bucket。
- retry count。
- outcome。
- validation fingerprint 的不可逆本機 hash。
- evidence class。
- error category。

Corporate mode 不應保存可由單筆事件反推出實際專案內容的資料。

## 8.5 Synthetic sentinel 測試

Smoke test MUST 送入明確 sentinel，例如：

```text
AI_OBSERVABILITY_SECRET_SENTINEL_7F3B9D
```

該 sentinel 至少放入：

- prompt-like attribute。
- tool-output-like attribute。
- authorization-like attribute。
- absolute-path-like attribute。

驗證結果：

- Loki 查不到 sentinel。
- Tempo 查不到 sentinel。
- Phoenix 查不到 sentinel。
- Collector debug logs 不得輸出完整 sentinel。
- 測試報告仍能確認事件本身成功被接收與匯出。

不要只靠「看起來有 transform processor」就宣告去機敏完成。

---

# 9. Telemetry 資料契約

## 9.1 契約原則

1. 保留各 vendor 的原始非機敏欄位，不直接改名破壞除錯能力。
2. 另增加 `ai_context.*` 正規化命名空間。
3. 不宣稱 vendor token、credit 或 cost 可直接互相比較。
4. 高基數欄位只放 logs／traces，不放 metrics labels。
5. 所有自訂欄位在 `docs/DATA-CONTRACT.md` 定義：
   - 型別。
   - allowed values。
   - 基數預期。
   - 是否可進公司彙總。
   - 是否可能含機敏資料。
   - schema version。

## 9.2 建議自訂欄位

### Framework 與工作流

```text
ai_context.schema.version
ai_context.framework.name
ai_context.framework.version
ai_context.framework.commit
ai_context.workflow.id
ai_context.workflow.type
ai_context.workflow.stage
ai_context.task.id
ai_context.task.type
```

### Context、skill 與 rule

```text
ai_context.skill.id
ai_context.rule.id
ai_context.rule.state
ai_context.context.manifest_hash
ai_context.context.loaded_files
ai_context.context.loaded_bytes
ai_context.context.estimated_tokens
```

`ai_context.rule.state` 建議值：

```text
declared
loaded
evaluated
triggered
affected_action
```

### Validation 與重作

```text
ai_context.validation.id
ai_context.validation.tier
ai_context.validation.fingerprint
ai_context.validation.reused
ai_context.validation.invalidation_reason
ai_context.retry.parent_id
ai_context.retry.reason
```

### 狀態與結果

```text
ai_context.state
ai_context.wait.reason
ai_context.outcome
ai_context.evidence.class
ai_context.manual_correction
ai_context.export.phoenix
```

`ai_context.state` 建議值：

```text
active
tool_running
tool_queue
awaiting_owner
awaiting_hosted_check
blocked_environment
paused
sleep
disconnected
completed
```

`ai_context.evidence.class` 建議值：

```text
repository_record
git_fact
provider_readback
conversation_observation
derived_interval
manual_annotation
```

## 9.3 Metrics label 規則

可以成為 metrics labels 的欄位：

- tool
- model_family
- operation
- success
- stage
- task_type
- token_type
- environment profile

不得成為 metrics labels：

- session ID
- conversation ID
- prompt ID
- task UUID
- tool call ID
- validation fingerprint
- commit SHA
- branch
- path
- email
- raw error message

## 9.4 Cost 欄位

為後續公司使用量分析預留：

```text
ai_cost.value
ai_cost.unit
ai_cost.source
ai_cost.rate_card.version
ai_cost.attribution.confidence
```

`ai_cost.source`：

```text
official
vendor_reported
estimated
allocated
unknown
```

`ai_cost.attribution.confidence`：

```text
exact
bounded
proportional
manual
unattributed
```

MVP 只建立設計與 dashboard placeholder，不建立官方 ChatGPT Enterprise API／CSV importer，也不得把本機 token 估算標成官方 credit。

---

# 10. Grafana、Prometheus、Loki、Tempo 規格

## 10.1 Grafana

- 使用 provisioning 建立 datasources 與 dashboards。
- 禁止要求使用者手動在 UI 新增 datasource。
- Datasource UID 固定且有文件：
  - `prometheus`
  - `loki`
  - `tempo`
- 建立 log-to-trace 與 trace-to-log 關聯；若因實際欄位限制無法完整支援，文件必須說明。
- Grafana UI 只綁定 `127.0.0.1`。
- 不啟用匿名 Admin。
- 密碼來自 `.env`。
- Dashboard JSON 必須可重建，不把 dashboard 只留在 volume。

## 10.2 Prometheus

- 只收低基數 metrics。
- 設定本機合理 retention，並在文件列出調整方式。
- scrape：
  - Collector exported application／AI metrics。
  - Collector internal metrics。
  - 其他後端 metrics 只有在能提供實際診斷價值時加入。
- 使用 `promtool` 驗證設定。
- 不啟用不需要的 remote-write receiver。

## 10.3 Loki

- 使用目前支援的單機開發設定。
- OTLP resource attributes 只有低基數欄位成為 index labels。
- 其他欄位使用 structured metadata。
- 設定本機 retention。
- 不使用 deprecated schema／storage configuration。
- 使用 Loki 官方 readiness endpoint 與 API smoke test。

## 10.4 Tempo

- 使用單機 local storage。
- 啟用 OTLP receiver，僅供 Docker network。
- 設定 compactor retention。
- Grafana 可以搜尋 smoke-test trace。
- 不啟用不必要的 multi-tenant 或 distributed components。

---

# 11. Phoenix 規格

## 11.1 定位

Phoenix 是 AI evaluation layer，不是 Tempo 的替代品。Evaluation mode 預設接收已去機敏、
且已宣告 `openinference.span.kind` 的 spans；generic agent internal spans 留在 Tempo。

只接收：

- 已去機敏。
- 具 `openinference.span.kind`，因此有明確 evaluation semantic boundary。
- 缺少 `x-ai-observability-phoenix` header，或值為 `true`。
- 未設定 legacy resource attribute，或 `ai_context.export.phoenix != false`。

Header 與 resource attribute 的 `false` 都是明確 opt-out。所有路由判斷發生在 privacy
processor 之後；header 衍生的暫存 attribute 必須在 export 前刪除。

## 11.2 Persistence

- 使用官方 Phoenix Docker image。
- 使用 PostgreSQL 14 或更新且符合當前官方支援範圍的版本。
- Phoenix database 與未來 usage ledger 必須邏輯隔離。
- PostgreSQL port 預設不暴露 host。
- 使用 named volume。
- 提供 migration／upgrade 注意事項。

## 11.3 Port

- Phoenix UI 預設綁定 host `127.0.0.1:${PHOENIX_PORT}`。
- Phoenix OTLP port 只在 Compose network 內提供給 Collector。
- 不讓 Codex 直接送到 Phoenix。

## 11.4 OpenInference

Codex、Claude、Copilot 的原生 OTel 不保證完整符合 OpenInference。

MVP：

- generic traces 只保留在 Tempo，不複製進 Phoenix。
- 不建立未經驗證的欄位轉換，也不把一般 internal span 冒充成 LLM/CHAIN/TOOL。
- 在 `PHOENIX-INTEGRATION.md` 說明：
  - generic OTel trace 的限制。
  - 未來 OpenInference adapter。
  - dataset／annotation／evaluator 的預計用法。

## 11.5 Phoenix 驗收

Evaluation smoke test 至少送六個 traces：

1. 缺少 header 與 resource attribute：Tempo 與 Phoenix 都能找到。
2. header `true`：Tempo 與 Phoenix 都能找到。
3. header `false`：Tempo 能找到，Phoenix 找不到。
4. `ai_context.export.phoenix=true`：Tempo 與 Phoenix 都能找到。
5. `ai_context.export.phoenix=false`：Tempo 能找到，Phoenix 找不到。
6. 缺少 `openinference.span.kind`：Tempo 能找到，Phoenix 找不到。

若 Phoenix 沒有穩定公開查詢 API，必須：

- 先尋找官方支援的 client／API。
- 若仍無法自動化，將 Phoenix presence check 明確標成 manual acceptance，其他路由條件仍以 Collector metrics／logs 與 Tempo 自動驗證。
- 不可以假造 API。

---

# 12. Codex 整合

## 12.1 使用者層級設定

範例放在：

```text
examples/codex/config.toml.example
```

文件說明路徑：

- Windows：`%USERPROFILE%\.codex\config.toml`
- Linux／WSL：`~/.codex/config.toml`

只合併 `[otel]` 區塊，不覆寫現有 model、sandbox、MCP、skills 或其他設定。

## 12.2 必要範例

```toml
[otel]
environment = "personal-local"
log_user_prompt = false
exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "binary" } }
trace_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/traces", protocol = "binary" } }
metrics_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/metrics", protocol = "binary" } }
```

實作時必須依目前 Codex 官方 config schema 驗證此 TOML。若目前版本需要不同結構，更新範例並在 `DEPENDENCIES.md` 記錄最小支援 Codex 版本。

## 12.3 驗證

`CODEX-INTEGRATION.md` 必須說明：

1. 啟動 Toolkit。
2. 備份現有 Codex config。
3. 合併 `[otel]`。
4. 重新啟動 Codex client。
5. 執行一個低風險短工作階段。
6. 確認 Collector 收到 logs、metrics、traces。
7. 在 Grafana 查看。
8. 發生問題時如何暫時改回 `none`。
9. 如何區分 CLI、Desktop、IDE extension 的實際支援狀況；未驗證的 client 不得宣稱支援。

## 12.4 Dashboard 對 Codex 欄位的處理

Codex 目前可提供 conversation、API request、SSE／WebSocket、tool、MCP、skill、multi-agent、compaction、turn duration、TTFT 與 token usage 等資料。

實作 Agent MUST：

- 先送入實際 Codex telemetry。
- 觀察 Prometheus sanitize 後的 metric names 與 labels。
- 依實際資料建立 dashboard。
- 不要僅根據猜測把 `.` 換成 `_`。
- 在 `DATA-CONTRACT.md` 留下 raw name → backend name 對照。

---

# 13. Grafana Dashboards

## 13.1 `collector-health`

至少包含：

- Receiver accepted／refused records。
- Processor dropped records。
- Exporter sent／failed records。
- Queue size／capacity。
- Batch size／flush。
- Collector memory 與 CPU。
- 各 exporter 是否持續失敗。
- 最近一次收到 telemetry 的時間。

## 13.2 `codex-usage`

至少包含：

- input／cached input／output／reasoning output tokens。
- token type 比例。
- turn 數量。
- model 分布。
- API request success／failure。
- tool call count、duration、failure。
- MCP call count、duration、failure。
- compaction 次數。
- multi-agent spawn 次數。
- skill injection 次數。
- Grafana time range 與 environment 變數。

## 13.3 `ai-agent-usage`

首屏至少包含 telemetry 新鮮度、所選時間範圍 token／estimated cost／turns、
估價 coverage 與 cached-input ratio。Provider-specific 或 extension-observed
snapshots 應收進清楚標示的細節區，不讓不支援的欄位佔滿首屏。

## 13.4 `ai-agent-activity`

使用 Loki metadata-only events 呈現 prompt 提交、tool/API/sandbox 活動、
失敗狀態與時間軸，並保留 trace_id 供 Tempo 關聯。不得呈現 raw prompt、
assistant response、tool arguments/results、command output、source code 或 path。

`ai_context.*` schema 與 fixtures 保留，但在 deterministic framework-owned
emitter 完成前，不 provision workflow/effectiveness dashboards。Prompt
self-report 與 provider-native telemetry 都不能替代獨立 framework evidence。

## 13.5 Dashboard 品質

- 不以 session ID 作為預設高基數 template variable。
- 可由彙總 panel drill down 到 Loki／Tempo。
- 每個 panel 有單位、說明與資料來源。
- 不把估算值標示成官方值。
- 使用 version-controlled dashboard JSON。

---

# 14. Smoke Test 與驗收資料

## 14.1 OTLP Fixtures

建立 OTLP/HTTP JSON fixtures 或另一個不需要在 host 安裝 SDK 的可重現發送器，至少產生：

- 一筆 metric。
- 一筆 log。
- 一個 trace。
- 一個 Phoenix selected trace。
- 一個 Phoenix rejected trace。
- 一組敏感 sentinel attributes。

若使用額外 container／tool：

- 使用官方或可信 image。
- 明確 pin version。
- 不將它加入常駐服務。
- 在 `DEPENDENCIES.md` 記錄用途。

## 14.2 Core smoke test

自動驗證：

1. Compose config 有效。
2. 核心容器啟動。
3. Collector 可接收 OTLP/HTTP。
4. Prometheus 找得到 smoke metric。
5. Loki 找得到 smoke log。
6. Tempo 找得到 smoke trace。
7. Grafana datasources health 正常。
8. 敏感 sentinel 不存在於後端。
9. 重啟容器後 named volume 資料仍存在。
10. 測試結束後回傳非零 exit code 表示失敗。

## 14.3 Evaluation smoke test

額外驗證：

- PostgreSQL ready。
- Phoenix UI ready。
- selected trace 進 Phoenix。
- rejected trace 不進 Phoenix。
- 兩者皆依規格進 Tempo。
- sentinel 不進 Phoenix。

## 14.4 Smoke report

腳本輸出清楚摘要：

```text
[PASS] compose config
[PASS] collector OTLP HTTP
[PASS] prometheus metric
[PASS] loki log
[PASS] tempo trace
[PASS] redaction sentinel absent
[SKIP] phoenix API verification — documented manual check
```

`SKIP` 必須帶原因，不得當作 `PASS`。

---

# 15. 操作腳本

## 15.1 `up`

支援：

```text
core
evaluation
corporate
```

要求：

- 檢查 Docker 與 Compose v2。
- 檢查 `.env`，缺少時提示從 `.env.example` 建立。
- 驗證 mode。
- corporate 與 evaluation 不得同時使用。
- 啟動後等待必要 readiness。
- 顯示 UI URL 與 OTLP endpoint。
- 不洩漏密碼。

## 15.2 `down`

- 使用相同 mode 的 Compose file 組合。
- 預設不刪 volume。
- 明確顯示資料仍保留。

## 15.3 `status`

- 顯示容器狀態。
- 顯示 health。
- 顯示 host ports。
- 顯示最近 Collector exporter 錯誤摘要，若可安全取得。

## 15.4 `validate-config`

至少執行：

- `docker compose config` 的三種 mode。
- Collector config validate。
- Prometheus `promtool check config`。
- JSON parse。
- shell syntax。
- PowerShell parse（CI 可用 PSScriptAnalyzer 或最低限度 parser）。
- 禁止 floating image tags。
- 禁止 committed `.env`。
- 禁止 `0.0.0.0` host port binding。

## 15.5 `reset-data`

- 預設拒絕執行。
- 需要 `--confirm` 或明確輸入 project 名稱。
- 列出即將刪除的 named volumes。
- 不刪除其他 Compose project 的 volume。
- 退出碼可供 CI／script 判讀。

## 15.6 `resource-snapshot`

輸出：

- 各 container CPU。
- memory usage。
- network IO。
- block IO。
- mode。
- image version。
- 時間戳。
- Docker／Compose 版本。

不得收集 host 檔案內容或使用者敏感資訊。

---

# 16. 文件要求

## 16.1 `README.md`

包含：

- Toolkit 定位。
- 核心與 evaluation 架構圖。
- 最短啟動流程。
- Codex 設定連結。
- URL／port 表。
- 三種 mode。
- 隱私警告。
- 不等於官方 credit 帳務的聲明。
- 相關專案連結。
- 常見問題入口。

## 16.2 `ARCHITECTURE.md`

包含：

- C4-style context／container 圖或清楚 Mermaid。
- Collector pipeline。
- Core／evaluation／corporate 差異。
- 為何不是 Phoenix-only。
- 為何 MVP 不使用 ClickHouse／SigNoz／ELK。
- 為何 Phoenix 只收 curated traces。
- 失敗模式與資料遺失邊界。

## 16.3 `DATA-CONTRACT.md`

包含第 9 節所有欄位與基數／隱私分類。

## 16.4 `PRIVACY.md`

包含：

- personal／corporate 資料分類。
- 預設刪除欄位。
- sentinel test。
- retention。
- 使用者告知與公司治理注意事項。
- 日後中央化前需要的 auth、TLS、RBAC、稽核。

## 16.5 `OPERATIONS.md`

包含：

- 啟停。
- 升級。
- 備份。
- reset。
- retention。
- disk full。
- version rollback。
- port conflict。
- Collector exporter failure。
- Docker Desktop／WSL2 注意事項。

## 16.6 `TROUBLESHOOTING.md`

至少涵蓋：

- `4317`／`4318` 被占用。
- Codex 沒有送出資料。
- OTLP HTTP path 錯誤。
- Loki reject。
- Tempo 查不到 trace。
- Prometheus metric name 不如預期。
- Phoenix 連不上 PostgreSQL。
- Docker Desktop volume／WSL2 效能。
- 公司代理／憑證替換。
- 時區與 timestamp。
- Collector redaction 規則造成資料缺失。

## 16.7 `COST-ATTRIBUTION.md`

明確區分：

- official credits。
- estimated credits。
- vendor-reported cost。
- allocated internal cost。
- 本機 token 觀測。
- attribution confidence。

說明 MVP 沒有官方 Enterprise credit importer，未來才會加入 PostgreSQL usage ledger 與 reconciliation。

## 16.8 `DEPENDENCIES.md`

表格至少有：

| Component | Image | Pinned version | Release date | Official source | License | Reason | Upgrade notes |
|---|---|---:|---|---|---|---|---|

版本必須以實際驗證組合為準，不要盲目使用各元件最新版本。

## 16.9 `RESOURCE-BASELINE.md`

記錄：

- 測試機 OS。
- Docker／Compose 版本。
- CPU／RAM。
- Core idle。
- Core smoke load。
- Evaluation idle。
- Evaluation smoke load。
- Disk growth sample。
- 已知公司電腦最低建議。

不要宣稱單次測量是正式容量規劃。

## 16.10 `IMPLEMENTATION-REPORT.md`

最後由實作 Agent 填寫：

- 實際新增檔案。
- 版本與選型。
- 驗證命令與結果。
- 未完成／manual／skip。
- 偏離規格。
- 已知風險。
- 建議下一步。
- 不得把失敗或未測試項目寫成完成。

---

# 17. GitHub Actions

## 17.1 `validate.yml`

每次 push／PR：

- checkout。
- 驗證 Compose 三種 mode。
- 驗證 YAML／JSON／TOML。
- 驗證 Collector。
- 驗證 Prometheus。
- 檢查 shell。
- 檢查 floating tags。
- 啟動 Core mode。
- 執行 core smoke test。
- 收集失敗時的 compose logs。
- teardown，不保留 volume。

## 17.2 `evaluation-smoke.yml`

- 可使用 `workflow_dispatch` 加上排程或 PR path filter。
- 啟動 Evaluation mode。
- 執行 evaluation smoke test。
- 嚴格 timeout。
- 失敗時上傳去機敏 logs 作 artifact。
- 若 GitHub-hosted runner 資源不足，可保留為 manual workflow，但必須留下實測證據與理由；不得直接刪除驗證。

## 17.3 CI 安全

- 不使用真實 API key。
- 不接觸 ChatGPT Enterprise。
- 所有 smoke telemetry 使用合成資料。
- artifact 不得含 sentinel 原值以外的任何真實敏感內容。
- 不使用 mutable action version；GitHub Actions SHOULD pin major 或 commit SHA，依 Repository 既有治理決定。

---

# 18. Image 版本選擇與相容性

實作 Agent 在開始前必須查詢目前官方文件與 release：

- OpenTelemetry Collector Contrib
- Prometheus
- Loki
- Tempo
- Grafana
- Phoenix
- PostgreSQL
- 任何 smoke-test image

選擇原則：

1. 官方 stable／GA。
2. 相互相容。
3. 目前 Docker Compose 可驗證。
4. 不使用未必要的 nightly／preview。
5. 優先安全修正版。
6. 記錄 release date 與 breaking changes。
7. 完成後輸出 `docker compose images` 證據。

禁止只因範例文章使用舊版就沿用。

---

# 19. 實作階段

## Phase 0：Bootstrap 與 dependency decision

- 基本 Repository files。
- dependency matrix。
- Compose mode strategy。
- 實作計畫。

完成條件：

- 目錄結構確定。
- image 版本確定。
- `docker compose config` 可開始迭代。

## Phase 1：Core LGTM

- Collector。
- Prometheus。
- Loki。
- Tempo。
- Grafana。
- provisioning。
- health checks。
- named volumes。

完成條件：

- Core mode 啟動。
- 三訊號 smoke test 通過。

## Phase 2：Privacy 與 Corporate mode

- personal redaction。
- corporate allowlist。
- sentinel tests。
- company mode override。

完成條件：

- sentinel absence 自動驗證。
- corporate 不啟動 Phoenix／不對外 export。

## Phase 3：Phoenix Evaluation

- PostgreSQL。
- Phoenix。
- evaluation Collector config。
- selected／rejected trace routing。
- Phoenix 文件。

完成條件：

- 路由測試完成。
- 未驗證部分明確 manual／skip。

## Phase 4：Dashboards 與 Codex

- 實際 Codex telemetry。
- dashboard queries。
- Codex integration docs。
- raw → backend name mapping。

完成條件：

- 使用者可執行短 Codex session 並看到資料。
- `log_user_prompt=false`。
- dashboard 不依賴猜測 metric name。

## Phase 5：Scripts、CI、Documentation

- PowerShell／Bash parity。
- validation。
- resource baseline。
- GitHub Actions。
- implementation report。

完成條件：

- 新環境可依 README 重建。
- 所有 acceptance criteria 有結果。

---

# 20. 完整驗收條件

## 20.1 必須全部通過

- [ ] `docker compose config`：Core。
- [ ] `docker compose config`：Evaluation。
- [ ] `docker compose config`：Corporate。
- [ ] 所有 image 明確 pin。
- [ ] 無 `container_name`。
- [ ] 所有 host ports 綁 `127.0.0.1`。
- [ ] Core 容器啟動並 ready。
- [ ] OTLP logs 進 Loki。
- [ ] OTLP metrics 進 Prometheus。
- [ ] OTLP traces 進 Tempo。
- [ ] Grafana datasources provisioning 成功。
- [ ] Grafana dashboards provisioning 成功。
- [ ] Sentinel 不在 Loki。
- [ ] Sentinel 不在 Tempo。
- [ ] Evaluation mode PostgreSQL ready。
- [ ] Evaluation mode Phoenix ready。
- [ ] selected trace 路由到 Phoenix。
- [ ] rejected trace 不路由到 Phoenix。
- [ ] Sentinel 不在 Phoenix。
- [ ] Codex TOML 通過目前 schema／實機驗證。
- [ ] Codex prompt content 預設關閉。
- [ ] PowerShell 與 Bash 腳本皆可執行。
- [ ] named volumes 在一般 restart 後保留。
- [ ] reset 需要明確確認。
- [ ] Core CI 通過。
- [ ] `IMPLEMENTATION-REPORT.md` 完整且誠實。

## 20.2 可標示 manual，但不可假裝通過

- Phoenix UI 內 selected trace 的人工畫面確認。
- ChatGPT Desktop／Codex IDE extension 的支援差異。
- 公司憑證替換環境。
- 真實 ChatGPT Enterprise credit reconciliation。
- 無 Docker 公司端 bundle 流程。

---

# 21. Out of Scope

本次不要實作：

1. ChatGPT Enterprise Admin API。
2. 官方 credit CSV importer。
3. 個人／團隊 RBAC。
4. LDAP／OIDC。
5. 中央多使用者服務。
6. Internet-facing reverse proxy。
7. TLS 憑證管理。
8. Production HA。
9. Kubernetes。
10. ClickHouse。
11. SigNoz／OpenObserve／ELK。
12. Claude Code／Copilot 的完整原生整合。
13. Phoenix dataset／evaluator 自動化。
14. LLM-as-a-judge。
15. 自動刪除上游規範。
16. 自動修改 ChatGPT Enterprise spend limit。
17. 收集 raw prompt、response、code、diff。
18. 無 Docker endpoint agent。
19. 公司資料外傳。
20. 自動建立 GitHub remote／PR／Release。

---

# 22. Roadmap

## 22.1 Phase 2：AI Context instrumentation

此 phase 必須先交付 deterministic framework-owned emitter 或 hooks，並以
至少一個真實 workflow 驗證。完成前不得恢復 AI Context dashboards。

- workflow root span。
- stage spans。
- validation fingerprint。
- wait／sleep／resume。
- context manifest。
- skill／rule state。
- manual correction。
- outcome。
- Git／build／test metadata。

## 22.2 Phase 3：Phoenix improvement loop

- 從 traces 建 dataset。
- duplicate-validation evaluator。
- late-environment-preflight evaluator。
- unattributed-wait evaluator。
- context-route-budget evaluator。
- subagent-overlap evaluator。
- framework A/B experiments。

## 22.3 Phase 4：Company usage ledger

- 官方 CSV／Admin API ingestion。
- PostgreSQL usage ledger。
- official vs estimated reconciliation。
- attribution confidence。
- 個人 showback。
- 團隊匿名彙總。
- 不建立使用者生產力排行榜。

## 22.4 Phase 5：Corporate feedback bundle

- metadata-only JSONL。
- 去機敏 aggregate。
- `ai-context-feedback-bundle.json`。
- schema validation。
- 本機保留與刪除政策。
- 可人工帶回上游的安全摘要。

## 22.5 Phase 6：No-Docker collector agent

- 單一原生 binary。
- 本機檔案 queue。
- 明確 data retention。
- 受控匯出。
- Windows／Linux installer。
- 公司資安審查。

---

# 23. 模型與 Antigravity 執行建議

## 23.1 主實作模型：Gemini 3.6 Flash（High）

建議負責：

- Repository scaffold。
- Compose／YAML／JSON／PowerShell／Bash。
- 官方文件核對。
- 多輪執行與修正。
- CI 與 smoke test。
- 文件同步。

理由：

- 本規格已把架構與邊界寫清楚，主要風險是跨多個設定檔的一致性與實際驗證，而不是重新發明架構。
- Gemini 3.6 Flash 是 stable／GA，Google 將它定位於 agentic、coding 與多步工作流，並特別強調較少 unwanted edits、tool loops 與 token 使用。
- 在 Antigravity 中可直接選 High reasoning。

不要用 Low 作為第一次完整建置；Medium 可用於後續小修，High 用於初次跨元件整合。

## 23.2 架構與隱私 Review：Gemini 3.1 Pro（High）

在主實作完成、所有測試已跑過後，另開一個 user turn，要求它只做：

- 規格符合性 review。
- Collector routing review。
- privacy／redaction review。
- Compose mode conflict review。
- 未測試與假陽性檢查。
- 不做大範圍重寫。

Gemini 3.1 Pro 目前是 preview，適合深度 review，但不建議拿它承擔所有機械式檔案產出與反覆修正。

## 23.3 獨立最終稽核或疑難除錯：Claude Opus 4.6（Thinking）

只在下列情況使用：

- Collector OTTL／filter 路由經多次修正仍不可靠。
- Loki、Tempo、Phoenix 的語意或隱私邊界有疑問。
- CI 與本機結果矛盾。
- 需要獨立審查是否有「看似完成、實際未驗證」的項目。
- 最終 release 前做一次規格與安全稽核。

不要一開始就用 Opus 4.6 生成所有檔案；這會把高成本模型花在大量可由 3.6 Flash 完成的機械式工作。

## 23.4 建議模型流程

```text
Turn 1 — Gemini 3.6 Flash High
  → 讀本規格、規劃、完整實作、執行測試、寫報告

Turn 2 — Gemini 3.1 Pro High
  → 僅 review 規格、隱私、路由、測試證據
  → 產出具體 findings，不做無邊界重寫

Turn 3 — Gemini 3.6 Flash High
  → 修正已確認 findings，重跑驗證

Turn 4（必要才用）— Claude Opus 4.6 Thinking
  → 獨立最終稽核或疑難根因分析
```

Antigravity 的模型選擇在單一 user turn 內具黏著性；切換模型應在前一個 turn 完成或取消後進行。

---

# 24. 建議提供給 Antigravity 的起始訊息

```text
請完整閱讀 repository 內的
docs/IMPLEMENTATION-BRIEF.md，並將它視為本次工作的權威規格。

你的工作是直接建立 ai-collaboration-observability-toolkit：
1. 先檢查 repository 狀態與官方目前 stable 版本。
2. 先產生實作計畫與 dependency matrix。
3. 依規格完成 Core、Corporate、Evaluation 三種模式。
4. 建立 PowerShell/Bash 腳本、smoke tests、Grafana dashboards、Codex 範例與文件。
5. 實際執行可執行的驗證。
6. 將結果、skip、manual check、偏差與風險寫入
   docs/IMPLEMENTATION-REPORT.md。

不要加入規格列為 Out of Scope 的元件。
不要使用 latest image。
不要收集 raw prompt、response、code、diff 或 secrets。
不要將未測試項目描述成完成。
不要建立或推送遠端 Repository、PR、tag 或 Release。
```

---

# 25. 官方參考資料

實作時優先使用最新官方文件；以下 URL 是起點，不代表可以跳過版本核對。

## Codex

- <https://developers.openai.com/codex/config-advanced>
- <https://developers.openai.com/codex/config-reference>
- <https://developers.openai.com/codex/config-sample>

## OpenTelemetry

- <https://opentelemetry.io/docs/collector/>
- <https://github.com/open-telemetry/opentelemetry-collector-contrib>
- <https://opentelemetry.io/docs/specs/otlp/>

## Grafana 生態系

- <https://grafana.com/docs/grafana/latest/>
- <https://grafana.com/docs/loki/latest/send-data/otel/>
- <https://grafana.com/docs/tempo/latest/>
- <https://prometheus.io/docs/prometheus/latest/configuration/configuration/>

## Phoenix

- <https://arize.com/docs/phoenix/self-hosting>
- <https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/instrumentation>
- <https://arize.com/docs/phoenix/tracing/concepts-tracing/translating-conventions>

## Antigravity／Gemini

- <https://antigravity.google/docs/models>
- <https://ai.google.dev/gemini-api/docs/models>
- <https://ai.google.dev/gemini-api/docs/latest-model>

---

# 26. 最終交付摘要格式

完成時回報必須使用下列結構：

```markdown
## 完成內容
- ...

## 實際版本
| Component | Version | Evidence |
|---|---:|---|

## 驗證結果
| Check | Result | Command / Evidence |
|---|---|---|

## 未完成或人工驗證
- ...

## 隱私驗證
- Sentinel:
- Loki:
- Tempo:
- Phoenix:

## 資源基準
- Core idle:
- Core smoke:
- Evaluation idle:
- Evaluation smoke:

## 規格偏差
- ...

## 已知風險
- ...

## 建議下一步
- ...
```

不得省略失敗、skip、manual 或不確定項目。
