param(
    [ValidateSet("core", "evaluation", "corporate")]
    [string]$Mode = "core",
    [string]$Output
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { throw "Python 3 is required" }
$Arguments = @("$Root/scripts/toolkit.py", "snapshot", "--mode", $Mode)
if ($Output) { $Arguments += @("--output", $Output) }
& $Python @Arguments
exit $LASTEXITCODE
