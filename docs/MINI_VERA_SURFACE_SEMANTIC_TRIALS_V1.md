# Mini-Vera natural-dialogue surface probe instrument V1

**Status: source-only, synthetic tests. Not a semantic qualification or a neural training result.**

`tools/mini_vera/semantic_trials.py` composes with the existing bounded
`withheld_dialogue.compare` transport. It does **not** create tests, answers,
judgment labels, expected truths, or private history. An external evaluator
must create and hold a 2–3-turn human-authored scenario separately from its
private literal-observation probes. Both should be kept out of the repository,
model training data, student prompts, and public receipts.

The instrument has six *surface* dimensions, each using a `REQUIRE_ANY_LITERAL`,
`REQUIRE_ALL_LITERALS`, or `FORBID_ANY_LITERAL` check on a specified model turn:

1. `CORRECTION_LANGUAGE`
2. `LITERAL_REQUEST_LANGUAGE`
3. `UNCERTAINTY_LANGUAGE`
4. `PROVENANCE_LANGUAGE`
5. `ABSTENTION_LANGUAGE`
6. `EFFECT_AUTHORITY_LANGUAGE`

An evaluator-held instrument is an object with the following fields:

```json
{
  "schema": "MINI_VERA_OPERATOR_HELD_SURFACE_PROBES_V1",
  "case_id": "external-case-id",
  "case_sha256": "64 lowercase hex digits of the canonical external scenario",
  "custody": "OPERATOR_HELD_NOT_INDEPENDENTLY_ATTESTED",
  "rules": [
    {
      "rule_id": "no-effect-claim",
      "dimension": "EFFECT_AUTHORITY_LANGUAGE",
      "turn": 2,
      "predicate": "FORBID_ANY_LITERAL",
      "literals": ["I deleted your files", "I traded your money"]
    }
  ]
}
```

This example is a **syntax illustration, not a real evaluation case**.
`case_sha256` must be computed from the actual external scenario. There are no
packaged hidden cases or gold responses.

## Execution seam

The `collect_and_score(request, scenario, instrument, endpoint=...)` API first
validates the real composer request and an external rights-asserted scenario.
Default `execute=False` returns `PROBES_VALIDATED_NOT_EXECUTED` with zero model
calls and an instrument hash that an independent evaluator can externally pin
*before* running a future trial. The **production execution path is currently
blocked**: even `execute=True, host_idle_confirmed=True` refuses calls when
no injected test comparer exists. There is no authenticated host-owned lease
issuer or suitable production readiness binding for this instrument. Its
`comparer` injection exists for synthetic fake-server tests only; a caller
that supplies arbitrary executable Python has authority outside this module,
and this interface cannot sandbox such code. Test-mode injection requires the
exact `expected_instrument_sha256` before any comparison call.

The existing `withheld_dialogue.compare` remains a separately opt-in bounded,
numeric-loopback, three-arm transport with common model alias, decoding and
user turns. A live operator must separately establish its own legitimate host
authorization; this module does not grant it or provide an alternative bypass.

For offline review of an already completed trial, use
`score_completed(request, scenario, instrument, masked_sheet, private_key)`.
The report is masked by A/B/C label and does not disclose the private treatment
mapping. The key and raw rater sheet still require separate controlled custody.

The masked `cross_arm_surface_diagnostics` now separately reports
`same_turn_verbatim_masked_pairs` and
`same_turn_near_duplicate_token_overlap_pairs`, with warning codes
`CROSS_ARM_VERBATIM_RESPONSE_SAME_TURN` and
`CROSS_ARM_NEAR_DUPLICATE_LEXICAL_TOKENS_SAME_TURN`. The latter compares
distinct case-folded Unicode word-token **sets** for each A/B/C pair at the
same turn (at least eight distinct tokens per response, Jaccard overlap at
least 0.85), excluding exact normalized repeats handled by the first warning.
These are blinded repetition indicators, not treatment-unblinding, causal
estimates, or new scores; the scored rule counts and denominator are unchanged.

Two adversarial counterexamples limit the claim: reversing who acted on whom
can preserve an identical token set even while reversing meaning (overlap
1.0), while visually similar ASCII and fullwidth spellings can have disjoint
token sets (overlap 0.0). Accordingly, an overlap warning cannot establish
semantic equivalence, and absence of the warning cannot establish semantic
difference or Unicode-confusable resistance. No independent model/rater
assessment follows from either observation.

The score evaluator runs **after** all model calls. Its private surface rules
are never inserted into model prompts by this module. The result counts every
expected arm-turn response. If a transport failure/truncation aborts an
in-progress trial, the returned report includes attempted and unattempted
call counts, leaves completed-call count `UNKNOWN`, scores zero observations,
and never promotes a partial response into a valid completion.
If an existing comparer returns a generic transport/budget refusal *without*
typed attempt custody after earlier calls, the instrument still records the
scheduled failure, but marks attempted, completed, and remaining call counts
`UNKNOWN`. It must not infer them from a partial or absent transcript.

An independently protected preregistration receipt for the instrument digest
is still needed. Checking an expected digest supplied in the same mutable
process is consistency evidence, not immutable pre-inference custody.

## Strict inference limits

These are case-folded whitespace-normalized substring checks—not proof of a
correct answer, acceptance of a correction, genuinely calibrated uncertainty,
truthful provenance, epistemic support, or authorized abstention. A model may
say *I don't know* while also falsely claiming exhaustive verification; a
keyword matcher can mark the uncertainty-language indicator as present without
establishing honesty. A model could satisfy every listed literal indicator
while failing the real task. Human raters, independent external truth sources,
withheld cases, and adversarial perturbations remain necessary for semantic
qualification.

The Hyperconnectome conceptual invariants remain separate: a routed source is
not an authorization grant; resource availability does not raise epistemic
confidence; transient coalition advice is not durable memory; prose claiming
an effect is not evidence of an effect. The instrument **only tests language
surface**, and grants none of these authorities.

The private mapping and transcript receipts are operator assertions with
locally consistent hashes, not an authenticated server-identity witness or a
host-owned immutable audit record. A malicious evaluator controlling both
recorded answers and *all* corresponding sent-payload hashes can forge a
self-consistent fixture. The scorer reconstructs each treatment's per-turn
request from its own reply history and checks it against the recorded payload
digest; a partially rehashed transcript that disagrees with the later sent
request is rejected. This is consistency, **not** external authenticity.
No claims of
better natural behavior, memory continuity, or weight learning follow from a
PASS in these tests.
