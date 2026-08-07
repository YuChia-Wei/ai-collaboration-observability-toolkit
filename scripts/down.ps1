param(
    [ValidateSet("core", "evaluation", "corporate")]
    [string]$Mode = "core"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { throw "Python 3 is required" }
& $Python "$Root/scripts/toolkit.py" down --mode $Mode
exit $LASTEXITCODE
