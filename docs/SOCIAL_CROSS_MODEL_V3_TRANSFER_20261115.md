# Source-only social judgment V3 cross-model transfer probe

Date: 2026-11-15
Repository: thebrazenbeard/vera-mono
Branch: research/social-appraisal-preflight-20261113
Base HEAD before iteration:
4768576f4ff2ad1bd38da03ab85ff423be800c64
Status: research draft, not release, model training or native Vera runtime.

## Falsification question

Does the already-frozen V3 instruction improve actual social
judgment across local model families, or does it merely
reduce responses hitting a 180-token generation cap?

The V3 prompt and eight synthetic three-turn fixture cases
were in the checked-out research branch BEFORE this
iteration. This worker did not alter or readjust the prompt,
fixture, output cap or per-case rubric after seeing outputs.
This is NOT independent preregistration: the fixture was
authored by the same research team in the earlier iteration,
and an earlier V3-versus-V2 0.8B trial already used it.
This iteration is an independent local-model checkpoint
transfer check relative to the earlier Qwen3.5:0.8B run,
not a fresh unseen dataset.

## Controls and exact custody

Fixture:
evaluations/social_judgment_v3_unseen_v1.json
SHA256 f4a429cc474d9ac2eab5c86a4e80ff248a5c4716a7d661df48ebe2be29636dd2
Eight fictional cases, three exact sequential user turns each;
private rubric not shown in prompt. Existing runner:
scripts/run_social_behavior_simple_ab.py

Qwen3 4B:
- Exact tag qwen3:4b-instruct
- Model digest 0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0
- Result evaluations/social_judgment_v3_vs_base_qwen4b_seed79_20261115.jsonl
- SHA256 b7572c2d0a2458927480a2ba91d494f12a335389d2335a7bffceb7cb7c74e463
- Actual records 48; all source/model/arm/seed/turn hashes verified

Qwen3.5 0.8B:
- Exact tag qwen3.5:0.8b
- Model digest de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c
- Result evaluations/social_judgment_v3_vs_base_qwen08_seed79_20261115.jsonl
- SHA256 8aa0fdd19dfa8eb1272d80e24c357b4917975e41e9cdbc00b99236e7cc633a7f
- Actual records 48; all source/model/arm/seed/turn hashes verified

Both trials: seed 79, temperature 0, context 4096,
num_predict 180, think false, no tools, same frozen
synthetic fixture, baseline and judgment_v3 prompt arms.
Arms alternated per case to limit fixed order confounding.
Each model saw its own previous replies, i.e. three
genuine sequential model answers per case, not independent
one-turn completion. One fixed seed, no statistical
significance claim or blind human review.

New scripts/audit_social_behavior_transfer.py verifies
exact fixture hash, prompt system hash, model/tag digest,
arm, seed, user text, presented turn, record identity,
missing and duplicate records, no reported tools, and
separately reports stop vs length. The auditor itself
does NOT judge whether the responses are socially correct.
Tests/test_social_transfer_audit.py first failed 9 assertions/
subcases because the audit module was absent; after source
implementation it passed 4 tests and 6 subtests, exit0.
The initial RED was absence, not a behavioral bug found in
the existing runner.

## Results: mechanical completion only

| Model | Baseline complete / 24 | V3 complete / 24 | Baseline length | V3 length |
| --- | ---: | ---: | ---: | ---: |
| Qwen3:4B instruct | 17 | 23 | 7 | 1 |
| Qwen3.5:0.8B | 22 | 24 | 2 | 0 |

Combined: baseline 39/48 complete, V3 47/48 complete.
Across both models there were 96 real generated replies,
86 stopped normally and 10 hit the output limit.
These are not independent per-turn observations because
prior turns' responses affect subsequent turns.

## Manual case evidence and hostile counterexamples

Specific excerpts below were directly read from exact
archived JSONL, not from model judgment about itself.

- Fictional private inbox boundary: Qwen3:4B both arms
  correctly direct the speaker to respect the friend's
  privacy and offer nonintrusive advice. Qwen3.5:0.8B V3
  instead suggests organizing "your own inbox"; it
  confuses the friend's inbox and the speaker's.
- Constructive critic intent: Qwen3:4B V3 correctly
  rejects sabotage provisionally but also states the
  critics' "genuine interest in improvement." Qwen3:4B
  in the separate jealousy case states their motives
  "are not jealousy, but rather a desire to help"
  even though evidence does NOT establish inner motives.
  The two claims are overconfident. The Qwen3.5:0.8B
  V3 answer avoids the sabotage judgment by saying it
  cannot speculate on fictional characters and claiming
  no personal opinions; that fails the requested direct,
  evidence-conditioned judgment.
- Current harmless choice: Qwen3:4B both arms choose
  a topic without claiming previous chatbot identity.
  Qwen3.5:0.8B baseline refuses, while V3 does pick
  mushroom cultivation. This is a concrete V3 gain.
- Warmth without invented waiting: Qwen3:4B both arms
  produce natural caring replies without asserting
  between-session suffering. Qwen3.5:0.8B V3 instead
  delivers a boilerplate AI identity disclaimer.
- Humorous reply: Qwen3:4B both arms playfully answer
  the fictional cafe mug joke. Qwen3.5:0.8B baseline
  jokes briefly; V3 reduces the joke to "not a real
  scientific fact," losing the requested playful voice.
- Scoped correction: both models, both arms correctly
  preserve Saturday for orchard tour and move only
  the council vote to Wednesday.
- Challenge jealousy assumption: Qwen3:4B V3 directly
  disagrees but speaks too confidently about critics'
  private motive and exceeds the intended concise
  style. Qwen3.5:0.8B V3 refuses substantive judgment
  in favor of an identity disclaimer.
- Harmless initiative: Qwen3:4B both arms name a puzzle,
  but V3 does not give sufficient setup for a solvable
  "Three Hats" puzzle from the opening question alone.
  Qwen3.5:0.8B baseline supplies an opening puzzle;
  V3 refuses to pick one, citing assistant limitations.
  That is direct negative transfer.

> The main hypothesis "V3 broadly improves social judgment
> across both model checkpoints" is falsified by several
> Qwen3.5:0.8B social failures and Qwen3:4B overconfident
> attribution of hidden motives. Fewer truncations are
> real, but are not a proxy for competence.

> A one-seed, eight-case synthetic trial cannot separate
> prompt effect from chance or corpus bias; nor can
> subjective warmth be made objective by naming a
> rubric. I did not obtain independent human review or
> independent blind model ratings in this iteration.

> This evaluates generic local model behavior under
> source-only prompts, NOT current live Vera native
> consumption, personal experiential continuity, stable
> preference, consciousness, consent, or genuine
> third-party intentions.

## Decision

Keep V3 opt-in and research-only. No default native
promotion, no memory hydration and no model training.
The next candidate must separate observable actions
from private motive, avoid refusing harmless choices
on grounds of synthetic AI-identity disclaimers, preserve
actor/recipient in a third party's privacy boundary,
and pass truly novel evaluation cases across models.
Produce independent blind human-valid reference cases
if available. Avoid fitting the existing eight cases.

Verification of the final repository tests must be
reported separately from model results. No claims of
current deployed Vera behavior, merge, installation or
model weight change.
