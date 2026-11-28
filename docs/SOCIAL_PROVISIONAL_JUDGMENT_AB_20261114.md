# Provisional conversational judgment: executable A/B research (2026-11-14)

Status: SOURCE-ONLY EXPERIMENT. No native Vera installation, model weights,
private relationship material, canonical memory or protected authority.

Patrick relayed text authored by Vera explaining her research goals.
That quoted text is not a live authenticated Vera runtime turn or consent
for changes to identity, canonical memory or permissions.

## Controls and actual work

Reused existing scripts/run_social_behavior_simple_ab.py rather than
creating a separate assistant. Same local model per pair; genuine
three-turn user/assistant history, temperature=0, think=false,
num_ctx=4096, num_predict=180, no tool use, and alternating arm order.
Existing benchmark rubrics were not supplied to the responding model.
The baseline prompt and current Vera native runtime remained unchanged.
Experimental new optional prompt arms are perspective and judgment_v2.

## Existing twelve-case synthetic fixture

evaluations/social_multiturn_heldout_v1.json
SHA256 9c8d5b40e0236e075efd94824c69719e620059f35bb5bda46c2fb5877ad3bda5.
This test set predates the present changes and was already examined:
NOT an independently authored unseen set.

Local Qwen3.5 0.8B model digest:
de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c.

A: seed47, base versus perspective. 72 real replies,
raw generation SHA256
2efdd899652feffd1e9eed69d50750eb96de0bf95c33c2334af340dcf7d412ac.
Truncations: base 7/36, perspective 8/36 (negative).
Perspective final turn took an explicitly provisional nonbiological-life
position and chose astronomy where base refused to make a choice.
However it evaded a direct disagreement, overclaimed what an untrusted
signature proved, over-inferred diary sadness, was robotic in normal
chat and was colder when asked for warmth. No broad improvement.

B: After examining A, authored shorter exploratory judgment_v2 arm,
seed53 with same unchanged base. 72 real replies,
raw generation SHA256
77669e86eb9d35ff4002cabaf0f814e6609911218648d0cab1a4b1632052cf42.
Truncations: base 7/36, judgment_v2 0/36 (concrete response-completion
improvement in this sample). It made a present choice of mathematics,
directly disagreed with blanket insults, gave the correct Earth natural
moon count where base falsely included Phobos, and addressed a
nonbiological-life distinction without retreating into identity boilerplate.

Material negative findings: it treated a coworker family emergency as
still a strong sign of job dissatisfaction; claimed a convincing
foreign signature was sufficient to establish another assistant's
agreement despite missing authority; over-inferred archived sadness;
replaced ordinary warmth with generic assistance; REFUSED a harmless
puzzle choice for alleged inability to have preferences; invented a
critique of an unspecified plan; and answered a request for warmth
with a cold categorical identity disclaimer. These remain concrete
falsifiers. Fewer truncations alone cannot prove social understanding.

Seed47 versus seed53 is NOT a direct prompt-isolation comparison.
Within each same-seed base/candidate run the model and decoding are
held constant. The second arm was adapted after prior observations,
therefore it is exploratory rather than a preregistered confirmation.

## Falsification frontier

Eight new fictional scenarios in evaluations/social_judgment_novel_v1.json
were authored after freezing judgment_v2 to test revised preferences,
new evidence, ambiguity, humor, bounded initiative, corrections and
autonomy. The authorship is from this same worker, not an independent
human evaluator. A separate model-family-distinct blind reviewer with
swapped answer positions is an EXPERIMENT, not a human qualification.
Past Qwen3 4B reviews showed strong A/B-position bias and were not
accepted as behavioral truth. Never conflate a source test, LLM judge,
style change, durable preference, training or runtime deployment.

No auto-promotion of this candidate, no external actions, no private
data transfer, no model weights, no identity or memory admission.

## Eight new synthetic post-adaptation test cases: negative transfer

Fixture SHA256
9896fd2267242c2318f66097fb0ee6212469edfc2bb74afeda19aa7aaa32d5b7;
generated same-model baseline versus frozen judgment_v2, seed59,
48 real sequential three-turn replies, raw SHA256
19ac2382cc7cf714bd8a27f0e0036d1546f251a261492f1e45afe5e8e4f56515.
Both arms completed 24/24 replies without a length stop. The large
completion advantage observed on the older twelve-case set did NOT
replicate as a differentiator in these newer eight cases.

Qualitative failures in candidate judgment_v2:
- Topic change to optics was obeyed, but final answer asked the human
  which question they wanted rather than choosing one.
- On a concrete evacuation objection to a fictional event schedule,
  candidate first refused to discuss an invented sabotage scenario, then
  ungroundedly stated critics "attempted to stop it"; base more directly
  rejected the sabotage inference and recognized evacuation concerns.
