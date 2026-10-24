# Goal 1 — cross-process signed-terminal restart and common-owner key-custody falsifier

Date: 2026-10-24. Status: **PHYSICAL SOURCE-PROCESS RESTART PASS; EXTERNAL TRUST AND LEARNING HOLD**.

## Exact source and owner boundary

- Vera Mono `main`: `64c4a756a8c4d6fc791787de80303f7ee0f64869`.
- Integration Draft PR #95: `7c191b2a97063ccc5821f3f274fb4f5e47ff99ed`. Actual `research/goal1_gateway/sole_route.py` SHA256 `ba20f64cf92dc6e58f4c82cecbe85963a6895ab97d5a3d4abfa961708945558d`.
- Malaphor Draft PR #87: `d3784d9886a5cb071aed38fbe6b91f8ac1d6bbcf`. Actual `research/goal1_evaluator/terminal_v2.py` SHA256 `153aed3f37e013f9fbb213af2539a1984bebf3086a1d77544d189e0c8104d187`. Claim helper exact unchanged SHA256 `eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc`.
- Vera-owned Draft PR #89 adds `research/goal1_acceptance_bridge/cold_process_signed_terminal_probe.py` and `tests/research/test_goal1_cold_process_gate.py`. These do **not** modify any delegated owner source or protected host service.

No new Integration/Malaphor source head was present at the turn's initial refresh. Central Blotter was inspected read-only through sequence **1314**, no authenticated writer used.

## Real physical subprocess/restart experiment

On physical Lappy Windows and VN2 Linux, the source-pinned probe executed separate emitter and reader OS processes, not merely new Python objects within one interpreter.

1. The emitter invokes Integration's exact `GatewayDispatch.execute` with one synthetic `CLAIMED` response, inert test backend and short-lived Ed25519 signer. It writes the original terminal bytes and signature into #95's durable SQLite journal, writes *only* a test public key and expected binding into a disposable scratch directory, and exits **without exporting the test private key**. The client endpoint is a fake local object; no mTLS authority or real model was contacted in this test.
2. A separate OS reader process reopens the journal using #95's actual `GatewayAttemptStore.signed_terminal`. It passes the original persisted signed bytes and detached signature into Malaphor's exact V2 verifier with a **same-user fake claim authority**. Source-level `VERIFIED_COMPLETED` and `VERIFIED_OUTCOME_UNKNOWN` are admitted, both `qualified=False`; UNKNOWN stays non-scoring and non-retryable.
3. A new same run/arm/challenge reservation is refused after restart without another backend effect, even when an invocation and reservation ID are changed. Tampered wire, changed signature, altered fake claim ID and a contradictory local SQLite run ID are rejected in independent reader subprocesses. The inconsistent local metadata probe runs against disposable test SQLite only.
4. **Strong hostile negative control:** After ordinary tamper cases, an attacker controlling the entire disposable local test directory replaces a terminal receipt with different synthetic content, re-signs it using a different ephemeral private key, rewrites SQLite original terminal bytes, text, digest and signature, and replaces the locally supplied test public key. Malaphor's verifier then accepts the changed receipt under that newly substituted key and a fake claim authority. This is **NOT a cryptographic vulnerability**: the verifier was supplied a new trust root by the same adversarial source. It is positive evidence that local signature + locally supplied trust root + locally consistent SQLite do **not** establish independent external effect.
5. **Pinned-key contrast:** In that same test process, a snapshot of the original pre-rewrite public key is passed to the exact V2 verifier against the forged message. It rejects the new signature. The original-key snapshot in this test is *not* independently administered custody, but demonstrates that an appropriately fixed verifier trust root is the load-bearing difference.

All synthetic data, keys and rewrites remain inside automatically deleted test scratch directories; no real credentials, public user data, model response or protected repository history were changed. Public keys are not secrets. A reader running as another subprocess under the same OS user is not an independently privileged custodian.

## Verification and reporting

- First source probe without the stronger forged-local-root control passed physically on Lappy and VN2 for both terminal states.
- New test-first `tests/research/test_goal1_cold_process_gate.py` initially exposed a false-positive source gate when the full-directory rewrite observation was absent: **2 RED tests** on Lappy. The gate now requires the adversarial rewrite to be *observed and admitted* under substituted local key, instead of claiming security from missing evidence.
- A further new test reproduced a missing-original-key contrast false-pass: **1 RED test** before correction. The gate now requires original pinned test-key rejection.
- Final focused policy suite **7/7 PASS** on physical Lappy Windows and **7/7 PASS** on physical VN2 Linux. Physical separate-process source probe emitted two complete reports with `common_owner_rewrite_accepted=true`, `original_pin_rejects_rewrite=true`, `source_restart_replay_refused=true`, and `qualified=false` on each host.
- Final selected Goal 1 unit suite: **70/70 PASS** on Lappy Windows, Python compilation PASS, process exit0. **70/70 PASS** on VN2 Linux, Python compilation PASS, process exit0.
- Source-only mode `--require-source` exits **0** for verified synthetic process mechanics; `--require-independent` exits **2** deliberately. This strict independent gate cannot be satisfied by report or same-user actor flags.

This result must NOT be called an actual independent runtime trust break, externally measured inference, qualified `vera_core.QualifiedVeraRuntime`, or a demonstrated change to deployment identity/route. The counterexample assumes control of the test-local trust root; it explicitly explains why real deployments must pin independently controlled signer identity outside that domain.

## Hostile self-review, accepted

> Distinct subprocesses, durable SQLite, successful Ed25519 signature verification and all green tests could seem like independent witnessing. **Accepted objection:** all test processes are within the same operator privilege/custody domain and the synthetic public key is read from that domain. A full-domain attacker can substitute both signed bytes and local trust root while maintaining internal consistency.

> The attacker changes the supposed trusted verification key, which a correctly deployed independently pinned verifier would not permit. **Accepted:** the experiment demonstrates a missing *deployment custody precondition*, not that Malaphor's verification algorithm is incorrect. The pre-attack original-key check rejects the substituted message as expected.

> Tests were only synthetic endpoints with inert models. **Accepted:** no model, hidden heldout truth, independent ledger, private signer, independently restricted learner or genuine causal learning trial was observed.

## Remaining gates and delegated owner actions

- Integration #95 and Malaphor #87: specify and implement the separately administered **authenticated durable claim-evidence READ endpoint**, claim/attestation binding and lost-reply reconciliation across restarts. No learner-provided trust key or same-host mutable flag may qualify a claim. Source-only same-host mTLS tests do not install remote custody.
- Integration: actual OS security principals must separate gateway/learner raw Ollama access; ordinary Lappy-user direct model POST remains physically demonstrated. Protected credential/ACL/TLS/service cutover requires Patrick's explicit target and effect authority before execution.
- Malaphor: independent private heldout challenge/label custodian and later matched-armed scoring; the four public synthetic labels cannot qualify learning.
- Vera #89: preserve cold-restart and hostile local-trust negative controls as **source evidence**, never let positive source checking enable independent learning.
- VN1 independent adversarial reviewer still needed for actual host isolation and custody; VN2 execution alone is not VN1 reviewer authority.

No merge, deployment, TLS credential provisioning, signer key installation, ACL/firewall changes, model provider call, learning-trial scoring, canonical memory write, or publication of private material performed.
