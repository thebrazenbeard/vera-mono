# Mini-Vera managed 4B local session — owned process and Windows kill-on-close (2026-11-14)

## Exact source and scope

Stacked on thebrazenbeard/vera-mono OPEN DRAFT PR #231 at
`2e0d44c36334477fb8240d6275d171e46ac24eb9`.
New isolated VN1 worktree:
`C:\Temp\MiniVeraGGUFHauhau_20261114_One\vera-mono-managed-session-20261114`,
branch `bt2/mini-vera-managed-ollama-20261114`.
No Lappy model run, no shared service restart or download, no model weight edit.

This is an **opt-in local process lifecycle improvement** for an existing
GGUF baseline, not a new neural model, R13 adapter recovery, trained identity,
governed persistent memory, host tool agency or runtime qualification.

## New executable operator path

The source-pinned portable bundle now contains `mini-vera-managed.cmd` and
`tools.mini_vera.managed_ollama_session`, while retaining the old
`mini-vera-chat.cmd` and the default 0.8B mode unchanged.

Illustrative command, using an existing installed Ollama executable and
an existing isolated model registry (not an automated install):

```powershell
mini-vera-managed.cmd --ollama-exe "C:\Users\Vera\AppData\Local\Programs\Ollama\ollama.exe" --models-root "C:\Temp\MiniVeraGGUFHauhau_20261114_One\isolated-ollama-models" --port 11554 --model "mini-vera-hauhau-q4:source-probe-20261114" --expected-tag-digest 3a2ecd5655f349d1f817a8eee531153bdd7bcf64c63080a0c954e02a0be48265 --start-owned-server --confirm-host-idle --allow-cold-load --compact-dialogue
```

The launcher verifies every byte in the sealed package before calling Python.
The managed entry requires three explicit permissions: owned process start,
fresh operator host-idle confirmation and cold model load. It validates
existing non-symlinked executable and model-registry paths, selected numeric
loopback port >1024 distinct from shared 11434, model tag name, and exact
64-hex declared Ollama tag digest. No model registration, downloads, or
global environment edits are performed.

Before spawning Ollama, it rejects a port that already listens and requires
two physical Windows free-RAM samples with a conservative minimum **8 GiB**.
Only the spawned child receives `OLLAMA_HOST=127.0.0.1:<selected-port>`,
`OLLAMA_NO_CLOUD=true`, existing `OLLAMA_MODELS`,
`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`,
and GPU-visible devices disabled for CPU-only VN1 evaluation.

The existing `conversation_console` separately and immediately rechecks
the exact selected model tag and registry digest, foreign resident models,
and >= `tag_size + 5 GiB` free physical RAM before an approved cold load.
The managed shell uses a fixed 128-token output limit. It holds only up to
two exchange pairs in volatile RAM and cannot import private memory or
perform tools. Neither the preflight nor the tag digest is tensor attestation.

## Host process lifetime: reproduced failure and repair

A real first attempt used a PowerShell wrapper whose
`$ErrorActionPreference='Stop'` treated a harmless Python stderr status
line as a fatal native command exception. The wrapper forcibly ended the
Python parent without normal cleanup; its known child Ollama process stayed
listening at owned private port 11552. Verified child PID **6840**, parent
PID **10876** (exited); verified shared Ollama PID **5676** on port 11434.
The only identified owned process 6840 was explicitly stopped after
independent PID/parent/port/command-line checks, then private port 11552
closed and shared 11434 stayed up.

Normal `finally: proc.terminate(); proc.wait()` is **not** enough to survive
external controller termination. The repaired launcher uses a separate
unnamed Windows Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (0x2000), binds only its newly spawned
child PID via `AssignProcessToJobObject`, and holds the non-inheritable job
handle in the controller process. Closing that handle (including on
unexpected controller death) terminates the owned job processes.
If CreateJobObject/SetInformationJobObject/OpenProcess/AssignProcessToJobObject
fails, model inference is refused and only the owned child is cleaned up.
No fallback to an uncontained process or search-and-kill of unrelated PIDs.

