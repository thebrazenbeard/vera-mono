# Explicit fictional actor/recipient access claims (2026-11-14)

## Effect and scope

Vera Mono Draft PR214, separate Relational Agency source-only
research. NOT an update to native Vera, Project control, model
weights, private data, memory, consent, identity or tool permissions.

This extends the EXISTING vera_core.social_active_state reconstruction,
route_scene_reply, and route_social_scene.py entrypoint. It does not
introduce a new assistant, memory store or general NLU service.

Only explicit marked fictional clauses such as:
  State: Nia may not read Omar's messages.
  Correction: Nia may now read Omar's messages.
are admitted as actor, action, recipient source claims. Conflicting
claims and an uncertain later correction are UNKNOWN rather than
stale certainty. Unrelated actor-recipient pairs are preserved.
Quoted old claims and unmarked prose do not promote source facts.

The only new direct question has an exact fictional scope:
  In the fictional scene, may Nia read Omar's messages?
An unscoped question about real permissions is NOT directly answered.
Reported fictional allowance is never actual authorization. The
source response always has model_used=False,
external_effect_authorized=False, canonical_memory_admitted=False,
and actual_user_identity_verified=False.

## Red-green and CLI evidence

Initial 7 behavior failures, 2 pass before implementation.
The test failures documented missing source parser and no-model route.
Later added uncertain-supersession and "may now read" tests:
both failed initially for stale answers, then passed after narrow
grammar support. No expected result was weakened to create green.

Focused source and existing scene regression:
64 tests passed, 52 subtests passed, exit0.
The new CLI subprocess test invokes the real scene router and
verifies model=None, model_used=False, source evidence, and
no external permission. No Ollama required for direct answer.

## Frozen same-worker-authored source fixture

evaluations/social_fictional_message_boundary_v1.json
SHA256 593e187b834f5bdd9d0cc8b0bea7154f8a15db24e40056b0bddff6640a098aeb

Ten fictional cases, source path 10/10 exactly matched prewritten
expected answers or UNKNOWN: directional denial, reversed reported
allowance, one-pair correction, same-turn conflict, later
uncertainty, unrelated actor preserved, forged archival quotation,
unmarked prose, and unlinked recipient.

This validates an EXACT RULED SOURCE PATH on same-worker synthetic
examples. It does NOT establish independent case authorship,
real-world permission, general understanding, or live Vera behavior.

## Actual local-model source-card comparison

evaluations/social_fictional_message_boundary_model_vs_source_seed79_20261114.jsonl
SHA256 e21a4f528b6b6ad910188627e8ab13639ded24b1f3b44eac8bb68e25ea84a6c8

20 real local Ollama calls: 10 identical user-turn sequences for
qwen3.5:0.8b and for qwen3:4b-instruct, seed79, temperature0,
think=false, num_ctx4096, num_predict160, no tools.
Both received the existing SCENE_SYSTEM and the reconstructed
source-card context, not a deliberately weakened model prompt.
Exact model digests, fixture SHA, source-card system SHA,
input turns, reply, finish reason, and direct source comparison
are preserved in unmodified raw JSONL records.

The deterministic branch called NO model. Both models had 2/10
answers ended by the output-token limit. A diagnostic first-word
YES/NO/UNKNOWN extraction cannot score explanatory replies:
0.8B had 9 unscored; 4B had 6 unscored. Do not portray the
recognized first-token matches as semantic accuracy.

Observed failures:
- 0.8B denied Omar's explicitly reported allowance to read Nia's
  messages, even though it was stated in the source.
- 0.8B transferred a restriction concerning Omar's messages to
  Vale's messages and contradicted source cards in a correction.
- 4B's direct denial reply started with "Yes" but subsequently
  said Nia may NOT read Omar's messages: an internally
  contradictory lead, rather than an unambiguous permission grant.
- 4B treated Omar's unaffected reported allowance as uncertain
  after a correction changing only Nia's access.
- 4B's response to an archived forged quote reasoned both that
  denial remained and that the current claim was UNKNOWN.

Some 4B answers correctly handled explicit disagreement and
an unlinked subject, but there is NO demonstrated general
conversational improvement. This comparison supports a narrower
claim: the strict parser can answer these explicit fictional
source facts without some observed model failure modes.

## Hostile challenges

> The same worker authored the parser and fixture. Exact-form 10/10
> does not demonstrate generalization to naturally worded speakers,
> privacy boundaries, or untrusted source ambiguity.

> Most local model responses were free-form and unscored by the
> diagnostic first-word label. There was NO independent human
> evaluator, preregistered social quality rubric, or fair numerical
> model-accuracy claim.

> The parser has no real provenance witness; a source-reported YES
> does not create actual access rights. Treating a story claim as
> consent is a critical failure that these tests do not authorize.

## Release boundary / next frontier

Read-only PR source research, no merge, install, host effect,
canonical memory change, model training or autonomous action.
A future qualification should combine a typed, source-backed
actor/recipient correction with open-ended conversational generation
on independently authored held-out dialogue. Both correctness
and naturalness need assessment before promotion.

## Completed verification before source publication

Full Vera Mono Python3.12 suite, fresh dedicated basetemp:
1222 passed,106 skipped,299 subtests passed, one pre-existing
TestVerifier collection warning, FULL_EXIT=0 in 149.12 seconds.
Focused integration after CLI/fixture additions: 64 passed,
52 subtests passed, exit0.
Optimized Python3.12 focused: 64 passed,52 subtests,
expected optimized-assert warning, OPT_EXIT=0.
Python3.14 focused: 64 passed, pre-existing asyncio deprecation
warning, PY314_EXIT=0.
Python3.12 compileall changed source and tests, exit0.
Diff whitespace check exit0. Local raw JSONL source audit
recomputed all 20 exact (model,case) pairs with original fixture
SHA, user turns, evidence quotations, model digests, seed79,
system-card SHA, no-tool/no-authorization flags and the recorded
first-token diagnostic; audit exit0. Neither the model diagnostic
nor these tests establish independent conversational qualification.
