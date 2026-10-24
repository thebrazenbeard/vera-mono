# Goal 1 cross-owner exact signed terminal V2 acceptance — 2026-10-24

**Disposition: SOURCE V2 POSITIVE SAMPLES INTEROPERATE; STRICT SOURCE COMPATIBILITY STILL HOLD; INDEPENDENT EXECUTION/LEARNING NOT QUALIFIED.**

## Immutable owner source and scope

- Vera Mono canonical `main` at refresh: `64c4a756a8c4d6fc791787de80303f7ee0f64869`.
- Integration owner Draft PR #90 frozen head `5758bdd07f3ef0020f8e7318f8b277ab7da6c72c`, `research/goal1_gateway/sole_route.py` SHA-256 `27f6f7832d4ea5f2da0f8616fe4f475d6953861910bd2f0e1328d22d35d970ce`.
- Malaphor owner Draft PR #87 **NEW V2 head** `c46d95156359d25a404e400695d7f13653b3e490`, `research/goal1_evaluator/terminal_v2.py` SHA-256 `cd6923597ada9bcfc07011fab43fbb75d8967f975590313e069cefa7e8ba81dc`.
- Integration owner Draft PR #92 new head `54bc1537f2a8f0a6965d546d20e420c52532ffad`, a fail-closed direct-Ollama socket preflight diagnostic. Lappy observed raw port accessible, NOT an OS enforcement change.
- Vera-owned PR #89 added `research/goal1_acceptance_bridge/terminal_v2_source_interop.py` as an opt-in isolated research executable. It never imports or modifies delegated branch source in this repository; it requires exact owner source bytes staged locally, pinned by SHA256. Synthetic same-process ephemeral Ed25519 keys, fake endpoint and inert model backend. No independent authority, live inference, private corpus, real selected QVR or production effects.

## Physical cross-owner experiments

Actual owner source under the probe:

1. #90 GatewayDispatch creates durable `RESERVED`, obtains a synthetic `CLAIMED`, records local claim ID, invokes the inert fake backend and calls the injected signer with the **exact canonical terminal UTF-8 bytes**.
2. Probe captures **the signer's original byte argument**, compares it to the SQLite persisted canonical `terminal_json` bytes, passes that original signed byte array + detached signature directly to Malaphor's new `verify_terminal_v2` without a dict-to-dict transformation.
3. Under a synthetic same-process `verify_claim_evidence` double, Malaphor V2 accepts #90 original signed `COMPLETED` (`VERIFIED_COMPLETED`, `qualified=False`, `score_eligible=True`) and honest signed `OUTCOME_UNKNOWN` (`VERIFIED_OUTCOME_UNKNOWN`, no score/prediction, no retry). Changed claim ID from the fake claim verifier and appended noncanonical byte whitespace each cause ValueError.
4. **Separate observed negative condition:** Initial unmodified fast inert backend completed in less than one whole millisecond on physical Lappy and VN2. #90's `(time.monotonic_ns()-start)//1_000_000` emitted a valid signed `gateway_wall_ms=0`, which exact Malaphor V2 rejects with `COMPLETED gateway wall time must be positive`. This was an ACTUAL red cross-owner source test on both hosts, not a hypothetical.
5. For source-format positive demonstration, the inert fake backend was changed to sleep 5ms (actual measured positive interval). Both original signed outcomes were then directly accepted by V2 on Lappy and VN2, no resigner or schema translator. This positive fixture does NOT repair the real zero-millisecond incompatibility.
6. For deterministic independent reproduction, the probe injects `monotonic_ns=1000` only into the isolated #90 execute function's dependency during one disposable fake inference; the exact #90 code signs `gateway_wall_ms=0`, exact #87 V2 rejects it with the specific positive-duration error on both hosts. The synthetic injected clock is not a real provider timing observation.

Physical **Lappy Windows** and **VN2 Linux**: diagnostic mode `exit=0` with both positive outcome cases accepted and explicit zero-ms owner boundary; **strict `--require-compatible` exits 2** because the zero-ms signed completion remains rejected. Neither source module was changed in owner branches.

## Hostile review and claim limits

> **ACCEPTED:** A synthetic claim verifier returning the input's expected fields could accept a forged authority claim. This test is **only** signed-byte **SOURCE INTEROPERABILITY**. A valid Ed25519 signature from a same-process test key proves no independently controlled signing custody, endpoint authorization, model effect, measured resource provenance or learner privilege isolation. Every result explicitly reports `independent_custody=False` and `learning_qualified=False`.

> **ACCEPTED:** A zero whole-millisecond duration can correctly describe a sub-millisecond measured elapsed time at millisecond integer precision. Blindly promoting `0` to `1` without specifying a round-up precision contract could misrepresent the measurement. Integration and Malaphor must explicitly agree whether V2 accepts nonnegative integer gateway ms, whether gateway rounds up and labels precision, or whether higher-resolution timestamps are signed and checked. Do not fabricate chronology or silently weaken the verifier.

> **ACCEPTED:** A score-eligible source-signed COMPLETED response is not a qualified score. A real independently administered claim authority with durable atomic CLAIMED evidence, selected restricted learner process denied direct Ollama access, genuine independent signing key custody, private unseen heldout data and four-arm cold-restart causal trial are all still absent. PR #92's socket preflight is a failure detector, not the access-control mechanism.

## Cross-owner next acceptance

- **Integration #90 / #91 / #92:** reconcile gateway wall time format and ensure exact canonical bytes originally signed are transported intact, with signed-byte SHA256 and independently authenticated claim evidence. Do not edit Malaphor-owned verifier without handoff, forge unknown usage, or deploy protected host controls without exact Patrick authorization.
- **Malaphor #87:** review the `0 ms` semantics, preserving truthful timing and independent acceptance; keep private datasets off candidate-readable source/hosts, claim-verifier custody separate.
- **Vera #89:** repeat source-pinned cross-host negative and positive controls on frozen owner heads after convergence. Do not promote positive source compatibility into independent execution proof.
- **Learner #86:** four-arm matched-budget hidden-truth trials remain blocked, and published four-case synthetic fixture is not a private holdout.

No merge, main mutation, runtime deployment, TLS credential provisioning, trust/ACL/firewall changes, Ollama provider modifications, model training or canonical memory effect performed.
