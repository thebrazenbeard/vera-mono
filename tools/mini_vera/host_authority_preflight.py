"""Read-only Windows host-principal preflight; NEVER qualifies an issuer.

This tool can falsify an alleged independent local authority. It cannot prove
a separate trust domain, protected key custody, signed host identity or
rollback-resistant revision history. It makes no changes and reads no keys.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

PROBE_SCHEMA = "MINI_VERA_WINDOWS_AUTHORITY_PROBE_V1"
REPORT_SCHEMA = "MINI_VERA_HOST_AUTHORITY_READINESS_V1"
ISSUER_SERVICE_NAMES = ("MiniVeraIssuer", "VeraIssuer", "VeraHostBroker")
MAX_PROBE_BYTES = 8192

# Fixed read-only query, not expanded from user-supplied data. Never output
# account names, SIDs, service command paths, key material or secret values.
_WINDOWS_PROBE = r'''
$ErrorActionPreference='Stop'
$me=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($me)
$adminSid=New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
$services=@()
foreach($name in @('MiniVeraIssuer','VeraIssuer','VeraHostBroker')){
  $svc=Get-CimInstance Win32_Service -Filter "Name='$name'" -ErrorAction Stop
  if($null -eq $svc){
    $services+=@{name=$name;present=$false;running=$false;same_principal_as_caller=$null}
  }else{
    $owner=$null
    if([string]::IsNullOrWhiteSpace($svc.StartName)){
      $owner=$null
    }else{
      $owner=([string]$svc.StartName -ieq [string]$me.Name)
      if($svc.StartName -eq 'LocalSystem'){$owner=($me.User.Value -eq 'S-1-5-18')}
    }
    $services+=@{name=$name;present=$true;running=($svc.State -eq 'Running');same_principal_as_caller=$owner}
  }
}
$model=@(Get-CimInstance Win32_Process -Filter "Name='ollama.exe'" -ErrorAction Stop)
$sameAny=$false
$unknown=0
foreach($proc in $model){
  try{
    $result=Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid -ErrorAction Stop
    if($result.ReturnValue -ne 0 -or [string]::IsNullOrWhiteSpace($result.Sid)){
      $unknown++
    }elseif($result.Sid -eq $me.User.Value){
      $sameAny=$true
    }
  }catch{$unknown++}
}
$same=$null
if($model.Count -gt 0 -and $sameAny){$same=$true}
elseif($model.Count -gt 0 -and $unknown -eq 0){$same=$false}
$report=@{
  schema='MINI_VERA_WINDOWS_AUTHORITY_PROBE_V1'
  platform='Windows'
  caller_token_is_admin=[bool]$principal.IsInRole($adminSid)
  caller_is_system=[bool]($me.User.Value -eq 'S-1-5-18')
  model_process_count=[int]$model.Count
  model_same_principal_any=$same
  model_owner_unknown_count=[int]$unknown
  issuer_services=$services
}
$report | ConvertTo-Json -Depth 5 -Compress
'''


class PreflightRefused(ValueError):
    """No defensible preflight report can be produced."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PreflightRefused("duplicate host probe field")
        result[key] = value
    return result


def _validate(probe: Any) -> dict[str, Any]:
    keys = {
        "schema", "platform", "caller_token_is_admin", "caller_is_system",
        "model_process_count", "model_same_principal_any",
        "model_owner_unknown_count", "issuer_services",
    }
    if (type(probe) is not dict or set(probe) != keys
            or probe["schema"] != PROBE_SCHEMA or probe["platform"] != "Windows"
            or type(probe["caller_token_is_admin"]) is not bool
            or type(probe["caller_is_system"]) is not bool
            or type(probe["model_process_count"]) is not int
            or not 0 <= probe["model_process_count"] <= 10000
            or type(probe["model_owner_unknown_count"]) is not int
            or not 0 <= probe["model_owner_unknown_count"] <= probe["model_process_count"]
            or not (probe["model_same_principal_any"] is None
                    or type(probe["model_same_principal_any"]) is bool)
            or (probe["model_same_principal_any"] is False
                and probe["model_owner_unknown_count"] != 0)
            or type(probe["issuer_services"]) is not list
            or len(probe["issuer_services"]) != len(ISSUER_SERVICE_NAMES)):
        raise PreflightRefused("host probe shape refused")
    if (probe["model_process_count"] == 0
            and probe["model_same_principal_any"] is not None):
        raise PreflightRefused("no model identity may be inferred")
    for expected_name, svc in zip(ISSUER_SERVICE_NAMES, probe["issuer_services"]):
        if (type(svc) is not dict
                or set(svc) != {"name", "present", "running",
                               "same_principal_as_caller"}
                or svc["name"] != expected_name
                or type(svc["present"]) is not bool
                or type(svc["running"]) is not bool
                or not (svc["same_principal_as_caller"] is None
                        or type(svc["same_principal_as_caller"]) is bool)
                or (not svc["present"]
                    and (svc["running"] or svc["same_principal_as_caller"] is not None))):
            raise PreflightRefused("host probe issuer service invalid")
    return probe


