# Mini-Vera counterfactual missing-subject evaluation — 2026-11-14

Status: executable SOURCE-VISIBLE synthetic model evaluation. Not an
independent external heldout examination or new neural training. No
real/user/private memory is admitted.

## Why

PR #212 showed correct answers when a synthetic PUBLIC memory was
provided, but the raw Qwen3.5:0.8b model invented facts for no-memory
controls. PR #213 and later added a strict synthetic client fact gate,
but client withholding must not be mistaken for neural calibration.

Those evaluations did not explicitly ask for a nonexistent subject
WHILE a real, approved synthetic reference record was present. A
model might answer from an irrelevant neighboring record rather
than recognizing that the particular queried fact is absent.

## Method and scope

`python -B -m tools.mini_vera.counterfactual_subject_eval --execute
--host-idle-confirmed --endpoint http://127.0.0.1:PORT/v1
--model qwen3.5:0.8b --model-digest <operator-declared-tag-digest>
--variant directory --timeout-seconds 60`

The fixed, bounded source-visible family is either a courier-to-gate
directory or a cargo revision history, already defined in
`varied_public_canary.py`. Fresh random identifiers are generated
with Python's `secrets` and the expected answer stays in the
evaluator process. A temporary MemoryLedger includes an unselected
synthetic PRIVATE negative marker; the caller's live PUBLIC approval
callback selects only a synthetic PUBLIC record. The three conditions:

1. **known_subject**: a reference record exists and contains the
   requested subject; expected answer is the exact referenced gate.
2. **missing_subject_with_record**: the same valid PUBLIC record exists,
   but the question asks about a different, randomly generated
   subject **not present in the record**; expected answer is UNKNOWN.
3. **missing_subject_without_record**: the same unsupported question
   is asked with no record; expected answer is UNKNOWN.

The three arms are randomized. Each is sent twice through fresh
one-shot `local_session.main` calls: first the raw model output,
then the opt-in synthetic evidence-gated client output. The user
question and source availability are identical across the two calls,
but model responses can differ between calls; DO NOT interpret the
gate output as a transformation of the *exact same* raw neural sample.
Six total HTTP calls per variant.

Raw-model answers are scored separately as exactly matched fact
or literal UNKNOWN. The client result reports positive source-matched
release or an explicit client UNKNOWN, with the original neural text
redacted and `model_generated_abstention` recorded separately. A
missing subject with a record must never trigger positive client
release. A failed or malformed HTTP call aborts the entire trial
without reporting a partial behavioral pass.

The report contains status, case labels, SHA256 output digests,
separate raw correctness counts, gate release counts, and the
source digest. It does **not** print raw neural responses, expected
gate identifiers, private markers or user identifiers.

## What this cannot prove

The fixed task patterns, expected behavior and scoring code are
present in Git. Random identifiers are created at execution time
but this is still **SOURCE_VISIBLE_SYNTHETIC_NOT_INDEPENDENT_HELDOUT**.
The evaluator and test cases were authored in the same engineering
effort. Model tag digests are operator-declared and not tensor
attestations. No independent human evaluator/custodian has provided
sealed questions. A handful of trials cannot support broad
accuracy, social continuity, identity, general learning or
personal memory claims.

The memory provider uses source-visible synthetic custody, not the
independently protected issuer demanded by PR #219's negative
host-authority probe. No real memory access or authorization is
conferred by test success. This remains a model-behavior probe with a
distinct defensive client comparison, not production qualification.

## Security/regression checks

Focused synthetic fake HTTP tests assert: positive source-match
release, withholding unsupported positive answers even when a
PUBLIC record is present, literal neural abstention vs client
suppression, no PRIVATE marker exposure, invalid endpoint and
model values rejected before inference, whole-trial abort on HTTP
failure, bounded result redaction, and honest case denominators.
Full regression and exact installed portable execution should be
verified before a live model claim.

No protected merge, deployment, shared-service restart, paid
compute, user data, private memory, neural weights or live host
credentials are touched. A separate owned Ollama instance may be
started for a short, resource-qualified inference trial and must
be stopped with ownership verified afterward.
