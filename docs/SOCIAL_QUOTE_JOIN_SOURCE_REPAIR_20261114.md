# Source-boundary repair: quoted-fragment concatenation (2026-11-14)

**Scope:** Source-only, isolated `thebrazenbeard/vera-mono` Draft PR #214, fictional active-state parser. Not a host, deployment, credential, canonical memory, real current-user authentication, or model-level behavioral qualification.

## Measured failure (RED, Python 3.12 on Lappy)

The parser previously used `_QUOTED_SPAN.sub("", body)`. Removing an archived quoted excerpt could concatenate two **noncontiguous** unquoted fragments into an invented present claim, which was then stored as a current role.

- Input `State: Av"an old memo"a is the pilot of the Heron.` was incorrectly admitted as actor **Ava** being the current Heron pilot. Nobody asserted that contiguous source sentence.
- Input `State: Ava is "not"the pilot of the Heron.` was incorrectly admitted as the positive statement **Ava is the pilot of the Heron**, reversing the source meaning.
- Real unquoted follow-up after a quoted old log remained separately parsed in the control case: `Correction: "Ben is the pilot of the Heron" was from an old log; Kira is the pilot of the Heron.` must yield **Kira**.

Three test cases were added first. Observed RED: **2 failed, 1 passed, 26 deselected**, `RED_EXIT=1`, with both false CURRENT values named by real assertion failures. No mocks or production code changed before that failure.

## Minimal fix (GREEN)

Replace each paired quoted excerpt with a clause separator `;` rather than deleting it. This preserves lexical boundaries and prevents a complete pattern from being assembled across archived text, without blocking a separate explicit current correction. No new parser grammar, dependency, service, training or effect authority.

Observed GREEN: **3 passed, 26 deselected**, exit 0; focused source/answer/long-evaluation suite **47 passed, 42 subtests passed**, exit 0. Original preceding quoted-source repairs remain retained. Tests use synthetic names only.

## Limits

This is a deterministic pattern-parser safety correction, not natural-language comprehension. Unknown or contested referents still fail closed; source labels alone do not prove the actual user, session, host admission, durable replay protection, privacy consent, current desire, or permitted external action. Any claims about real Vera behavioral improvement require independently grounded model evaluations. Full-suite results and exact Git head are appended after verification.

## Final verified local results and release boundary

- Full Windows Lappy Python 3.12.10 Vera Mono suite, isolated `--basetemp=D:\VERA\experiments\social-quote-join-full-20261114`: **1181 passed, 104 skipped, 278 subtests passed**, one existing PytestCollectionWarning (the pre-existing `TestVerifier` class constructor), **FULL_EXIT=0**, 125.08 seconds.
- Focused normal Python 3.12: **47 passed, 42 subtests passed**, exit0; optimized `py -3.12 -O`: **47 passed, 42 subtests passed**, exit0 (expected PytestConfigWarning about interpreter assertions); Python 3.14: **47 passed**, exit0 (pytest-asyncio deprecation warning).
- `compileall` exit0; `git diff --check` exit0. Hosted CI is not established by these local runs. Independent human/model review, native installation, persistence, real identity/host provenance, protected effects and actual relational competence remain unqualified.
