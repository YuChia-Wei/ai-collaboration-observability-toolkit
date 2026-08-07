#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-core}"
if [[ "$mode" == -* ]]; then
  exec python3 "$ROOT/scripts/toolkit.py" reset "$@"
fi
shift || true
args=(--mode "$mode")
if [[ ${#@} -gt 0 && "${1:-}" != -* ]]; then
  args+=(--confirm "$1")
  shift
fi
exec python3 "$ROOT/scripts/toolkit.py" reset "${args[@]}" "$@"
