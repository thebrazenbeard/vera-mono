# Mini-Vera 4B candidate console — VN1 verified source-integrated trial, 2026-11-14

## Subject and evidence ceiling

Base: thebrazenbeard/vera-mono OPEN DRAFT PR #230 exact head
278112511d3cb589d52cbf8b744cc3222d83d748. New branch
bt2/mini-vera-candidate4b-console-20261114 in isolated VN1 worktree
C:\Temp\MiniVeraGGUFHauhau_20261114_One\vera-mono-candidate4b-console-20261114.

This is a NONDEFAULT, UNQUALIFIED local conversation console for a 4B candidate.
It is not a neural training completion, R13 adapter pairing, private memory,
production installation on Lappy, or behavioral qualification.

Verified publisher file: Unrestricted/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive
revision f38fa6c98f07d536880be5a1fe31207775b77dc0, Q4_K_M GGUF,
2,707,513,696 bytes, full verified SHA-256
79e28ecacf84e75b6056cf4059636d435aa9eb67795780f7b7dbc7d32a962741.
Ollama alias mini-vera-hauhau-q4:source-probe-20261114
reported tag size 2,707,513,830 bytes, tag digest
3a2ecd5655f349d1f817a8eee531153bdd7bcf64c63080a0c954e02a0be48265.
The tag digest is NOT a tensor hash or ancestry attestation.

Pinned rodrigomt HF metadata versus this GGUF architecture comparison:
ARCHITECTURE_MATCH_ANCESTRY_UNKNOWN, zero architecture mismatches, EOS match,
expected non-certifying exit 2, report SHA-256
d603bed0ca1be710a58fc7bbf5bce16d16d68b7972f38a4c23cbbcc695e9872c.
R13 completion and trained-against tensor lineage remain unverified.

## Guard implementation

Existing default 0.8B model budget and response schema remain unchanged.
The explicit --candidate-4b option adds:
- Mandatory --expected-tag-digest: 64 hex characters, matches selected tag.
- Strict server-reported size greater than 2 GiB and at most 3 GiB.
- Cold resource requirement: reported model bytes PLUS 5 GiB of physically free
  Windows RAM. Warm requirement: at least 3 GiB physically free.
- Two real Windows free-physical-memory reads per preflight; minimum wins.
- Read-only loopback GET /api/tags and GET /api/ps; reject any foreign resident
  model and all resident/expected digest mismatches.
- --confirm-host-idle required for inference, --allow-cold-load separately
  required for nonresident models, max output tokens exactly 128.
- Second read-only inventory and RAM preflight immediately before session
  handoff, rejecting changes in status, model alias, model size, schema,
  candidate class or tag digest.

Existing local_session and compose modules remain the actual request path.
The console does not start services, download model weights, grant tools,
import private user memory, persist chat, or install model artifacts.
This is snapshot-based TOCTOU mitigation, NOT a host workload lease, CPU/GPU
execution attestation, model identity proof or runtime authority grant.

## Actual live source-integrated model runtime, VN1

VN1 host was inspected before use: free RAM 9.13 GiB, CPU 1%.
Only the owned local Ollama port 11546 was started, with isolated owned model
registry, OLLAMA_NO_CLOUD=true, CUDA_VISIBLE_DEVICES=-1 and
ROCR_VISIBLE_DEVICES=-1. Shared VN1 Ollama 11434 remained untouched.

The owned smoke script reverified the full candidate GGUF SHA-256 and launched
the actual conversation_console.py from this edited isolated worktree.
Read-only --check exit 0 and reported zero inference calls, correct candidate
schema; inference without cold-load consent refused exit 2.
Approved real fiction question answered Starling; inaccessible private chat
phrase answered explicitly unknown; two-turn session corrected Ardent to
Wayfarer. All actual source console calls exited 0. Owned port closed.

OffGit receipt:
C:\Temp\MiniVeraGGUFHauhau_20261114_One\vn1-candidate4b-integrated-console-v1.json
SHA-256 5f703872f41f821401ed0d07cebb9f67696cb665e2ba61b5c4745f6d259eb422.
OffGit driver:
C:\Temp\MiniVeraGGUFHauhau_20261114_One\vn1_source_integrated_console_smoke_v1.py
SHA-256 3c00ea7527c1b33d68d394e41b8661c5a0ccade0e9c54639aaa611cd85bd6a4f.

Earlier 18-call unblinded neutral-versus-compact prompt report:
SHA-256 557af743bbbf84465aed2d386f38a1efc058c757e11a34e247cacf891ad1028a.
Negative: compact greeting had boilerplate and garbled punctuation.
No independent heldout evaluator, human Vera-identity signoff or trained LoRA.

## Tests and negative evidence

RED: first new 11-test candidate file produced 13 missing-seam errors
(including subtest branches); new feature did not exist.
GREEN: 52 tests, four skipped, zero failures, exit 0, combining new 4B
cases with existing console and 0.8B preflight tests (Python 3.13.15).
Cases cover missing tag pin, too large/small candidate, cold and warm memory,
mid-probe RAM drop, foreign resident model, cold-load refusal, consent, 128
token cap, second-pass digest change, and invalid preflight class.
Git diff --check exit 0.

The first global-Python full Mini-Vera suite on VN1 was NOT GREEN:
445 run, 3 failed, 4 errors, 37 skipped, exit 1.
Global Python lacked cryptography and jsonschema (project dependencies), and
the external ephemeral issuer tests refused Ed25519 support.
An isolated offGit venv at
C:\Temp\MiniVeraGGUFHauhau_20261114_One\venv-mini-vera-candidate4b
installed cryptography 48.0.1 and jsonschema 4.26.0, plus transitive packages,
without changing globally installed Python or installed shared services.
The full isolated-venv suite **PASSED**: 452 tests, 17 skipped, 0 failures,
exit 0, 106.292 seconds under Python 3.13.15. OffGit full log:
C:\Temp\MiniVeraGGUFHauhau_20261114_One\vn1-candidate4b-full-mini-vera-unittest.log
SHA-256 37293d44ea26617463a3f2ad7f2882696589608d27cde2d3be1257b44498a930.
There was one nonfatal preexisting Windows mock HTTP teardown diagnostic
ConnectionAbortedError WinError10053; not a failed assertion or suite failure.

HOLD: no R13 adapter loaded, no neural learning/weight transfer, no
persistent governed memory, no tool actions, no Lappy 4B load or model
install, no trained-base tensor ancestry attestation, no qualified identity,
no protected merge, no paid compute, no deployment. Latest measured Lappy
free RAM was only 0.72 GiB; do not evict another workload.
LANTERN_CURRENTNESS=UNKNOWN; no retired DB was queried.
