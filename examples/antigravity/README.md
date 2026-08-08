# Google Antigravity 觀測範例

這個範例使用 Antigravity 的 JSON Hooks，將**去內容化的執行 metadata** 轉成 OTLP/HTTP logs 與 traces，送到本工具的 OpenTelemetry Collector。

目前官方設定文件沒有提供可直接填入 Collector endpoint 的原生 OTLP exporter；Antigravity 的「Enable Telemetry」則是提供給 Google 的產品遙測開關，不是本機 OTLP 設定。因此這裡使用 workspace/global plugin hooks 作為可控的本機橋接層。

## 收集範圍

預設收集：

- model invocation 次數、模型名稱與耗時；
- session 開始至停止的 wall-clock duration；
- 工具類別的完成次數與成功／失敗；
- termination reason 與是否仍有背景工作；
- AI Context framework 名稱與版本（由環境變數提供）。

預設**不收集**：

- prompt、模型回應或 transcript；
- tool arguments、tool result 或原始 error 內容；
- workspace 路徑、artifact 路徑或 Repository 名稱；
- 原始 `conversationId`；
- token 與 credit。Antigravity hook payload 目前沒有提供這兩項資料。

`conversationId` 只在本機以隨機 HMAC key 轉成 trace ID，原值不會送出。Corporate mode 仍會在 Collector 套用更嚴格的 allowlist。

## 安裝成 workspace plugin

在要觀察的專案根目錄執行：

```bash
mkdir -p .agents/plugins
cp -R examples/antigravity/plugin \
  .agents/plugins/ai-collaboration-observability
```

PowerShell：

```powershell
New-Item -ItemType Directory -Force .agents\plugins | Out-Null
Copy-Item -Recurse -Force `
  examples\antigravity\plugin `
  .agents\plugins\ai-collaboration-observability
```

Antigravity 同時支援舊版 `.agent/` 路徑，但新設定應使用 `.agents/`。

## 安裝成 global plugin

Linux／macOS／WSL：

```bash
mkdir -p ~/.gemini/config/plugins
cp -R examples/antigravity/plugin \
  ~/.gemini/config/plugins/ai-collaboration-observability
```

PowerShell：

```powershell
$Target = Join-Path $HOME '.gemini\config\plugins\ai-collaboration-observability'
New-Item -ItemType Directory -Force (Split-Path $Target) | Out-Null
Copy-Item -Recurse -Force examples\antigravity\plugin $Target
```

重新啟動 Antigravity 或重新載入 Customizations，確認 plugin 已被掃描。

`hooks.json` 預設使用 `python`。若環境只有 `python3` 或 Windows Python Launcher，請將五個 command 改成 `python3 scripts/emit_otel.py ...` 或 `py -3 scripts/emit_otel.py ...`。

## 啟動觀測後端

```bash
./scripts/up.sh core
```

公司電腦則使用：

```bash
./scripts/up.sh corporate
```

bridge 預設送到：

```text
http://127.0.0.1:4318
```

## 選用環境變數

| 變數 | 預設 | 用途 |
| --- | --- | --- |
| `AI_OBSERVABILITY_ENABLED` | `true` | 設為 `false` 可暫停 hook export。 |
| `AI_OBSERVABILITY_OTLP_HTTP_ENDPOINT` | `http://127.0.0.1:4318` | Collector OTLP/HTTP base endpoint。 |
| `AI_OBSERVABILITY_TIMEOUT_SECONDS` | `0.75` | 每次 HTTP export timeout，上限 3 秒。 |
| `AI_CONTEXT_FRAMEWORK_NAME` | `ai-collaboration-framework` | 寫入 resource metadata。 |
| `AI_CONTEXT_FRAMEWORK_VERSION` | `unknown` | 寫入 resource metadata。 |
| `ANTIGRAVITY_OBSERVABILITY_SERVICE_NAME` | 自動判斷 | 可覆寫 `antigravity-2`／`antigravity-cli`。 |
| `ANTIGRAVITY_VERSION` | `unknown` | Antigravity client 版本。 |
| `ANTIGRAVITY_OBSERVABILITY_STATE_DIR` | OS user state directory | 儲存 invocation 起始時間與本機 HMAC key。 |

例如：

```bash
export AI_CONTEXT_FRAMEWORK_VERSION=0.8.0
export ANTIGRAVITY_VERSION=2.0
```

Windows 使用者可建立使用者層級環境變數後重新啟動 Antigravity：

```powershell
[Environment]::SetEnvironmentVariable(
  'AI_CONTEXT_FRAMEWORK_VERSION',
  '0.8.0',
  'User'
)
```

## 為什麼沒有使用 `PreToolUse`

`PreToolUse` hook 必須回傳 `allow`、`ask`、`deny` 等權限決策。純觀測 hook 若回傳 `allow` 可能改變既有安全邊界，回傳 `ask` 也可能增加核准次數。因此預設範例只使用 `PostToolUse`，並透過 matcher 將工具歸類為：

- `file-operation`
- `search-operation`
- `execution-operation`
- `agent-collaboration`
- `interaction-operation`

代價是目前無法取得精確 tool duration，也不會讀 transcript 反推出 tool arguments 或名稱。這是刻意的隱私與行為不干預取捨。

## 驗證

1. 啟動 `core` 或 `corporate` mode。
2. 安裝 plugin 並重新啟動 Antigravity。
3. 執行一個包含檔案檢視、指令與 sub-agent 的小型工作。
4. 在 Loki 搜尋 `service_name=antigravity-2` 或 `service_name=antigravity-cli`。
5. 在 Tempo 搜尋 `antigravity.model.invocation` 與 `antigravity.agent.session`。
6. 確認沒有 prompt、回應、tool args、workspace path、原始 error 或 conversation ID。

## 已知限制

- hooks 目前不提供 token/credit，因此本範例不能取代 Antigravity `/credits` 或官方使用量資料。
- `PostToolUse` 的 payload 不包含 tool call args；範例只記錄由 matcher 決定的工具類別。
- hook export 採 best-effort。Collector 停止時事件會被丟棄，不會阻擋 agent。
- 新增的 Antigravity 工具不會自動落入既有 matcher；升級後應檢查官方 supported tools 清單。
- 此範例針對 Antigravity 2.0 與 Antigravity CLI 的 JSON Hooks。不要假設舊 Antigravity IDE 具有相同資料契約。

詳見 [`docs/ANTIGRAVITY-INTEGRATION.md`](../../docs/ANTIGRAVITY-INTEGRATION.md)。
