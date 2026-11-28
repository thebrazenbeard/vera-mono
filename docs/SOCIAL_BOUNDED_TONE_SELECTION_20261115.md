# Relational Agency: bounded model-selected tone (2026-11-15)

Status: SOURCE-ONLY RESEARCH / DRAFT. No native install or runtime consumption.

## Implemented behavior

The existing research CLI scripts/route_social_scene.py now has an
optional --bounded-tone flag. The local model may choose only one
of DIRECT, GENTLE, FIRM and CASUAL. It does not author relationship
claims or final permission prose. The final dialogue is built from
four deterministic, source-bound surface styles under
vera_core.social_active_state.route_styled_boundary_reply.

Only supported exact fictional questions for how a named reader
could respect a named message owner's boundary, or how that
owner could address the reader, can enter this route. The
source resolver must independently find an explicit current denial
of that exact actor reading that exact person's messages.
Conflicts, uncertainty, unrelated recipients and unsupported
questions abstain without calling the model. An invalid model
selection falls back to the direct source line, not a model quote.
This is bounded stylistic choice, NOT free-form generative social
reasoning, self-authored preferences or validated relational
judgment. All permission statements remain FICTIONAL SOURCE CLAIMS,
not real user consent. The default CLI/router remains unchanged.
--bounded-tone cannot share a trial with the opt-in Personification
donor.

## Reproduced test-first cycle

First added tests/test_social_bounded_tone_choice.py. The initial
missing symbol produced an import error; after adding an explicit
unimplemented stub, witnessed behavioral failures with
NotImplementedError (RED), before implementing the selector
(GREEN, 7 passed and 19 subtests).
Next added tests/test_social_bounded_tone_cli.py, witnessed
3/3 CLI tests fail from unrecognized --bounded-tone (RED,
exit1), then implemented the option and model callback.
Final combined focused Python3.12 run: 49 passed and 80 subtests,
exit0. The tests include real JSON-stdin CLI parsing, source
corrections, invalid/injected model text, refusal of unrelated
people, no model invocation for an unknown fact, and no
canonical-memory, actual identity or external effect promotion.

## Actual installed-model observations

Used same-worker synthetic fixture
evaluations/social_fictional_natural_boundary_v1.json
SHA256 89999a6879a481988b62f5db04fb41cdfd1f9bc9938e6f17ba63c0594d97a435.

Raw research record:
evaluations/social_bounded_tone_local_models_seed41_20261115.jsonl
SHA256 112b8101ef0cbf551943ac83982e6648e6430d2edc113b3e38c60cdabf5fb11d.

Actual local Ollama models:
- qwen3.5:0.8b, digest
  de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c
- qwen3:4b-instruct, digest
  0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0.

All model inference was LOCAL, seed41, temperature0,
think=false, stream=false, num_ctx2048, num_predict24,
no tools and no external effects.

16 raw records: eight scenarios per model.
For each model, four grounded denial cases and four
unsupported/unknown/uncertain cases.
- 0.8B: four FIRM selections; four UNKNOWN/no-model.
- 4B: two DIRECT and two GENTLE; four UNKNOWN/no-model.
- Total eight actual model inference calls; the other eight
  cases never invoked Ollama.
- Every chosen raw response was a valid one-token tone.
  No final sentence came from free-form model generation.
- Full posthoc audit 16/16 exact distinct case/model records,
  fixture hash, source quote and evidence index, exact
  request options, model digest, no-tools, no-effects,
  and presence/absence of actual model calls, exit0.
- The model weights were not modified or trained.

## Hostile interpretation limits

> These are authored fixture and test cases from this SAME worker,
> not independent human or cross-model social-quality review.
> The outputs prove bounded-source consistency only.

> Four template styles are more flexible than a single canned
> line but not spontaneous dialogue, revised preference,
> deep social insight, or a general solution to false beliefs.

> The model is prevented from fabricating permission in
> the final text here by restricting the output channel,
> NOT because its belief revision was improved.

> The previous free-form local Qwen4B probe had 6/8 output
> truncations and an invented fictional permission. This
> trial has a 24-token style selector and skips unknown
> cases. These fundamentally different output and call
> budgets preclude a controlled quality comparison.

> Exact fictional state text is not live authenticated user
> identity or actual access authority. No source parser,
> template or local model may promote it to one.

No protected merge, install, native Project control, memory,
host trust key, consent authority, credentials, paid compute,
private source, model training or production effect occurred.
The work remains source-only, unmerged and unqualified for
general conversational or relational competence.

Next: independent natural-dialogue challenge authoring,
dialogue quality judgments with evidence and position-bias
controls, wider referent and correction coverage; do not
promote to the native runtime on this narrow dataset.

## Final local verification (before draft PR publication)

Python3.12 Lappy whole Vera Mono test suite using isolated
D: pytest base: **1240 passed, 106 skipped, 333 subtests
passed**, one pre-existing TestVerifier pytest collection
warning, FULL_EXIT=0, elapsed 184.37 seconds.

Focused six-file test collection:
- Python3.12: 49 passed, 80 subtests, exit0.
- Python3.12 -O: 49 passed, 80 subtests, exit0,
  standard optimized-assert warning.
- Python3.14: 49 passed, exit0, pre-existing pytest
  asyncio deprecation notices.
- Python3.12 compileall of changed implementation and
  tests exit0.
- git diff --check exit0.
- Actual model raw 16-record field-by-field posthoc
  fixture/prompt/permission audit exit0.
The numerical tests do not establish independent or
general social behavior competence.
