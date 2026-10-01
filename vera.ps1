[CmdletBinding()]
param(
    [switch]$Refresh,

    [string]$StateRoot,

    [string]$ProjectId,

    [string]$IdentityId,

    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$ConsoleArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$VenvRoot = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$VeraExe = Join-Path $VenvRoot "Scripts\vera-mono.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating local Vera Mono environment at $VenvRoot"

    $python = Get-Command python -ErrorAction SilentlyContinue
    $pythonUsable = $false
    if ($null -ne $python) {
        & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)"
        $pythonUsable = ($LASTEXITCODE -eq 0)
    }

    if ($pythonUsable) {
        & $python.Source -m venv $VenvRoot
    }
    else {
        $py = Get-Command py -ErrorAction SilentlyContinue
        if ($null -eq $py) {
            throw "Python 3.12+ is required. Install Python, then run .\vera.ps1 again."
        }
        & $py.Source -3.12 -m venv $VenvRoot
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

$ForwardArgs = @()
if ($PSBoundParameters.ContainsKey("StateRoot")) {
    $ForwardArgs += "--state-root"
    $ForwardArgs += $StateRoot
}
if ($PSBoundParameters.ContainsKey("ProjectId")) {
    $ForwardArgs += "--project-id"
    $ForwardArgs += $ProjectId
}
if ($PSBoundParameters.ContainsKey("IdentityId")) {
    $ForwardArgs += "--identity-id"
    $ForwardArgs += $IdentityId
}
if ($null -ne $ConsoleArgs) {
    $ForwardArgs += $ConsoleArgs
}

& $VeraExe shell @ForwardArgs
exit $LASTEXITCODE
