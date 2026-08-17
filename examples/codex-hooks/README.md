# Codex Hooks lifecycle trace 實驗

這個 opt-in 範例預設把 Codex lifecycle Hooks 轉成 metadata-only OTLP traces，送到既有
`127.0.0.1:4318` OpenTelemetry Collector。也可明確選擇 `size-only` 與個別 scope，
只輸出使用者 prompt 或 exact-allowlisted MCP response 的 UTF-8 byte 數值；不輸出內容。Evaluation mode 會將其中具
`openinference.span.kind` 的 spans 同時保留於 Tempo 與 Phoenix。

## 能觀察什麼

| Hook pair | OpenInference kind | 可讀資訊 |
| --- | --- | --- |
| `UserPromptSubmit` → `Stop` | `AGENT` | turn 期間、模型 slug、完成事件 |
| `PreToolUse` → `PostToolUse` | `TOOL` | 固定工具類別、期間、parent turn |
| `UserPromptSubmit`（僅 `size-only`） | Delta histogram | 使用者 prompt UTF-8 byte 長度、筆數與分布 |
| `PostToolUse`（`size-only` + MCP scope + exact allowlist） | Delta histogram | 指定 MCP response payload 的 UTF-8 byte 長度、筆數與分布 |

Exporter 不產生 `LLM` span，不輸出 token/cost，也不判斷 prompt effectiveness 或回答正確性。`size-only` 的 byte 長度不是 token、完整模型 context、載入檔案大小或帳務用量。
Codex Hooks 沒有提供足以支持這些宣稱的 model-call 邊界與 usage 欄位。

## 隱私邊界

預設 `metadata-only` 不讀取或儲存 `prompt`、`last_assistant_message`、`tool_input`、
`tool_response`、`cwd` 或 `transcript_path`。明確選擇 `size-only` 時，只有選取的 scope
會在記憶體中被讀取一次以計算 UTF-8 byte 長度；內容不會寫入 state、trace、metric attribute、capture
artifact、log 或 debug output，也不會雜湊後輸出。原始 session、turn 與 tool IDs 只用於計算本機 state
路徑的 SHA-256，不會寫入 state 或 OTLP。輸出的 trace/span IDs 是新產生的隨機值。

輸出的 opt-in metric 名稱為 `ai_agent.observed.user_prompt.bytes`；Prometheus 顯示為
`ai_agent_observed_user_prompt_bytes_sum` 與 `_count`。它只有固定維度：`operation=turn`、
`evidence_class=observed`、`content_scope=user_prompt`、`measurement_method=utf8_bytes`，以及既有受限 resource 維度。
Corporate mode 會在 hook 與 Collector 兩層停用並丟棄此 metric。

MCP response 的 scope 還需要 `--mcp-size-tool EXACT_MCP_TOOL_NAME=SAFE_LOGICAL_ID`。
Exporter 先做 exact match，匹配後才讀取 `tool_response`；metric 只輸出 safe logical ID，
不輸出 raw tool name。未匹配的 tool response 完全不讀取也不計量。Corporate mode 會丟棄
user-prompt 與 MCP-response 兩種 content-derived metrics。

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

## 選擇隱私模式

Installer 預設會把 `--capture-mode metadata-only` 寫進 hook command；這是完全不讀取 prompt 的模式。
若你要規劃每次提交的大小、且接受只保留數字而不保留內容，先用 `--print` 檢查，再在 project-local hook
設定中明確選擇：

```powershell
python examples\codex-hooks\install_hooks.py --capture-mode size-only --print
```

若只想量 Codebase Memory MCP 的特定工具回傳大小：

```powershell
python examples\codex-hooks\install_hooks.py `
  --capture-mode size-only `
  --size-scope mcp-tool-response `
  --mcp-size-tool mcp__codebase_memory_mcp__search_graph=codebase-memory.search `
  --print
```

可重複 `--size-scope` 同時選取 prompt 與 MCP response，也可重複
`--mcp-size-tool` 建立多個 exact allowlist entry。這個值只代表 Hook payload 的序列化
UTF-8 bytes，不是 provider token 或模型實際載入的 context。

把審閱後的 command 合併到你的 `.codex/hooks.json`，重新開啟 Codex 並在 `/hooks` 重新信任 exact definition。
要回到隱私預設，將 command 改回 `--capture-mode metadata-only`。不需要也不會修改 user-level
`%USERPROFILE%\.codex\config.toml`。Exporter 未收到 CLI mode 時，才會採用 `AI_OBSERVABILITY_CAPTURE_MODE`；無效值一律 fail-safe 回到 `metadata-only`。

Grafana 的「AI Agent 用量」>「Extension 觀測快照」會顯示 prompt byte 指標；
「Claude / Codex Context 歸因」會顯示 allowlisted MCP response 的 byte 總量與筆數。使用
`sum(increase(ai_agent_observed_user_prompt_bytes_sum{ai_agent_product="codex"}[$__range]))` 做選定時間範圍查詢；不要把它與 provider-reported token 逐筆相除或當作 billing。

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
