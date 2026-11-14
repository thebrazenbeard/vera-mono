"""Windows kill-on-close Job Object, scoped solely to an explicitly bound PID.

Protects against abrupt Python-controller termination after the child is bound.
No service discovery, process enumeration, credentials, or global settings.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys


class JobRefused(OSError):
    """Kernel denied owned process containment; no fallback privilege."""


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_void_p),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class KillOnCloseJob:
    """Create a private unnamed Windows job that kills its bound child on close."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise JobRefused("owned process jobs require Windows")
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.OpenProcess.restype = wintypes.HANDLE
        k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        k.CloseHandle.restype = wintypes.BOOL
        self._kernel = k
        self._handle = k.CreateJobObjectW(None, None)
        if not self._handle:
            raise JobRefused(f"CreateJobObject failed: {ctypes.get_last_error()}")
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(
                self._handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            self.close()
            raise JobRefused(f"SetInformationJobObject failed: {err}")

    def bind(self, pid: int) -> None:
        """Bind only the exact newly spawned PID; fail closed if unsupported."""
        if type(pid) is not int or pid <= 0 or not self._handle:
            raise JobRefused("invalid or closed job/process binding")
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE; smallest documented rights.
        process = self._kernel.OpenProcess(0x101, False, pid)
        if not process:
            raise JobRefused(f"OpenProcess failed: {ctypes.get_last_error()}")
        try:
            if not self._kernel.AssignProcessToJobObject(self._handle, process):
                raise JobRefused(
                    f"AssignProcessToJobObject failed: {ctypes.get_last_error()}")
        finally:
            self._kernel.CloseHandle(process)

    def close(self) -> None:
        if getattr(self, "_handle", None):
            self._kernel.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "KillOnCloseJob":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()
