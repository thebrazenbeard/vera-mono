"""Windows handle-relative, no-reparse open for an offline model artifact.

Only the drive-volume root is opened by absolute path. Every remaining model
root ancestor and relative artifact component is opened by NtCreateFile with
RootDirectory set to the *already open* parent handle. No joined child path is
ever passed to CreateFileW or NtCreateFile. Reparse points are opened as links
and rejected by file attributes before a child can be traversed.

This is a source candidate until the Windows CI runner exercises it. It does
not attest model-server residency, and deliberately rejects UNC/device paths.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys

from .compose import CompositionRejected


_DRIVE = re.compile(r"[A-Za-z]:\\\Z")
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                       *(f"LPT{i}" for i in range(1, 10))})


def _component(name: str) -> None:
    if (type(name) is not str or not name or name in {".", ".."}
            or any(c in name for c in "/\\:\0") or name.endswith((" ", "."))
            or name.split(".", 1)[0].upper() in _RESERVED):
        raise CompositionRejected("unsafe Windows model path component")
    if len(name.encode("utf-16-le")) > 510:
        raise CompositionRejected("Windows model path component too long")


def _drive_and_components(root: Path, parts: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    """The caller's declared D:\\... path, not a symlink-resolved target."""
    if not root.is_absolute() or not _DRIVE.fullmatch(root.anchor):
        raise CompositionRejected("Windows model root must use an absolute drive path; UNC/device paths unsupported")
    if not parts:
        raise CompositionRejected("Windows model artifact name required")
    components = (*root.parts[1:], *parts)
    for name in components:
        _component(name)
    return root.anchor, components


def open_relative_no_reparse(root: Path, parts: tuple[str, ...]) -> int:
    """Return an owned CRT fd; every ancestor was opened by a parent handle.

    The native relative-open interface is explicitly documented by Microsoft
    for NtCreateFile(ObjectAttributes.RootDirectory). OPEN_REPARSE_POINT opens
    a filesystem reparse object without following it; we reject the handle's
    FILE_ATTRIBUTE_REPARSE_POINT before using it as a parent. Fail closed on
    any API, filesystem or permission rejection; no path-only fallback.
    """
    if os.name != "nt" or sys.platform != "win32":
        raise CompositionRejected("Windows native model handle walk unsupported on this host")
    anchor, components = _drive_and_components(root, parts)

    import ctypes
    from ctypes import wintypes
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

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    native = ctypes.WinDLL("ntdll")
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                    ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    native.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                    ctypes.POINTER(ObjectAttributes),
                                    ctypes.POINTER(IoStatusBlock), ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    native.NtCreateFile.restype = wintypes.LONG

    # Microsoft WinNT/ntifs constants. AttributeTagInfo is enum index 9.
    FILE_ATTRIBUTE_DIRECTORY = 0x10
    FILE_ATTRIBUTE_REPARSE_POINT = 0x400
    FILE_READ_DATA = 0x0001
    FILE_TRAVERSE = 0x0020
    FILE_READ_ATTRIBUTES = 0x0080
    SYNCHRONIZE = 0x00100000
    SHARE_ALL = 0x7  # SHARE_READ|SHARE_WRITE|SHARE_DELETE
    OPEN_EXISTING = 3
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
    FILE_OPEN_REPARSE_POINT = 0x00200000
    OBJ_CASE_INSENSITIVE = 0x40
    FILE_OPEN = 1
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    def check_handle(handle: int, *, directory: bool) -> None:
        info = FileAttributeTagInfo()
        if not kernel.GetFileInformationByHandleEx(
                wintypes.HANDLE(handle), 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise CompositionRejected("Windows handle attribute query failed")
        if info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise CompositionRejected("Windows model path reparse point rejected")
        if bool(info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) is not directory:
            raise CompositionRejected("Windows model handle directory type mismatch")

    def open_child(parent: int, name: str, *, directory: bool) -> int:
        # UnicodeString.Length is UTF-16 bytes *without* trailing NUL.
        raw = ctypes.create_unicode_buffer(name)
        encoded_len = len(name.encode("utf-16-le"))
        u = UnicodeString(encoded_len, encoded_len + 2,
                          ctypes.cast(raw, ctypes.c_wchar_p))
        attrs = ObjectAttributes(ctypes.sizeof(ObjectAttributes),
                                 wintypes.HANDLE(parent), ctypes.pointer(u),
                                 OBJ_CASE_INSENSITIVE, None, None)
        out_handle = wintypes.HANDLE()
        io_status = IoStatusBlock()
        access = FILE_READ_ATTRIBUTES | SYNCHRONIZE | (FILE_TRAVERSE if directory else FILE_READ_DATA)
        # The Win32 NtCreateFile reference's narrow FILE_DIRECTORY_FILE
        # compatibility list does not include OPEN_REPARSE_POINT. Avoid that
        # combination: open an existing object with OPEN_REPARSE_POINT, then
        # REQUIRE its exact directory/non-directory type from the handle.
        options = FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT
        status = native.NtCreateFile(ctypes.byref(out_handle), access,
                                     ctypes.byref(attrs), ctypes.byref(io_status), None,
                                     0, SHARE_ALL, FILE_OPEN, options, None, 0)
        # A synchronous FILE_OPEN should complete with STATUS_SUCCESS (zero).
        # Positive NTSTATUS values may indicate pending/informational states;
        # none are an authenticated completed open for this read-only seam.
        if status != 0 or not out_handle.value:
            if out_handle.value:
                kernel.CloseHandle(out_handle)
            raise CompositionRejected(f"Windows handle-relative model open refused (NTSTATUS 0x{status & 0xffffffff:08x})")
        handle = out_handle.value
        try:
            check_handle(handle, directory=directory)
            return handle
        except BaseException:
            kernel.CloseHandle(wintypes.HANDLE(handle))
            raise

    # Open only the VOLUME ROOT absolutely, then pin each path component.
    # A rooted drive path does not let an attacker swap D:\\VERA midway and
    # redirect a previously opened parent handle to a different tree.
    root_handle = kernel.CreateFileW(
        "\\\\?\\" + anchor, FILE_READ_ATTRIBUTES | FILE_TRAVERSE | SYNCHRONIZE,
        SHARE_ALL, None, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, None)
    if root_handle is None or root_handle == INVALID_HANDLE_VALUE:
        raise CompositionRejected("Windows model drive-root open refused")
    handle = int(root_handle)
    try:
        check_handle(handle, directory=True)
        for index, name in enumerate(components):
            child = open_child(handle, name, directory=index < len(components) - 1)
            kernel.CloseHandle(wintypes.HANDLE(handle))
            handle = child
        # On successful conversion the C runtime owns the HANDLE; os.close
        # of the returned fd closes it. Never CloseHandle it a second time.
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = 0
        return fd
    except (CompositionRejected, OSError, ValueError):
        raise
    except Exception as exc:
        raise CompositionRejected("Windows native handle walk unavailable") from exc
    finally:
        if handle:
            kernel.CloseHandle(wintypes.HANDLE(handle))
