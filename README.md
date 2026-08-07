# AI Collaboration Observability Toolkit

一套以 OpenTelemetry Collector（OTel Collector）為唯一入口、預設執行資料最小化的本機 AI
協作可觀測性（observability）工具。它用來分析 Codex、Claude Code、GitHub Copilot、AI
Context 工作流，以及下游專案在開發期間產生的執行證據。

核心目標不是監看對話內容，而是回答：

- token 與模型用量花在哪一種工作、skill、規範或驗證階段；
- 哪些驗證被重複執行，哪些等待無法歸因，哪些環境問題發現得太晚；
- AI Context 版本精簡後，成功率、人工修正、返工與成本是否改善；
- 公司環境能否只保留已核准的 metadata，供個人與團隊進行用量揭露與自我改善。

[English](README.en.md)

## 架構

```text
AI tools / applications / ai-context hooks
                   │ OTLP gRPC or HTTP
                   ▼
          OpenTelemetry Collector
          ├─ metrics ─▶ Prometheus ─┐
          ├─ logs ────▶ Loki ───────┼─▶ Grafana
          └─ traces ──▶ Tempo ──────┘
                       └─ selected + minimized ─▶ Phoenix（evaluation）
```

Collector 在資料分流前完成：

- 記憶體限制與批次處理；
- 環境與 framework metadata 正規化；
- prompt、回應、工具輸出、程式碼、路徑、身分與憑證欄位移除；
- metric label 高基數（high cardinality）欄位移除；
- Phoenix trace 的明確 opt-in 路由。

## 執行模式

| 模式 | 用途 | Phoenix | 資料政策 |
| --- | --- | --- | --- |
| `core` | 個人本機 LGTM 基線 | 無 | 已知內容欄位刪除、log body 固定化、metric label allowlist |
| `evaluation` | trace 評註、資料集與 framework 實驗 | 有 | 與 core 相同；只有 `ai_context.export.phoenix=true` 的 trace 進入 Phoenix |
| `corporate` | 公司電腦 metadata-only 基線 | 無 | 嚴格 `keep_keys` allowlist，未知欄位一律丟棄 |

`evaluation` 與 `corporate` 不可同時啟用。

## 快速開始

### 1. 安裝操作工具相依套件

建議使用 Python 虛擬環境（virtual environment）：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 準備本機設定並啟動

```bash
cp .env.example .env
# 先修改 .env 內的範例密碼
./scripts/up.sh core
./scripts/status.sh core
./scripts/smoke-test.sh core
```

PowerShell：

```powershell
Copy-Item .env.example .env
# 先修改 .env 內的範例密碼
.\scripts\up.ps1 -Mode core
.\scripts\status.ps1 -Mode core
.\scripts\smoke-test.ps1 core
```

停止服務不會刪除資料：

```bash
./scripts/down.sh core
```

刪除所有 named volumes 必須明確輸入 Compose 專案名稱：

```bash
./scripts/reset-data.sh core ai-collaboration-observability
```

## 本機介面

所有 host port 預設明確綁定 `127.0.0.1`：

- Grafana: `http://127.0.0.1:3000`
- Prometheus: `http://127.0.0.1:9090`
- Loki: `http://127.0.0.1:3100`
- Tempo: `http://127.0.0.1:3200`
- Phoenix（evaluation）: `http://127.0.0.1:6006`
- OTLP gRPC／HTTP: `127.0.0.1:4317`／`127.0.0.1:4318`

Tempo 與 Phoenix 的 OTLP receiver 沒有發布到 host；AI 工具只能經過 Collector。

## Codex

將 [`examples/codex/config.toml.example`](examples/codex/config.toml.example) 的 `[otel]` 區段
**合併**至使用者層級 `~/.codex/config.toml`；Windows 路徑為
`%USERPROFILE%\.codex\config.toml`。不要覆寫既有 model、sandbox、MCP、skills 或 project 設定。
重新啟動 Codex 後執行一個小型工作，再確認 Collector 與 Grafana 有收到資料。

`log_user_prompt=false` 只是第一層控制；Collector 仍會執行第二層資料最小化與 sentinel 測試。

## 驗證

不需 Docker 的靜態檢核：

```bash
python scripts/toolkit.py validate --mode all --static-only
python -m unittest discover -s tests -v
```

有 Docker／原生 validator 時：

```bash
python scripts/toolkit.py validate --mode all
```

端到端煙霧測試（smoke test）：

```bash
./scripts/up.sh evaluation
./scripts/smoke-test.sh evaluation
./scripts/down.sh evaluation
```

煙霧測試會送入含 synthetic sentinel 的 OTLP logs、metrics 與 traces，並確認 sentinel、synthetic
email、路徑、憑證值及高基數欄位沒有進入 Prometheus、Loki、Tempo 或 Phoenix。

## 已提供的 Dashboard

- Collector health
- Codex／AI 工具 normalized usage
- AI workflow efficiency
- AI Context effectiveness

前 1 版 dashboard 不會捏造 AI 工具未提供的資料。要分析 rule、skill、validation fingerprint、等待
狀態與 framework 版本，仍需要 `ai-collaboration-prompts-dotnet-backend` 後續加入 `ai_context.*`
instrumentation。

## 文件

- [架構](docs/ARCHITECTURE.md)
- [資料契約](docs/DATA-CONTRACT.md)
- [隱私與公司模式](docs/PRIVACY.md)
- [操作手冊](docs/OPERATIONS.md)
- [Codex 整合](docs/CODEX-INTEGRATION.md)
- [Phoenix 整合](docs/PHOENIX-INTEGRATION.md)
- [成本歸因](docs/COST-ATTRIBUTION.md)
- [相依套件與版本](docs/DEPENDENCIES.md)
- [完整實作規格](docs/IMPLEMENTATION-BRIEF.md)
- [實作報告](docs/IMPLEMENTATION-REPORT.md)
- [驗證報告](docs/VALIDATION-REPORT.md)
- [Roadmap](docs/ROADMAP.md)

## 安全邊界

這是本機研究與團隊試行基線，不是可直接暴露到網路的正式多租戶平台。不要將 port 改綁
`0.0.0.0` 後直接共用。公司推廣仍需資安審查、使用者告知、權限控管、保存期限、稽核與資料
刪除政策。

## 目前不包含

- OpenAI Enterprise Admin／Cost API 與正式 credit 對帳；
- 多租戶登入與 row-level authorization；
- Rider／ChatGPT Desktop 尚未驗證的 telemetry；
- 完整 AI Context instrumentation SDK；
- 自動刪除規範或以 AI 用量評比人員；
- Kubernetes、高可用性與網路暴露設定。

詳見 [Roadmap](docs/ROADMAP.md)。
