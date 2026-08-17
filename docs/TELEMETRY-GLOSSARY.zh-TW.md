# Telemetry 詞彙表（zh-TW）

這份詞彙表提供人類閱讀用的中文解釋。Canonical attribute、metric、span name
和 query identifier 必須維持英文原值；不要在 producer、Collector 或 dashboard
query 中把它們翻譯成中文。

## 三層證據

| Canonical 名稱 | 中文說明 | 可以支持的判讀 | 不可直接推論 |
| --- | --- | --- | --- |
| Provider native | AI 工具原生 telemetry，例如 `codex.*`、`antigravity_*` | 特定工具的操作、duration、token 或 lifecycle evidence | 跨工具語意一致、framework 效果 |
| `ai_agent.*` | 跨 provider 的受限 canonical 用量契約 | provider/product/model family、bounded tool category、觀測用量 | task 成功、答案品質、費用 |
| `ai_context.*` | Framework workflow 與 context evidence | rule/skill/context 載入、validation、wait、retry、明確 outcome | 沒有上游 instrumentation 時不得由 provider span 補猜 |

## Trace 與 OpenTelemetry

| Identifier / term | 穩定中文解釋 |
| --- | --- |
| `service.name` | 送出 telemetry 的服務名稱；不是使用者身份 |
| `openinference.project.name` | Phoenix Project 分組名稱 |
| `openinference.span.kind` | OpenInference span 類別，例如 CHAIN、AGENT、TOOL、LLM |
| Trace ID | 同一條端到端 trace 的識別值；高 cardinality，不得放入 Prometheus/Loki index label |
| Span ID | 一個 span 的識別值；用於 parent/child 關係 |
| Root span | 沒有 parent span 的起點；不一定等於完整人類 task |
| Parent / child | 操作巢狀關係；child 可能重疊，不可直接將 duration 全部相加 |
| Waterfall | 依時間排列 spans 的視圖，用於找 critical path、重疊與空白區段 |
| `OK` | Producer 明確標記該 span 操作成功，不代表答案正確 |
| `ERROR` | Producer 明確標記操作錯誤，仍需其他 evidence 說明原因 |
| `UNSET` | Producer 未設定 status；不是成功或失敗結論 |
| `UNKNOWN` | 現有 metadata 無法分類；代表證據不足 |
| Attributes | Span 上的 key-value metadata；本工具包只保留隱私政策允許內容 |
| Events | Span 期間的結構化事件；敏感 event body 應被移除 |

## 常見 Codex 原生 Span 名稱

| Span name | 中文閱讀提示 |
| --- | --- |
| `handle_responses` | 處理 Responses API 資料；重複出現不必然是 retry |
| `receiving` | 等待或接收資料的內部階段；長時間不自動等於網路故障 |
| `append_items` | 將項目加入內部流程；不代表人類已看到答案 |
| `persist_rollout_items` | 保存 rollout metadata 的內部操作；不代表 Git commit 或 release 已完成 |

## AI Agent canonical identifiers

| Identifier | 中文說明 |
| --- | --- |
| `ai_agent.provider` | Provider 類別，例如 OpenAI；必須是 bounded value |
| `ai_agent.product` | 工具產品，例如 Codex；不是 project 名稱 |
| `agent_role` | 執行角色：primary、approval_reviewer、subagent 或 unknown；不是模型名稱 |
| `model_id` | 可供 rate-card join 的 exact model；不可得時為 unmapped |
| `model_family` | 受限模型家族，不應包含 request/session ID |
| `token_type` | input、output、cached 等 token 類型 |
| `usage_class` | Accounting 使用的互不重疊 token 類別；不可和 raw input 重複相加 |
| `tool_category` | 去除原始工具名稱後的 bounded category |
| `evidence_class` | 說明資料是 provider-reported、observed extension 或其他核准證據類別 |
| `content_scope` | 僅用於明確核准的本機量測範圍；Codex size-only 固定為 `user_prompt`，不含內容或 ID |
| `measurement_method` | 本機量測方法；Codex size-only 固定為 `utf8_bytes`，不是 tokenizer 或 provider 計價方法 |
| `ai_agent_turn_duration_ms` | Canonical 回合 duration histogram；不是 task 完成時間 |
| `ai_agent_tool_call` | Canonical 工具呼叫 counter；不含原始參數或結果 |
| `ai_agent_observed_context_used_ratio` | Extension 觀測到的 context 使用率；不是 provider 帳單 |
| `ai_agent_observed_quota_remaining_ratio` | Extension 觀測到的 quota；不是權威餘額 |
| `ai_agent_observed_user_prompt_bytes_sum` / `_count` | 使用者明確選擇 Codex Hook size-only 後的提交 prompt UTF-8 byte 量測；不含內容、不是完整 context、token 或帳單 |
| `ai_agent_estimated_cost_usd_total` | 公開 API USD 牌價估算；不是帳單或訂閱扣款 |
| `ai_agent_estimated_credit_usage_total` | 公開 Codex credits rate-card 等值估算；不是官方剩餘額度 |
| `ai_agent_unpriced_credit_token_usage_total` | 沒有公開 Codex credits rate 的 token；未知不等於免費 |

## AI Context identifiers

| Identifier | 中文說明 |
| --- | --- |
| `framework_version` | 產生 evidence 的 framework 版本 |
| `task_type` | Bounded task 類別，不得使用 task UUID |
| `stage` | Workflow 階段 |
| `outcome` | 上游明確記錄的結果；blocked/skipped 不得改寫成 success |
| `reason` | Wait/retry 的 bounded 原因 |
| `tier` | Validation 層級，例如 static、native、runtime |
| `reused` | Validation evidence 是否重用；不等同驗證仍然有效 |
| `state` | Rule lifecycle 狀態，例如 loaded/applied；loaded 不代表 effective |
| `ai_context.workflow.duration` | Framework workflow duration evidence |
| `ai_context.wait.duration` | 有明確 wait attribution 的 duration evidence |
| `ai_context.validation.runs` | Validation run evidence；必須保留真實 outcome |
| `ai_context.validation.duplicate` | Framework 明確判定的重複 validation evidence |
| `ai_context.retry` | Framework 明確記錄的 retry；不要由同名 provider spans 猜測 |
| `ai_context.task.outcome` | 明確 task outcome evidence；仍需與驗收或 CI 對照 |

## Dashboard 常見統計詞

| Term | 中文說明 |
| --- | --- |
| P95 | 第 95 百分位；95% 觀測值小於或等於此值 |
| Counter | 單調遞增計數，通常以 `increase()` 或 `rate()` 查詢 |
| Gauge | 某一時間點可上可下的觀測值 |
| Histogram | 以 buckets、count、sum 表示的分布；不能當作一般 counter 解讀 |
| Rate | 每秒變化率，受查詢時間範圍與 scrape interval 影響 |
| RSS | 程序目前占用的實體記憶體 |
| TTFT | Time to first token，從開始到首個 token 的等待時間 |

完整判讀步驟請參閱
[Phoenix Trace 閱讀指南](PHOENIX-READING-GUIDE.zh-TW.md)。
