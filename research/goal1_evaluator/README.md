# Goal 1 evaluator falsification scaffold

Status: **research-only scaffold; not independent evaluator custody, not a QVR integration, and not a self-learning qualification result.**

## Scope

- Learner-facing cases omit the answer label.
- Prediction receipts bind candidate, challenge, prediction, prompt digest, commit sequence, and budget into a SHA-256 commitment.
- The scorer takes predictions but no caller-supplied outcome labels; it scores against its own answer-key map.
- It rejects a structurally post-outcome commit, receipt/prompt tampering, incomplete qualification batches, and same-instance replay.
- A SQLite event journal can be reopened by a distinct OS process and checks a local hash chain.
- A tiny synthetic rule-reversal fixture demonstrates that a stale policy can fail after the rule flips.

## Reproduce

From repository root:

```bash
python -m unittest discover -s tests/research -p 'test_goal1_evaluator.py' -v
```

The initial isolated local run on 2026-10-23 produced **10 tests, 10 passed** (Python stdlib only). This is local source-level verification of this scaffold, not a run of the full repository suite.

## Deliberate counterexample and limits

`test_compromised_truth_custodian_can_still_fabricate_a_win` is an intentional passing exploit demonstration: if the evaluator's answer key is poisoned before construction, an always-A candidate appears perfect. The test is meant to keep the trust boundary visible, not to claim poisoning resistance.

The receipt's SHA-256 field is an **unkeyed self-consistency digest**, not a cryptographic commitment to an independently timestamped event: anyone can choose a prediction and sequence, recompute the digest, and claim it was committed before the outcome. The explicit chronology-forgery test demonstrates that limitation. The scorer now revalidates exact field types and non-negative budget values even when callers construct `PredictionReceipt` directly, but this input validation does not establish authenticity or chronology.

The event journal is mutable by a same-privilege writer who can rewrite the SQLite file and recompute the hash chain. `commit_sequence` is only structurally checked by this scaffold; it is not an externally attested clock or trusted event sequence. In-process Python object privacy is not isolation. Replay state is in memory and does not provide durable cross-process nonce consumption. The restart test proves only that journal records survive a separate-process reopen, not that learned behavior survives restart.

This scaffold does **not** invoke QVR or a model, apply a correction, implement an adaptive learner, establish hidden-answer secrecy against a malicious host, compare learned/frozen/placebo/shuffled candidates, quantify statistical confidence, or qualify transfer. Those are explicit next gates, not implied capabilities. Private evaluator truth and credentials must not be committed here.
