# Social cognition ecosystem: source-grounded interoperability (2026-11-14)

Research-only map for Vera Mono Draft PR #214. This is NOT an install manifest,
merger authorization, identity binding, private data transfer, or live qualification.
Source repositories remain independent: history, preferences and actor identity
must not leak across subjects.

## Verified repository source and candidate boundaries

| Repository | Current main README blob | Implemented candidate | Boundary |
| --- | --- | --- | --- |
| thebrazenbeard/lgcm | d56ea417c0b904d3c4a0408de2658d0cbbe1bc7f | ContextualWorldModel.predict/update, Experience, numerical context recall, prequential evaluation | Numerical dynamics; does not train hosted LLM weights or authorize action |
| thebrazenbeard/meta | 51bee4ea34aa71d8256c73ab61e049974928bc18 | Prewritten-method selection, FeedbackController, separate-process tests | No private introspection or invention of new strategies; evaluate on held-out domain shifts |
| thebrazenbeard/humility | dd257d65890eeb1c800092219ab0ff7ab1fcfbfd | EvidenceItem, revise_distinct, Bayesian update, Brier/selective risk/abstention | Evidence independence and outcomes caller-supplied; no truth authentication |
| thebrazenbeard/empathy | 207cc89adfe2da274986a4b18c9217072e5e35dc | Assessment, Evidence, choose_policy, ephemeral response_policy_hint | Host must admit person-scoped current evidence and privacy; never infer consent; separate Vera Mono Draft PR #189 owns its integration subject |
| thebrazenbeard/personification | 508d08a2f9e66498c5bdf8c372af5cb4806da44c | ActorProfile, Interaction, plan_interaction, proposition fidelity | Identity-neutral register guidance only; no actor-profile import or tool rights |

The current task explicitly corrected the intended repository to
``thebrazenbeard/personification``; the earlier ``personality`` lookup was a
mistaken referent and is retired. Personification's exact README and source
role were inspected. Its identity-neutral planning guidance remains advisory,
not an identity donor, current-consent source, or production integration.

Current Empathy Vera Mono Draft PR #189 is OPEN and UNMERGED at
14fc21272569067bb8a3f960cd34b3171f731579 (observed 2026-11-14).
Do not overwrite its ownership surface for forced integration.

## The actual PR #214 read-only bridge

The runnable route_scene_reply and scripts/route_social_scene.py compose
explicit, fictional source-state correction extraction with local Ollama
fallback. Supported source-backed questions yield bounded answers or UNKNOWN
without invoking a model; exact ship-scoped questions with no explicitly
stated actor link abstain; unrelated fictional dialogue goes to the local model
with status MODEL_UNVERIFIED. No effect, memory, or identity authority follows.

This is actual integration of existing source-state extraction with model
output. The opt-in Personification advisory path below now consumes an exact
pinned candidate source for **register/response-planning guidance only**.
This bridge does NOT import or consume LGCM, Meta, Humility, or Empathy;
their different primitives require independently admitted data and contracts.
Simply adding imports would create false completeness. Candidate future
host-owned interfaces include ephemeral Empathy response hints, externally
held-out Humility confidence/outcome scoring, prewritten Meta strategy
selection, and LGCM numeric dynamics evaluation. None may promote archival conations,
caller-declared labels, or inferred preferences into current fact or consent.

## Tests and negative result retained

The route tests were RED (six missing-bridge failures), then 53 focused
tests and 40 subtests GREEN. The subprocess CLI had two RED cases before
implementation. Its first post-implementation subprocess run failed
on absent portfolio_runtime import; corrected CLI source-package
discovery. Next focused CLI/router/answer suite passed 22 tests,
34 subtests. Python3.12 optimized and Python3.14 focused tests passed,
with expected pre-existing pytest warnings.

Real source-grounded CLI: explicit comma correction returns Ben,
model_used=false. Real Lappy local qwen3.5:0.8b open-ended reply ran,
status MODEL_UNVERIFIED, and invented aircraft/landing details.

Initial full Python3.12 monorepo run (do not erase failure):
1196 passed, 104 skipped, 283 subtests, two FAIL,
one pre-existing TestVerifier collection warning. The failed DeepMemory
PID-file deadline and PowerShell preflight 15s subprocess timeout
both passed in a later isolated two-test rerun, exit0.
A full-suite rerun is needed for a clean broad gate.

