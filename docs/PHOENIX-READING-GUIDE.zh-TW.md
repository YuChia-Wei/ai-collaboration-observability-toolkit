# Phoenix Trace 閱讀指南（zh-TW）

這份指南說明如何閱讀本工具包送進 Phoenix 的隱私安全 trace。Phoenix
用於逐筆檢視執行路徑與人工評註；Grafana 用於趨勢、用量和系統健康；Tempo
則保留目前 mode 中較完整的最小化 trace 歷史。三者回答的問題不同。

## 先知道哪些事不能從畫面推論

本工具包預設移除 prompt、assistant response、工具參數／結果、command output、
source code、diff、credential、電子郵件、帳號識別資訊和絕對路徑。因此目前的
Phoenix trace 可以支持「發生哪些操作、花多久、是否重複、是否有錯誤狀態」等
操作層判讀，但不能單獨證明：

- 回答在語意上正確、完整或符合需求；
- task 已成功完成或驗收已通過；
- 某個 rule、skill 或 context 確實造成行為改變；
- token、request 或 duration 對應多少費用；
- span 之間只有時間先後就具有因果關係。

`UNSET` 通常表示 producer 沒有設定 status；`UNKNOWN` 通常表示 UI 或 backend
無法從現有 metadata 判定分類。兩者都不等同成功，也不等同失敗。

## 核心名詞

| Phoenix 名詞 | 中文理解 | 本工具包的判讀界線 |
| --- | --- | --- |
| Project | 將相關 traces 分組的容器 | 可用來隔離應用、環境與 synthetic fixture，但不是權限邊界 |
| Trace | 一次端到端執行路徑，由一個或多個 spans 組成 | 低階 Codex trace 不必然等於一個完整使用者 task |
| Span | 一段有起訖時間的操作單位 | 名稱描述操作，不自動代表 outcome 或答案品質 |
| Waterfall | 依開始時間與 duration 排列 spans 的瀑布圖 | 用來找 critical path、重疊、重複與空白區段 |
| Parent / Child | 父操作與其子操作的巢狀關係 | Child duration 可能互相重疊，不能直接全部相加 |
| Duration | span 從開始到結束的時間 | 長 duration 只表示慢，不提供原因或責任歸屬 |
| Status | producer 設定的 `OK`、`ERROR` 或未設定狀態 | `UNSET` 不是通過；`ERROR` 仍需搭配 attributes/events 判讀 |
| Attributes | span 的 key-value metadata | 只讀取隱私政策允許留下的 bounded metadata |
| Events | span 期間發生的結構化事件 | 不應期待看到已被移除的 exception body 或工具輸出 |
| Annotations | 人工、code 或 LLM 加上的 label、score、reason | 是後加判斷，不是原始執行事實 |
| Dataset | 為重複比較整理的一組 examples | v0.1.5 只提供案例候選標記，不建立 v0.2 evaluator dataset |
| Experiment | 用相同 inputs 與評估準則比較不同版本 | 必須控制 task、版本、環境與 evaluator，不能只比較兩筆任意 traces |

Canonical identifier 與中英對照請參閱
[Telemetry 詞彙表](TELEMETRY-GLOSSARY.zh-TW.md)。

## 建議閱讀順序

1. 先選對 Project 和時間範圍。若只想看真實資料，避開
   `ai-collaboration-observability-fixture`。
2. 在 trace table 先比較 start time、root span、duration、status 與 span count。
3. 打開一筆 trace，先找 root span，再沿 Waterfall 由左到右查看最長路徑。
4. 展開最長或重複的 spans，查看 parent/child、attributes、events 與 status。
5. 把觀察寫成「看見的證據」和「人工推論」兩段，不把兩者混寫。
6. 若需保留，使用本指南的中文 annotation rubric；若證據不足就明確標記。

`handle_responses`、`receiving`、`append_items`、`persist_rollout_items` 等名稱是
Codex 內部操作名稱。它們可以指出時間與重複模式，但不代表回答已正確、資料已
被人類看見，或 task 已完成。

## 四種診斷情境

### 1. 回合很慢

1. 從 root span 的 duration 確認整體確實偏慢。
2. 沿 Waterfall 找最長的 child span 或沒有 child span 解釋的長區段。
3. 比較 inference、Responses API、receiving、tool/MCP 等可見階段。
4. 確認 spans 是否重疊；重疊時間不可重複加總。
5. 只能把最大 duration span 記成「主要時間所在」，除非有額外 evidence，否則
   不寫成 root cause。

### 2. 重複工具或 response handling

