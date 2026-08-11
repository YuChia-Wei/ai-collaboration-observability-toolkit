# Codex Hooks lifecycle trace 實驗

這個 opt-in 範例把 Codex lifecycle Hooks 轉成 metadata-only OTLP traces，送到既有
`127.0.0.1:4318` OpenTelemetry Collector。Evaluation mode 會將其中具
`openinference.span.kind` 的 spans 同時保留於 Tempo 與 Phoenix。

## 能觀察什麼

| Hook pair | OpenInference kind | 可讀資訊 |
| --- | --- | --- |
| `UserPromptSubmit` → `Stop` | `AGENT` | turn 期間、模型 slug、完成事件 |
| `PreToolUse` → `PostToolUse` | `TOOL` | 固定工具類別、期間、parent turn |

Exporter 不產生 `LLM` span，不輸出 token/cost，也不判斷 prompt effectiveness 或回答正確性。
Codex Hooks 沒有提供足以支持這些宣稱的 model-call 邊界與 usage 欄位。

## 隱私邊界

Exporter 不讀取或儲存 `prompt`、`last_assistant_message`、`tool_input`、
`tool_response`、`cwd` 或 `transcript_path`。原始 session、turn 與 tool IDs 只用於計算本機
state 路徑的 SHA-256，不會寫入 state 或 OTLP。輸出的 trace/span IDs 是新產生的隨機值。

工具名稱只被分類為 `execution`、`editor`、`connector`、`agent-collaboration` 或 `other`；
raw tool name 不會輸出。`PostToolUse` 沒有獨立的成功旗標，因此 span 僅標示
`completed`，不把完成誤報為成功。

## 安裝到此 Repository

先啟動 Evaluation mode：

```powershell
docker compose -f compose.yaml -f compose.evaluation.yaml up -d
```

用 installer 產生 project-local hook 設定：

```powershell
python examples\codex-hooks\install_hooks.py
```

Installer 會把目前 Python 與 exporter 的絕對路徑寫入 `.codex/hooks.json`，避免 Windows
巢狀 shell、引號、啟動目錄與 `python3` alias 問題。若目標檔已存在，它會拒絕覆寫；請先人工
合併或使用 `--print` 檢查輸出。`config/hooks.personal.json.example` 僅供檢查 schema 與手動設定。

重新開啟 Codex，使用 `/hooks` 檢查來源並信任 exact hook definition。Codex 會在 hook
command 或設定變更後要求重新檢查。不要同時在 user-level 與 project-level 安裝同一 exporter，
否則 lifecycle spans 會重複。

停用或 rollback：在 `/hooks` 停用，或移除自行產生的 `.codex/hooks.json`。Exporter failure
採 fail-open，不會改變 tool permission 或 Codex turn control flow。

## 乾跑

PowerShell 範例：

```powershell
$fixture = Get-Content -Raw examples\codex-hooks\fixtures\user-prompt-submit.json
$fixture | python examples\codex-hooks\codex_hooks_otel_exporter.py `
  --dry-run `
  --state-dir artifacts\codex-hooks-state `
  --capture-dir artifacts\codex-hooks-capture
```

完整隱私與 parent/child correlation 測試：

```powershell
python -m unittest tests.test_codex_hooks_exporter -v
```

## Phoenix routing

缺少 routing header 時，Evaluation Collector 預設轉送 compatible spans。加入
`--no-phoenix` 可明確退出；`--phoenix` 可明確送入。Core 與 Corporate 沒有 Phoenix
pipeline，因此旗標不能建立第二條 route。

## 覆蓋限制

Codex 官方文件指出 hosted tools 與部分 specialized tool paths 可能不經過 tool hooks。
因此這是 useful lifecycle trace，不是完整 enforcement 或 accounting boundary。使用量與 token/cost
仍以 Codex native telemetry、AI Agent 用量 dashboard 與可核對的 provider evidence 為準。

官方契約：[Codex Hooks](https://learn.chatgpt.com/codex/hooks)、
[OpenInference semantic conventions](https://arize-ai.github.io/openinference/spec/semantic_conventions.html)。
