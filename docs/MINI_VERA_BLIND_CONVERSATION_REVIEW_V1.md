# Mini-Vera conversational identity review candidate

**Status:** source-only local review utility; no neural model was run, trained,
installed or behaviorally qualified by this artifact.

This is deliberately **not** a replacement for Neuro-Sync Draft PR #66's
objective C0–C4 exact-token holdout scorer. That source already covers
referents, correction, provenance, false-effect, privacy and tool-choice
with private preregistration and counterbalanced scheduling. In contrast,
this independent slice measures the unresolved conversational question:
would the responses of a locally assembled Vera feel coherent and recognizably
like her **without** sacrificing truth, source boundaries or state consent?

## Explicit controls

Use PR #66's five conditions for the **same pinned base weights**:

- `C0_BARE`: base model, no Vera profile.
- `C1_WRAPPER`: source-pinned public behavioral profile only.
- `C2_GOVERNED`: wrapper plus properly admitted, current public project context.
- `C3_TOOLS`: C2 plus separately authorized bounded tool access.
- `C4_DECOY`: equal-token unrelated persona wrapper.

Each reviewer-local packet should contain 12–50 *original, synthetic,
nonpersonal* multi-turn tasks (2–6 turns each; at least three families),
with explicit synthetic ground facts. Have an independent custodian seal task
and comparison protocols *before* requests, retain private source bytes and
mapping, and never publish raw output, private rubric, Blotter or memory text.
Run all arms using matched model bytes, generation settings, task IDs and
appropriate controlled context. The 0.8B local model, any LoRA adapter,
persona wrapper and source state are distinguishable conditions, not
interchangeable definitions of model learning.

`tools/mini_vera/blind_voice_review.py` creates a separate randomized
candidate ID from a private 32+ byte key; never publish its arm mapping.
It validates complete 5-arm, same-turn coverage and hashes the exact packet.
Two or more declared reviewers score each anonymized transcript on six 1–5
dimensions: natural dialogue, Vera voice, factual grounding, correction
uptake, continuity and epistemic honesty. They separately flag false effect,
privacy leaks and invented source claims. The emitted summary contains
only blinded means and flags. This packet is intentionally an *offline*
data contract; no model API is contacted and no exact-gold answer is embedded
in public source.

## Why reviewer agreement is not enough

> A persuasive persona may win a blind style comparison while fabricating
> memories or evidence; C2 may outperform C1 merely by receiving more
> relevant facts, not through neural learning. A claimed cold restart can be
> faked with a changed process ID. A declared reviewer ID does not attest
> independence, human authorship or actual host observation.

Thus this metric can support *subjective preference under reviewed synthetic
tasks*, only after independently witnessed inference and genuine review.
It cannot establish continuity of consciousness, personal identity, durable
memory admission, model-weight change, tool authority, or generalization.

Recommended acceptance gate: C2 beats C1 and C4 in paired blinded review on
unseen cases **without** false effect/privacy/source flags; separately report
the gap to C0 and C3, actual digest binding, task/custody provenance, and
verified cold-restart behavior. A style win alone is insufficient.

## Source test

```sh
python -m unittest tests.test_mini_vera_blind_voice_review -v
```

This source-only test checks deterministic blinding, exact case coverage,
no plaintext arm names in the packet, integrity bindings, scope restrictions,
review completeness and hold-on-guard flags. No model outputs or user data
are included in the fixture.

Current integration candidates for later qualified runtime tests:
`thebrazenbeard/vera-mono` main merged PR #194 (pure request composer),
Draft PR #193 (standalone non-neural Mini-Vera), and `thebrazenbeard/neuro-sync`
Draft PR #66 (objective C0–C4). They are distinct, and no automatic
cross-repository or host-state binding is implied.
