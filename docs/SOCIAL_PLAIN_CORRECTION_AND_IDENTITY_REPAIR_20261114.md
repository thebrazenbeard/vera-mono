# Vera social-dialogue active-state: ordinary corrections and exact identity (2026-11-14)

**Research/source-only for existing thebrazenbeard/vera-mono Draft PR #214.** This is a bounded improvement in how the optional source-grounded fictional scene tracker reads explicit corrections. It does **not** create native conversational memory, identity proof, a model upgrade or permission to act.

## Three real defects and repairs

1. **Scoped pronoun falsely treated as named actor.** In `State: Ava is the pilot of the Heron` followed by `Correction: He is now the pilot of the Heron`, a case-insensitive name expression previously accepted `He` as the pilot, giving a false concrete answer rather than uncertainty. A new test first failed for `He`, `She`, and `They` (three negative subtests). The parser now recognizes an ambiguous scoped pronoun before attempting a named scoped assignment, and the exact scoped role becomes `UNRESOLVED`. Original named actors still resolve normally. Red->green observed; **not general pronoun resolution**.

2. **Natural corrections were ignored.** The prior parser required literal `State:`, `Correction:`, `Update:` or `Only change:` headers. Three explicit present-user correction forms `Actually, Ben is the pilot of the Heron`, `No, Kira is the pilot of the Heron`, and `I meant Tessa is the pilot of the Heron` first failed, each preserving the obsolete Ava role. A narrowly expanded explicit prefix recognizer now accepts those specific correction markers, including unsupported role changes that must invalidate rather than retain old facts. It deliberately **does not** treat arbitrary unmarked prose, past memoirs or quotes as a current instruction. RED->GREEN observed.

3. **Name capitalization created duplicate and stale slots.** `Ivo carries a red card` then `Actually, ivo carries a green card` created `card:Ivo` and `card:ivo` separately; an exact-answer query about the messenger could retrieve the wrong color or `UNKNOWN`. Two new tests first failed for distinct state keys, and a third direct-answer test failed because a lowercase initial card identity did not match a later capitalized messenger. Explicit card/type source-slot keys now use a case-insensitive match against existing keys, preserving the spelling of the first occurrence and treating same-turn case aliases as a conflict. Direct supported-question lookup also resolves corresponding case aliases without claiming that unrelated names are the same person. RED->GREEN observed.

## Strict limits

- The model-free parser processes only strings supplied as *current user turns to the caller*, not raw historical model output or imported authority. This Python function itself **does not authenticate a live host user**. A quoted old record cannot become the present correction through its label.
- Supported facts remain limited to deliberately small fictional scene syntax, named roles and cards, and exact source quotes. There is no semantic resolution of anaphora (`he`, `she`, `they`) or unrestricted free-form natural language, and there is no permanent memory.
- Corrections never grant canonical user memory writes, privileged effects, credentials, publication or live model runtime changes.
- Preserve original eight-case historical fixture's corrected scope outcome: **7/7 supported correct and one unsupported ship-specific question**. The prior `8/8` claim was retired in the preceding correction and must not be revived.

## Evidence record

TDD RED: scoped pronoun test failed three subtests with `He`/`She`/`They` returning concrete actor instead of `UNKNOWN`. Natural prefix test failed three correction subtests and the final invalidation assertion. Slot identity tests failed because four keys were retained instead of two and because a same-turn case alias was split across two slots. Direct supported-answer test failed with `UNKNOWN` instead of `Ivo, green`.

After source changes: focused Lappy Python3.12 source/answer/model-audit tests **38 passed, 42 subtests passed**, exit0. Full-suite, Python optimized, Python 3.14 and GitHub commit verification results are recorded after execution, not inferred.

All changes are to the same research PR source and test ownership; no separate Mini-Vera runtime files, actual private user chats or model weights were changed. Four preexisting unrelated scratch files in the isolated checkout remain excluded.

## Final execution/readback evidence (same Lappy checkout, 2026-11-14)

- Test-first scoped pronoun: three exact `He`/`She`/`They` synthetic cases previously returned pronouns as concrete named vessel pilots, **RED** with 3 subtest failures. After adding narrow ambiguous-scoped-role handling, focused test GREEN.
- Test-first ordinary correction markers: three sequential user turns `Actually, Ben ...`, `No, Kira ...`, `I meant Tessa ...` failed to update the last scoped pilot, plus unsupported-role correction left an old actor current. RED 4 assertions/subtests; after narrow prefix recognizer, GREEN. Quoted historic examples remained rejected.
- Test-first capitalization identity: `card:Ivo` and `card:ivo` split into distinct slots both across turns and in one turn. Two RED tests; repaired canonical existing-key choice with first spelling retained. The direct role+card answer still returned UNKNOWN when role said Ivo but initial card said ivo; that separate RED was fixed via case-insensitive existing-slot lookup.
- Final focused tests: **38 passed, 42 subtests passed**, exit0 Python3.12 normal and optimized `-O` (one expected pytest warning). Python3.14: **38 passed**, exit0 (pytest-asyncio deprecation warning). Compileall exit0.
- First complete repo pytest run, isolated D: basetemp: **1171 passed, 104 skipped, 278 subtests passed, 1 failure** from unrelated existing `test_deep_memory_cli_transport::PinnedCLITest::test_slow_stdout_is_killed_at_deadline` requiring an external subprocess PID file within 0.2 seconds; exit1. The exact test then passed three isolated retries with no code change (3/3).
- Second full run: **1171 passed, 104 skipped, 278 subtests passed, 1 failure** because this branch's CLI subprocess smoke test exceeded its **14-second launch timeout under suite load**, exit1. That test passes in focused runs; its launch timeout was raised to 60 seconds without changing the checked behavior or assertions. Both failed runs remain recorded.
- Third/final full Lappy Python3.12 Vera Mono run after that test deadline change, isolated `D:\VERA\experiments\social-natural-corrections-full-final-20261114` basetemp: **1172 passed, 104 skipped, 278 subtests passed, one pre-existing collection warning, exit0**, 124.88s. No hosted CI or independent human behavioral qualification implied.
- No model download, weights, independent user-source authentication, protected effects, Mini-Vera runtime changes or native ChatGPT installation. Four pre-existing unrelated scratch files left untracked.
