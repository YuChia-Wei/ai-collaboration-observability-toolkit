#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
args=("$@")
if [[ ${#args[@]} -eq 0 ]]; then
  args=(--mode core)
elif [[ "${args[0]}" != -* ]]; then
  args=(--mode "${args[0]}" "${args[@]:1}")
fi
exec python3 "$ROOT/scripts/toolkit.py" status "${args[@]}"
