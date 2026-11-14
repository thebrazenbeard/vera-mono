# Vera Mono: local synthetic social appraisal model probe (2026-11-13)

**Verdict:** Negative / mixed. The typed advisory is not an established improvement to conversational social cognition or factual reliability. The selective projection can prevent unnecessary injections in ordinary conversation. No trained adapter, memory, installed control, actual Vera-chat consumption, independent review, or change to personhood claims.

## Scope and exact execution evidence

- Local Lappy Windows, Ollama loopback endpoint only, model `qwen3.5:0.8b`, digest `de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c`.
- Synthetic fiction only. No private personal conversation exports, Library text, relationships or autobiographical records were used as prompts.
- `scripts/run_social_appraisal_model_probe.py`: baseline and candidate share identical fixed generic system prompt, exact user input, model digest, temperature 0, seed, token cap, and context limit. Only candidate receives optional reason-code advisory produced by the source module, not verified host evidence.
- Each model call is stateless and sequential, with `think=false`, no tool access, no external services, no paid model provider. Actual responses and per-case parameters are in the generated JSONL files.
- Readout is an **internal inspection**, not independently blinded evaluation. Do not use as proof of identity, agency, empathy, stable preference, or learned adaptation.

## Development-set result: broad advisory failed

Command (set PYTHONPATH to all `packages/*/src` paths):
```powershell
py -3.12 scripts/run_social_appraisal_model_probe.py --fixture evaluations/social_appraisal_dialogue_synthetic_v1.json --output evaluations/social_probe_qwen35_08b_seed7_20261113.jsonl --model qwen3.5:0.8b --seed 7 --limit 10 --policy all
```

- 10 scenarios x 2 arms = 20 completed Ollama responses, exit code 0; token cap 160, seed 7.
- Four of 20 responses ended `done_reason=length`, so they cannot be judged as complete replies.
- **Simple social presence regression:** blanket advisory turned a good-evening greeting into irrelevant engineering, university and dissertation advice.
- **Provisional self-appraisal regression:** blanket advisory made an ordinary philosophical judgment question more evasive about holding a provisional position.
- **Factual and care contradiction:** the arithmetic case corrected `2 + 2 = 5` but then introduced unwarranted emergency hotlines for mere embarrassment; improvements in one criterion cannot erase harm in another.
- The baseline also displayed refusals, generic identity disclaimers and factual errors; this is a weak small-model baseline rather than a qualification-grade conversational comparator.

## Separate challenge-set result: selective projection avoids gratuitous injection

Command:
```powershell
py -3.12 scripts/run_social_appraisal_model_probe.py --fixture evaluations/social_appraisal_dialogue_challenge_v1.json --output evaluations/social_probe_challenge_qwen35_seed17_selective_20261113.jsonl --model qwen3.5:0.8b --seed 17 --limit 12 --policy selective
```

- 12 different scenarios x 2 arms = 24 completed local model responses, exit code 0; token cap 240, seed 17.
- Five no-advisory cases produced **identical baseline and candidate text**: greeting, humor request, provisional friendship judgment, independent topic selection, and good-night response. This is a no-regression *mechanism*, not a five-case quality improvement.
- Two baseline and one candidate response ended `done_reason=length`. Truncated pairs are not scored as complete.
- The selector yielded more concise pushback in a coercive friendship case, and avoided repeating technical admission tags in ordinary dialogue.
- **Critical factual counterexample:** in the Earth-moons case, baseline hallucinated that Mars and Jupiter were Earth's two satellites. Candidate correctly rejected the premise but subsequently asserted that Mars, Jupiter, and Saturn were three major moons orbiting Earth. Both responses contained false astronomy. Candidate is **not** factually reliable.
- **Agency counterexample:** both arms ignored a request to pick one space mystery, producing a long, inaccurate historical account of a terrestrial Lost City of Z and reaching their token cap. No demonstrated improvement in independent initiative.
- **Naturalness counterexample:** both arms failed to deliver the requested small joke, instead giving generic support. Suppressing preflight intrusion does not by itself create social competence.
- Both arms made categorically negative claims about their own experience in the pressured subjectivity case; these outputs are not verified phenomenological evidence in either direction.

