# Goal 1 — cold-process claim/dispatch recovery matrix (2026-10-23)

**Classification:** exact-source integration test + real-host subprocess crash observation. **No independent reservation endpoint, gateway service, production QVR route, model call, externally attested inference, private heldout result or learning qualification is demonstrated by this matrix.**

## Scope and immutable subjects

Vera-owned Draft PR #89, branch `research/goal1-crossbranch-acceptance-20261023`. Integration #82 and Malaphor #87 remain independent owned drafts; neither was modified.

Source:
- `research/goal1_acceptance_bridge/local_attempt.py`: Git blob `030743dbc384f008e513842bf758957a1bcecc2b`.
- `research/goal1_acceptance_bridge/endpoint_claim_dispatch.py`: Git blob `1eb4efc822a3df023a147bff30e667e82b0fda5a`.
- `tests/research/test_goal1_crash_recovery.py`: Git blob `c8946f66f60300db09af75c4d4ad7a060f568eca`.
- `tests/research/test_goal1_endpoint_claim_dispatch.py`: Git blob `2a12b28b58e530f195a692b1e1ebbf9688dda27e`.

Malaphor #87 has selected an independently authenticated gateway-pulled atomic reservation claim endpoint. The new crash tests run against the existing **source-only local adapter with an in-process endpoint mock**. The endpoint mock writes a synthetic marker to a temporary file; the transport mock does the same for a simulated model effect. Every crash is a separate child Python process terminated with exit 77. **These markers do not constitute external attestations or real model calls.**

## Reproduced crash windows

| Deliberate child-only hard exit | Simulated remote claim marker | Simulated model marker | Durable local row after new-process open |
| --- | --- | --- | --- |
| Before endpoint claim | Absent | Absent | RESERVED, no claim ID |
| After endpoint claim, before local claim write | Present | Absent | RESERVED, no claim ID |
| After local claim write, before model effect | Present | Absent | RESERVED, local claim ID |
| After simulated model effect, before terminal write | Present | Present | RESERVED, local claim ID |

All four survived exact SQLite readback, and every attempted reservation replay for the same run/arm/case was rejected. In particular, **the first two cases have identical local database state despite different simulated remote state**. A local journal therefore cannot decide whether the independent endpoint claimed a reservation. Even with a claim ID, it cannot establish whether model dispatch occurred.

New read-only `LocalAttemptStore.recovery_report()` classifies:
- `RESERVED_REMOTE_CLAIM_UNKNOWN`: local RESERVED, no local claim ID;
- `CLAIM_RECORDED_OUTCOME_UNKNOWN`: local RESERVED, claim ID recorded;
- `TERMINAL_OUTCOME_UNKNOWN`: local terminal unknown;
- `LOCAL_COMPLETION_UNATTESTED`: local successful completion.

Every category has `automatic_retry_permitted=False`, `independent_reconciliation_required=True`, and `independent_attestation=False`. The method neither contacts nor modifies the external endpoint and never changes a terminal state.

## Active hostile falsifier

The local database includes an editable `independent_attestation` field used historically by local readers. The new test changed that value directly to 1 in a disposable same-user SQLite file. Before the fix, the recovery report incorrectly propagated this mutable local flag as independent attestation (Lappy RED: 1 FAIL, plus a Windows fixture cleanup error). The new report intentionally emits `independent_attestation=False` even if the local flag was forged. The fixture now closes SQLite deterministically on Windows. This is a boundary *against false reporting by this method*, not protection of the underlying SQLite against tampering.

> **Accepted objection:** Local crash/restart persistence is not an independently administered claim ledger. An authentic remote endpoint may be CLAIMED even while the local row is RESERVED with a blank claim ID. Automatic retry, inferred rollback or fabricated terminal status would risk a duplicate model invocation or false provenance. The authentic endpoint, not this database, must settle that ambiguity.

> **Accepted objection:** This recovery report still cannot prove that the gateway was the sole path to the model, measure usage independently or establish actual model weights. Any future promotion must be verified against the installed selected QVR route and independently held-out evaluator evidence.

## Fresh physical verification

- TDD initial RED on Lappy: `recovery_report` missing, 5 errors. After implementation: 23/23 tests PASS and Python compilation PASS on Lappy; VN2's first run showed 29/29 including a stale retired ticket test file. These were transitional source cuts.
- Added forged-local-attestation test; Lappy RED exposed unsafe report promotion and an unclosed SQLite test fixture, then both fixed.
- **Final exact selected-source tests:** Lappy Windows 24/24 PASS, `py_compile` PASS, exit 0. VN2 Linux 24/24 PASS, `py_compile` PASS, exit 0, with explicit loading of exactly 7 controller tests + 3 crash tests + 7 endpoint tests + 7 local attempt tests. The previously retired ticket module was excluded; the executed selected-source Python and tests match the GitHub blobs above.
- No production provider, service, credentials, TLS, signing keys, model weights, canonical memory, main branch or protected endpoint was changed by this increment.

**Next owner boundary:** Integration #82 must provide a real independently authenticated, durable endpoint and sole-route selected QVR gateway, including atomic claim and independently signed terminal result. #89 can then replace the in-process client mock with a genuine authenticated client and perform a separate, observed cross-host crash/recovery trial; Malaphor #87 remains the independent verifier. The four-arm causal learning and process-restart behavior study under #86 remains BLOCKED.
