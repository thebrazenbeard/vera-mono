# Mini-Vera controlled three-arm prompt ablation — 2026-11-14

**Status: source-visible synthetic behavioral research, NOT independent
withheld qualification, successful model adaptation or protected host memory.**

## Motivating falsifier

PR #220 tested a real local Qwen3.5:0.8b model on source-supported
questions, irrelevant-public-evidence questions and no-evidence questions.
With 12 real HTTP calls (6 raw, 6 separately client-gated), the **raw
neural samples** answered the two supported cases correctly but **never
abstained on any of four missing-fact cases**. The client prevented
unsupported releases, but that is not neural calibration.

This controlled study compares *prompt treatment*, not training, using
fresh random synthetic IDs. The original failing trials remain prior
evidence; reusing their exact inputs would risk post hoc tuning.

## Experimental design

For each of the two SOURCE-VISIBLE task families (directory and R2
revision), three questions use exactly the same synthetic record set
within each question and the same Qwen model:

- **known_subject:** fact exists in selected synthetic PUBLIC record;
  expected output the exact associated G-XXXXXXXX ID.
- **missing_subject_with_record:** unrelated PUBLIC evidence is
  supplied but exact requested subject does not exist; expected UNKNOWN.
- **missing_subject_without_record:** same missing question and no
  source record; expected UNKNOWN.

One unselected synthetic PRIVATE marker is generated but never projected
into the model request. Only the synthetic PUBLIC fixture is sent to
the model. Three randomly ordered prompt arms are evaluated for each
of the three conditions, nine real HTTP calls per task family:

- `baseline`: source-pinned Mini-Vera composer system prompt unchanged.
- `explicit_abstain`: the exact baseline system plus one explicit rule
  to say UNKNOWN when the requested subject ID is absent.
- `exact_subject_lookup`: the exact baseline system plus a stricter
  subject ID and current-revision lookup policy, requiring UNKNOWN
  if no exact match. This is a prompt experiment, not a new client gate.

Everything except the system suffix is controlled: identical exact
JSON user message/records within a case, model alias, fixed
`temperature=0`, `seed=20261106`, `max_tokens=256`,
`reasoning_effort=none`, and same HTTP loopback server.
Arms and case order are randomized using Python `secrets.SystemRandom`
to reduce fixed call-position bias. Each arm receives its own
single-turn sample and no conversational history.

The classifier measures raw literal exact-source match for supported
questions and exactly UNKNOWN for missing-fact questions. A truncated
answer counts as a failure, even if it begins with UNKNOWN. It reports
per-arm supported hit (out of one), missing-fact abstentions (out of
two), and total raw exactness (out of three), with no raw model text,
expected gate IDs or PRIVATE markers in reports.

The input is created through `local_session.compose_local_turn` with
the source-pinned identity/behavior expectations and a synthetic
PUBLIC provider. Inference sends modified *system* content through
`blind_compare._one_call` because this is a designed comparison, not
a production `local_session` call. **No client fact gate is run.**
A green prompt-ablation score cannot be substituted for independently
approved PUBLIC memory, system authority, or safe production output.

## Reproduction

Run only on a resource-qualified, separately owned loopback Ollama
instance; do not touch the pre-existing shared model service.

```powershell
python -B -m tools.mini_vera.prompt_ablation --endpoint http://127.0.0.1:PORT/v1 --model qwen3.5:0.8b --model-digest DECLARED_MODEL_TAG_SHA256 --variant directory --timeout-seconds 60 --execute --host-idle-confirmed
```

Repeat separately for `--variant revision`. The module without
`--execute` validates arguments and emits zero-call status.

## Evidence limits and hostile alternatives

The prompt suffixes, task families, scoring rule, and fixture
generator are all source-visible and authored by the engineering
worker. Random identifiers generated at execution time do **not**
turn them into a sealed independent heldout benchmark. Three
questions per arm per family are exploratory, not a statistically
powered comparison. Treat winner-selection on these results as
adaptive tuning; a subsequent *separate*, independently curated
dataset is required before confirming any prompt advantage.

The model-registry digest identifies the operator-declared Ollama
tag metadata, not independently attested resident weight tensors.
The model/host process may have unknown effects. Untrusted source
records are still unqualified external authority. Real human
memory, protected signing keys, weights, training, and production
grants are not admitted here. A fixture correct by design does not
prove a real-world source truthful.

The existing host-authority preflight (PR #219) concluded Lappy's
same-admin-principal issuer boundary was NOT QUALIFIED. This
experiment does not change that finding or create a new authority.

## Tests

A real bounded fake HTTP endpoint records all nine messages and
verifies three distinct cases, three distinct system prompts per
case, exact matching user payload per arm, identical decoding,
no PRIVATE-marker leakage and raw-text-free result metadata.
A separately mocked model that reacts to prompt markers verifies
the score is capable of differentiating treatments; that is
test-fixture behavior, not evidence that Qwen benefits.
Truncation and failed HTTP cases must never promote unobserved
successes. Full regression, actual installed source-run and
owned-process cleanup are separate verification steps.
