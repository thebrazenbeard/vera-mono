# Goal 1 physically observed local inference reservation — 2026-10-23

**Evidence classification: HOST-LOCAL RESEARCH OBSERVATION. NOT QVR selected-runtime proof, independent dispatch custody, causal learning, or AGI.**

Goal: close the local loss-of-attempt ambiguity exposed in Integration PR #82 without modifying that delegated branch. The additive `local_attempt.py` adapter in Vera-owned Draft PR #89 reserves an invocation in SQLite **before any call to the existing PR #82 `LocalCognitionGate.generate`**, then commits `COMPLETED` on a validated reply or conservatively records `OUTCOME_UNKNOWN` on a caught failure. A surviving `RESERVED` row after crash blocks reuse; no auto-resumption or falsely certain failure state. SQLite `BEGIN IMMEDIATE` and unique invocation/reservation/run-arm-case constraints serialize concurrent processes.

## Exact source and physical tests

- Vera Mono Integration #82: `packages/vera_core/src/vera_core/local_cognition.py` at immutable commit `26271c5d69dee4663e07d4dbcf63efcf033626e8`. Loaded as a standalone, non-installed module from GitHub on Lappy.
- New research adapter: `research/goal1_acceptance_bridge/local_attempt.py`, commit `81e0ad4a3ca7d6a9120ff917a10d88dd03eedaea`, local file SHA-256 `6f33df7552b40e50f03a665f2a46bbc173f978c785fc3d2e63a943587609b61d` independently computed on Lappy after GitHub download. Exact Git blob is verified separately in GitHub.
- Tests: `tests/research/test_goal1_local_attempt.py`, commit `314ad545197c8e0e86f7837b35519bf42250153a`.
- TDD RED: physical VN2 Linux 7 tests yielded **1 failure, 6 errors** against the earlier adapter after the new controller-reservation identity/pre-send assertion was introduced. GREEN after adapter update: **7/7 passed physical VN2 Linux Python3.12; 7/7 passed physical Lappy Windows**. Includes two separate Python-process reservation collision, timeout/unknown, pre-send durable readback inside `generate()`, malformed response, crash-reserved reopen and no same-ID replay.

## One actual source-level live model call on physical Lappy

- Isolated user-temp experiment DB, not VeraMonoPilot production state. Existing Windows VeraMonoPilot service was observed `Stopped` / `Manual`; not started or changed.
- Exact model tag `qwen3:4b-instruct`. Ollama `GET /api/tags` registry **reported** digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`, not a verified loaded-weight SHA.
- Explicit `InferencePermit` scope `SYNTHETIC_LOCAL_INFERENCE_TEST`, loopback-only gate, armed for this single controlled research call, `max_tokens=8`, timeout 10 seconds. The prompt was harmless inert synthetic transport text, not an evaluator challenge/answer-key fixture.
- Controller **not connected**; research caller provided: `run_id=goal1-local-inference-20261023`, `arm=FROZEN`, `challenge_id=transport-probe-02`, `reservation_id=research-reservation-20261023-02`, `invocation_id=qwen3-live-probe-20261023-02`.
- Returned through actual loopback Ollama `LocalCognitionGate`: local adapter `COMPLETED`; response length **2 bytes** (not persisted); response SHA256 `565339bc4d33d72817b583024112eb7f5cdf3e5eef0252d6ec1b9c9a94e12bb3`; prompt SHA256 `ea8b29bdf43aa7abd63fb6bae26364851ddb8f485ce366699aa13e2261e888b4`; elapsed **5,024 ms** as observed on Lappy. One SQLite attempt record.
- A separate, newly launched Python process reopened the DB and verified `sequence=1`, `COMPLETED`, exact reservation ID, and rejected the same invocation/reservation being used a second time. No second model call was initiated by this readback.
- `independent_attestation=False`; no trusted input/output token measurement, model weight byte proof, independently timestamped dispatch, or externally held signing key.

A predecessor live call using an earlier version without the controller reservation field also completed (2-byte response, 5,934 ms). It remains historical local observation only; the **second** call above is the current-source evidence cut.

## Hostile review / missing gate

> **ACCEPTED: A caller-provided reservation_id is not a controller-issued reservation.** A learner could invent an ID, bypass this adapter and call Ollama directly, or rewrite the same-user SQLite file. A host-local PRE-DISPATCH row is an important recovery/failure-handling mechanism, **not** an independent dispatch witness. The source does not sign anything, impersonate Malaphor, or claim that `model_identity_level=REGISTRY_SELF_REPORTED` verifies loaded model weights. Recorded elapsed_ms is host local, not external resource metering.

Malaphor has independently advanced #87 to `fe217e504ff5f75ef2b047d4a92137e7441d2d6a` with `Ed25519DispatchEvidenceVerifier`, signed envelope + durable replay checks. His source expressly lacks a provisioned real gateway and requires an **evaluator-controlled** reservation, deployment-pinned public key and distinct signing authority. Our local research adapter is not to be passed as `witness_kind=independent_dispatch_gateway` or self-signed into that verifier. The frozen source-compatibility probe in PR #89 pins the **earlier** #87 head and should not be presented as current-head interoperability against the new verifier.

**Next owner-specific integration:** Integration #82 chooses whether to absorb the local durable state machine into `QualifiedVeraRuntime` and restricts the actual dispatch path; Malaphor #87 binds his authentic separately controlled reservation/witness against it. Vera #86 then runs actual four-arm withheld-truth matched controls and distinct-process restart behavior. No protected networking, trust keys, provider settings, service activation, canonical memory or main-branch mutations occurred in this lab.
