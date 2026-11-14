"""Host authority preflight must not promote same-user Windows facts to trust."""
from __future__ import annotations
import json
import subprocess
import sys
from unittest import TestCase, main
from unittest.mock import patch

from tools.mini_vera import host_authority_preflight as readiness


class HostAuthorityReadinessTests(TestCase):
    def fixture(self, *, admin=True, same=True, services=None):
        names = readiness.ISSUER_SERVICE_NAMES
        return {
            "schema": readiness.PROBE_SCHEMA, "platform": "Windows",
            "caller_token_is_admin": admin, "caller_is_system": False,
            "model_process_count": 1,
            "model_same_principal_any": same, "model_owner_unknown_count": 0,
            "issuer_services": services if services is not None else [
                {"name": name, "present": False, "running": False,
                 "same_principal_as_caller": None} for name in names],
        }

    def test_actual_same_admin_user_has_no_qualified_issuer(self):
        verdict = readiness.evaluate(self.fixture())
        self.assertFalse(verdict["issuer_host_qualified"])
        self.assertEqual("NOT_QUALIFIED", verdict["status"])
        self.assertIn("CALLER_ADMIN_ON_PROPOSED_HOST", verdict["findings"])
        self.assertIn("MODEL_SHARES_CALLER_PRINCIPAL", verdict["findings"])
        self.assertIn("NO_NAMED_ISSUER_SERVICE_DETECTED", verdict["findings"])
        self.assertIn("PROTECTED_SIGNER_CUSTODY_UNVERIFIED", verdict["findings"])
        self.assertNotIn("qualified", verdict["evidence_class"].lower())

    def test_apparently_separate_nonadmin_service_still_cannot_claim_qualification(self):
        services = [
            {"name": name, "present": True, "running": True,
             "same_principal_as_caller": False}
            for name in readiness.ISSUER_SERVICE_NAMES
        ]
        verdict = readiness.evaluate(self.fixture(admin=False, same=False, services=services))
        self.assertEqual("INSUFFICIENT_INDEPENDENT_EVIDENCE", verdict["status"])
        self.assertFalse(verdict["issuer_host_qualified"])
        self.assertIn("PROTECTED_PIN_CUSTODY_UNVERIFIED", verdict["findings"])
        self.assertIn("PROTECTED_REVISION_STORE_UNVERIFIED", verdict["findings"])

    def test_same_principal_named_service_always_unqualified(self):
        services = self.fixture()["issuer_services"]
        services[0] = {"name": services[0]["name"], "present": True,
                       "running": True, "same_principal_as_caller": True}
        report = readiness.evaluate(self.fixture(admin=False, same=False, services=services))
        self.assertFalse(report["issuer_host_qualified"])
        self.assertEqual("NOT_QUALIFIED", report["status"])
        self.assertIn("ISSUER_SERVICE_SHARES_CALLER_PRINCIPAL", report["findings"])

    def test_unresolved_service_owner_fails_without_inventing_isolation(self):
        services = self.fixture()["issuer_services"]
        services[0] = {"name": services[0]["name"], "present": True,
                       "running": True, "same_principal_as_caller": None}
        report = readiness.evaluate(self.fixture(admin=False, same=None, services=services))
        self.assertFalse(report["issuer_host_qualified"])
        self.assertIn("ISSUER_SERVICE_OWNER_UNVERIFIED", report["findings"])

    def test_probe_injection_and_type_coercion_refused(self):
        values = [
            {"caller_token_is_admin": "false"},
            {"model_process_count": True},
            {"model_owner_unknown_count": -1},
            {"model_same_principal_any": "no"},
            {"platform": "Linux"},
            {"issuer_services": []},
            {"extra": "ATTESTED"},
        ]
        for change in values:
            with self.subTest(change=change):
                with self.assertRaises(readiness.PreflightRefused):
                    readiness.evaluate({**self.fixture(), **change})
        with self.assertRaises(readiness.PreflightRefused):
            readiness.evaluate(None)

    def test_boolean_and_owner_claims_must_not_coerce_integer_values(self):
        malformed = [
            {"model_same_principal_any": 1},
            {"model_same_principal_any": 0},
            {"model_owner_unknown_count": 1, "model_same_principal_any": False},
        ]
        for change in malformed:
            with self.subTest(change=change):
                with self.assertRaises(readiness.PreflightRefused):
                    readiness.evaluate({**self.fixture(), **change})
        services = self.fixture()["issuer_services"]
        services[0] = {**services[0], "present": True, "running": True,
                       "same_principal_as_caller": 1}
        with self.assertRaises(readiness.PreflightRefused):
            readiness.evaluate(self.fixture(services=services))

    def test_invalid_service_claim_refused(self):
        cases = [
            [{"name": "NotMiniVera", "present": True, "running": True,
              "same_principal_as_caller": False}, *self.fixture()["issuer_services"][1:]],
            [{"name": readiness.ISSUER_SERVICE_NAMES[0], "present": False,
              "running": True, "same_principal_as_caller": False},
              *self.fixture()["issuer_services"][1:]],
            [{"name": readiness.ISSUER_SERVICE_NAMES[0], "present": False,
              "running": False, "same_principal_as_caller": True},
              *self.fixture()["issuer_services"][1:]],
        ]
        for services in cases:
            with self.subTest(services=services):
                with self.assertRaises(readiness.PreflightRefused):
                    readiness.evaluate(self.fixture(services=services))

    def test_reader_uses_fixed_noninteractive_read_only_windows_command(self):
        synthetic = json.dumps(self.fixture()).encode()
        result = subprocess.CompletedProcess(
            ["powershell.exe"], 0, stdout=synthetic, stderr=b"")
        with patch.object(readiness.subprocess, "run", return_value=result) as mocked:
            probe = readiness.collect_windows(platform_name="nt")
        self.assertEqual(self.fixture(), probe)
        args, kwargs = mocked.call_args
        argv = args[0]
        self.assertIn("-NoProfile", argv)
        self.assertIn("-NonInteractive", argv)
        self.assertNotIn("Set-Acl", argv[-1])
        self.assertNotIn("Start-Service", argv[-1])
        self.assertFalse(kwargs.get("shell", False))
        self.assertLessEqual(kwargs["timeout"], 20)

    def test_missing_transport_and_bad_output_fail_closed(self):
        with patch.object(readiness.subprocess, "run",
                          side_effect=FileNotFoundError("PowerShell missing")):
            with self.assertRaises(readiness.PreflightRefused):
                readiness.collect_windows(platform_name="nt")
        with patch.object(readiness.subprocess, "run",
                          return_value=subprocess.CompletedProcess(
                              ["powershell.exe"], 0, stdout=b"[]", stderr=b"")):
            with self.assertRaises(readiness.PreflightRefused):
                readiness.collect_windows(platform_name="nt")
        with self.assertRaises(readiness.PreflightRefused):
            readiness.collect_windows(platform_name="posix")

    def test_json_report_contains_no_account_sid_or_paths(self):
        report = readiness.evaluate(self.fixture())
        serialized = json.dumps(report)
        for marker in ("S-1-5-", "C:\\Users\\", "D:\\VERA", "private_key",
                       "LOCAL_USER_NAME", "NT AUTHORITY"):
            self.assertNotIn(marker, serialized)
        self.assertFalse(report["issuer_host_qualified"])


if __name__ == "__main__":
    main()
