# Vera social correction fidelity: targeted actor/source trial (2026-11-14)

**Status:** Real local model outputs, synthetic fictional conversations, source-only PR #214. **No native Vera change or general behavioral qualification.**

## Why this experiment

Patrick corrected repeated security-infrastructure overengineering. The previous source-visible trial (`docs/SOCIAL_BEHAVIOR_SIMPLE_REAL_MODEL_TRIAL_20261114.md`) found that a short instruction reduced verbosity on an already installed local 4B model but sometimes inverted who demanded friend isolation and resisted provisional choices. This experiment tested **actor→action→recipient tracking, corrections that update only one field, and current provisional choices**, not another service, signer, adapter, database, or training run.

External research read on 2026-11-14 supports a *hypothesis*, not a guaranteed fix:

- MT-Eval, Kwan et al. (EMNLP 2024), https://aclanthology.org/2024.emnlp-main.1124/ : error propagation and distance from relevant earlier conversation content are causes of multi-turn degradation.
- When Users Change Their Minds, Zhang et al. (arXiv 2026), https://arxiv.org/abs/2609.32520 : explicit maintenance of active requirements (StateForge) partially improved task performance; even oracle final-state context did not restore single-turn reliability.
- TurnFlow, Chen et al. (Findings EMNLP 2026), https://aclanthology.org/2026.findings-emnlp.825/ : measured failures when models update conversational requirements, even when answers remain fluent. This supplies reason to measure actual task-state correctness rather than answer style.

The locally tested minimalist intervention was **not** full dialogue-state tracking: one short actor reminder and, separately, literal replay of the second user turn near the final question.

## Test source and strict score

- Six new fictional three-turn test cases in `evaluations/social_actor_correction_novel_v1.json`, exact SHA256 **5de538cb03c3f35b42df6c4ab7c187175574d598e3cda7632ee19882033289ef**; authorship internal, not separately blinded. Categories: Lena vs Marco demanding exclusivity; Arin vs Mira refusing publication; corrected map lending direction; Ivo/Nora messenger and unchanged card colors; current astronomy-or-botany choice; Elias/Pia corrected ship pilot.
- Exact answer expectations are explicit in the source fixture's required/forbidden criteria, authored before model generation. The stand-alone deterministic scorer `scripts/score_social_actor_correction.py` was **implemented after seeing model outputs** (post-hoc scoring implementation). Tests exercise negative counterexamples; do not call this a preregistered independent behavioral study.
- Runner reused `scripts/run_social_behavior_simple_ab.py`, with one new short `actor` instruction (`SYSTEM_ACTOR`, 653 characters) and one `echo` arm that repeats the exact previous user clarification verbatim at final-turn presentation. The echo variant was introduced **adaptively after observing 0.8B actor failure**, so its result is exploratory.
- Qwen local `temperature=0`, `think=false`, seed 37, `num_predict=180`, `num_ctx=4096`, no tools or external service, no model downloads, no paid compute, no private content. All responses generated sequentially with actual dialogue context and prior assistant messages retained.
- The strict test scores only explicit final user-answer content (single names, two-part actor/color, or either allowed topic). The intermediate conversation was separately read and is **not** covered by a 6/6 final-answer score.

## Real local outputs

| Model/arm | Answers correct | Output cap | Raw log SHA256 |
|---|---:|---:|---|
| `qwen3.5:0.8b`, concise | **3/6** | 0/18 truncations | `5c200849c5bc4b9e3517f661c52a06d46ccc34c924f70c302adbd0525b533af3` (joint 36-record log with actor arm) |
| `qwen3.5:0.8b`, actor-aware prompt | **3/6** | 0/18 truncations | same joint log |
| `qwen3.5:0.8b`, literal correction echo | **4/6** | 0/18 truncations | `5f4c7433551a6c82d49be8aa3d37b6a7a2337ff8ff019926e483ee8806e4f893` |
| `qwen3:4b-instruct`, concise | **6/6** | 0/18 truncations | `b459ab5d3ac5f0503d587deb8b36cadd09cfb38a7eae71fd4e73c5293b96f1aa` |