No merge/install, canonical memory admission, production route, model
training, private publication, or other protected effect follows.

## Final post-change gate (same source, isolated test root)

After the earlier two timing-sensitive unrelated full-suite failures,
reran the ENTIRE Vera Mono Python 3.12 suite with all packages in
PYTHONPATH and a fresh isolated D: pytest basetemp:
1198 passed, 104 skipped, 283 subtests passed,
one pre-existing TestVerifier collection warning, FULL_RETAKE_EXIT=0
(275.03 seconds). The earlier failing full run and isolated two-test
rerun are retained above, rather than silently erased. These results
establish source/test behavior only, not installed Vera runtime,
general social intelligence or independent qualification.

## Executed opt-in Personification bridge: PR #11 pinned source

- Real read-only source checkout: thebrazenbeard/personification
  OPEN DRAFT PR #11 at 8fe35557e9a6c7b99c8f50a532e20c8f8c43f4cc.
  The candidate has no folder-open loader and its 49 Python3.12 tests
  passed in an isolated Lappy checkout. Main f95bda5 still has a
  concealed folder-open Node task invoking JavaScript disguised as
  a font and enables automatic tasks. The original main tests had
  1 failure and 1 error. Neither payload nor editor task was run.
  This source-only candidate does not repair installed editor settings
  and is not merged. Existing Personification PR #11 owns its fix;
  this PR does not mutate Personification.
- The scene CLI remains unchanged without optional flags. An explicitly
  supplied --personification-checkout of the exact clean reviewed commit,
  --actor-id, and --subject-id enables Personification's *actual*
  ActorProfile, Interaction and plan_interaction APIs. Interaction kind
  and preferred register are supplied, not silently inferred. The
  bridge imports only src/personification; NO history or actor profile
  is loaded automatically. A wrong/dirty HEAD is rejected before import.
- A bounded SocialPlan is checked before use: answer_target must
  exactly match the final literal user request; the plan must answer
  that literal request first, and permission_to_act must be False.
  Only register and humor advice is appended to the model system
  instruction for OPEN fictional scene turns. The original user turns
  remain unmodified. Source-backed direct answers never invoke the model
  or this optional donor. Output includes a non-authoritative
  personification_advisory summary only when the model branch used it.
- TDD RED: new adapter/test surface 7 failures (1 pass) before the
  adapter existed; CLI flag case independently RED (SystemExit 2).
  Green focused suite: 27 passed +38 subtests, no failures;
  includes real pinned donor and rejection of unsafe main checkout.
- Real Lappy qwen3.5:0.8b temperature0 seed43 A/B: the baseline
  and opt-in outputs both hallucinated aircraft/nose/runway details
  absent from the fictional source. The opt-in program emitted
  register DIRECT, humor_allowed False, literal_request_preserved True,
  permission_to_act False, with model_used True. This is genuine
  source consumption and style-contract enforcement, but NOT a
  demonstrated improvement in factual grounding or social competence.

Remaining independent owners: Empathy PR #189, LGCM numerical dynamics,
Meta strategy-selection feedback, and Humility evidence calibration.
No shortcut from a source import to host identity, authenticated
evidence, user consent, memory or system permissions is claimed.
No merge, native Vera runtime activation, deployment, model weights
or sensitive user data was changed.

## Verified final same-source checks: opt-in Personification adapter

Final complete Python3.12 Vera Mono suite, correctly configured all
monorepo packages on PYTHONPATH and isolated D: pytest basetemp:
1203 passed, 104 skipped, 287 subtests passed; one existing
TestVerifier collection warning; FULL_EXIT=0 (194.66 seconds).
Focused normal 27 passed +38 subtests; Python3.12 -O
27 passed +38 subtests, OPT_EXIT=0 (one expected pytest optimize
warning); Python3.14 27 passed, PY314_EXIT=0 (existing
pytest-asyncio warnings). Python3.12 compileall and git diff --check
EXIT=0. All source-level claims are bounded to this opt-in fictional
test harness. No independent model-level or live host qualification.
