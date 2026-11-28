# Relational Agency: correction currentness and subject isolation

Date: 2026-11-15. SOURCE ONLY, DRAFT PR 214, NOT NATIVE VERA.
Parent commit: 9c96ad710ea9b1cd1a52e985281972d56df0ad1a.

## Defect and fix

A fictional scene originally reported that Nia may not read Omar's
messages. An explicit later correction such as "Correction: Nia can now
view Omar's messages" did not match the narrow parser; consequently
the old denial remained CURRENT. Its cited natural dialogue could
mistakenly present stale source evidence as current.

The new narrowly scoped matcher recognizes an unsupported explicit
current correction referencing a specific named reader and owner.
It marks ONLY that fictional read_messages relation UNRESOLVED with
the correction's exact text and turn number. This does not establish
access, consent, truth, authority or permission. Other relationships
stay untouched; reversing reader and owner does not rewrite their
opposite direction. Later exact supported claims can restore a
source-backed current relationship. Quoted old memos, indirect
historical reports and unmarked narrative do not supersede sources.
Unknown state bypasses optional tone selection entirely.

## Hostile regression

A fictional actor named Pilot can coexist with an independent
pilot role occupied by Mira. Initially the correction
"Pilot can now view Omar's messages" marked the right relation
UNRESOLVED but also incorrectly invalidated the role:pilot slot.
The extra role fallback was accidentally matching Pilot the NAME
as pilot the ROLE. The newly added test failed for precisely
that reason. The correction now skips generic role invalidation
after identifying a specific relation.

## Evidence

Initial seven-test file RED: 8 failed, 3 passed and 4 subtests,
exit1; missing unsupported-correction behavior.
First GREEN across five focused source/boundary test files:
40 passed and 63 subtests, exit0.

A subsequent role-name test was initially appended below the
unittest main guard and NOT collected; that first trial's
7 passing tests did not establish RED. After relocating the
test inside the class it FAILED as intended: 1 failed,
7 passed and 8 subtests, exit1. Fixed code; final targeted:
Python3.12 41 passed and 63 subtests, exit0.
Python3.12 -O 41 passed and 63 subtests, exit0,
expected optimized assertions warning.
Python3.14 41 passed, exit0, existing pytest-asyncio warning.

Full Python3.12 suite before role-name fix: 1254 passed,
106 skipped and 350 subtests, exit0.
FRESH FINAL full suite after both fixes: 1255 passed,
106 skipped and 350 subtests, exit0, 116.65 seconds.
One known TestVerifier pytest collection warning.
Git diff --check exit0; a CRLF normalization notice does not
indicate a whitespace error.

## Strict evidence boundary

> This deliberately narrow correction matcher is not general
> natural language understanding. It identifies a few direct
> grammatical forms and refuses to promote them into permission.

> This establishes source/proposition currentness regression
> behavior, not independent social cognition, free-form model
> response quality, social intimacy, consciousness, or genuine
> current native Vera consumption.

No new local neural model generations in this iteration; no
model weights, canonical/private memory, host authority, native
Project configuration, merged source, other PRs, spending,
deployment or real-world access changes. Four unrelated
untracked research files were left untouched.

Next: verified natural-language adversarial scenarios,
real multi-turn model trials and independent blinded review.
