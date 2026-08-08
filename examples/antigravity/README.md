# Google Antigravity 可觀測性範例

本範例使用 Google Antigravity 的文件化 **Hooks** 與 **Antigravity CLI custom status line**，將
生命週期與用量中繼資料轉成 OTLP/HTTP，送到本機 OpenTelemetry Collector（OTel Collector）。

目前不假設 Antigravity 提供可由使用者直接指定的原生 OTLP endpoint；產品設定中的
`Enable Telemetry` 不等同於送到你的 `127.0.0.1:4318`。

## 提供的資料面

| 來源 | 訊號 | 主要資料 |
| --- | --- | --- |
| `PreInvocation`／`PostInvocation` | logs、traces | invocation、model、期間、完成狀態 |
| `PostToolUse` | logs | 低基數工具類別、step index、成功／失敗 |
| `Stop` | logs、traces | execution 期間、停止原因、idle 狀態 |
| CLI status line | logs、metrics | token、context、quota、task、artifact、等待輸入與核准狀態 |

Status-line token 與 quota 是當下觀測值，不是 Google 或公司正式 credit／帳務資料。

## 隱私原則

Exporter 不讀取或輸出 prompt、response、transcript、artifact／程式碼內容、workspace path、branch、
email、`toolCall`、tool arguments/results、raw error 或 raw conversation ID。

`PostToolUse` matcher 只傳入五種低基數類別：

```text
file-operation
search-operation
execution-operation
agent-collaboration
interaction-operation
```

個人模式可輸出本機 HMAC session pseudonym；公司模式停用 session 識別，Corporate Collector
profile 會再做一次 allowlist 過濾。

本範例刻意不設定 `PreToolUse`，因為被動觀測不應參與工具權限決策。Repository 只提供一條 direct
Hooks 路徑；不要再安裝執行相同 exporter 的第二套 plugin，否則會重複上報 lifecycle 事件。

## 1. 啟動 Collector

在工具包 Repository 根目錄：

```bash
cp .env.example .env
# 修改 .env 內的範例密碼
docker compose up -d
```

Exporter 預設送往：

```text
http://127.0.0.1:4318/v1/logs
http://127.0.0.1:4318/v1/metrics
http://127.0.0.1:4318/v1/traces
```

## 2. 專案層 Hooks：POSIX／WSL

在要觀察的 Antigravity workspace 根目錄：

```bash
mkdir -p .agents/observability
cp /path/to/toolkit/examples/antigravity/antigravity_otel_exporter.py \
  .agents/observability/
cp /path/to/toolkit/examples/antigravity/config/hooks.personal.posix.json.example \
  .agents/hooks.json
chmod +x .agents/observability/antigravity_otel_exporter.py
```

公司模式改用 `hooks.corporate.posix.json.example`。

## 3. 專案層 Hooks：Windows PowerShell

```powershell
New-Item -ItemType Directory -Force .agents\observability | Out-Null
Copy-Item C:\path\to\toolkit\examples\antigravity\antigravity_otel_exporter.py `
  .agents\observability\
Copy-Item C:\path\to\toolkit\examples\antigravity\config\hooks.personal.windows.json.example `
  .agents\hooks.json
```

公司模式改用 `hooks.corporate.windows.json.example`。若 `python` 不是正確 interpreter，請將
`.agents/hooks.json` 中的 command 改成 `py -3` 或完整路徑。

Antigravity 也支援使用者層 `~/.gemini/config/hooks.json`。此時應使用 exporter 絕對路徑，並避免
同一組 Hooks 同時在 workspace 與使用者層啟用。

## 4. CLI status line

Antigravity CLI 設定檔：

```text
~/.gemini/antigravity-cli/settings.json
```

將符合 OS 與 profile 的 `settings.statusline.*.json.fragment.example` 合併到現有 JSON，並把 exporter
placeholder 改成絕對路徑。例如 POSIX 個人模式：

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 /absolute/path/to/antigravity_otel_exporter.py statusline --profile personal-local --product antigravity"
  }
}
```

修改後重新啟動 Antigravity CLI。Status line 可與 direct lifecycle Hooks 同時使用，因為兩者負責不同
資料面。

## 5. Evaluation mode 的 Phoenix opt-in

要將已去機敏 lifecycle trace 送往 Phoenix，在個人 Hooks command 加上：

```text
--phoenix
```

只有 Evaluation mode 具備 Phoenix exporter；公司 profile 不應加入此旗標。

## 6. 乾跑與隱私測試

```bash
rm -rf artifacts/antigravity-example artifacts/antigravity-state
python3 examples/antigravity/antigravity_otel_exporter.py statusline \
  --profile personal-local \
  --product antigravity \
  --dry-run \
  --capture-dir artifacts/antigravity-example \
  --state-dir artifacts/antigravity-state \
  < examples/antigravity/fixtures/statusline.json

python3 -m unittest tests.test_antigravity_example -v
```

測試 fixture 內含假的 email、workspace、branch、command、tool arguments、raw error、conversation ID
與 sentinel；任一值出現在送出的 OTLP payload 都會使測試失敗。

## 選用環境變數

| 變數 | 預設值 | 用途 |
| --- | --- | --- |
| `AI_OBSERVABILITY_OTLP_HTTP_ENDPOINT` | `http://127.0.0.1:4318` | Collector base endpoint |
| `AI_OBSERVABILITY_SESSION_SALT` | 空值 | 選用 HMAC key；否則建立使用者本機 key |
| `AI_OBSERVABILITY_STATE_DIR` | 使用者本機 cache/state | dedup／timing 與 HMAC key，不保存內容 |
| `AI_OBSERVABILITY_HTTP_TIMEOUT_SECONDS` | `0.35` | 本機 OTLP timeout；失敗不阻塞 Antigravity |
| `AI_OBSERVABILITY_STATUS_HEARTBEAT_SECONDS` | `60` | 未變更 status 的重新上報間隔 |
| `AI_OBSERVABILITY_PHOENIX` | `false` | 明確啟用 Phoenix trace route |
| `AI_OBSERVABILITY_DEBUG` | `false` | 只輸出錯誤類型，不輸出 payload |

## 限制

- 不攔截模型 API、不讀 transcript，因此不能重建每個 request 的完整 prompt composition。
- Hooks 與 status line 是獨立 callback；公司 no-session 模式只能做彙總分析。
- Antigravity 更新後，Hook matcher 與 payload schema 可能改變，必須重新核對官方文件與測試。
- Exporter 對 Antigravity execution 採 fail-open；Collector 隱私處理仍採 fail-closed。

完整欄位政策與設計理由請見 [`../../docs/ANTIGRAVITY-INTEGRATION.md`](../../docs/ANTIGRAVITY-INTEGRATION.md)。
