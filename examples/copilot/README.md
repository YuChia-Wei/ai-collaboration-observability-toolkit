# GitHub Copilot integration notes

GitHub Copilot surfaces do not all expose identical OpenTelemetry controls. Configure only a supported CLI or IDE integration and send OTLP to the local Collector. Keep content capture disabled.

Treat Copilot CLI, VS Code, and Rider/JetBrains as separate telemetry sources until their installed versions have been verified. Do not infer Rider support from a CLI or VS Code document.
