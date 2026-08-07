param(
    [ValidateSet("core", "evaluation", "corporate")]
    [string]$Mode = "core",
    [string]$Confirm
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { throw "Python 3 is required" }
$Arguments = @("$Root/scripts/toolkit.py", "reset", "--mode", $Mode)
if ($Confirm) { $Arguments += @("--confirm", $Confirm) }
& $Python @Arguments
exit $LASTEXITCODE
