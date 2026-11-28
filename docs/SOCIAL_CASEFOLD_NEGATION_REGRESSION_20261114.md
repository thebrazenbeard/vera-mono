# Case-insensitive corrections and actor conflict fidelity — 2026-11-14

**Scope:** Existing Vera Mono research Draft PR #214 only. This is a source-only correction to the bounded fictional-dialogue active-state tracker, not an installation, general natural-language understanding, user identity evidence, or canonical memory.

The question being repaired is precise: when the user changes a named actor's role, should capitalization differences make the old fact survive? No. The previous source treated a capitalized actor name and its lowercase variant inconsistently between role-creation and negation, allowing stale identity claims to remain CURRENT.

## Executed test-first defects and fixes

1. Old `State: Ava is the pilot; Tessa is the guide.`, then present `Correction: ava is no longer the pilot.` **failed**: `role:pilot` stayed CURRENT, while the unrelated guide was valid. A new regression first failed, then the exact named global-negation comparison was changed to casefold both strings and to require a string actor before comparison. The pilot is now UNRESOLVED with turn-2 provenance; Tessa remains the guide.
2. `State: Ava is the pilot; ava is not the pilot.` **failed**: case-sensitive candidate-vs-negated-actor comparison selected Ava as CURRENT. The mixed current/negated candidate matcher now compares casefolded actors, so the same-turn negative evidence cannot be defeated by capitalization.
3. `State: Ava is the pilot; ava is the pilot` **failed**: two different-cased mentions of the same named actor were interpreted as a contradiction. The current same-turn distinct-value test now folds capitalization for strings. Two genuinely distinct actors, Ava and Mira, continue to be UNRESOLVED; regression covers both outcomes.

All three defects were recorded as RED with real assertion failures before source changes. After fixes, the source, direct-answer and long-evaluation focused tests were **42 passed, 42 subtests passed**, exit0 on Lappy Python3.12. The rest of the monorepo and optimized Python compatibility are qualified separately and only reported after actual runs.

## Boundaries

This parser still accepts only narrow explicitly marked fictional user-state declarations, corrections and tested conversational prefixes. Casefolding here is a local name-equivalence assumption within that fiction; it does not merge legal identities or authenticate the current user. The source-only tracker returns no authority for publication, credential use, personal memory, model training or protected effects. The original historical eight-case limit remains **7 correct/7 supported and 1 unsupported**; no earlier scope overclaim is revived. No model download or background task was initiated.

## Final Lappy verification and custody

After the last same-turn spelling-alias repair, the exact Vera Mono Python3.12 full suite `py -3.12 -m pytest -q --tb=short --basetemp=D:\VERA\experiments\social-casefold-negation-full-20261114 tests` returned **1176 passed, 104 skipped, 278 subtests passed**, one existing `PytestCollectionWarning`, exit0 (139.05 seconds). The source/answer/long-evaluation focused tests returned **42 passed, 42 subtests passed**, exit0 under Python3.12 normal and optimized `-O` (the latter warns about assert optimization), and **42 passed** under Python3.14 (pytest-asyncio deprecation warning), exit0. Python3.12 `compileall` exit0, `git diff --check` exit0.

No hosted CI or independent evaluator is asserted. The current branch is an open, draft, unmerged research PR. The four pre-existing unrelated untracked scratch files in Lappy's worktree are excluded. There are no user-authenticated inputs or native user-memory effects in these tests.
