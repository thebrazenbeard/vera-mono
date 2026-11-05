"""Windows-only synthetic probe for relative NtCreateFile reparse rejection.

This is NOT a production directory scanner or an OneDrive safety check.
It never opens file payloads, scans user folders, or grants permission to
ingest historical exports. The user-mode NtCreateFile + OBJ_DONT_REPARSE
combination needs per-Windows-build evidence and is not a cross-version
contract in the official documentation.
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import platform
import struct
import sys
import tempfile

STATUS_SUCCESS = 0x00000000
STATUS_REPARSE_POINT_ENCOUNTERED = 0xC000050B
_PUBLIC_RECEIPT_FIELDS = (
    "status", "windows_build", "architecture", "python_pointer_bits",
    "genuine_child_status", "reparse_child_status",
    "live_host_qualified", "onedrive_hydration_proven_safe",
)


def _synthetic_pair_status(genuine: int, reparse: int) -> str:
    return (
        "SYNTHETIC_BUILD_PROBE_PASS"
        if genuine == STATUS_SUCCESS
        and reparse == STATUS_REPARSE_POINT_ENCOUNTERED
        else "SYNTHETIC_BUILD_PROBE_FAIL"
    )


def require_synthetic_build_pass(result: dict[str, object]) -> None:
    """Fail closed on unavailable fixtures, native errors, and wrong statuses."""

    if result.get("status") != "SYNTHETIC_BUILD_PROBE_PASS":
        raise AssertionError(f"Windows native fixture did not qualify: {result.get('status')}")
    if (
        type(result.get("windows_build")) is not str
        or not result["windows_build"]
        or type(result.get("architecture")) is not str
        or not result["architecture"]
        or type(result.get("python_pointer_bits")) is not int
        or result["python_pointer_bits"] not in (32, 64)
        or result.get("live_host_qualified") is not False
        or result.get("onedrive_hydration_proven_safe") is not False
    ):
        raise AssertionError("Windows native fixture lacks pinned build/negative authority metadata")


def _relative_directory_open_status(parent: Path, child: str) -> int:
    """Query one synthetic directory child through a held parent handle.

    Deliberately private: caller must supply one ordinary child component.
    The root opened here is a test fixture, not a security-confined entry point.
    """

    if os.name != "nt":
        raise RuntimeError("Windows-only native probe")
    if not child or child in (".", "..") or any(x in child for x in ("\\", "/", "\x00", ":")):
        raise ValueError("expected one non-special child component")

    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", ctypes.c_void_p),
            ("SecurityQualityOfService", ctypes.c_void_p),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [
            ("Status", ctypes.c_void_p),
            ("Information", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    nt_create = ntdll.NtCreateFile
    nt_create.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG,
        ctypes.POINTER(ObjectAttributes), ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
        wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
    ]
    nt_create.restype = wintypes.LONG

    FILE_LIST_DIRECTORY = 0x0001
    FILE_READ_ATTRIBUTES = 0x0080
    SYNCHRONIZE = 0x00100000
    SHARE_ALL = 0x00000007
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    OBJ_CASE_INSENSITIVE = 0x00000040
    OBJ_DONT_REPARSE = 0x00001000
    FILE_OPEN = 1
    FILE_DIRECTORY_FILE = 0x00000001
    FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020

    root = create_file(
        str(parent),
        FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
        SHARE_ALL, None, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if root in (None, invalid_handle):
        raise OSError("synthetic parent could not be opened")
    try:
        name_buffer = ctypes.create_unicode_buffer(child)
        name = UnicodeString(
            len(child) * ctypes.sizeof(ctypes.c_wchar),
            (len(child) + 1) * ctypes.sizeof(ctypes.c_wchar),
            ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        attrs = ObjectAttributes(
            ctypes.sizeof(ObjectAttributes), root, ctypes.pointer(name),
            OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE, None, None,
        )
        status_block = IoStatusBlock()
        result_handle = wintypes.HANDLE()
        status = nt_create(
            ctypes.byref(result_handle),
            FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
            ctypes.byref(attrs), ctypes.byref(status_block), None, 0, SHARE_ALL,
            FILE_OPEN, FILE_DIRECTORY_FILE | FILE_SYNCHRONOUS_IO_NONALERT,
            None, 0,
        ) & 0xFFFFFFFF
        handle_value = result_handle.value
        if status == STATUS_SUCCESS and handle_value in (None, invalid_handle):
            raise OSError("native open reported success without a valid handle")
        if handle_value not in (None, invalid_handle):
            if not close_handle(result_handle):
                raise OSError("native child handle could not be closed")
        return status
    finally:
        if not close_handle(root):
            raise OSError("native parent handle could not be closed")


def run_synthetic_reparse_probe() -> dict[str, object]:
    """Run on an isolated temporary fixture; never read external content.

    A PASS demonstrates the specific OS-build behavior only. A SKIP or FAIL
    is not an authorization to inventory OneDrive. Neither is a PASS.
    """

    if os.name != "nt":
        return {"status": "NOT_RUN_NON_WINDOWS"}
    version = sys.getwindowsversion()
    host = {
        "windows_build": f"{version.major}.{version.minor}.{version.build}",
        "architecture": platform.machine(),
        "python_pointer_bits": struct.calcsize("P") * 8,
        "live_host_qualified": False,
        "onedrive_hydration_proven_safe": False,
    }
    with tempfile.TemporaryDirectory(prefix="vera-nt-reparse-probe-") as name:
        parent = Path(name)
        real = parent / "real"
        real.mkdir()
        link = parent / "link"
        try:
            os.symlink(real, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            return {**host, "status": "UNQUALIFIED_SYMLINK_FIXTURE_UNAVAILABLE"}
        try:
            real_status = _relative_directory_open_status(parent, "real")
            link_status = _relative_directory_open_status(parent, "link")
        except (OSError, AttributeError, TypeError, ValueError, ctypes.ArgumentError):
            return {**host, "status": "UNQUALIFIED_NATIVE_OPEN_UNAVAILABLE"}
        return {
            **host,
            "status": _synthetic_pair_status(real_status, link_status),
            "genuine_child_status": f"0x{real_status:08x}",
            "reparse_child_status": f"0x{link_status:08x}",
        }


def main() -> int:
    """Emit a bounded, non-sensitive CI receipt even when the probe fails."""

    result = run_synthetic_reparse_probe()
    receipt = {key: result[key] for key in _PUBLIC_RECEIPT_FIELDS if key in result}
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")), flush=True)
    require_synthetic_build_pass(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
