# Goal 1 evaluator falsification scaffold

Status: **research-only scaffold; not independent evaluator custody, not a QVR integration, and not a self-learning qualification result.**

## Scope

- Learner-facing cases omit answer labels and evaluator-only `split`, `family`, and `rule_version` metadata; IDs are opaque and split-independent.
- Prediction receipts hash candidate, case, prediction, prompt digest, caller-supplied sequence, and caller-reported budget into an **unkeyed SHA-256 self-consistency digest**; this does not prove authenticity or chronology.
- The scorer takes predictions but no caller-supplied outcome labels; it scores against its own answer-key map.
- It rejects malformed receipt fields, a structurally post-outcome commit, receipt/prompt tampering, incomplete qualification batches, per-call scoring-split substitution, and same-instance replay.
- The scoring split is configured when the evaluator is constructed, rather than selected on each scoring call; this only helps if evaluator construction/configuration is controlled independently.
- A SQLite event journal can be reopened by a distinct OS process and checks a local hash chain.
- A tiny synthetic rule-reversal fixture demonstrates that a stale policy can fail after the rule flips.

## Reproduce

From repository root:

```bash
python -m unittest discover -s tests/research -p 'test_goal1_evaluator.py' -v
```

The initial isolated local run on 2026-10-23 produced **10 tests, 10 passed** before the subsequent adversarial hardening. The current branch adds metadata/split leakage, malformed-receipt, duplicate-sequence, non-finite JSON, scoring-split-substitution, chronology-forgery, candidate-ID replay-rotation, and budget-underreporting cases; those additions are not locally rerun in this session and require current-head CI confirmation. This is source-level verification of a synthetic scaffold, not a run of the full repository suite.

## Deliberate counterexample and limits

`test_compromised_truth_custodian_can_still_fabricate_a_win` is an intentional passing exploit demonstration: if the evaluator's answer key is poisoned before construction, an always-A candidate appears perfect. The test is meant to keep the trust boundary visible, not to claim poisoning resistance.

The receipt's SHA-256 field is an **unkeyed self-consistency digest**, not a cryptographic commitment to an independently timestamped event: anyone can observe an outcome, then choose a prediction and earlier sequence, recompute the digest, and claim it was committed before the outcome. The chronology-forgery test demonstrates that limitation. Candidate IDs are also caller-authored; the replay-rotation test demonstrates that an identical prediction batch can be rescored under a new claimed ID. The scorer revalidates exact field types and non-negative budget values even when callers construct `PredictionReceipt` directly, but input validation does not establish authenticity, chronology, or stable candidate identity.

The event journal rejects non-finite JSON values but remains mutable by a same-privilege writer who can rewrite the SQLite file and recompute the hash chain. Duplicate sequence values within a batch are rejected, but `commit_sequence` is still caller-supplied; it is not an externally attested clock or trusted event sequence. Budget units are also caller-reported metadata, not actual host-side metering, and can be underreported. In-process Python object privacy is not isolation. Replay state is in memory and does not provide durable cross-process nonce consumption. The restart test proves only that journal records survive a separate-process reopen, not that learned behavior survives restart.

This scaffold does **not** invoke QVR or a model, apply a correction, implement an adaptive learner, establish hidden-answer secrecy against a malicious host, compare learned/frozen/placebo/shuffled candidates, quantify statistical confidence, or qualify transfer. Those are explicit next gates, not implied capabilities. Private evaluator truth and credentials must not be committed here.