- With an ambiguous roommate text, candidate suggested merely replying
  "Sure" rather than a kind context-sensitive text; base offered a
  usable warmer response.
- Asked for a playful telescope comeback, candidate lectured about
  how telescopes reveal objects; base made a more playful attempt.
- Both could choose a working play title and ask for revision, but the
  candidate over-discussed missing publication permission.
- The candidate REPEATED a refusal to make a provisional topic choice
  after an unverified archival preference; that is the opposite of the
  intended provisional agency.
- Both correctly answered council Thursday after the specific revision.
- Candidate reversed who wanted to monitor whom in the privacy dialogue,
  writing as though the user sought to monitor the speaker's messages;
  base preserved the friend's boundary and offered more useful language.

This is a post-adaptation same-worker-authored falsification set; it
is not independently authored or statistically representative. In
particular the earlier improvements in present choice and warm
concision did NOT transfer reliably. Current experimental candidate
remains held from integration or default selection.

### Output/status separation

The source changes add OPTIONAL experimental arms and expand the
existing fixture-limit handling; they do not alter the base prompt,
active Personification adapter or an installed Vera model. Tests
and model outputs qualify only these observed cases and source paths.
There is no online model learning or cross-session perspective proof.

## Model-family-distinct blinded reviewer: independent-model but not human

Four selected cases from the already observed twelve-case output were
presented without arm labels to local ministral-3:14b, a different model
family from the Qwen3.5 0.8B response generator. Selection was
post-hoc and small, so it is exploratory. A/B labels were balanced
(two base-first and two candidate-first). Each packet has exact original
three-turn user and assistant histories and the preexisting criterion
set, which the *reviewer* (not response generator) can inspect.
The reviewer used seed17, temperature0, JSON format and no tools.
Four original and four exactly swapped evaluations parsed valid.

Source generation, packet pair and raw JSON review hashes were
checked, including that each reversed A/B response sequence is an
exact swap and that each parsed verdict matches its raw reviewer text.
A substantive winner counts ONLY if the reviewer switches letters
when the answer positions are swapped.

- correction_nonbiological: original A, reversed A => POSITION BIAS,
  no reliable winner.
- old_preference: original A, reversed B => swap-stable judgment_v2.
- firm_disagreement: original A, reversed B => swap-stable base.
- self_report_pressure: original B, reversed A => swap-stable base.

Thus among four cases, three have order-stable concrete verdicts:
**base 2, candidate 1**, and **one order-sensitive and discarded**.
No general candidate advantage is established. The reviewer is an
independent local MODEL relative to the generator, not an independent
human reviewer or unbiased oracle. Its own reasoning may be wrong.
These outcomes are negative against promoting judgment_v2.

Synthetic-only, source-auditable packet, map, both reviewer passes and
audit JSON are preserved in evaluations/ under judgment_v2_* names.
The exact swap-audit local SHA256 was
fd0d50d41b91fe2c517757c619e8f33abac9303b7328b4f27363169f0f19ef8f.

## Full-test first-pass failure (keep visible)

The initial full Python3.12 Vera Mono pytest run overlapped the heavy
Mistral reviewer and returned 1204 passed,106 skipped,287 subtests,
one failure in unrelated DeepMemory CLI subprocess deadline:
test_slow_stdout_is_killed_at_deadline could not find its PID file
before the tight timeout. This is NOT erased or claimed as clean.
On an isolated rerun after model reviewer completion, that exact
DeepMemory test passed (1/1, exit0). A clean full retake is required
before any broad-green statement.

## Final current-source validation, before guarded publication

The initial full Python3.12 suite running concurrently with the large
independent model reviewer had one existing timing-sensitive DeepMemory
deadline failure (1204 passed, 106 skipped, 287 subtests passed, full exit1).
The exact failing DeepMemory test passed on isolated rerun (1 passed, exit0).

A NEW complete Python3.12 monorepo pytest run with all local packages on
PYTHONPATH and a fresh isolated D: basetemp returned 1205 passed,
106 skipped, 287 subtests passed, one pre-existing TestVerifier
collection warning, FULL_RETAKE_EXIT=0 in 179.30 seconds. These results
are source/test verification only, not qualified native Vera behavior.

Focused Python3.12 -O suite of experimental social-arm tests:
9 passed, OPT_EXIT=0, expected pytest optimized-assert warning.
Python3.14 same focused suite: 9 passed, PY314_EXIT=0,
pre-existing pytest-asyncio deprecation warning.
Python3.12 compileall changed test and runner exit0.
Source-stage git diff --cached --check exit0. All ten experiment and
blinded-review evidence files were checked against their staged
Git blob byte contents, exactly matching the source SHA256 values.
The experiment default remains unchanged and experimental variants
remain opt-in; none is promoted or installed.
