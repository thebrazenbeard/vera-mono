# Read-only Windows host-boundary negative preflight.
# This script is NOT an authentication or authorization certificate.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $CandidateRoot
)
$ErrorActionPreference = 'Stop'

function Get-BroadWriteRisk {
    param([Parameter(Mandatory = $true)][string] $Path)
    $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    $broadSids = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545')
    $fs = [System.Security.AccessControl.FileSystemRights]
    [long] $mask = ([long]$fs::Write -bor [long]$fs::Modify -bor
        [long]$fs::Delete -bor [long]$fs::DeleteSubdirectoriesAndFiles -bor
        [long]$fs::ChangePermissions -bor [long]$fs::TakeOwnership)
    $broad = $false
    $unknown = $false
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -ne
            [System.Security.AccessControl.AccessControlType]::Allow) {
            continue
        }
        try {
            $sid = $rule.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value
        } catch {
            $unknown = $true
            continue
        }
        if ($broadSids -contains $sid) {
            [long] $rights = [long] $rule.FileSystemRights
            if (($rights -band $mask) -ne 0) {
                $broad = $true
            }
        }
    }
    return [pscustomobject]@{
        broad_write_grant = [bool]$broad
        unresolved_acl_identity = [bool]$unknown
    }
}

try {
    $item = Get-Item -LiteralPath $CandidateRoot -ErrorAction Stop
    if (-not $item.PSIsContainer) {
        throw 'Candidate root must be an existing directory'
    }
    $parent = Split-Path -Path $item.FullName -Parent
    if (-not $parent) {
        throw 'No independently inspectable candidate parent'
    }
    $candidate = Get-BroadWriteRisk -Path $item.FullName
    $parentResult = Get-BroadWriteRisk -Path $parent
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    $admin = $principal.IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    )
    $referenceService = Get-CimInstance Win32_Service -Filter "Name='VeraMonoPilot'" -ErrorAction Stop
    $serviceState = 'UNKNOWN'
    if ($null -eq $referenceService) {
        $serviceState = 'NOT_FOUND'
    } elseif ($referenceService.State -eq 'Running') {
        $serviceState = 'RUNNING_UNQUALIFIED'
    } else {
        $serviceState = 'NOT_RUNNING'
    }
    # Service-name presence is not signing-key or user-origin evidence.
    [pscustomobject]([ordered]@{
        schema = 'VERA_SOCIAL_HOST_BOUNDARY_PREFLIGHT_V1'
        mode = 'READ_ONLY'
        trust_class = 'UNTRUSTED_HOST_OBSERVATION'
        candidate_broad_write_grant = $candidate.broad_write_grant
        candidate_parent_broad_write_grant = $parentResult.broad_write_grant
        acl_identity_resolution_uncertain = (
            $candidate.unresolved_acl_identity -or
            $parentResult.unresolved_acl_identity
        )
        current_process_admin_token = [bool]$admin
        reference_service_state = $serviceState
        user_authentication_verified = $false
        independent_checkpoint_verified = $false
        issuer_credential_custody_verified = $false
        production_qualified = $false
        effect = 'NONE'
        reason = 'HOST_AUTHENTICATION_AND_CHECKPOINT_CUSTODY_UNVERIFIED'
    }) | ConvertTo-Json -Compress -Depth 5
} catch {
    [Console]::Error.WriteLine('HOST_BOUNDARY_PROBE_FAILED_CLOSED')
    exit 2
}