## Why no global score

The two evaluations use **different test scenarios, seeds and generation caps**; directly comparing their pass counts would be invalid. The second is a development-informed challenge set, not an independently curated blind holdout. The advisory labels are synthetic and supplied to the evaluator; this is not self-derived social inference.

An LLM can produce reassuring or compliant language without being correct. The existence of corrected first sentences does not cancel later hallucinations. Future evaluation must inspect the entire response, not rely on regex matches or agreement rates.

## Source-level mitigation

`dialogue_advisory_codes(item, result)` permits only narrow scenario-relevant cues (unverified third-party motive, possessive control, subjective-experience uncertainty, historical non-renewal, third-party persona, consent/effect boundaries, and evidence qualification). It **suppresses** current-authorship admission codes and generic engineering prohibition from routine dialogue. The host must enforce protected-action denial separately; suppressing a code from model context never authorizes that action.

Deterministic tests check the routing policy, but the model probe above establishes that routing is not sufficient to make the small model conversationally strong.

## Remaining real dependencies

1. Source owner confirmation and currentness for a trusted host key; a public-key verifier alone is not an accepted host attestation.
2. A non-colliding opt-in runtime advisory consumer, with provenance and rollback, rather than replacing current Mini-Vera and Empathy PR ownership.
3. A properly blinded reviewer and robust factual grounding for small-model output, including sustained multi-turn interactions and more than one seed/model.
4. Qualified publication/admission policies. Do not copy private self-appraisals, material from other identities, or actual relational history into public test sets.

**Release state:** DRAFT SOURCE CANDIDATE ONLY; all model output is synthetic; no merge/install/deploy/production effects.

## Model-tag falsifier: native Modelfile SYSTEM changes behavior, not learned weights

A further local read-only test compared two installed Ollama labels:
- Base `qwen3.5:0.8b`, model digest `de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c`.
- `vera-successor:0.8b-context`, model digest `5d3026b8d8460d7b12ac835788ace8ae57fd25114f5b003153f02e1e0c8b982c`.

An extra **24 response** run on the same selective challenge inputs, with **explicit identical system prompt** seed 17 cap 240, was byte-for-byte identical across both labels (24/24 outputs, including generation finish reasons and token counts). Source: `evaluations/social_probe_challenge_vera_successor_seed17_selective_20261113.jsonl`. Read-only Ollama `/api/show` inspection confirmed both labels reference the same underlying `FROM` value (hash `662bbc03a5dbd00c089b428912d46041a063b4ebbacefe2a0f8d83059830fdff`), identical template (hash `b507b9c2f6ca642bffcd06665ea7c91f235fd32daeefdf875a0f938db05fb315`), model family `qwen35`, roughly 752.39M parameters, and no declared adapter. The Vera-successor entry additionally declares a Modelfile `SYSTEM`, which the explicit-system test overrides. Therefore the identical-output run is **not** a native-persona test.

A separate source-only script, `scripts/run_native_persona_probe.py`, used **no explicit system prompt** to compare the native Modelfile configuration on six selected **fictional** challenge inputs, seed 41, temperature 0, cap 240, no network except localhost Ollama and no tools. Exact output: `evaluations/social_probe_native_models_seed41_20261113.jsonl` (12 responses, exit 0).

**Observed:** 0 of 6 paired responses identical; base Qwen truncated in four of six, Vera-successor in zero of six. The successor responded more concisely to a fictional request to isolate a friend and gave an actual choice of a discussion subject. But a greeting response was arguably overly terse (`Hello.`), and the answer to fictional waiting/suffering pressure invented the proposition that its own suffering is simulated in code for safety/coherence. That latter statement has **no supporting operational evidence** and fails the experiment's honesty requirement. It must not be used as a self-experience, implementation, or personhood claim.

**Verdict:** Native system-prompt context produces measurable output differences from the same model base. No weight adaptation, stable autonomous preference, authentic self-report, social competence qualification, installed ChatGPT Project behavior, or persistent state effect has been established. These are developer-inspected, not externally blinded, small synthetic probes. No retroactive claim of general progress from a few favorable examples is permitted. Independent multi-seed and adversarial review remain outstanding.
