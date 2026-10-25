[CmdletBinding()]
param(
    [switch]$Refresh,

    [switch]$Chat,

    [string]$Endpoint,

    [string]$Model,

    [string]$ApiKeyEnv,

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

# Reject incomplete or ambiguous configuration before venv creation/install.
# The model-free semantic shell stays the default. Chat always requires a
# deliberate, existing state binding and an explicitly selected local model.
if ($Chat) {
    foreach ($Name in @("StateRoot", "ProjectId", "IdentityId", "Endpoint", "Model")) {
        if (-not $PSBoundParameters.ContainsKey($Name) -or
            [string]::IsNullOrWhiteSpace((Get-Variable -Name $Name -ValueOnly))) {
            throw "Explicit -$Name is required with -Chat."
        }
    }
    if ($null -ne $ConsoleArgs -and $ConsoleArgs.Count -gt 0) {
        throw "-Chat is interactive and does not accept console arguments."
    }
    # This is a read-only filesystem preflight. Python owns lifecycle/identity
    # reconstruction; a caller-supplied project/identity is not authenticated here.
    if (-not (Test-Path -LiteralPath $StateRoot -PathType Container) -or
        -not [System.IO.Directory]::Exists($StateRoot)) {
        throw "Chat -StateRoot must name an existing directory; no state root is created."
    }
}
else {
    foreach ($Name in @("Endpoint", "Model", "ApiKeyEnv")) {
        if ($PSBoundParameters.ContainsKey($Name)) {
            throw "-$Name requires explicit -Chat."
        }
    }
}

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
        # The launcher may have Python 3.13+ but no 3.12. Select its latest
        # Python 3, then enforce our minimum version before creating a venv.
        & $py.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)"
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.12+ is required. Install Python, then run .\vera.ps1 again."
        }
        & $py.Source -3 -m venv $VenvRoot
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

if ($Chat) {
    # Array splatting invokes the exact executable; no shell/evaluation layer
    # can reinterpret a model name, endpoint, or environment-variable name.
    # The Python chat boundary enforces numeric loopback and no tool effects.
    $ChatArgs = @(
        "--interactive",
        "--state-root", $StateRoot,
        "--project-id", $ProjectId,
        "--identity-id", $IdentityId,
        "--endpoint", $Endpoint,
        "--model", $Model
    )
    if ($PSBoundParameters.ContainsKey("ApiKeyEnv")) {
        $ChatArgs += "--api-key-env"
        $ChatArgs += $ApiKeyEnv
    }
    Write-Host "Opening unverified local chat (stateless; no tools or memory admission)."
    & $VeraExe chat @ChatArgs
    exit $LASTEXITCODE
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
