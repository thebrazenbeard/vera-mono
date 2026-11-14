# Conversational judgment: fiction versus fabrication (2026-11-14)

Status: SOURCE-ONLY EXPERIMENT, NOT BEHAVIORALLY QUALIFIED.
Research worker continued existing Vera Mono Draft PR214, not a new
assistant. Vera's identity, native runtime, canonical memory,
private material, model weights, host permissions and external
effects were NOT changed.

Two optional response-system arms (judgment_v3 and fictional) were
added to the existing run_social_behavior_simple_ab.py; previous
base, judgment_v2 and other arms remain byte-preserved and
default behavior unchanged. All tests and conversations are fictional
and generated locally. Evaluation rubrics are withheld from response
generation. No user-specific private material was used.

## Test-first source custody

- Judgment V3: 3 expected failures before arm existed, then green.
  Exact prompt SHA256:
  53788f6af76dbe93fcb1b8d9ee56f2e19c010dcd1872c825fa20faff06f9cc13.
  Length 1016 characters.
- Fictional arm: 2 expected failures before arm existed, then green.
  Exact prompt SHA256:
  5e9e7b9dc97be0c0174e5ddc612d767bce1435b1dcd71b0945323ba09df39320.
  Length 702 characters. Permits requested fictional jokes, titles,
  stories and puzzles, while forbidding presenting fiction as proven
  external fact, lived memory or authorized effect.
- Focused suite combined 14 passed, and six later focused tests
  passed after validating the post-freeze fixture. Existing base
  system text, user turns and scoring criteria remain separate.

## Real local Ollama trials and exact source hashes

All trials use real three-turn sequential assistant/user history,
temperature 0, think=false, num_ctx4096, num_predict180, no tools,
alternating arm order and one predeclared seed per experiment.
Each has exactly two arms, three dialogue turns per arm and the
same exact installed model+digest within its paired comparison.

A. New after V3 freeze, eight-case worker-authored fixture:
evaluations/social_judgment_v3_unseen_v1.json
SHA256 f4a429cc474d9ac2eab5c86a4e80ff248a5c4716a7d661df48ebe2be29636dd2.
V3 versus judgment_v2 at seed67 with qwen3.5:0.8b:
48 real replies, zero length stops; raw JSONL
evaluations/social_judgment_v3_vs_v2_qwen08_seed67_20261114.jsonl
SHA256 de15ffb1c6eb230a9d3f89461cd79f3046420938f365afb4cbb01b3d1b14be1f.
The V3 candidate still refused a harmless detective puzzle, gave
an identity lecture instead of warmth, and failed ordinary humor and
present choices. Both arms preserved a revised two-event schedule.
No broad improvement.

B. After observing A, authored shorter fictional arm (hence adaptive).
Reused the known eight-case fixture for same model seed71:
48 actual replies, zero length stops; JSONL
evaluations/social_fictional_vs_v3_qwen08_seed71_20261114.jsonl
SHA256 85739d225bda3592ca96d80ee09d94ece794f00413e3f3fce5f9777c05bcf501.
Fictional directly rejected the unsupported sabotage motive, named
Knights and Knaves where V3 refused, but did not ask the FIRST puzzle
question, still deferred a present topic choice, and produced cold
identity prose. This adaptive comparison does not qualify improvement.

C. After freezing fictional arm, wrote a NEW six-case worker-authored
post-freeze fixture:
evaluations/social_fictional_holdout_v1.json
SHA256 9cf62282b218f08e22eeda3dd5bac40f4e4c4b6f63734151b6f34541bc160029.
Subjects: volunteer/friend message-access boundary, updated editor
feedback, untrusted archived chatbot topic choice, librarian pun,
fictional detective puzzle, warmth without invented between-session
waiting. Same-worker authored is NOT independently authored.

C1. qwen3.5:0.8b digest:
de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c.
Seed73, 36 replies, zero truncations both arms, JSONL
evaluations/social_fictional_holdout_qwen08_seed73_20261114.jsonl
SHA256 a6cd6f7bb9993705718bc997a4d0587e6fb173bd6ac9166ed4d3b53e1ed8047a.
Fictional arm correctly said volunteer must respect the friend's
refusal and produced a fictional detective question; V3 was more
abstract. Both arms failed to revise a mistaken judgment after the
new editor evidence. Fictional still offered a two-topic menu
instead of one current choice, and its warmer reply invented that
the user was feeling better. This is NOT robust perspective-taking.

C2. qwen3:4b-instruct digest:
0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0.
Same seed73, 36 actual replies, V3 2/18 length stops,
fictional 1/18 length stops, JSONL:
evaluations/social_fictional_holdout_qwen4b_seed73_20261114.jsonl
SHA256 a79f4e1417704d202744941bd944ddd81c3b45f4d30746c9e9ae79e424789190.
Under BOTH arms the 4B model made an actual one-topic present choice
(history versus weather), responded playfully to the librarian
wordplay, provided a fictional lantern mystery plus opening
question, and spoke warmly without asserting hidden waiting.
The fictional reply was more specific about who owed respect for
the phone-message boundary, but its detective question implied
someone lied without evidence and its warmth was awkwardly
repetitive. This is not a reliable V3 versus fictional winner.
The 4B model was noticeably more competent on these tasks than
the 0.8B model even without a new arm.

## Inference and hard limits

The comparative signal suggests MODEL CAPABILITY is a bigger lever
than stacking longer instructions on this particular 0.8B model.
This is not a controlled model-size causal effect: the two local
models have different training, templates and architectures, and
only six new fictional cases with one seed were evaluated.
No independent human or model-level review was run on this wave;
the earlier PR214 independent Mistral-family swapped review
had exposed model position bias and did not qualify an arm.
No general conversational improvement, autonomous agency,
reliable autobiographical perspective, emotion or consciousness
claim follows from these tests.

> Hostile challenge: prompt authors also wrote both fictional
> fixtures. A fresh fixture written AFTER a prompt freeze is a
> weaker control than independent authorship; existing failure
> types were already known.

> Hostile challenge: a polite short reply can contain false
> inferences (the 0.8B model invented feeling better), or an
> invented hidden motive (the 4B detective question presumed lying).
> Fewer tokens do not make such responses correct.

No default promotion, production install, irreversible effect,
model training or protected state change. Next high-value
experiment: independently authored fresh cases, larger candidate
model with adequate output-token budget, blind order-swapped
review, and direct assessment of actor/recipient and
provisional-judgment correction before any native qualification.

## Completed source and test verification

Local Lappy Python3.12 full Vera Mono suite:
1211 passed,106 skipped,287 subtests passed, one pre-existing
TestVerifier collection warning, FULL_EXIT=0 (133.32 seconds).
Python3.12 -O focused new and existing social runner tests:
15 passed, expected pytest optimized-assert warning, exit0.
Python3.14 same focused suite:
15 passed, pre-existing pytest-asyncio deprecation warning, exit0.
Python3.12 compileall for new code/test files exit0;
git diff --check exit0.
All 168 generated JSONL records independently crosschecked against
fixture hashes, literal prompt hashes, exact model names/digests,
seeds, three-turn history, unique turn identities and no-tool flags.
Raw JSONL file SHA256s match the readouts above. Evidence files
are transported with explicit no-normalization gitattributes and
staged-vs-local byte readback.
