# Antigravity 委派起始訊息

建議模型：**Gemini 3.6 Flash（High）**

請完整閱讀 repository 內的 `docs/IMPLEMENTATION-BRIEF.md`，並將它視為本次工作的權威規格。

你的工作是直接建立 `ai-collaboration-observability-toolkit`：

1. 先檢查目前 repository 狀態。
2. 查閱各元件最新官方 stable release，建立 dependency matrix，所有 Docker image 使用明確版本，禁止 `latest`。
3. 先產生可追蹤實作計畫，再直接執行，不必針對文件已決定的架構重新詢問。
4. 完成：
   - Core：OpenTelemetry Collector + Prometheus + Loki + Tempo + Grafana。
   - Corporate：嚴格 metadata-only 去機敏設定，不啟動 Phoenix、不對外 export。
   - Evaluation：Core + Phoenix + PostgreSQL；只有明確選取的 curated traces 進 Phoenix。
5. 建立 PowerShell 與 Bash 啟停、驗證、smoke test、resource snapshot、reset scripts。
6. 建立 Grafana provisioning、dashboards、Codex `config.toml` 範例與完整臺灣繁體中文文件。
7. 實際執行可執行的驗證；敏感 sentinel 必須證明未出現在 Loki、Tempo、Phoenix。
8. 將實際版本、測試結果、manual／skip、規格偏差與已知風險寫入 `docs/IMPLEMENTATION-REPORT.md`。

限制：

- 不加入 ClickHouse、SigNoz、OpenObserve、ELK、Kubernetes 或自訂 Web UI。
- 不收集 raw prompt、response、tool output、code、diff、absolute path、email、account ID 或 secrets。
- 不把估算 token／cost 宣稱為 ChatGPT Enterprise 官方 credit。
- 不把未測試或跳過的項目寫成通過。
- 不建立或推送遠端 repository、branch、PR、tag 或 Release。
- 不覆寫已存在的使用者 Codex 設定；只提供可合併的 `[otel]` 範例。
