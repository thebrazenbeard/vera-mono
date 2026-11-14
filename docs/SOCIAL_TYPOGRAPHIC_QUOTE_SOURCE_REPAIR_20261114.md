# Typographic quote source-boundary repair — 2026-11-14

**Scope:** Existing `thebrazenbeard/vera-mono` Draft PR #214, isolated Lappy research worktree. This is a bounded correction to source-grounded fictional active-state reconstruction, not a new database, training run, model memory, native ChatGPT change, credential, or privileged effect.

## Reproduced defect

The parser ignored ASCII quoted source excerpts (`"..." `, `'...'`, and backticks) but did not recognize typographic paired quotes (`“...”` and `‘...’`). Consequently, a present-turn statement describing an archived quotation could cause the actor's current role to become `UNRESOLVED`, replacing a valid earlier assertion even though no current correction had been made.

Test-first RED evidence, executed on Lappy Python3.12:

- `Correction: “Ben is the pilot of the Heron” was an old quotation.` incorrectly invalidated `Ava` as the current pilot of Heron; likewise an archived curly-single-quoted `Milo` assertion could invalidate current owner `Rhea`. These are quotes, not present assignments.
- `Correction: “Ben is the pilot of the Heron” was an old memo; Kira is the pilot of the Heron.` failed to admit the actual current unquoted correction to `Kira`, returning `UNRESOLVED`.

Both new tests were observed failing before the fix (2 failures, exit1), and passed afterward (2 passed, exit0).

## Bounded implementation

`packages/vera_core/src/vera_core/social_active_state.py` now masks complete, paired Unicode typographic double/single-quoted excerpts before parsing, alongside prior ASCII quoted forms. The exact present unquoted correction remains available and retains its turn index and verbatim source quotation. Incomplete unmatched typographic delimiters cause conservative truncation of the remainder of that update rather than automatic promotion of its contents to current facts.

This does not resolve arbitrary quotation attribution, historical context or natural language in general. It only prevents a measured source-boundary error on a common text-input form. Original fictional cases and raw model output evidence are untouched; no model generation was necessary for this deterministic provenance defect.

## Verification

Local focused source, answer, and prior long-evaluation suite: **44 passed, 42 subtests passed**, exit0 Python3.12. Python compileall and `git diff --check` exit0. Full repo and cross-version results are appended after actual execution. No hosted CI or independent human behavioral qualification is claimed. No private user text is included.

## Final verified Lappy results

The complete Vera Mono Python3.12 suite `py -3.12 -m pytest -q --tb=short --basetemp=D:\VERA\experiments\social-typographic-quote-full-20261114 tests` completed with **1178 passed, 104 skipped, 278 subtests passed**, one existing PytestCollectionWarning, exit0 (126.46s). Focused source/answer/long-evaluation tests: **44 passed +42 subtests**, exit0 under Python3.12 normal and Python3.12 `-O` (expected optimization warning); Python3.14 **44 passed**, exit0 (pytest-asyncio deprecation warning). `compileall` and `git diff --check` exit0. No hosted CI, independent human behavioral review, model training or deployment is claimed. Four pre-existing untracked scratch artifacts remain outside this commit.