def evaluate(probe: dict[str, Any]) -> dict[str, Any]:
    """Return negative/unknown evidence only; no local probe grants authority."""
    values = _validate(probe)
    reasons: list[str] = []
    blockers: list[str] = []
    if values["caller_token_is_admin"]:
        blockers.append("CALLER_ADMIN_ON_PROPOSED_HOST")
    if values["caller_is_system"]:
        blockers.append("CALLER_SYSTEM_ON_PROPOSED_HOST")
    if values["model_same_principal_any"] is True:
        blockers.append("MODEL_SHARES_CALLER_PRINCIPAL")
    elif values["model_same_principal_any"] is None:
        reasons.append("MODEL_OWNER_NOT_FULLY_ESTABLISHED")
    if not any(svc["present"] for svc in values["issuer_services"]):
        blockers.append("NO_NAMED_ISSUER_SERVICE_DETECTED")
    for svc in values["issuer_services"]:
        if svc["present"]:
            if not svc["running"]:
                blockers.append("NAMED_ISSUER_SERVICE_NOT_RUNNING")
            if svc["same_principal_as_caller"] is True:
                blockers.append("ISSUER_SERVICE_SHARES_CALLER_PRINCIPAL")
            if svc["same_principal_as_caller"] is None:
                reasons.append("ISSUER_SERVICE_OWNER_UNVERIFIED")
    reasons.extend((
        "PROTECTED_SIGNER_CUSTODY_UNVERIFIED",
        "PROTECTED_PIN_CUSTODY_UNVERIFIED",
        "PROTECTED_REVISION_STORE_UNVERIFIED",
        "INDEPENDENT_HOST_ATTESTATION_UNAVAILABLE",
    ))
    findings = list(dict.fromkeys([*blockers, *reasons]))
    return {
        "schema": REPORT_SCHEMA,
        "status": "NOT_QUALIFIED" if blockers
                  else "INSUFFICIENT_INDEPENDENT_EVIDENCE",
        "issuer_host_qualified": False,
        "evidence_class": "LOCAL_READ_ONLY_SELF_REPORT_NO_ATTESTATION",
        "probe_platform": "Windows",
        "named_services_examined": list(ISSUER_SERVICE_NAMES),
        "findings": findings,
        "source_protection_proved": False,
        "host_approval_activated": False,
    }


def collect_windows(*, platform_name: str | None = None) -> dict[str, Any]:
    """No user-supplied commands, credentials, paths, or mutations."""
    if platform_name is None:
        platform_name = os.name
    if platform_name != "nt":
        raise PreflightRefused("only native Windows read-only probe is supported")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             _WINDOWS_PROBE],
            capture_output=True, shell=False, timeout=15, check=False,
        )
        if (result.returncode != 0 or not result.stdout
                or len(result.stdout) > MAX_PROBE_BYTES):
            raise PreflightRefused("Windows host probe unavailable or oversized")
        probe = json.loads(
            result.stdout.decode("utf-8-sig"), object_pairs_hook=_unique)
        return _validate(probe)
    except (OSError, subprocess.TimeoutExpired, UnicodeError,
            json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PreflightRefused("Windows read-only host probe failed") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only-windows", action="store_true", required=True,
                        help="Read local principal/service facts; never qualify authority")
    args = parser.parse_args(argv)
    try:
        report = evaluate(collect_windows())
    except PreflightRefused:
        print("HOST_AUTHORITY_PREFLIGHT_REFUSED", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "INSUFFICIENT_INDEPENDENT_EVIDENCE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
