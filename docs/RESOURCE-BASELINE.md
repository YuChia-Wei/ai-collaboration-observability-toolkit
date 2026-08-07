# Resource baseline procedure

No universal workstation resource claim is encoded as a requirement. Docker virtualization, CPU,
disk, retained data, and query activity materially change usage. Establish a baseline on every target
class instead.

## Capture protocol

For each mode:

1. Reset volumes or record current data size.
2. Start the stack and wait five minutes.
3. Capture `resource-snapshot` at idle.
4. Send the smoke fixture 100 times over a controlled interval.
5. Capture during ingestion and two minutes afterward.
6. Run representative Grafana queries.
7. Capture during query and after cache warm-up.
8. Record Docker/OS/version/storage conditions.

## Report fields

```text
mode
host CPU / RAM
Docker backend and allocated resources
component image versions
retained data size and age
container CPU percentage
container memory usage/limit
block IO
network IO
query/ingest scenario
timestamp and duration
```

## Decision guidance

- Core is the default for resource-constrained workstations.
- Evaluation can be started only while performing trace review/experiments.
- Corporate endpoints can run core storage locally, but a future metadata-only file/bundle mode may
  be preferable where Docker resources are constrained.
- Investigate sustained exporter queues, container restarts, swap pressure, or disk growth before
  tuning individual databases.

The initial repository validation environment had no Docker daemon, so it provides no credible
runtime resource baseline. See `docs/IMPLEMENTATION-REPORT.md` for validation status.
