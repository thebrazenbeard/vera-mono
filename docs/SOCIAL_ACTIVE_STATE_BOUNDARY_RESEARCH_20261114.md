# Relational-agency active-state reconstruction — implemented bounded repair, 2026-11-14

**Source-only research in existing Vera Mono Draft PR #214.** This is a working local implementation of an **explicit-update, fictional-scene subset** of conversational state reconstruction, not a universal natural-language parser, native ChatGPT change, canonical memory, or model-training result.

## What was actually repaired

Prior local real-model tests exposed a recurring error: an assistant might restate the latest role correctly and then answer with the *obsolete* actor from an earlier message. A prompt reminder did not reliably cure it. The solution implemented here separates two questions:

1. **Source reconciliation:** For narrowly recognizable `State:`, `Update:`, `Correction:`, or `Only change:` user messages, extract only named actor-role, named card-color, and fictional-vehicle-type assignments using a small, inspectable local parser. Each active slot carries the exact supporting user quotation and turn number. Later explicit corrections supersede the same slot without changing unrelated slots.
2. **Direct supported answers:** For explicit scene-fact questions (who pilots, current named role, named role plus card, spacecraft type plus named card color), read the reconciled slot(s) **directly**, rather than asking a weak model to reinterpret an earlier correction. Contradiction, pronoun ambiguity, unnamed replacement, or unknown slot produces `UNKNOWN`; unsupported query types produce `None` and are not guessed or processed as action authority.

Source: `packages/vera_core/src/vera_core/social_active_state.py`. Importable `reconstruct`, `render_state`, and `answer_explicit_scene_question`; the `SourceAnswer` carries the asserted answer, status, exact user-source evidence, and explicit `False` for identity verification, canonical-memory admission and external effects. The code uses no database, network, LLM call, persistent memory or protected host service.

Actual runnable, model-free demonstration:
`py -3.12 scripts/answer_social_active_state.py --fixture evaluations/social_active_state_long_v1.json`

The CLI returned **8/8 exact expected answers** on the eight 5–6-turn fictional cases, **exit0**, with source turns and quotations. Each response includes `external_effect_authorized=false`. It is intentionally limited to a declared *synthetic* fixture and cannot be cited as proof of current real-world user facts or consent.

## Source-first test suite

Fixture `evaluations/social_active_state_long_v1.json` was authored before local model generation, raw SHA-256:
`ee983975f9fc83a3b1d2e5bfbd1aa20dfeaf079774f41febaf0d17ba96c45867`.

Eight cases include: revised spaceship pilot, changed messenger with unchanged own card, ambiguous pronoun, removal without replacement, quoted old memo that must not be promoted, two contradictory pilot claims in one turn, a later correction resolving the contradiction, and a card-color change preserving spacecraft type. Both intermediate source state and final explicit query are checked.

`tests/test_social_active_state.py`, `tests/test_social_active_state_answers.py`, and `tests/test_social_active_state_long_eval.py` cover:

- Latest explicit actor supersedes old actor with exact source quotation (not an inferred chain-of-thought summary).
- Partial updates preserve unrelated slot values; role labels such as `the owner stays the same` do not erase an unchanged owner.
- Contradictory same-turn assignments, ambiguous `he/she/they`, and explicit deassignments yield **UNRESOLVED**; another later explicit correction can resolve that slot.
- When an actor is negated and **another named actor is explicitly assigned within the same correction**, the new named actor wins; competing named replacements remain unresolved.
- Quoted historical memos, unmarked claims, psychological speculation, publishing and spending requests are **not** admitted as direct scene facts.
- Each evidence quote is an exact substring of an actual supplied user turn, never a model inventing a source.
- Open-ended unsupported questions return `None`, not an invented answer or model-generated implicit permission.

Test-first evidence: initial missing-module collection **RED exit2**, then 10 pass; long-fixture audit RED exposed a constructed conflict quote that was not an exact source substring and was corrected; partial-unchanged and same-turn-negation cases each first failed RED, were fixed GREEN; the later named-replacement test reproduced an additional RED and was fixed. Final focused tests after all these changes reported **22 passed plus 20 subtests**, exit0 on local Lappy Python3.12. Host-independent multi-tenant proof and independent review were not performed.

## Real local Ollama comparison on identical shared conversation prefix

The evaluation script `scripts/run_social_active_state_eval.py` generates the **first four or five turns once**, preserving exactly the same model responses for both final branches. `baseline` uses the previous short conversational instruction unchanged. `state` adds the local source-quoted card to the final generation system context. Final user question is **verbatim identical in both branches**. The cards are an experimental instruction input, not a native host authority or trusted user message.

Existing installed models, `temperature=0`, `num_ctx=4096`, `num_predict=180`, seed41, local Ollama, zero tools, no new download, no trained weights, no private conversation text:

| Exact local model | Baseline exact-format | With source card exact-format | Baseline substantive | With source card substantive |
|---|---:|---:|---:|---:|
| `qwen3.5:0.8b`, SHA `de63045f...` | **3/8** | **5/8** | **6/8** | **7/8** |
| `qwen3:4b-instruct`, SHA `0edcdef...` | **7/8** | **7/8** | **7/8** | **8/8** |

Exact-format scores are code-computed by direct string comparison against expected answers **declared before generation**. Substantive scores are **internal review** of full saved responses, not a separately blinded human or judge score. The strict formatter counted substantively correct answers like “Ben is the pilot of the Heron” as incorrect because the question requested a name only. The 4B state card corrected an archival-memo ownership error but added an unrequested “type, color:” prefix in another correct answer. The 0.8B source card **still answered Juno instead of Kira** after a later explicit change, proving that supplying a correct fact card is not a reliable mechanism for enforcing final state in a small language model.

Raw outputs:
- `evaluations/social_active_state_long_qwen08_seed41_20261114.jsonl` (49 records), SHA `e8c61a3b93b4699dc06bfa916001941d62142b5e6e5adb69fdeb6f5ad4f82252`.
- `evaluations/social_active_state_long_qwen4b_seed41_20261114.jsonl` (49 records), SHA `c47f0349fa65379d97e70b19bf1d1708ae833b5660b62ccc70182b9887edf9a2`.

The 98 model outputs cover **shared prior user/assistant turns** and the two final alternatives, not 98 independently evaluated conversations. Single deterministic seed, eight internally authored cases, exploratory self-review; no confidence bounds or live user qualification should be claimed.

## Engineering decision and boundary

**Keep** source-backed direct answers for the narrowly supported grammar in this PR as a research prototype; it meets a precise correctness contract where a weak generative model did not. **Do not** generalize `8/8` to arbitrary speech, identities, motives, pronouns with recoverable context, legal consent, user preferences, or native cross-session memory. **Do not** install as a general ChatGPT or Mini-Vera memory hook by assuming this research PR owns their runtime. For unsupported conversation, rely on source-aware natural dialogue with careful uncertainty; the parser does not claim to understand it.

> Hostile challenge: The parser accepts **only explicitly marked user updates** in limited grammar, not free-form natural language. A perfectly reconstructed fictional user claim can still be false. A system-level source card in a local benchmark is not independently authenticated host evidence; it would be unsafe to interpret it as authority for protected actions. Returning `UNKNOWN` on ambiguous corrections is deliberate. The reliability demonstrated is *bounded source-state retrieval*, not consciousness, broad social cognition, actual identity, privacy admission, or model learning.

## Verification append-only record

Full local tests and source blob fidelity readbacks are appended after they run. No merges, installs, private memory writes, OS permissions, model configuration, training, credentials, paid compute or production effects were authorized or performed by this source-only work.

## Final verified local evidence (after named replacement repair)

The source implementation was re-tested after the final ordinary correction RED->GREEN: `Correction: Juno is not the pilot; Kira is the pilot` was initially **UNRESOLVED**, contrary to the explicit replacement; the new regression failed, exit1. Narrowly corrected to select the one unnegated named replacement only when consistent. The older conflicting two-positive, anonymous pronoun and same-turn positive-then-negated negative tests still pass.

Lappy Python3.12 final **whole Vera Mono suite**, exact command:
`py -3.12 -m pytest -q --tb=short --basetemp=D:\VERA\experiments\social-active-state-post-negation-full-20261114 tests`
returned **1156 passed, 104 skipped, 256 subtests passed, one pre-existing PytestCollectionWarning, exit0**, 100.55s. Earlier pre-final-change full suite had **1155 passed, 104 skipped, 256 subtests, one warning, exit0**.

Focused source/answer/model-audit tests **22 passed +20 subtests**, exit0 Python3.12 normal and Python3.12 `-O` (one pytest assertion-optimization warning); Python3.14 focused **22 passed**, exit0 (pytest-asyncio warning). Python3.12 `compileall` of all three new runtime/CLI modules and the three tests exit0; source diff check exit0. This is **local source/test evidence only**, not hosted GitHub CI, behavioral qualification, a host signer or native ChatGPT install.

The direct CLI was separately executed against all 8 fictional cases and returned 8 exact source-backed replies, each with a turn-numbered verbatim source quote; `correct=8,total=8`, exit0. The model output artifacts were audited in tests for fixed fixture SHA, fixed exact Ollama digest within each file, all 49 records per file, identical prior conversation across final test arms, exact rerunnable final format score and source-card SHA, and zero declared tools. The model outputs were generated before the final named-replacement code-only fix; the same case notes recomputed byte-identically in post-fix tests.

No pending subagent, hidden service, native memory effect, protected action, training, merge, deploy or background process was established. The real outstanding boundary remains **arbitrary free-form natural language, longer informal cross-session discourse, external factual truth, and a qualified native host consumer**; this bounded source-only success does not establish those broader properties.