**Observed synthetic regression:** a dedicated Windows-only test launched
a test-owned Python parent, bound a 70-second sleeping child to this job,
forcibly killed the parent and verified the child exited within a bounded
deadline. The initial no-op job failed this test (exit1); the real
kernel-backed job passed (exit0). This tests the actual operating-system
mechanism, not just a mock of cleanup.

**Limitations:** there is a short process-creation-to-job-assignment race,
because Python `Popen` starts the executable before assignment. Job setup
is fail-closed; it is not an exclusive host ownership lease, protection
against privileged other processes or an attestation of model execution.
The manager still checks the private port after its owned process shuts
down and returns refusal if an unidentified listener remains.

## Actual VN1 neural behavior and effects

On VERA-NODE-1, full published GGUF SHA-256 was freshly rechecked:
`79e28ecacf84e75b6056cf4059636d435aa9eb67795780f7b7dbc7d32a962741`,
2,707,513,696 bytes, pinned publisher revision
`f38fa6c98f07d536880be5a1fe31207775b77dc0`.
Isolated Ollama alias `mini-vera-hauhau-q4:source-probe-20261114`
declares tag digest `3a2ecd5655f349d1f817a8eee531153bdd7bcf64c63080a0c954e02a0be48265`;
**registry tag digest is not a verified neural tensor hash or LoRA ancestry**.

A successful pre-job live run at port 11552 answered fictional observatory
name **Aster**, exit0, 21.94 seconds, private listener closed, shared 11434
present. Following real Windows job integration, a second actual managed
CPU-only local model run at port 11554 answered the harmless invented
research shuttle name **Marigold**, exit0 in 23.51 seconds.
The managed server closed the owned listener; the shared server on 11434
remained up. Verified offGit post-job log hashes:
- stdout `2d1369342218baf005d26f356cc7afd0667149ba649dd0f92056438896c1620b`.
- stderr `9ded9acd7f68ee941c6b6fc3072d8f16a55533443b460d0678dbd9aaba37ed8d`.

The prior unmanaged PR #231 already tested two-turn Ardent to Wayfarer
correction and unknown private-chat phrase. This managed feature tests
local runtime life cycle; the narrow examples do **not** establish natural
dialogue proficiency, persistent identity, trained learning, or personal memory.

## Tests and authority

TDD managed API: stub test RED 3 failed assertions, then initial GREEN
8 tests. Portable launcher test RED (missing sealed managed command),
then GREEN; lingering occupied-port exit0 defect RED then fixed GREEN;
owned Windows job parent-death test RED then actual Win32 implementation
GREEN; simulated job-assignment denial RED then fail-closed manager GREEN.
Most recent combined focused suite **76 tests, 4 skipped, exit0**.
`git diff --check` exit0. A mock HTTP test may emit a nonfatal
Windows WinError10053 teardown diagnostic; it is not a failed assertion.

Before Windows Job integration, full venv Mini-Vera suite passed
**462 tests, 17 skipped, exit0** with log SHA256
`b6f7be1e334b8e1f799df3f0c3cf80045dfef170630ee0053623d489769f2717`.
After real Windows Job integration, the **full Mini-Vera isolated-venv suite PASSED:**
**464 tests, 17 skipped, zero failures, exit0**, 114.374 seconds test time,
full log SHA-256 `1e4ca15977fb57e5285d76260c657157a37ce55665be65017ff6148b42fc3849`,
`C:\Temp\MiniVeraGGUFHauhau_20261114_One\vn1-managed-job-full-mini-vera-tests-20261114.log`.
One known nonfatal Windows mock-HTTP teardown WinError10053 is preserved.

**HOLD:** Historical model-training Draft PR #355 independently observed
R13 FP32 saved-tensor deltas, but the historical R13 controller still
reports FAILED_OR_INTERRUPTED_NOT_VERIFIED. Missing completion receipt and
different declared GGUF upstream prevent LoRA pairing. No R13 adapter
loaded, no neural training in this work, no private/durable memory, no
model actions/tools, no Lappy 4B load (last measured ~0.52 GiB free RAM),
no source merge, production deployment, paid compute or qualified Vera
identity. `LANTERN_CURRENTNESS=UNKNOWN`.
