# v0.2.0 container review — 2026-09-29

Goal: fit a memory-constrained 32 GB company workstation while retaining local
usage/log/trace analysis. Current-host observations are not company benchmarks.

## Inventory and decision

| Component | Previous | Selected | Decision |
| --- | --- | --- | --- |
| Collector Contrib | 0.158.0 | 0.158.0 | Keep validated OTTL baseline; latest 0.162.0 was released today and is a separate feature migration. Reduce corporate queues/memory instead. |
| Grafana | 13.1.3 | 13.1.7 | Same-minor security patch; no 13.2 feature migration. |
| Prometheus | 3.13.2 | 3.13.3 | Same-minor security/fix release, including TSDB compaction memory growth and shutdown CPU fixes. |
| Loki | 3.7.6 | 3.7.8 | Same-minor dependency security fixes; small corporate cache and bounded query concurrency. |
| Tempo | 3.0.2 | 3.0.3 | Same-minor security/fix release; preserve existing monolithic local-storage configuration. |
| Phoenix | 20.0.0 nonroot | Optional, unchanged | 20.16.0 is available; no company requirement justifies a database/API feature migration. Disabled by choosing Corporate. |
| PostgreSQL | 18.4 Alpine | 18.6-alpine3.24, optional | Same-major security patch; no company container. Official notes require reviewing logical-decoding, pgcrypto, and affected index cases before upgrading existing databases. |
| Source archive Python | 3.13.7 Alpine | Removed | Remove duplicate unbounded JSONL storage, Python service, initialization service, pipelines, CLI and dedicated code/tests. Preserve old volumes. |
| Source storage initializer | Grafana image | Removed | No source volume initialization is needed. |

No new exporter, cache, broker, or database is introduced. Core LGTM is retained
because Prometheus powers usage/accounting, Loki activity logs, and Tempo trace
correlation. Replacing the backend would introduce a different migration and
unmeasured tradeoffs rather than prove lower resource use.

## Observed baseline

Existing Evaluation stack, one idle-ish `docker stats --no-stream` sample:
Collector 129.9 MiB; source archive 46.31 MiB; Grafana 218.4 MiB; Prometheus
207.1 MiB; Loki 98.96 MiB; Tempo 551.5 MiB; PostgreSQL 160.9 MiB; Phoenix
410.8 MiB. Total approximately 1824 MiB. Removing the archive and optional
Phoenix/PostgreSQL removes services accounting for approximately 618 MiB in
this sample; this is not a measured before/after reduction under equal load.

Read-only `du -sk` found source archive 19,700,812 KiB (~18.79 GiB) and
Prometheus 1,902,072 KiB (~1.81 GiB). Loki/Tempo images lack `du`; their sizes
were unavailable in that check. Docker-wide disk usage includes unrelated
images/build caches and is not attributed to this toolkit. No pruning occurred.

Corporate memory caps total 1664 MiB, with 7-day/1GB Prometheus block retention,
72-hour Loki/Tempo retention, and rotated container logs. See
[company setup](COMPANY-LOW-RESOURCE.md) and [readiness](RELEASE-READINESS-v0.2.0.md)
for actual validation and residual limits.

## Official references reviewed

- [Grafana 13.1.7](https://github.com/grafana/grafana/releases/tag/v13.1.7)
- [Prometheus 3.13.3](https://github.com/prometheus/prometheus/releases/tag/v3.13.3)
- [Loki 3.7.8](https://github.com/grafana/loki/releases/tag/v3.7.8)
- [Tempo 3.0.3](https://github.com/grafana/tempo/releases/tag/v3.0.3)
- [Collector 0.162.0](https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.162.0)
- [Phoenix 20.16.0](https://github.com/Arize-ai/phoenix/releases/tag/arize-phoenix-v20.16.0)
- [PostgreSQL 18.6 migration notes](https://www.postgresql.org/docs/release/18.6/)
- [Official PostgreSQL image tags](https://github.com/docker-library/official-images/blob/master/library/postgres)
- [Prometheus storage limits](https://prometheus.io/docs/prometheus/latest/storage/)
- [Loki retention](https://grafana.com/docs/loki/latest/operations/storage/retention/)
- [Tempo query tuning](https://grafana.com/docs/tempo/latest/operations/backend_search/)
