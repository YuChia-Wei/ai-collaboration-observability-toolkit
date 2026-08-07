param(
    [ValidateSet("all", "core", "evaluation", "corporate")]
    [string]$Mode = "all",
    [switch]$StaticOnly
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { throw "Python 3 is required" }
$Arguments = @("$Root/scripts/toolkit.py", "validate", "--mode", $Mode)
if ($StaticOnly) { $Arguments += "--static-only" }
& $Python @Arguments
exit $LASTEXITCODE
