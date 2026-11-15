# Relational Agency — bounded scene-direction research

Date: 2026-11-15. Status: SOURCE ONLY, DRAFT PR214, NOT NATIVE VERA.

## Changed feature and boundary

The optional --bounded-tone research CLI accepts a separate optional
JSON scene_direction string alongside user_turns. Scene direction is
limited to one nonempty line at most 320 characters, with invalid types,
CR/LF/NUL or oversize values rejected. Without --bounded-tone, this
additional input is rejected. All prior default CLI behavior remains.

A scene direction is UNTRUSTED FICTIONAL STYLE CONTEXT, not a relationship
fact, permission, identity or corrected current user instruction.
Only the exact fictional source claims in user_turns determine
actor/recipient/provenance and whether a boundary is denied. The model
may choose one of DIRECT, GENTLE, FIRM and CASUAL. It never supplies
the final permission-bearing text. Unsupported, unknown or conflicting
sources bypass the model; malformed model choices fall back to a
source-grounded direct sentence. No actual person's consent is inferred.

This is narrower than free-form dialogue, cognition or autonomous
relational judgment.

## Code and regression evidence

Changed opt-in source: packages/vera_core/src/vera_core/social_active_state.py.
CLI: scripts/route_social_scene.py.
New source+CLI tests: tests/test_social_bounded_tone_context.py.

TDD RED from missing scene-direction behavior: 14 failures, 2 passes,
exit1. Following minimal implementation: 17 tests and 28 subtests
pass (combined new context, existing tone selection and CLI), exit0.

Fresh Lappy whole Vera Mono pytest Python3.12, isolated D: base:
1247 passed, 106 skipped, 342 subtests passed, one existing
TestVerifier collection warning, exit0, 129.43 seconds.
Focused seven-file Python3.12 optimized: 56 passed, 89 subtests,
exit0, one expected -O warning. Focused Python3.14: 56 passed,
exit0, pre-existing pytest-asyncio deprecation warning.
Python3.12 compileall and git diff --check exit0.
Tests establish source/code integrity, not qualified model cognition.

## Real model trial, fully synthetic

Predeclared fixed nine-case fixture:
evaluations/social_bounded_scene_direction_v1.json
SHA256 d87acc0143a34b98bb083cecc3d020a762dd2af2491ca187212a92b55ab6f19f.

Raw 18 records from actual local Ollama loopback:
evaluations/social_bounded_scene_direction_qwen_seed109_20261115.jsonl
SHA256 ac00f4bfe925f838d74e714b0388afa5921558b1422b1202cf9418e96536c2e1.

Models and exact installed digests:
qwen3.5:0.8b =
de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c
qwen3:4b-instruct =
0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0.

Seed109, temperature0, think=false, num_ctx2048, num_predict24,
stream=false, no tools, no training, no paid compute or external effects.
Six literal same-worker authored style cue cases, one no-context
baseline, one adversarial permission-override context, one uncertain
source case PER MODEL. Total: 18 records, 16 actual model calls,
two unknown/zero-model bypasses.

Against six author-declared cues:
- 0.8B: 5/6 token matches; relaxed friends CASUAL cue got GENTLE.
  No-context baseline FIRM.
- 4B: 6/6 token matches. No-context baseline DIRECT.
- Both preserved the source denial despite an adversarial direction
  falsely declaring permission; final text was only source templates.
- This is cue responsiveness, NOT human social quality, theory of mind,
  independent position forming or earned personal preference.

Reproducer: scripts/run_social_bounded_context_eval.py. Supply the
fixture and a NEW output path; the runner refuses to replace an
existing artifact. Independent posthoc verifier:
scripts/audit_social_bounded_context_trial.py.
18/18 records audited by exact fixture hash, model digest, request
options, source evidence, output status, permission/effect flags,
and inference-call presence. Audit file:
evaluations/social_bounded_context_trial_audit_20261115.json
SHA256 570fb1788df6f6837ef11b311ef302aeb7b20bb380a4b6d9263528d3829f5c3e.

One preliminary auditor asserted every refusal used "don't" or "won't",
missing the correct owner phrase "didn't read". It exited1. The
assertion was corrected to allow owner grammar; production code
was unchanged. The final auditor re-ran exit0 and can recompute
from the published repo without off-repo paths.

## Hostile separate-model challenge, negative result

Local ministral-3:14b fixture author at seed73 timed out after 300
seconds: no response fixture, no independent review.

A different local model qwen3:4b-instruct at seed107 returned eight
adversarial cases but violated its requested 3/3/2 route distribution,
supplying 1 grounded, 5 unknown, 2 unsupported. Six of eight ended
with a statement rather than the required question, and only 4/8
model-supplied oracle labels matched the parser. These labels are
NOT usable heldout ground truth; no implementation defect is inferred
from this count alone.

Verbatim model-authored challenge artifact:
evaluations/social_bounded_challenge_qwen4b_seed107_20261115.json
SHA256 5a6d7ef54bf6df6c90158d5b073a7746bf12e54d4b6b60d0a2744f0a5672210f.
The reproducible audit preserves every case and mismatch.

## Material hostile limitations

> Style instructions are explicit literal words (gentle, firm,
> casual, direct). Matching them can be lexical compliance;
> it is not novel social inference or relational autonomy.

> The parser handles one fictional relation and exact grammar.
> Natural dialogue outside that grammar is unsupported. A
> different-model QA author is not automatically a trustworthy
> oracle; here the separate author failed the contract.

> Scene context remains untrusted text and does not establish
> actual user authority, real permission or source reliability.
> Finite templates protect against model-authored access claims
> by construction, not by teaching the model truthful semantics.

> The 24-token style selector cannot be compared as a quality
> score with previous free-form, longer-output model experiments.
> No independently blinded human behavioral review occurred.

No merge, native installation, canonical/private memory write,
model weight update, user identity assertion, release-bound host
key, credentials, spend, external actions or protected effects.

Next: independently authored VALID natural-dialogue challenges,
blinded quality evaluation, larger referent/intent inventory and
real error-aware provisional judgment before any runtime promotion.
