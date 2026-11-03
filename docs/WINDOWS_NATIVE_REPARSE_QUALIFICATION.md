# Windows native reparse probe (source-only)

The standalone Python probe under `tools/security/windows_nt_reparse_probe.py`
uses a **new temporary fixture**. It opens a temporary parent directory handle
and requests each single-component child relative to that handle using the
Windows Native `NtCreateFile` function with `OBJ_DONT_REPARSE`. It never
reads file payload bytes or enumerates the user's real export tree.

Run on a specifically chosen Windows test host:

```powershell
python -m unittest tests.test_windows_nt_reparse_probe -v
```

The result is **synthetic build evidence only**:

- `SYNTHETIC_BUILD_PROBE_PASS`: genuine child opened and symlink child was
  rejected with `STATUS_REPARSE_POINT_ENCOUNTERED` on that Windows build.
- `SYNTHETIC_BUILD_PROBE_FAIL`: the expected relative reparse rejection was
  not observed. Do not use this backend for protected traversal.
- `UNQUALIFIED_*`: the fixture or native open was unavailable; **fails CI
  on Windows**, not a pass or a silently skipped test.
- `NOT_RUN_NON_WINDOWS`: nothing was tested on a Windows kernel.

**This does not implement an export scanner or qualify OneDrive.** Native
directory enumeration, per-child and per-ancestor handle pinning, cloud
placeholder attributes, no-recall semantics, filesystem change races,
Windows ACL custody, OS-version drift, and actual Lappy behavior remain
unverified. A positive synthetic result must never alter data-rights,
training, ingestion, public-release, or runtime authorization state.

Microsoft's reference documentation confirms the existence of a
`RootDirectory`-relative name for `NtCreateFile` and `OBJECT_ATTRIBUTES`,
and the `FILE_FLAG_OPEN_REPARSE_POINT` and
`FILE_FLAG_BACKUP_SEMANTICS` roles for `CreateFileW`:

- [NtCreateFile](https://learn.microsoft.com/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntcreatefile)
- [OBJECT_ATTRIBUTES](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes)
- [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)

The narrower **user-mode** documentation does not establish a
version-stable contract for combining `OBJ_DONT_REPARSE` with a filesystem
`RootDirectory` in `NtCreateFile`. A Microsoft Q&A clarification notes
empirical success on one Windows 11 build without elevating that experiment
to a guarantee:

- [Microsoft Q&A: user-mode NtCreateFile / OBJ_DONT_REPARSE](https://learn.microsoft.com/en-us/answers/questions/6056645/does-user-mode-ntcreatefile-support-obj-dont-repar)

Accordingly, even a passing Windows CI fixture cannot safely authorize a
live OneDrive inventory. Any future Windows backend requires both
version-qualified native integration and bounded actual-host negative tests.
The fixture reports the exact Windows major/minor/build, machine architecture,
and process pointer width; passing evidence is pinned to that environment.
