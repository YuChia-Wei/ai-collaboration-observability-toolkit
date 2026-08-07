# Security policy

This project handles telemetry that may describe developer activity. Treat telemetry schemas, Collector processors, retention settings, and dashboard access as security-sensitive changes.

Do not include real credentials or proprietary telemetry in issues, fixtures, screenshots, or commits. The supplied fixtures use synthetic identifiers and the sentinel `AI_OBSERVABILITY_SECRET_SENTINEL_7F3B9D` solely to test redaction.

Report a suspected data leak privately to the repository owner. Include the affected mode, Collector configuration revision, signal type, and a synthetic reproduction. Do not attach the original prompt, code, path, token, or tool output.
