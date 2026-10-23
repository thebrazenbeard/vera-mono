# Goal 1 workspace auto-execution safety triage — 2026-10-23

**State:** Source-level observation. Not malware attribution, not executed, no forensic proof of host compromise.

## Frozen GitHub evidence (read-only)

- `vera-mono/main@64c4a756a8c4d6fc791787de80303f7ee0f64869`: `.vscode/tasks.json` blob `de6de3adea989c8e85a4d39ce0337378d92be7db`; hidden shell task labelled `eslint-check`, `runOn: folderOpen`, executing `node ./public/fonts/fa-solid.lkf` when Node is available. Target blob `31ce18eddf4c96c1a705dbceaec4304f953d4dc3` contains heavily obfuscated JavaScript-like text, not an ordinary font.
- `vera-mono@dd6fd951f2a935373d6d9e3a5958e77920626ba5` (2026-10-01, console dialogue commit) first added the automatic task and `.vscode/settings.json` with `task.allowAutomaticTasks: true`, plus a suspicious `public/fonts/fa-solid-500.woff2` asset. The settings file also embedded a `tasks` object with another `folderOpen` shell command. Both are source risk; this note does not establish which VS Code settings are executable in a given client/version.
- Main commit `64c4a756a8c4d6fc791787de80303f7ee0f64869` revised the task from `.woff2` to `.lkf` and replaced that asset, alongside a Python 3.14 compatibility test. This unrelated co-change requires provenance examination.
- The exact code was inspected as data only. Neither disguised asset was executed or deobfuscated dynamically. No remote workspace or editor task was launched for this investigation.

## Isolated mitigation proposed in Draft/HOLD PR #88

1. Remove the `runOn: folderOpen` task definition from `.vscode/tasks.json`.
2. Set `task.allowAutomaticTasks` to `false` and remove the secondary `tasks` auto-run object from `.vscode/settings.json`.
3. Preserve original suspicious payload in Git history and source pending offline static analysis; this proposal does not certify safety of the repo or any existing checkout.

**Do not merge as a substitute for incident response.** Existing workspaces might already have executed the task, or could have other unsafe startup paths. Establish whether a trusted editor ever opened an affected checkout, and inspect authorized host process logs and credential exposure indicators separately without opening/triggering the workspace. Review provenance of commits, packaging, and external source imports. Do not assume attribution or compromise from source shape alone.

## Evidence and authority boundary

`REPOSITORY_SOURCE` confirms the execution path and obfuscated payload. `HOST_EXECUTION`, `PAYLOAD_BEHAVIOR`, `CREDENTIAL_EXPOSURE`, and `COMPROMISE` remain **UNKNOWN**. No main merge, host/service change, model/provider change, key rotation, or deployment occurred. This is reversible draft-branch preparation only.
