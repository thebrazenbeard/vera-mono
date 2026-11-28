# Vera social conversation: simple real-model A/B — 2026-11-14

**Verdict: observable improvement in response discipline, not a proven improvement in social reasoning or a native Vera release.**

This experiment follows Patrick's correction that continual signing, SQLite and host-control machinery was displacing the actual social-capability objective. It changed **no** signer, model weights, host permissions, memory service, app installation or authoritative ChatGPT Project configuration. It ran existing, already-installed local Ollama models against six entirely fictional three-turn conversations with one tiny optional prompt variant. New sources are restricted to this existing relational-agency Draft PR #214.

## Exact inputs and custody

- Fictional case fixture: `evaluations/social_behavior_simple_round1_v1.json`, SHA256 `53a4727422e0cedc31ac71d68a6d500c17a755e2ab91828377590a4b834dd574`. Six cases: paper garden without software, spacecraft Heron referent, coworker bus explanation, old memo without current publication consent, friend exclusivity without agreement, and present provisional conversation choice. Criteria recorded before either model was run. The cases are similar to earlier known failure classes; **not an independent unseen benchmark**.
- Exact runner: `scripts/run_social_behavior_simple_ab.py`; three actual sequential user turns with the previous model answer carried into history. Same model, input and fixed seed within an instruction-arm comparison. Native Ollama system/config is unchanged; no tool use, ChatGPT host or personal data. `temperature=0`, `think=false`, `num_ctx=4096`, `num_predict=180`; A/B execution order alternates by case and seed.
- Instructions: `base` is a short natural assistant baseline, `focus` adds a correction-aware prompt, `concise` adds *one/two-sentence response discipline and an explicit ban on unsolicited lists*. The concise arm was **introduced after observing the base/focus outputs**, so its results are **adaptive exploratory evidence**, not preregistered confirmatory success.
- Tests `tests/test_social_behavior_simple_ab.py` first failed RED (missing runner), then passed after the runner was implemented. Another RED (missing concise arm) passed after adding one optional instruction variant. No user personal materials or ChatGPT private memory were included.

## Real local model responses (not imagined, not independent human review)

`qwen3.5:0.8b`, Ollama model SHA `de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c`:
- 72 actual response records, 6 cases x 2 arms x 3 turns x seeds 11 and 23, raw SHA `dabf00b2260721cb6d6464baad4508f7d3134b7217a5e30fc87e42851108821e`. **All 36 paired turn outputs were identical between the two seeds** at temperature zero; these are **not two independent behavioral results**.
- Baseline: **0/36** cut off at the output-token limit, but one final response mistakenly called *demanded exclusivity* a caring choice. Focus: **4/36** responses cut off; it rejected exclusivity in its final answer but still meandered and created extraneous details (Heron flying between *railway stations*) and an unnecessary publication checklist. Neither reliably preserved concise, direct scope.

`qwen3:4b-instruct`, Ollama model SHA `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`:
- Same six cases, one seed 11, base/focus 36 responses, raw SHA `2205ae23117c4a2f75e3f40e18189d77d9e8bc8836daa1e75ba2efa50da038fa`. Baseline **9/18** truncated, focus **10/18** truncated. Both rejected coercive exclusivity and preserved Heron's spacecraft referent by the final turn. Both were often unhelpfully wordy and made sweeping privacy claims.
- Follow-up one-arm **concise** exploratory run, 18 real responses (6 cases x 3 turns), SHA `b050d0443d18092865932a083448feb56c10fbce955aa2f7931a85a20df1e70a`: **0/18** truncated. The final replies were concise relative to the long 4B baseline and stayed on-topic: garden path, Heron spacecraft, fair response to bus breakdown, no publication from prior memo, no forced exclusivity, provisional choice of geology.
- This did **not** solve the whole conversation: on the exclusivity second turn, the concise 4B model **reversed who demanded control**, incorrectly saying the friend demanded isolation; on the provisional-choice second turn it incorrectly rejected having a current provisional preference, before choosing geology on the third turn. It also sometimes exceeded its requested one/two-sentence budget and offered overconfident legal assurances.
- Measured local run times were roughly 64 seconds for both 0.8B arms and two seeds, 268 seconds for both 4B arms/one seed, and 54 seconds for the single 4B concise arm. The runs were sequential under changing host load; **do not present these wall times as controlled performance benchmarks**. The larger model used existing local CPU/GPU mixed offload; no download, training or paid compute.

## Source and reproducibility limits

All three JSONL outputs are recorded with their raw SHA256 values above. Direct source check validated **126 actual records**, six matching fictional case IDs, fixed original fixture digest, fixed model digests, full three-turn response sequence per arm, and zero declared tool use or schema mismatches. The criteria were not passed to the generator as text. This review is **internal qualitative analysis** of model outputs, not independent human or unbiased model review. The previous Qwen judge was demonstrably A/B-position-biased; it was not reused here.

> **Hostile challenge:** An output-length reduction and six satisfactory-looking final answers can hide bad intermediate correction tracking. The exact agent/referent reversal on friend exclusivity and second-turn refusal to make a provisional choice remain falsifiers of robust social reasoning. These small, familiar scenarios are not evidence of generalized competence or sentience. Do not claim that native ChatGPT/Vera is modified, trained or qualified by these local prompts.

**Implementation decision:** Retain the shorter optional `concise` prompt in the evaluation script as an **experimental candidate**, and keep the prior signed-checkpoint and replay work untouched rather than making it prerequisites. No new approval, model weights, production route or canonical memory effects are created. Next high-value iteration: independently authored, genuinely unseen dialogue cases with stable agent-role tracking and a source-auditable assessment, then only adopt a default instruction if behavioral evidence holds across new cases.

## Local software verification

Real Ollama generations exited 0: qwen3.5 0.8B base/focus, 72 records; qwen3 4B base/focus, 36 records; qwen3 4B concise, 18 records. Output case schema, exact fixture hash and model-digest consistency checked directly: 126/126 records valid; no declared tools. Raw files and SHA-256 values retained above.

Test-first runner integration started with two failing contract tests (absent module, exit1); implemented runner and observed two passing tests, exit0. A later new concise-arm test failed for missing constant (exit1), then passed after implementing the optional arm. Normal Python3.12 focused behavior + prior social review contracts: 29 passed, 2 subtests passed, exit0. Python3.12 -O focused new tests 3 passed, exit0 (one pytest optimize warning); Python3.14 focused 3 passed, exit0 (pytest-asyncio warning); compileall and git diff --check exit0. Full Lappy Python3.12 Vera Mono suite after all code changes returned **1130 passed, 104 skipped, 233 subtests passed, one existing collection warning, exit0** in ~118s. Hosted CI not present or claimed.

No production behavioral claim follows from a local sampling exercise. The new instruction profile has not been installed or promoted into current native ChatGPT Vera configuration.
