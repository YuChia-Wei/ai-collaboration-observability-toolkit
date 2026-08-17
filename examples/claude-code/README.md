# Claude Code 原生 OpenTelemetry

這個範例直接使用 Claude Code 原生 OpenTelemetry，不要求
`ai-collaboration-framework` 加入 prompt、emitter 或 ADK runtime。Collector 會把
`claude_code.token.usage` 保留為 provider-native metric，並另製作
`ai_agent.request.token_usage.total` canonical copy。

## 安裝

先審閱 `settings.local.json.example`，再把 `env` 合併到目標 repository 的
`.claude/settings.local.json`。不要直接覆蓋既有設定。啟動 Core 或 Evaluation mode 後，
重新啟動 Claude Code，讓新的環境變數生效。

範例只啟用 metrics，並明確關閉 prompt、assistant response、tool details 與 tool content
logging。OTLP 只送到既有 loopback Collector；不建立第二個 host-facing endpoint。

## 可以回答到什麼程度

Claude 原生 token metric 的 `type` 會正規化為 `input`、`cached_input`、
`cache_write_input`、`output`。`query_source` 會正規化為 primary/subagent，Core 與
Evaluation 會保留 provider 回報的 `skill.name`、`mcp_server.name`、`mcp_tool.name`
作為個人本機分析維度。Claude 對 user-configured MCP server/tool 預設以 `custom`
取代實際名稱，因此沒有開啟詳細 tool logging 時，MCP 歸因通常只能到 `custom`。

這些資料可用來做受控 before/after 比較，例如拆 skill 前後的 request token 差異，
或啟用 Codebase Memory MCP 前後的 token/compaction 趨勢。它不能單獨證明某個 prompt
規則或治理文件真的被載入、遵循或造成 token 差異。Corporate mode 會移除 skill/MCP
歸因，並且不應啟用任何 content/detail logging。

MCP attribution 的 request-consumption 行為需要 Claude Code v2.1.222 或更新版本；較舊
版本會把 MCP call 之後的後續 requests 一併標記，升級前後的數據不可直接混合比較。

官方契約：[Claude Code monitoring and OpenTelemetry](https://code.claude.com/docs/en/monitoring-usage)。
