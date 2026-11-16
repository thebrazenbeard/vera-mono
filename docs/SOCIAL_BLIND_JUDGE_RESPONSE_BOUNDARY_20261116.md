# Blinded local social-review response boundary (source-only, 2026-11-16)

## Concrete falsifiers

The earlier judge_social_multiturn_blind.py used the requested JUDGE_MODEL
and its /api/tags digest as row metadata without checking which model
the /api/chat response claimed. A stub responding as another model was still
logged under the requested judge name and digest.

The audit also reconstructed the reported verdict using json.loads.
A raw response containing two winner keys was accepted when its
judgment matched the parser's last-key-wins interpretation. Neither
a self-reported model tag nor a parser agreement authenticates a model.

## Narrow behavior change

- Fail before writing a judge row if the response reports a different/missing
  model, unfinished response, unexpected termination, invalid token count,
  non-assistant role, unexpected tool calls, or blank content.
- Parse raw judge JSON with duplicate-key and nonstandard-number rejection.
  Nested duplicate members are rejected as well.
- Preserve raw malformed judge text in the record with parsed_valid=false
  and judgment=null, rather than converting ambiguity into a verdict.
- Reparse the archived raw response with the same strict parser in
  audit_social_multiturn_review.py; reject a claimed parsed verdict
  inconsistent with that raw response.
- Keep the existing archived generations, blind mappings, rubric and scores
  unchanged. No new fields or schema versions.

## Test evidence

Synthetic RED before changing production code:
py -3.12 -m pytest -q tests/test_social_blind_judge_boundary.py --tb=short
returned exit 1, 17 failures and 2 passes. Failures demonstrated
a logged mislabeled judge and acceptance of duplicate-key evidence.

Synthetic GREEN after the minimal source fix:
py -3.12 -m pytest -q tests/test_social_blind_judge_boundary.py tests/test_social_multiturn_review_contract.py --tb=short
returned exit 0, 24 tests and 20 subtests passed.
Includes actual main() integration using a mocked localhost transport,
and re-audits the original archived 12-case blind/reversed evidence.

## Qualification limits

This is **source and parser integrity**, not independent model custody,
independent evaluation, behavioral improvement, installed Vera qualification,
autobiographical continuity, consciousness, or production-runtime effect.
The localhost response can still claim a false model identity; the same actor
can still forge both raw evidence and parsed claims. Those need separate
witness custody and independent, held-out review.