1. 找同名、同 parent 的 siblings，依開始時間排列。
2. 比較 attributes 中可公開的 tool category、status 和 duration。
3. 區分 parallel calls、framework retry 與 UI 顯示重複；只有名稱相同不代表 retry。
4. 若有 `ai_context.retry.*` 或明確 retry event 才能聲稱 framework retry；否則標記
   「疑似重複，原因待確認」。

### 3. 環境或工具失敗

1. 先找 `ERROR` status、error 類型 event，或 success=false 等 bounded attribute。
2. 往上查看 parent 是否繼續執行、重試或提前結束。
3. 不要期待 raw command output、tool result、path 或 secret 出現在 trace；它們應已移除。
4. 用 repository validation、terminal evidence 或 Issue/CI 結果補足；Phoenix 不是唯一
   執行證據來源。

### 4. 長時間等待

1. 找 duration 很長的 wait/receiving span，或 Waterfall 中沒有 child span 的空白區段。
2. 只有 `ai_context.wait.*` 有 reason/owner 時，才能說明等待歸因。
3. 沒有 span 的區段可能是等待、client-side 工作、缺少 instrumentation 或 clock
   邊界；不可直接命名原因。
4. 若 span status 是 `UNSET`，仍只表示沒有 status evidence。

## 執行證據與答案品質證據

| 問題 | 目前 trace 能否回答 | 需要的補充證據 |
| --- | --- | --- |
| 哪個操作最久？ | 通常可以 | 正確 parent/child 與時間範圍 |
| 是否出現工具錯誤？ | 有 bounded status/event 時可以 | 工具或 terminal 的去識別驗證紀錄 |
| task 是否完成？ | 低階 provider trace 通常不行 | 明確 `ai_context.task.outcome`、測試、CI 或 Owner 驗收 |
| 回答是否正確？ | 不行 | 人工 review、ground truth、deterministic evaluator 或受控 experiment |
| 某個 context 是否有效？ | 不行 | 版本化 framework evidence 與可重複 experiment |

## Synthetic smoke traces

Runtime smoke 使用固定 trace ID 和固定 Project，以便重跑 positive/negative assertions：

| Trace ID 縮寫 | 用途 | Phoenix 預期 |
| --- | --- | --- |
| `2222…2222` | legacy resource `true` | 有 |
| `3333…3333` | legacy resource `false` | 無 |
| `5555…5555` | header 缺少、default-on | 有 |
| `6666…6666` | header `true` | 有 |
| `8888…8888` | header `false` | 無 |
| `1111…1111` | Core 一般 fixture | 不屬於 Phoenix routing positive case |

這些 fixtures 的 Project 是 `ai-collaboration-observability-fixture`，並使用
`openinference.span.kind=CHAIN`。辨識真實與 fixture 的安全做法是依 Project 加上
固定 trace IDs 過濾，而不是刪除 PostgreSQL 歷史資料。若舊版錯誤設定曾把 negative
fixture 存入 Phoenix，保留它作為歷史 evidence，並以新的 smoke 時間窗判讀。

## 中文 Annotation Rubric

本工具包提供五個 annotation configurations：

- `執行結果`：成功、部分完成、受阻、失敗；
- `問題類型`：無明顯問題、工具失敗、環境問題、等待過久、重複工作、證據不足、其他；
- `是否值得保留為案例`：是、否、待確認；
- `人工判斷原因`：去識別的 freeform reason；
- `後續處置`：無需處理、追蹤觀察、建立 Issue、候選資料集、升級討論。

先以唯讀模式檢查，再明確套用到一個既有 Project：

```powershell
python scripts/toolkit.py phoenix-annotations --project "<project-name>"
python scripts/toolkit.py phoenix-annotations --project "<project-name>" --apply
```

`--apply` 只會以 Phoenix 版本化 REST API 建立／更新這五個 configs，並以 idempotent
assignment 加到指定 Project；不會刪除 annotations、traces、projects 或 owner data。
人工 reason 不可貼入原始 prompt、response、程式碼、路徑、工具輸出或身份資訊。

## 後續 v0.2 邊界

v0.1.5 的 rubric 是人類閱讀與案例整理基線。Dataset 建立、evaluator、LLM-as-a-judge、
semantic span normalization 和受控 experiments 屬於 v0.2 規劃，不應從本指南自動啟用。

## 上游參考

- [Phoenix tracing concepts](https://arize.com/docs/phoenix/tracing/concepts-tracing/what-are-traces)
- [Phoenix UI annotations](https://arize.com/docs/phoenix/tracing/how-to-tracing/feedback-and-annotations/annotating-in-the-ui)
- [Phoenix annotation config REST API](https://arize.com/docs/phoenix/sdk-api-reference/rest-api/api-reference/annotation-configs/create-an-annotation-configuration)

