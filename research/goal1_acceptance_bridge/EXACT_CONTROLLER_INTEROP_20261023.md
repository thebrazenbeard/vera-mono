# Goal 1 exact evaluator reservation → local inference seam (2026-10-23)

**Verdict: research compatibility demonstrated; independent dispatch authorization STILL BLOCKED.** Do not treat this as an installed QualifiedVeraRuntime consumer, authentic remote gateway, heldout prediction, correction use or learning result.

## Exact immutable source

- Source branch `research/goal1-crossbranch-acceptance-20261023`, Vera-owned Draft PR #89.
- Integration donor #82: `packages/vera_core/src/vera_core/local_cognition.py` at `26271c5d69dee4663e07d4dbcf63efcf033626e8`; its loopback `LocalCognitionGate` was imported into isolated Lappy research Python, not installed/selected in VeraMonoPilot.
- Malaphor evaluator owner #87 head `381145f4264d95649aade312b576da9226f44c98` loaded from GitHub as actual Python code. Source SHA-256 on Lappy: `causal_trial.py` `61c1e65422c26a0add48b7055dde37a2dbdbe37feb001be03ed9f41c2cbacedf`; `dispatch_attestation.py` `fbf4c1e80747bea8a5191ddddb88299be6b3a6684b967a70de600571fe9e5df5`.
- Only #89 source/tests changed: `LocalAttemptStore.execute_controller_reserved` requires exact Malaphor `reserve_invocation` eight-field dictionary shape and checks run ID, arm, challenge ID, public features digest, exact prompt digest, selected model identity and a **caller-pinned but unverified** model-artifact digest before any local transport entry. The separate pre-dispatch `LocalAttemptStore` remains responsible for durable SQLite reservation and conservative outcomes. **Neither method authenticates the reservation issuer**, binds to a protected external service, or enforces all alternative model-call paths.

## Tests run on physical hosts

- RED: new `tests/research/test_goal1_controller_envelope.py` initially failed on VN2 with 7 errors (new method absent).
- GREEN: newest test file + source run **7/7 controller-envelope tests + 7/7 previous local attempt tests** on physical Lappy Windows and VN2 Linux each, total **14/14 per host**. The new suite rejects changed/missing/extra fields, challenge or feature substitution, wrong prompt digest, model identity/artifact substitution, malformed IDs and duplicate local reservation. It also deliberately demonstrates that a **well-formed fabricated reservation dict is accepted** by the host-local method, even though `independent_attestation` remains false. This is a counterexample, not a successful security control.

## Actual Malaphor controller source + real Lappy model

An isolated Lappy process loaded **the above exact #87 controller and verifier source**, with an ephemeral same-process Ed25519 key (never used to sign a dispatch receipt), test-only verifier SQLite, and the public **TRAIN** fixture (not secret heldout). The real `CausalTrialController.reserve_invocation` returned `run_id`, a generated `reservation_id`, `arm`, `challenge_id`, `challenge_view_digest`, `model_prompt_sha256`, `model_identity`, `model_artifact_sha256`; it persisted the evaluator-side reservation under a test-only verifier.

That envelope was passed to the new #89 `execute_controller_reserved` calling the actual #82 `LocalCognitionGate` against **Lappy loopback Ollama Qwen3 4B** with registry-reported digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`, a synthetic bounded permit and max 8 output tokens. A deliberately altered prompt was rejected **before** dispatch without a local attempt row. The original controller-issued envelope completed with:

- Local attempt status: **COMPLETED**; ID matched exact controller-generated reservation
- Response SHA-256: `559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd`; **1 byte**
- Host-local elapsed time: **5,373 milliseconds**
- Replay with same reservation denied; genuine #87 `commit_prediction` with **no signed witness** correctly rejected: `independently verified dispatch evidence required`
- Artifact identity was an explicitly **synthetic placeholder** `a` repeated 64 times; it did not verify model weights. Ollama tag digest was the registry self-report, not independently verified weight bytes. The ephemeral Ed25519 key was in the same Lappy process and cannot establish independence.

**Physical test anomaly:** after these observations, the live test process raised Windows `PermissionError [WinError 32]` deleting its evaluator SQLite tempfile because the #87 verifier SQLite connection was not explicitly closed. It did not negate the already observed live call, but **the complete live command did not exit cleanly**. A follow-up separate exact-controller test-only (synthetic FakeModel, no additional Ollama inference) added explicit reference release + GC before temp directory cleanup; it checked the reservation-to-local-COMPLETED flow, unsigned feedback rejection, and exited cleanly. These are separate evidence classes. No new real-model run was claimed by the cleanup test.

## Hostile review

> **ACCEPTED: The locally supplied controller reservation can be fabricated.** Anyone able to invoke a model directly or call `execute_controller_reserved` with a structurally correct fabricated dict can bypass any claim that the evaluator authorized the attempt. The passing compatibility test does not prove an authenticated controller or a restricted gateway.

> **ACCEPTED: A signed receipt from a same-user synthetic key proves only signature verification, not independent custody.** No signing occurred in this live test. Real qualification requires an independently administered gateway that authenticates reservation issuance **and enforces it at the only allowed dispatch boundary**, then signs observed invocation/result/timing/usage evidence with keys outside candidate control.

The next actual blocking effect is an external enforcement/attestation path owned by Integration #82 and Malaphor #87, not more caller-side hash checks. Independent evaluator-controlled private labels and four-arm causal cold-restart testing under #86 remain later gates. No main merge, service activation, key provisioning, remote ingress, production state or paid compute changes occurred.
