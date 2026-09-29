# 公司 32 GB 工作站：低資源模式

使用 Corporate 模式，維持 Collector + Grafana + Prometheus + Loki + Tempo
五個服務。Phoenix/PostgreSQL 只在 Evaluation 出現；所有模式都移除 source
archive 與初始化容器。仍可分析 AI 工具用量、metadata logs、trace 與 Collector
健康狀態。這不會自動監看整台 Windows 或所有公司應用；應用需自行送出核准的
OTLP metadata，Corporate exact allowlist 也可能移除未核准的應用欄位。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 設定本機密碼後啟動；已有 .env 時請合併設定，不要覆寫。
docker compose -f compose.yaml -f compose.corporate.yaml up -d
python scripts/toolkit.py wait --mode corporate
python scripts/toolkit.py smoke --mode corporate
```

## 資源預算

| 元件 | memory limit | Go soft limit | CPU limit |
| --- | --- | --- | --- |
| Collector | 256 MiB | 192 MiB | 1 |
| Prometheus | 384 MiB | 288 MiB | 1 |
| Loki | 256 MiB | 192 MiB | 1 |
| Tempo | 512 MiB | 384 MiB | 1 |
| Grafana | 256 MiB | 192 MiB | 1 |

容器 memory limits 合計 1664 MiB（1.625 GiB），不是實測常態用量，也不包含
Docker Desktop/WSL VM、檔案 cache 與宿主開銷。容器 swap 額度設為與 memory
相同，避免這些服務額外借用 swap。超出預算可能拒收、逾時或 OOM；不要把限制
當成吞吐保證。公司實際工作負載仍需觀察 dropped/refused spans、重啟與查詢延遲。

Prometheus scrape/rule interval 為 30 秒，查詢並行度 2、最多 5M samples。
Loki cache 16 MiB、查詢並行度 2；Tempo 查詢並行度 2。Grafana unified alerting
停用，面板與資料來源查詢保留。較長時間範圍的查詢可能比一般模式慢。

## 磁碟保存範圍

- Prometheus：7 天或 1 GB block retention，先達者先清理。WAL/head 與暫存仍占空間，
  1 GB 不是 volume 的硬上限。
- Loki／Tempo：72 小時；刪除由非同步 retention/compaction 執行，並非硬容量配額。
- Docker container logs：每服務 3 × 10 MB；Grafana DB 仍需監看。
- 不再另存 OTLP JSONL source archive。未知且未被 analytical mapping 保留的欄位
  無法事後重建；這是降低磁碟需求的明確取捨。

在公司使用新 Compose project 可避免與個人資料混用。不要將既有個人 deployment
直接切成短 retention 而未備份：套用短 retention 會正常淘汰較舊資料。

## 現有 deployment 升級

備份設定與需保留的 volumes，在維護時段停止舊 project，再以選定模式啟動。
`python scripts/toolkit.py down --mode evaluation` 保留 volumes；之後
`python scripts/toolkit.py up --mode corporate` 會移除 orphan containers，但不刪
volumes。這會停止 Phoenix/PostgreSQL 與舊 archive。既有 `collector-source-data`
仍占空間，需另外核對 project/volume、export 需求後才刪除；本次不自動清掉。

Phoenix 的用途是已有 OpenInference 語意的 trace 人工評註、dataset/evaluator/
experiment 管理；一般用量、費用與工具活動主要在 Grafana。沒有這些 evaluation
需求時，公司關閉 Phoenix 合理，且同步省下 PostgreSQL。
