param(
    [ValidateSet("core", "evaluation", "corporate")]
    [string]$Mode = "core",
    [switch]$PersistenceCheck,
    [switch]$SkipPersistence,
    [string]$Report
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { throw "Python 3 is required" }
if ($PersistenceCheck -and $SkipPersistence) { throw "PersistenceCheck and SkipPersistence are mutually exclusive" }
$Arguments = @("$Root/scripts/toolkit.py", "smoke", "--mode", $Mode)
if ($PersistenceCheck) { $Arguments += "--persistence-check" }
if ($SkipPersistence) { $Arguments += "--skip-persistence" }
if ($Report) { $Arguments += @("--report", $Report) }
& $Python @Arguments
exit $LASTEXITCODE
