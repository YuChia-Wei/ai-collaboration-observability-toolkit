# Gemini implementation guidance

Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/PRIVACY.md`, and `docs/IMPLEMENTATION-BRIEF.md` before modifying this repository.

Keep changes narrow and evidence-backed. Preserve one host-facing Collector, pinned images, low-cardinality metrics labels, native Loki OTLP ingestion, and explicit Phoenix selection. Corporate mode must remain stricter than personal mode and must not add an external exporter.

Before finishing, run the validation commands in `AGENTS.md`, inspect the merged Compose configuration for every affected mode, and write unresolved runtime or compatibility questions into `docs/IMPLEMENTATION-REPORT.md` rather than guessing.