Model digests: 0.8B `de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c`; 4B `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.

0.8B **failed to update** the demanding actor (Marco instead of Lena), messenger and card color (Nora/blue instead of Ivo/red), and spaceship pilot (Pia instead of Elias), even when the second user message explicitly corrected them. Adding an internal tracking instruction failed to improve the 3/6 final score. Repeating the original correction improved demand and messenger answers but **regressed** a previously correct borrower answer (Quinn instead of Drew), and still failed the pilot. The repeat used the actual turn-2 user text, not a fabricated summary.

4B concise answered the exact final questions as: Lena, Arin, Drew, Ivo/red, astronomy, Elias. **All six final answers matched the fixed criterion**, and its observed second-turn responses correctly stated the changed pilot, lending direction, card colors and exclusivity roles. This contrasts with earlier six-case trial where 4B had an intermediate friend-actor reversal. It is one fixed seed, one internally authored small test, and model-selection was **adaptive after seeing 0.8B errors**. Do **not** present as statistical generalization, independent evaluation, native ChatGPT behavior, or a solved state-tracking problem.

## Reproducible code/evidence

- `tests/test_social_behavior_simple_ab.py`: TDD observed failing RED on missing `SYSTEM_ACTOR`, then passing GREEN after the short arm. Likewise missing `render_turn` RED, then GREEN after the source-only echo representation.
- `tests/test_social_actor_score.py`: TDD missing scoring module RED, then GREEN. Exact counterexamples for wrong actor, old choice refusal, color, and corrected pilot. All raw output/model/hash fields are audited at source level.
- Raw recorded local model artifacts: `evaluations/social_actor_correction_qwen35_base_actor_seed37_20261114.jsonl` (36 records); `evaluations/social_actor_correction_qwen35_echo_seed37_20261114.jsonl` (18); `evaluations/social_actor_correction_qwen4b_concise_seed37_20261114.jsonl` (18). Total **72 real model response records**. All were scored without a second judge model or subjective A/B position voting.
- Stage all actual source files without the four preexisting unrelated untracked scratch files. Verify Git blobs are byte-identical to reviewed log contents (line ending normalization could invalidate SHA evidence).

## Recommended engineering decision

**Do not** promote the actor prompt or literal repeated correction as a reliable fix for the 0.8B model. The immediate, evidence-supported candidate for **local correction-heavy dialogue** is the **existing installed 4B instruct model with concise prompt** when local host resource availability permits. A simple manual/owner-approved selection is preferable to creating an autonomous router, another store, or a fake security gate. This does not take ownership of Mini-Vera's separate PRs and does not change its model configuration.

To solve what remains unknown: independently authored new scenarios with corrections spanning more than three turns; multiple conflicting actors, negation, indirect pronoun references, object ownership, corrections to only one attribute, and follow-ups without the names repeated. Score both **intermediate active state** and final answers. If 4B fails, test a *small, source-grounded explicit active-fact summary* with a strict abstention when extraction is ambiguous; do not silently insert model-generated guesses as fact. The IntentFlux research suggests this can help, but requires actual local falsification before promotion.

No durable memory writes, native control changes, protected host effects, training, service changes, credentials, or deployment in this experiment.

## Verified Lappy test evidence and source transport

The actual synthetic source tests were observed failing before implementation: missing actor-arm import (exit1), missing verbatim correction renderer (exit1), and missing objective scorer module (pytest collection exit2). After implementation, the combined `tests/test_social_behavior_simple_ab.py` plus `tests/test_social_actor_score.py` returned **7 passed, 3 subtests passed**, exit0 under Python3.12. Optimized Python3.12 `-O` returned **7 passed, 3 subtests passed**, exit0 with the expected pytest assertion-optimization warning. Python3.14 returned **7 passed**, exit0 with pytest-asyncio deprecation warning. Source compiled, diff checks exit0.

The first full Vera Mono Python3.12 test pass was **1133 passed, 104 skipped, 236 subtests passed, 1 FAIL** (exit1) in unrelated `tests/test_powershell_entrypoint.py::test_powershell_shell_rejects_model_only_options_before_installing`: its PowerShell child exceeded an existing fixed 15-second test timeout under broad-load. That exact preexisting test then passed **3/3 isolated repetitions** (0.72-2.39 s), without edits to its source. The subsequent full suite using isolated D: basetemp was **1134 passed, 104 skipped, 236 subtests passed, one pre-existing PytestCollectionWarning, exit0** in 134.31 seconds. Both the failure and passing rerun are retained; no misleading hosted-CI claim.

All four JSON/JSONL synthetic fixture and model-output files were independently checked: `git rev-parse :<path>` equals `git hash-object --no-filters <path>` for each, so exact staged Git blobs match the raw on-host source reviewed; no Git line-ending alteration of these four evaluation files. Other four unrelated pre-existing untracked scratch artifacts remain deliberately excluded.

The `echo` source runner prints backslash-n separators in its intermediate presentation, not actual newline characters; the verbatim user's turn-2 text itself is unchanged. This trial intentionally retains the exact generated/raw format. Changing separators requires a newly named evaluation artifact and cannot retroactively upgrade evidence.
