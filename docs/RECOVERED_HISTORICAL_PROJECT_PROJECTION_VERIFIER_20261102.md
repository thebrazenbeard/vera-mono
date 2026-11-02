# Recovered historical Project projection verifier (July v0.2.0)

This is a **read-only compatibility tool** for six-file historical Project
projection directories. It does not reinstall the historical projection
adapter or import the old memory kernel.

**Private source provenance:** Patrick's local
C:\Users\patri\OneDrive\Downloads\VERA_PROJECT_PROJECTION_ADAPTER_V0.2.0_VALIDATED.zip
(SHA-256: 4741579ae7a90722578c6e543f88c7e3f14e8ce6d7eb5eda88d9a934d27bc64f).
Source was inspected as **archival reference data**, not current authority.

## Functional recovery

The historical lifecycle exported **five Markdown Project files** and one
VERA_PROJECT_PROJECTION_MANIFEST.json metadata file. This current
vera_ingest implementation verifies that layout without running any
historical code:

- Exact historical file set, nonempty UTF-8 text, bounded sizes, and rejection
  of symlink/reparse/cloud placeholders.
- Strict JSON, duplicate-key rejection, exact v0.2.0 version
  bindings, explicit historical branch, and canonical availability flag.
- Each of five SHA-256 file digests and the stable manifest fingerprint
  computed using archived canonical JSON rules (excluding self-hash).
- Explicit distinction between structurally intact historical available-state
  and degraded-state snapshots. **Neither is described as currently valid.**
- Local output contains status, count, evidence class and a manifest
  digest, but **never private Project text, branch value or absolute path**.

To inspect a previously exported, **quiescent local directory**, not the
ZIP containing Python source and not a live ChatGPT Project:

    $env:PYTHONPATH = 'packages/vera_ingest/src'
    py -3.12 -m ingest.legacy_project_projection_cli --project-directory 'D:\private\historical-project-export' --expected-branch 'main'

Exit code 0 denotes a structurally self-consistent historical export.
Exit code 2 indicates failure. This command does not install, refresh,
replace, delete, sync or update files.

## Evidence limits

A manifest digest is **local consistency, not a signature**. A coordinated
rewriter can replace every file, its listed hashes and the manifest
fingerprint; a synthetic test explicitly demonstrates that such a forged
but internally consistent set can pass while all currentness and authority
claims remain false. Historical canonical availability and event sequence are
claims *inside the old manifest*, not facts about today's canonical source.
External trusted custody/currentness evidence and Patrick's exact effect
authorization remain separate.

This verifier does **not** validate semantic memories, identity, consent,
experience, current control owners, runtime consumption, host installation,
or publication rights. Reading ordinary local files is subject to filesystem
TOCTOU races against a malicious same-user process; do not use it as an OS
security boundary. Input contents remain on Lappy and are not committed.

The implementation was tested with source-derived synthetic v0.2.0 fixtures,
not a real historical five-file export. That qualification remains outstanding
until a real eligible archive with the exact manifest is found.
