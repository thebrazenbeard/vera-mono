"""Isolated native Windows experiment for private Mini-Vera output creation.

This is NOT production custody authority and does not enable the deliberately
held Windows writer in qualification_workflow.py. It writes one harmless marker
to an automatically removed temporary directory. Running it establishes only
the local process's observed NTFS descriptor and exclusive-create behavior;
it cannot attest a host-owned parent, foreign-user denial, or resistance to
equally privileged directory movers.

Run explicitly on an isolated Windows host with Python 3.11+:
    python tools/mini_vera/windows_private_output_probe.py
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile


MARKER = b"MINI_VERA_WINDOWS_PRIVATE_OUTPUT_PROBE_ONLY\n"


def _long_declared_dos_path(path: Path) -> Path:
    """Expand 8.3 spelling without resolving an ancestor junction target.

    Windows CI temp paths can contain `RUNNER~1`, while a handle's normalized
    final name reports `runneradmin` (the same object). Compare long *declared*
    spelling to the opened handle's final path; `Path.samefile` would follow
    junctions and incorrectly accept a redirected parent.
    """
    if sys.platform != "win32" or os.name != "nt":
        raise RuntimeError("Windows declared-path normalization unavailable")
    method = ctypes.WinDLL("kernel32", use_last_error=True).GetLongPathNameW
    method.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    method.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32_768)
    count = method(str(path), buffer, len(buffer))
    if not count or count >= len(buffer) or not Path(buffer.value).is_absolute():
        raise RuntimeError("Windows declared directory path cannot be normalized")
    return Path(buffer.value)


def run_probe() -> dict[str, object]:
    """Return bounded observations, or refuse before creating any output."""
    if sys.platform != "win32" or os.name != "nt":
        raise RuntimeError("Windows native private-output probe requires Windows")

    import msvcrt

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", ctypes.c_wchar_p)]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(UnicodeString)),
                    ("Attributes", wintypes.ULONG), ("SecurityDescriptor", ctypes.c_void_p),
                    ("SecurityQualityOfService", ctypes.c_void_p)]

    class IoStatusUnion(ctypes.Union):
        _fields_ = [("Status", wintypes.LONG), ("Pointer", ctypes.c_void_p)]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("u", IoStatusUnion), ("Information", ctypes.c_size_t)]

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

    class AccessControlList(ctypes.Structure):
        _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte),
                    ("AclSize", wintypes.USHORT), ("AceCount", wintypes.USHORT),
                    ("Sbz2", wintypes.USHORT)]

    class AccessControlEntry(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", wintypes.USHORT), ("AccessMask", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    native = ctypes.WinDLL("ntdll")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)

    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                    ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                                 wintypes.DWORD, wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.GetSecurityInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetSecurityInfo.restype = wintypes.DWORD
    advapi.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p,
                                                     ctypes.POINTER(wintypes.USHORT),
                                                     ctypes.POINTER(wintypes.DWORD)]
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p,
                                                  ctypes.POINTER(wintypes.BOOL),
                                                  ctypes.POINTER(ctypes.c_void_p),
                                                  ctypes.POINTER(wintypes.BOOL)]
    advapi.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetAce.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                               ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    native.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                    ctypes.POINTER(ObjectAttributes),
                                    ctypes.POINTER(IoStatusBlock), ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    native.NtCreateFile.restype = wintypes.LONG

    FILE_READ_DATA = 0x0001
    FILE_WRITE_DATA = 0x0002
    FILE_ADD_FILE = 0x0002
    FILE_TRAVERSE = 0x0020
    FILE_READ_ATTRIBUTES = 0x0080
    READ_CONTROL = 0x00020000
    SYNCHRONIZE = 0x00100000
    SHARE_ALL = 0x7
    FILE_ATTRIBUTE_DIRECTORY = 0x10
    FILE_ATTRIBUTE_REPARSE_POINT = 0x400
    FILE_ATTRIBUTE_NORMAL = 0x80
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_CREATE = 2
    FILE_SYNCHRONOUS_IO_NONALERT = 0x20
    FILE_NON_DIRECTORY_FILE = 0x40
    FILE_OPEN_REPARSE_POINT = 0x00200000
    OBJ_CASE_INSENSITIVE = 0x40
    SE_FILE_OBJECT = 1
    DACL_SECURITY_INFORMATION = 4
    SE_DACL_PROTECTED = 0x1000
    FILE_ALL_ACCESS = 0x001f01ff
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    def final_name(handle: int) -> Path:
        buffer = ctypes.create_unicode_buffer(32_768)
        size = kernel.GetFinalPathNameByHandleW(wintypes.HANDLE(handle), buffer,
                                                 len(buffer), 0)
        if (not size or size >= len(buffer) or not buffer.value.startswith("\\\\?\\")
                or buffer.value.startswith("\\\\?\\UNC\\")):
            raise RuntimeError("opened Windows path cannot be attested")
        return Path(buffer.value[4:])

    def require_real_directory(handle: int) -> None:
        info = FileAttributeTagInfo()
        if not kernel.GetFileInformationByHandleEx(wintypes.HANDLE(handle), 9,
                                                   ctypes.byref(info), ctypes.sizeof(info)):
            raise RuntimeError("Windows parent attributes unavailable")
        if info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT or not \
                info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY:
            raise RuntimeError("Windows parent is a reparse point or not a directory")

    with tempfile.TemporaryDirectory(prefix="mini-vera-windows-acl-probe-") as isolated:
        parent = Path(isolated)
        parent_handle = kernel.CreateFileW(
            str(parent), FILE_ADD_FILE | FILE_TRAVERSE | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
            SHARE_ALL, None, OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, None)
        if parent_handle is None or parent_handle == INVALID_HANDLE_VALUE:
            raise RuntimeError("cannot open probe parent with native directory handle")
        parent_handle = int(parent_handle)
        descriptor = ctypes.c_void_p()
        child_handle = 0
        observed_descriptor = ctypes.c_void_p()
        try:
            require_real_directory(parent_handle)
            if final_name(parent_handle) != _long_declared_dos_path(parent):
                raise RuntimeError("probe parent final path drift")

            # Protected DACL: owner rights and Local System only. The exact
            # effective rights still require native foreign-principal testing.
            sddl = "D:P(A;;FA;;;OW)(A;;FA;;;SY)"
            if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl, 1, ctypes.byref(descriptor), None):
                raise RuntimeError("private Windows SDDL conversion refused")

            leaf = "probe-output.bin"
            wide = ctypes.create_unicode_buffer(leaf)
            leaf_bytes = len(leaf.encode("utf-16-le"))
            unicode_leaf = UnicodeString(leaf_bytes, leaf_bytes + 2,
                                         ctypes.cast(wide, ctypes.c_wchar_p))
            attrs = ObjectAttributes(ctypes.sizeof(ObjectAttributes),
                                     wintypes.HANDLE(parent_handle), ctypes.pointer(unicode_leaf),
                                     OBJ_CASE_INSENSITIVE, descriptor, None)

            def create_exclusive() -> tuple[int, int]:
                out = wintypes.HANDLE()
                io_status = IoStatusBlock()
                status = native.NtCreateFile(
                    ctypes.byref(out), FILE_READ_DATA | FILE_WRITE_DATA |
                    FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE,
                    ctypes.byref(attrs), ctypes.byref(io_status), None,
                    FILE_ATTRIBUTE_NORMAL, SHARE_ALL, FILE_CREATE,
                    FILE_SYNCHRONOUS_IO_NONALERT | FILE_NON_DIRECTORY_FILE |
                    FILE_OPEN_REPARSE_POINT, None, 0)
                return status, int(out.value or 0)

            status, child_handle = create_exclusive()
            if status != 0 or not child_handle:
                raise RuntimeError(f"NtCreateFile restricted-DACL create refused (0x{status & 0xffffffff:08x})")
            if final_name(child_handle) != _long_declared_dos_path(parent / leaf):
                raise RuntimeError("child final path drift")
            duplicate_status, duplicate_handle = create_exclusive()
            if duplicate_handle:
                kernel.CloseHandle(wintypes.HANDLE(duplicate_handle))
            if duplicate_status == 0 or duplicate_handle:
                raise RuntimeError("FILE_CREATE unexpectedly opened existing output")

            code = advapi.GetSecurityInfo(wintypes.HANDLE(child_handle), SE_FILE_OBJECT,
                                          DACL_SECURITY_INFORMATION, None, None,
                                          None, None, ctypes.byref(observed_descriptor))
            if code != 0 or not observed_descriptor.value:
                raise RuntimeError(f"created file DACL unavailable (Win32 {code})")
            control = wintypes.USHORT()
            revision = wintypes.DWORD()
            if not advapi.GetSecurityDescriptorControl(
                    observed_descriptor, ctypes.byref(control), ctypes.byref(revision)):
                raise RuntimeError("created file descriptor control unavailable")
            if not control.value & SE_DACL_PROTECTED:
                raise RuntimeError("created file inherited or unprotected DACL")

            present = wintypes.BOOL()
            dacl = ctypes.c_void_p()
            defaulted = wintypes.BOOL()
            if (not advapi.GetSecurityDescriptorDacl(
                    observed_descriptor, ctypes.byref(present), ctypes.byref(dacl),
                    ctypes.byref(defaulted)) or not present.value or not dacl.value):
                raise RuntimeError("created file has missing or null DACL")
            acl = ctypes.cast(dacl, ctypes.POINTER(AccessControlList)).contents
            if acl.AceCount != 2:
                raise RuntimeError("created file has unapproved additional DACL entries")
            permitted: set[str] = set()
            for index in range(acl.AceCount):
                ace = ctypes.c_void_p()
                if not advapi.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                    raise RuntimeError("created file DACL entry inaccessible")
                access = ctypes.cast(ace, ctypes.POINTER(AccessControlEntry)).contents
                if (access.AceType != 0 or access.AceFlags != 0 or
                        access.AccessMask != FILE_ALL_ACCESS or access.AceSize < 16):
                    raise RuntimeError("created file has unexpected DACL grant")
                sid_text = wintypes.LPWSTR()
                if not advapi.ConvertSidToStringSidW(
                        ctypes.c_void_p(ace.value + ctypes.sizeof(AccessControlEntry)),
                        ctypes.byref(sid_text)):
                    raise RuntimeError("created file DACL principal inaccessible")
                try:
                    permitted.add(sid_text.value)
                finally:
                    kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
            if permitted != {"S-1-3-4", "S-1-5-18"}:
                raise RuntimeError("created file DACL includes unexpected principals")

            # The CRT owns the native child HANDLE after successful adoption.
            fd = msvcrt.open_osfhandle(child_handle, os.O_RDWR | os.O_BINARY)
            child_handle = 0
            try:
                with os.fdopen(fd, "r+b", closefd=False) as output:
                    output.write(MARKER)
                    output.flush()
                    os.fsync(output.fileno())
                    output.seek(0)
                    if output.read(len(MARKER) + 1) != MARKER:
                        raise RuntimeError("same descriptor data readback mismatch")
            finally:
                os.close(fd)
            if final_name(parent_handle) != _long_declared_dos_path(parent):
                raise RuntimeError("probe parent changed after child output")
            return {
                "status": "TEMP_PROBE_PASSED_NOT_CUSTODY_QUALIFIED",
                "native_handle_relative_file_create": "SUCCESS",
                "exclusive_create_repeated": "REFUSED",
                "child_dacl_protected": True,
                "child_dacl_explicit_aces": "OWNER_RIGHTS_AND_LOCAL_SYSTEM_ONLY",
                "same_handle_marker_readback": "PASS",
                "foreign_user_access_check": "NOT_RUN",
                "trusted_host_parent_authority": "NOT_ESTABLISHED",
                "production_writer": "STILL_FAIL_CLOSED",
            }
        finally:
            if child_handle:
                kernel.CloseHandle(wintypes.HANDLE(child_handle))
            if observed_descriptor.value:
                kernel.LocalFree(observed_descriptor)
            if descriptor.value:
                kernel.LocalFree(descriptor)
            kernel.CloseHandle(wintypes.HANDLE(parent_handle))


def main() -> int:
    try:
        print(json.dumps(run_probe(), sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "TEMP_PROBE_FAILED", "error": str(exc),
                          "production_writer": "STILL_FAIL_CLOSED"}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
