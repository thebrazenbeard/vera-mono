# Synthetic Windows DACL witness (source-only)

This test is a **fixture**, not a permission assessment of anyone's real files.
It converts fixed in-memory SDDL security descriptors through Windows APIs,
enumerates basic ACEs, and checks direct `ALLOW` entries naming Everyone,
Authenticated Users, and BUILTIN Users. It does not access a file path,
modify a DACL, create a directory, hydrate OneDrive, or emit any SID or
private path. A failed/unavailable Windows API is a failing test, not a skip.

Run:

```console
python -m unittest -v tests.test_windows_acl_fixture
```

On Linux, passing the test means only `NOT_RUN_NON_WINDOWS`. On Windows,
`SYNTHETIC_ACL_FIXTURE_PASS` confirms that this **single build** parsed the
fixed test cases as expected. It is not evidence that a real source or output
directory has suitable access controls. It is not an effective-access engine:
object-specific/callback ACEs, nested group membership, privileges,
inheritance, share ACLs, and filesystem-specific behavior are not evaluated.

Before any private historical export manifest is written on Lappy:

1. Use the actual intended private output path and an authenticated host
   identity; inspect source and destination DACLs using a host-owned process.
2. Fail closed when the path/ACL identities, inherited allow ACEs, reparse
   status, or private custody scope are unknown. Do not infer Windows ACL
   protection from POSIX mode `0o600` in WSL.
3. Explicitly adjudicate access by Authenticated Users, BUILTIN Users,
   Everyone, and any other broadly scoped group; preserve a private audit
   receipt without publishing security descriptors or sensitive filenames.
4. Keep directory-path confinement, OneDrive hydration, data rights,
   evaluator custody, and training authority as separate qualifications.

Primary references:

- [Microsoft `ConvertStringSecurityDescriptorToSecurityDescriptorW`](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsecuritydescriptortosecuritydescriptorw)
- [Microsoft `GetSecurityDescriptorDacl`](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-getsecuritydescriptordacl)
- [Microsoft `GetAce`](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-getace)
- [Microsoft file-attribute flags](https://learn.microsoft.com/en-us/windows/win32/fileio/file-attribute-constants)

**No real host ACL, OneDrive, or Lappy permission state has been verified.**
