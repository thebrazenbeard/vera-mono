# GOAL 1 — PR #95 / Malaphor #87 terminal V2 current-source acceptance

2026-10-24. **DISPOSITION: SOURCE-LEVEL INTEROPERABILITY PASS; INDEPENDENT EXECUTION AND LEARNING HOLD.**

## Frozen owner sources

- Vera Mono `main` at freshness check: `64c4a756a8c4d6fc791787de80303f7ee0f64869` (no merge).
- Integration owner PR #95 head `7c191b2a97063ccc5821f3f274fb4f5e47ff99ed`, chained through #94/#93/#92/#91/#90/#82. Actual gateway source `research/goal1_gateway/sole_route.py`, SHA256 `ba20f64cf92dc6e58f4c82cecbe85963a6895ab97d5a3d4abfa961708945558d`.
- Malaphor owner PR #87 head `d3784d9886a5cb071aed38fbe6b91f8ac1d6bbcf`. `research/goal1_evaluator/terminal_v2.py`, SHA256 `153aed3f37e013f9fbb213af2539a1984bebf3086a1d77544d189e0c8104d187`. Malaphor's unchanged reservation claim helper from frozen source SHA256 `eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc`.
- Vera-owned Draft/HOLD PR #89 additive `research/goal1_acceptance_bridge/terminal_v2_converged_readback.py` and `tests/research/test_goal1_current_head_crossbranch_gate.py`. No owner branches modified, no protected effects.

## New physical cross-branch experiment

On each of **Lappy Windows** and **VN2 Linux**, the isolated probe verified exact source-byte hashes, loaded exact #95 `GatewayDispatch` and `GatewayAttemptStore`, and loaded exact Malaphor V2 verifier and reservation claim helper. The endpoint, model backend, and Ed25519 signing key were test-only synthetic same-process objects; no real model or independently operated authority was used.

Each case wrote to a fresh temporary SQLite file. A *new separate GatewayAttemptStore instance* reopened that file and called #95's actual `signed_terminal(invocation)`, retrieving original canonical payload bytes plus detached signature. The probe compared the retrieved bytes to the **actual signer-input bytes** and the persisted payload hash, ensuring it did not invent a reserialized receipt.

Three scenarios, all SOURCE accepted on both physical hosts:
1. `COMPLETED_0MS`: exact injected source monotonic observations span 654,321 nanoseconds. #95 signs `gateway_wall_ms=0` by truthful millisecond floor division. Malaphor exact #87 V2 accepts untouched signed payload and returns `VERIFIED_COMPLETED`, `qualified=false`.
2. `COMPLETED_1MS`: span 1,654,321 ns. Signed `gateway_wall_ms=1`; V2 accepts untouched bytes and returns `VERIFIED_COMPLETED`, `qualified=false`.
3. `OUTCOME_UNKNOWN`: inert backend raises synthetic timeout; durable signed UNKNOWN has null response SHA and null usage; V2 returns `VERIFIED_OUTCOME_UNKNOWN`, non-score, no retry, `qualified=false`.

For **each** scenario, a fake claim-evidence verifier's substituted claim ID was rejected by V2, the original signed wire with appended whitespace was rejected, and changing the local SQLite reservation `run_id` after terminal storage caused #95's signed_terminal readback to fail. The last is a **local consistency guard**, not independent custody or proof against an attacker who controls source, signer key and DB. Test-only source clock injection was restored after execution and never touched a selected live gateway or real provider.

## Strict separation of gates

The new `--require-source` CLI exits **0** only when all three exact-source cases are directly accepted and the negative checks pass. The `--require-independent` CLI **always exits 2**: this local script cannot prove independently issued durable claim, independently controlled signer, selected QVR gateway-only route, loaded model hardware behavior or private evaluator truth. Tests exercise missing case, omitted tamper check, false `qualified=true`, asserted independent custody and substituted source hash, all fail closed.

**Final physical verification at this exact source cut:**
- Lappy Windows: **63/63 selected Goal 1 tests PASS**, new source CLI `SOURCE_EXIT=0`, independent strict `INDEPENDENT_EXIT=2`, `py_compile` PASS, physical command exit0.
- VN2 Linux: **63/63 selected Goal 1 tests PASS**, source CLI `SOURCE_EXIT=0`, independent strict `INDEPENDENT_EXIT=2`, `py_compile` PASS, physical command exit0.
- These 63 are host-workspace selected tests (previous 58 plus 5 new policy tests); they do not prove merged repository CI, deployed gateway or actual learning.

## Accepted hostile review

> Same-process fake claim verification returns whatever `expected_binding` it is given and is not evidence of a remotely authenticated, durable `RESERVED → CLAIMED` transition. **ACCEPTED.** It establishes only that the source verifier behaves correctly when *supplied* a correctly bound witness.

> Both local SQLite and terminal signer are controllable in the synthetic harness; a common owner could replace the local journal and sign another terminal. **ACCEPTED.** Local consistency checks are not an external trust boundary. Claim authority/signer custody must be separately controlled and verified.

> Cross-branch timing/V2 compatibility now passes but the learner can still reach raw Ollama on Lappy's ordinary-user account, and no independently selected/installed `QualifiedVeraRuntime` gateway route is observed. **ACCEPTED.** Source compatibility is insufficient to qualify an inference or learning.

> #87's public four-case synthetic holdout is unsuitable for unseen learning qualification; the new private corpus has not been created under independent custody. **ACCEPTED.** No trial scores are qualified by this work.

## Next necessary boundary

Integration #95 owns source gateway behavior; Malaphor #87 owns independently authenticated evaluator claim-truth and private holdout custody. Before controlled learning:
- Independently operated durable claim-status/claim-evidence READ endpoint, authenticated remote identity and replay/ambiguous-state reconciliation across restart.
- Separate gateway/learner/model process privileges, protected keys, raw Ollama denial for **actual selected learner principal** and authorized gateway-only physical model invocation.
- Signed terminal measured resource/report provenance and independent verifier/key trust readback.
- Frozen candidate and genuine privately custodied never-seen challenges, matched FROZEN/LEARNED/PLACEBO/SHUFFLED arms, controlled restart and negative-transfer/reversal scoring.

The earlier PR #90 / first-V2 0ms timing disagreement is **historical negative evidence**, not the current #95/#87 source disposition. Do not silently reinterpret it as a current blocking mismatch.

No merges, service activation, ACL/firewall, mTLS credentials, key/trust custody, Ollama provider, production model, canonical memory or private material publication occurred.
