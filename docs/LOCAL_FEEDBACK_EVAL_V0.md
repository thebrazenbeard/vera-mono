# Local feedback adaptation: synthetic evaluation boundary (V0)

`vera_memory.local_feedback_learning` is a small executable mechanism probe for
**one** kind of adaptive behavior: exact-cue retrieval. It is not an autonomous
self-training Vera model. It does not observe conversations, tune model weights,
write to disk, connect to Ollama, admit autobiographical memory, choose truth,
or receive tool/effect authority.

## Sequence

1. An external host obtains specific opt-in consent and separately reviews
   privacy/redaction and source provenance. Each candidate sample carries
   nonempty references to those reviews. The probe checks their structure;
   **it cannot authenticate the references or perform redaction**.
2. `stage((FeedbackSample(...),))` builds an unactivated, bounded revision from
   the currently approved exact-cue map. A staged revision is invisible to
   `lookup`.
3. `evaluate(revision, heldout_cases)` compares active and candidate responses
   before any approval. Held-out case IDs and source IDs must be disjoint from
   active and candidate training identities. Duplicate held-out source IDs or
   normalized cues are rejected even if their case IDs or expected answers
   differ; contradictory labels cannot inflate apparent independent evidence.
   Previously approved holdouts become retained immutable canaries in
   **every subsequent evaluation**, so omitting one cannot conceal a regression.
   Every historically approved canary must pass the candidate even after a
   rollback leaves the active baseline failing it. **Every case** in the
   combined heldout suite must pass; partial passes never qualify or become
   permanent canaries. The candidate must also strictly improve the baseline.
   After one approval, a caller may pass
   an empty new suite to re-check retained canaries; the bounded cumulative
   suite cannot exceed 128 distinct cases.
4. `approve(evaluation, approval_ref=...)` changes only this Python object's
   in-process lookup behavior. A forged, stale, failed, or superseded
   evaluation is rejected. `rollback(prior_revision, approval_ref=...)`
   restores an explicitly previously approved in-process version.

No approval ref is self-authenticating; a host must verify operator identity
and consent outside this module. Source/case separation is identity-based,
not a semantic contamination detector. Case identifiers, source identifiers,
and the holdout contents remain caller-controlled: this is not an independent
qualification service. Rollback can deliberately restore earlier lower-scoring
behavior, but any later new approval must pass every historical canary.
A tiny exact-text holdout demonstrates mechanical regression fencing, not
generalization or real-world correctness.

## Synthetic smoke check

```python
from vera_memory.local_feedback_learning import (
    FeedbackSample, HeldoutCase, LocalFeedbackLearner,
)

learner = LocalFeedbackLearner()
before = learner.active_revision
revision = learner.stage((FeedbackSample(
    sample_id="synthetic-train-1", source_id="train-group",
    cue="color of a ripe banana", answer="yellow",
    consent_ref="synthetic-opt-in", privacy_review_ref="synthetic-reviewed",
    provenance_ref="synthetic-fixture",
),))
assert learner.lookup("color of a ripe banana") is None
evaluation = learner.evaluate(revision, (HeldoutCase(
    case_id="synthetic-holdout-1", source_id="holdout-group",
    cue="color of a ripe banana", expected="yellow",
),))
assert evaluation.qualified
learner.approve(evaluation, approval_ref="synthetic-operator-review")
assert learner.lookup("color of a ripe banana") == "yellow"
learner.rollback(before, approval_ref="synthetic-operator-rollback")
assert learner.lookup("color of a ripe banana") is None
```

Run the synthetic regression tests from the repo root with
`python -m pytest -q tests/test_local_feedback_learning.py` (with the repo's
normal test dependencies installed).

## Durable runtime remains separate

This evaluation-only probe deliberately forgets every sample and review on
process exit. A production Lappy conversation-memory adapter must instead
use existing governed `vera_memory.MemoryLedger` admission and the durable,
revision-bound `vera_memory.DurableLearnedInfluenceGate` qualified review and
consumption semantics. Their authority and privacy references also require
independent host verification. Such an adapter requires its own cross-restart,
user-consent, revocation, holdout, crash and privacy tests before qualification.

Evidence ceiling: **synthetic test evidence for a process-local exact-cue
retrieval update, not actual local deployment, private-data qualification,
continuous weight learning, or general intelligence.**
