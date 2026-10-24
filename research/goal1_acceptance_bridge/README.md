# Goal 1 cross-branch acceptance seam — 2026-10-23

**Status: executable source-contract diagnostic, acceptance BLOCKED.** This is not a model run, independently witnessed QVR dispatch, protected feedback, cold-restart learning experiment, installed runtime, or AGI result. The program deliberately uses existing sources from Integration, primary learner and independent evaluator; it does not create a competing protocol.

## Exact current source subjects

All files were fetched by explicit immutable GitHub commit, SHA-256 checked on two real hosts and executed in a disposable working directory without opening a VS Code workspace.

| Owner | PR and immutable head | Source passed to diagnostic | Source file SHA-256 |
| --- | --- | --- | --- |
| Integration | #82 `26271c5d69dee4663e07d4dbcf63efcf033626e8` | `packages/vera_core/src/vera_core/local_cognition_journal.py` | `4bff14c593c58dd5e328a02ad00d4f583dac4a04f6b55aa1ccebbe8adbee5351` |
| Primary learner | #86 `27e7b2a2e312b9a969a1a70f2cc0277580b32e1a` | `research/goal1_learning_trial/revision_context.py` | `0db8df1d4710189c8c0d8feccd253b5d533cad9241315c7a2a5c4363cf258acb` |
| Primary learner | #86 (same) | `research/goal1_learning_trial/challenge_binding.py` | `4b8bd97330a81fa2ae32f6296c1db2fa7cc19a730316839ad2ba26b0e6e9d07d` |
| Mister Malaphor | #87 `1a674c1cbe80e5a5c5f915e76b521af4715d3ac8` | `research/goal1_evaluator/causal_trial.py` | `99237cfd9c07c6b064538649b97fbcb23b301da36424c648706687fd443554f7` |

Run using local copies of those four *exact files* (no credentials or response labels):

```bash
PYTHONPATH=. python research/goal1_acceptance_bridge/test_probe.py \
  --journal /absolute/path/local_cognition_journal.py \
  --revision /absolute/path/revision_context.py \
  --binding /absolute/path/challenge_binding.py \
  --controller /absolute/path/causal_trial.py
```

The test includes an exact SHA-256 pin, so replacing any source with a newer/older version fails until an explicit new evidence cut is reviewed.

### Explicit qualification-gate check

The ordinary command exiting 0 means **only that its source-contract diagnostics behaved as tested**. It does not mean the learning experiment passed. To assert actual Goal 1 qualification, rerun the same command with `--require-qualified`. This **intentionally exits status 2** and prints `GOAL1_QUALIFICATION_GATE=BLOCKED_SOURCE_ONLY` even when all four protocol tests are green. This flag is a permanently red sentinel in the present source-only probe; it must not be made green by a caller-supplied JSON or by the synthetic `FakeVerifier`. Replace this sentinel with independently reviewed evidence-consuming integration only after the true witness, hidden evaluator, matched controls and restart experiment exist.

Physical host verification at the updated `test_probe.py` source head `bc45b3c5a6275474c8911e85764de2b5ca394899`: Lappy Windows Python 3.14.5 and VN2 Linux Python 3.12.3 both observed diagnostic exit 0 (4/4 tests) and explicit qualification exit **2**, with the red gate marker. No live model inference occurred.
 `probe.py` AST-extracts **only** the actual #86 `TrialPromptReceipt` dataclass, avoiding unrelated package initialization; it executes #86 binder and #87 controller as provided. This does **not** test the full QVR composition root, actual revised-rule gate, or any local model.

## Observed behavior

- Actual #82 journal append then new journal instance readback: works with synthetic success metadata. A simulated timeout **before append** leaves no durable reservation, and `require_unused` admits the same invocation ID again. This is an intentionally simulated reproduction of the concrete source gap described in Issue #85, not a second real Ollama timeout.
- An actual #86 frozen-arm binder maps its synthetic journal entry and public challenge to exactly the seven parameters consumed by #87.
- Actual #87 rejects the unwitnessed packet and separately rejects `same_host_self_report` and `OUTCOME_UNKNOWN`, even when the verifier test double returns True.
- When the test double unconditionally returns True and the caller writes the magic `independent_dispatch_gateway` label, #87 **accepts that simulated packet**. This confirms the injected verifier must be a real separately controlled trust boundary, not that current dispatch has been authenticated. The test's positive packet must never be presented as actual model execution.

**Cross-host verification:** physical Lappy Windows Python 3.14.5, **4/4 unittest PASS**; physical VN2 Linux Python 3.12.3, **4/4 unittest PASS**. Same source SHA-256 cut and identical `qualification: BLOCKED` result. Initial Windows RED was temporary SQLite handle cleanup (`PermissionError [WinError 32]`); test harness released objects and collected connections before deletion. No change to Integration's journal or service.

## Release gate and exact owners

1. **Integration #82:** reserve a controller-issued, run/arm/challenge-bound invocation **durably and transactionally before dispatch**; record `COMPLETED` or `OUTCOME_UNKNOWN`, prohibit ambiguous retries across processes/restarts, bind observed prompt/response/model/build bytes and measured resource data. Add crash and duplicate-race tests. Do not call the current `require_unused` check a reservation.
2. **Malaphor #87:** establish a real independently controlled gateway/verifier, hidden evaluator-owned truth and durable pre-feedback chronology. The test `FakeVerifier` is *not* an implementation proposal. Preserve separation and avoid publishing held-out answers in learner-accessible files.
3. **Primary #86:** provide independently controlled placebo and shuffled arms alongside learned and frozen, run matched budgets, unseen cases, reversal and negative-transfer probes; produce a fresh process-restart **behavioral** comparison after actual accepted corrections, not just journal readback.
4. **Independent review:** verify exact witness and evaluator custody plus controls before declaring bounded learning demonstrated. Never infer AGI from a green protocol suite.

This artifact is a reproducible blocker/compatibility check under an isolated noncolliding research branch. It does not mutate #82/#86/#87, merge main, install services, change credentials, enable networking, access production memory, or incur paid inference.

> **Hostile objection, accepted:** A program that passes a test with `FakeVerifier.verify() -> True` has shown dependency injection and trust placement, not independence. The only supported claim is that the controller rejects absent/explicitly bad evidence and *would trust* its configured verifier. Real custody and causal behavior must be established outside this same-author simulation.
