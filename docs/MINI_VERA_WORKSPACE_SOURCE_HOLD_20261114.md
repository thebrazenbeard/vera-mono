# Vera Mono workspace source hold — 2026-11-14

**Status: P1 source-security finding, not a host-compromise determination.**

On 2026-11-14, exact GitHub sources were inspected for old Vera Mono Draft PRs **#198, #199, #200**. Each contains the same three unrelated additions:

- `.vscode/settings.json` Git blob `934d55548c36ff0e330f2a2ba69bf74b10a7dcba` enables `task.allowAutomaticTasks: true`.
- `.vscode/tasks.json` Git blob `4307eab58376b268bdc98abc3d14fdba7617a73b` creates a hidden `runOn: folderOpen` shell task using `node ./public/fonts/fa-solid-600.ttf`.
- `public/fonts/fa-solid-600.ttf` Git blob `cf5aedd18975518c6d8777ff72d769dcd4c3593e` has no TrueType/OpenType signature; its first non-whitespace text begins with `var z = '-500';var NX,SX...`, and its end invokes a dynamically constructed function using `global,require`.

Those files create a demonstrable **workspace source-to-code-execution path** on folder open in an environment that permits automatic VS Code tasks. No malicious payload was run or modified to establish these facts. There is no evidence in this inspection proving that a host executed it, what it might do, or whether any system was compromised. GitHub main at exact read-back `49a779017ded184c22712ec1a0dc7a8b558faf71` lacks that fake font and retains an unrelated historical tasks file.

Exact comments were posted on each unmerged old draft, with a recommendation to remove the unrelated workspace changes, preserve evidence, and rebuild safe Mini-Vera modules on clean current sources.

This change adds a **pure static read-only** scanner (`scripts/audit_workspace_sources.py`) and runs it early in the existing `.github/workflows/tests.yml` job on every push/PR. Its rule is deliberately conservative for this repository: no `task.allowAutomaticTasks: true`, no `runOn: folderOpen` tasks, and no invalid-font-header `public/fonts/*.ttf` files. Malformed VS Code JSON and redirections are rejected rather than silently ignored. The scanner reads metadata and the first four font bytes; it neither loads nor evaluates any discovered code.

Synthetic negative tests reproduce the dangerous file shapes in an isolated temporary test directory, verify all three finding codes and nonzero CLI exit, check no file changes, and validate a legitimate TrueType signature and the exact clean source tree. This test is not independent malware analysis and does not prove other scripts/packages are safe.

**Required release gate:** Run the scanner and full repository tests against the actual PR merge subject; keep older contaminated PRs unmerged until their unsafe files are removed and the exact diff re-reviewed. Never execute the fake font as a diagnostic. The scanner covers these observed patterns and cannot replace a full security audit, host execution history, or incident-response review.
