"""Synthetic Windows DACL witness; never reads a real filesystem path.

The probe converts fixed in-memory SDDL descriptors and checks whether any
direct ALLOW ACE targets Everyone, Authenticated Users, or BUILTIN Users.
This is *not* effective-access evaluation or permission attestation for a
real OneDrive directory. Caller-supplied ACLs, inherited rights, privilege
tokens, and shared-folder access remain outside this fixture's scope.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


_BROAD_SIDS = ("S-1-1-0", "S-1-5-11", "S-1-5-32-545")
_ALLOW_ACE = 0x00
_DENY_ACE = 0x01

SYNTHETIC_CASES = (
    ("everyone_read", "D:(A;;GR;;;WD)", True),
    ("authenticated_users_read", "D:(A;;GR;;;AU)", True),
    ("builtin_users_read", "D:(A;;GR;;;BU)", True),
    ("system_admin_only", "D:(A;;FA;;;SY)(A;;FA;;;BA)", False),
    ("explicit_broad_deny", "D:(D;;GR;;;WD)(A;;FA;;;SY)", False),
)


class AclFixtureUnqualified(RuntimeError):
    """Synthetic descriptor could not be evaluated authoritatively."""


class _AclHeader(ctypes.Structure):
    _fields_ = (
        ("revision", wintypes.BYTE),
        ("reserved1", wintypes.BYTE),
        ("size", wintypes.WORD),
        ("ace_count", wintypes.WORD),
        ("reserved2", wintypes.WORD),
    )


def _has_direct_broad_allow_from_sddl(sddl: str) -> bool:
    if os.name != "nt":
        raise AclFixtureUnqualified("Windows-only synthetic fixture")
    if type(sddl) is not str or not sddl.startswith("D:") or len(sddl) > 512:
        raise AclFixtureUnqualified("unexpected synthetic SDDL input")

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    convert_sd = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert_sd.argtypes = (wintypes.LPCWSTR, wintypes.DWORD,
                           ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    convert_sd.restype = wintypes.BOOL
    convert_sid = advapi.ConvertStringSidToSidW
    convert_sid.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p))
    convert_sid.restype = wintypes.BOOL
    get_dacl = advapi.GetSecurityDescriptorDacl
    get_dacl.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                         ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL))
    get_dacl.restype = wintypes.BOOL
    get_ace = advapi.GetAce
    get_ace.argtypes = (ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
    get_ace.restype = wintypes.BOOL
    equal_sid = advapi.EqualSid
    equal_sid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    equal_sid.restype = wintypes.BOOL
    free = kernel.LocalFree
    free.argtypes = (ctypes.c_void_p,)
    free.restype = ctypes.c_void_p

    allocations: list[ctypes.c_void_p] = []
    try:
        descriptor = ctypes.c_void_p()
        if not convert_sd(sddl, 1, ctypes.byref(descriptor), None) or not descriptor.value:
            raise AclFixtureUnqualified("SDDL conversion failed")
        allocations.append(descriptor)

        broad: list[ctypes.c_void_p] = []
        for sid_text in _BROAD_SIDS:
            ptr = ctypes.c_void_p()
            if not convert_sid(sid_text, ctypes.byref(ptr)) or not ptr.value:
                raise AclFixtureUnqualified("well-known SID conversion failed")
            allocations.append(ptr)
            broad.append(ptr)

        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        acl = ctypes.c_void_p()
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)):
            raise AclFixtureUnqualified("DACL retrieval failed")
        if not present.value or not acl.value:
            # Absent or NULL DACL grants unrestricted access, not a safe ACL.
            return True
        header = ctypes.cast(acl, ctypes.POINTER(_AclHeader)).contents
        if header.ace_count > 16 or header.size < ctypes.sizeof(_AclHeader):
            raise AclFixtureUnqualified("unexpected synthetic ACE layout")

        for index in range(header.ace_count):
            ace = ctypes.c_void_p()
            if not get_ace(acl, index, ctypes.byref(ace)) or not ace.value:
                raise AclFixtureUnqualified("ACE retrieval failed")
            ace_type = ctypes.c_ubyte.from_address(ace.value).value
            ace_size = ctypes.c_ushort.from_address(ace.value + 2).value
            if ace_size < 12 or ace_type not in (_ALLOW_ACE, _DENY_ACE):
                # Object-specific/callback ACE layouts need separate analysis.
                raise AclFixtureUnqualified("unsupported synthetic ACE type")
            if ace_type == _ALLOW_ACE:
                sid_ptr = ctypes.c_void_p(ace.value + 8)
                if any(equal_sid(sid_ptr, check) for check in broad):
                    return True
        return False
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise AclFixtureUnqualified("Windows ACL API unavailable") from exc
    finally:
        for ptr in reversed(allocations):
            if ptr.value:
                free(ptr)


def run_synthetic_acl_cases() -> dict[str, object]:
    """Evaluate only fixed in-memory descriptors, never host ACLs."""
    if os.name != "nt":
        return {"status": "NOT_RUN_NON_WINDOWS", "real_acl_attested": False}
    try:
        outcomes = tuple((name, _has_direct_broad_allow_from_sddl(sddl))
                         for name, sddl, _ in SYNTHETIC_CASES)
    except AclFixtureUnqualified:
        return {"status": "UNQUALIFIED_NATIVE_ACL_FIXTURE", "real_acl_attested": False}
    expected = tuple((name, should_reject) for name, _, should_reject in SYNTHETIC_CASES)
    return {
        "status": "SYNTHETIC_ACL_FIXTURE_PASS" if outcomes == expected
                  else "SYNTHETIC_ACL_FIXTURE_FAIL",
        "real_acl_attested": False,
        "cases": len(outcomes),
    }
