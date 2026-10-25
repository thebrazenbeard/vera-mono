"""Host readiness must be conservative even with an apparently capable GPU."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from importlib import metadata

from tools.local_training.train_doctor import inspect_host_readiness, main


def _native_gpu(*, free=4 * 1024**3, bf16=True):
    return SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True,
        is_bf16_supported=lambda *, including_emulation: bf16 and including_emulation is False,
        mem_get_info=lambda: (free, 8 * 1024**3),
    ))


@contextmanager
def _qualified_host(*, torch=None, version_fn=None, filesystem_error=None):
    with tempfile.TemporaryDirectory(prefix="vera-host-doctor-") as private_parent:
        with ExitStack() as stack:
            stack.enter_context(patch("tools.local_training.train_doctor.sys.platform", "linux"))
            stack.enter_context(patch("tools.local_training.train_doctor._require_private_filesystem",
                                      side_effect=filesystem_error))
            stack.enter_context(patch("tools.local_training.train_doctor._reject_git_checkout"))
            stack.enter_context(patch("tools.local_training.train_doctor.metadata.version",
                                      side_effect=version_fn or (lambda _: "1.2.3")))
            imported = stack.enter_context(patch("tools.local_training.train_doctor.import_module",
                                                 return_value=torch or _native_gpu()))
            yield Path(private_parent), imported


@unittest.skipUnless(sys.platform.startswith("linux"), "host acceptance requires native Linux")
class LinuxHostReadinessTests(unittest.TestCase):
    def test_qualified_linux_host_returns_read_only_capability_receipt(self):
        with tempfile.TemporaryDirectory(prefix="vera-host-doctor-") as private_parent:
            with (patch("tools.local_training.train_doctor.sys.platform", "linux"),
                  patch("tools.local_training.train_doctor._require_private_filesystem"),
                  patch("tools.local_training.train_doctor._reject_git_checkout"),
                  patch("tools.local_training.train_doctor.metadata.version", return_value="1.2.3"),
                  patch("tools.local_training.train_doctor.import_module", return_value=_native_gpu())):
                result = inspect_host_readiness(Path(private_parent))
        self.assertEqual(result["status"], "HOST_PREFLIGHT_PASS_NOT_TRAINING_AUTHORIZATION")
        self.assertEqual(result["checks"]["bf16_native"], "PASS")
        self.assertEqual(result["checks"]["vram_free"], "PASS")
        self.assertNotIn(private_parent, str(result))

    def test_unqualified_filesystem_holds_without_torch(self):
        with _qualified_host(filesystem_error=ValueError("/private/alice/is-drvfs")) as (path, imported):
            result = inspect_host_readiness(path)
        self.assertEqual(result["status"], "HOST_HOLD")
        self.assertEqual(result["checks"]["filesystem"], "HOLD")
        imported.assert_not_called()
        self.assertNotIn("alice", str(result))

    def test_unexpected_mount_probe_exception_is_redacted_hold(self):
        with _qualified_host(filesystem_error=RuntimeError("/home/owner/private-source")) as (path, imported):
            result = inspect_host_readiness(path)
        self.assertEqual(result["status"], "HOST_HOLD")
        self.assertEqual(result["checks"]["filesystem"], "HOLD")
        self.assertNotIn("private-source", str(result))
        imported.assert_not_called()

    def test_insecure_parent_permissions_hold_before_torch_import(self):
        with _qualified_host() as (path, imported):
            original_mode = path.stat().st_mode & 0o777
            try:
                path.chmod(0o777)
                result = inspect_host_readiness(path)
            finally:
                path.chmod(original_mode)
        self.assertEqual(result["checks"]["filesystem"], "HOLD")
        imported.assert_not_called()

    def test_parent_inside_git_checkout_holds_before_torch(self):
        with tempfile.TemporaryDirectory(prefix="vera-host-git-hold-") as directory:
            with (patch("tools.local_training.train_doctor.sys.platform", "linux"),
                  patch("tools.local_training.train_doctor._require_private_filesystem"),
                  patch("tools.local_training.train_doctor._reject_git_checkout",
                        side_effect=ValueError("/sensitive/.git")),
                  patch("tools.local_training.train_doctor.import_module") as imported):
                result = inspect_host_readiness(Path(directory))
        self.assertEqual(result["status"], "HOST_HOLD")
        self.assertEqual(result["checks"]["filesystem"], "HOLD")
        self.assertNotIn("sensitive", str(result))
        imported.assert_not_called()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support required")
    def test_symlink_parent_refused_before_torch(self):
        with _qualified_host() as (path, imported):
            alias = path / "alias"
            os.symlink(str(path), str(alias), target_is_directory=True)
            result = inspect_host_readiness(alias)
        self.assertEqual(result["status"], "HOST_HOLD")
        self.assertEqual(result["checks"]["filesystem"], "HOLD")
        imported.assert_not_called()

    def test_missing_pytorch_package_holds_before_import(self):
        def version(name):
            if name == "torch":
                raise metadata.PackageNotFoundError(name)
            return "1.2.3"

        with _qualified_host(version_fn=version) as (path, imported):
            result = inspect_host_readiness(path)
        self.assertEqual(result["checks"]["dependencies"], "HOLD")
        self.assertEqual(result["package_versions"]["torch"], "NOT_INSTALLED")
        imported.assert_not_called()

    def test_cuda_unavailable_prevents_bf16_and_vram_queries(self):
        cuda = SimpleNamespace(is_available=lambda: False)
        with _qualified_host(torch=SimpleNamespace(cuda=cuda)) as (path, _):
            result = inspect_host_readiness(path)
        self.assertEqual(result["checks"]["cuda"], "HOLD")
        self.assertEqual(result["checks"]["bf16_native"], "NOT_CHECKED")
        self.assertEqual(result["checks"]["vram_free"], "NOT_CHECKED")

    def test_emulated_only_bf16_holds_before_vram_query(self):
        cuda = SimpleNamespace(is_available=lambda: True,
                               is_bf16_supported=lambda *, including_emulation: False)
        with _qualified_host(torch=SimpleNamespace(cuda=cuda)) as (path, _):
            result = inspect_host_readiness(path)
        self.assertEqual(result["checks"]["cuda"], "PASS")
        self.assertEqual(result["checks"]["bf16_native"], "HOLD")
        self.assertEqual(result["checks"]["vram_free"], "NOT_CHECKED")

    def test_legacy_bf16_api_fails_closed(self):
        cuda = SimpleNamespace(is_available=lambda: True, is_bf16_supported=lambda: True)
        with _qualified_host(torch=SimpleNamespace(cuda=cuda)) as (path, _):
            result = inspect_host_readiness(path)
        self.assertEqual(result["checks"]["bf16_native"], "HOLD")

    def test_insufficient_free_vram_holds(self):
        with _qualified_host(torch=_native_gpu(free=3 * 1024**3 - 1)) as (path, _):
            result = inspect_host_readiness(path)
        self.assertEqual(result["checks"]["vram_free"], "HOLD")
        self.assertIsNone(result["free_vram_gib"])

    def test_cuda_memory_query_exception_is_redacted_hold(self):
        cuda = SimpleNamespace(
            is_available=lambda: True,
            is_bf16_supported=lambda *, including_emulation: including_emulation is False,
            mem_get_info=lambda: (_ for _ in ()).throw(RuntimeError("/users/owner/my-secret-cache")),
        )
        with _qualified_host(torch=SimpleNamespace(cuda=cuda)) as (path, _):
            result = inspect_host_readiness(path)
        self.assertEqual(result["checks"]["vram_free"], "HOLD")
        self.assertEqual(result["status"], "HOST_HOLD")
        self.assertNotIn("my-secret", str(result))

    def test_exact_three_gib_is_acceptable_capability_only(self):
        with _qualified_host(torch=_native_gpu(free=3 * 1024**3)) as (path, _):
            result = inspect_host_readiness(path)
        self.assertEqual(result["status"], "HOST_PREFLIGHT_PASS_NOT_TRAINING_AUTHORIZATION")
        self.assertEqual(result["free_vram_gib"], 3.0)
        self.assertIs(result["training_authorized"], False)

    def test_metadata_probe_failure_masks_sensitive_exception(self):
        def raises(_name):
            raise RuntimeError("secret /home/owner/.cache/token")

        with _qualified_host(version_fn=raises) as (path, imported):
            result = inspect_host_readiness(path)
        self.assertEqual(result["status"], "HOST_HOLD")
        imported.assert_not_called()
        self.assertNotIn("secret", str(result))


class NativeWindowsSafetyHoldTests(unittest.TestCase):
    """Unskipped on every CI OS: native Windows must refuse before probing."""

    def test_windows_holds_before_path_probes_and_torch(self):
        with (patch("tools.local_training.train_doctor.sys.platform", "win32"),
              patch("tools.local_training.train_doctor._private_output_parent") as fs,
              patch("tools.local_training.train_doctor.import_module") as imported):
            result = inspect_host_readiness(Path("C:/private-secret-parent"))
        self.assertEqual(result["status"], "HOST_HOLD")
        self.assertEqual(result["checks"]["platform"], "HOLD")
        fs.assert_not_called()
        imported.assert_not_called()
        self.assertNotIn("private-secret-parent", str(result))

    def test_cli_hold_produces_machine_readable_sanitized_json(self):
        out = StringIO()
        with (patch("tools.local_training.train_doctor.sys.platform", "win32"),
              redirect_stdout(out)):
            exit_code = main(["--output-parent", "C:/my-secret-project"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(__import__("json").loads(out.getvalue())["status"], "HOST_HOLD")
        self.assertNotIn("my-secret-project", out.getvalue())


if __name__ == "__main__":
    unittest.main()
