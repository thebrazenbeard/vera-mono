[CmdletBinding()]
param(
    [switch]$Refresh,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ConsoleArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$VenvRoot = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$VeraExe = Join-Path $VenvRoot "Scripts\vera-mono.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating local Vera Mono environment at $VenvRoot"

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        & $py.Source -3.12 -m venv $VenvRoot
    }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) {
            throw "Python 3.12+ is required. Install Python, then run .\vera.ps1 again."
        }
        & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)"
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.12+ is required."
        }
        & $python.Source -m venv $VenvRoot
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the local Vera Mono virtual environment."
    }
}

if ($Refresh -or -not (Test-Path $VeraExe)) {
    Write-Host "Binding the local checkout into the Vera Mono environment"
    & $VenvPython -m pip install -e $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install the local Vera Mono checkout."
    }
}

if (-not (Test-Path $VeraExe)) {
    throw "The Vera Mono console executable was not created at $VeraExe."
}

& $VeraExe shell @ConsoleArgs
exit $LASTEXITCODE
