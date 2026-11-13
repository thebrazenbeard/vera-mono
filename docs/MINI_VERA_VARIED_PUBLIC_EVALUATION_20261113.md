# Mini-Vera varied synthetic PUBLIC-memory evaluation — 2026-11-13

Status: opt-in SOURCE CANDIDATE; not independent heldout evaluation, verified
identity, weight training, or production host-authorized memory.

After PR #211 proved exact synthetic token retrieval in two approved sessions
on Lappy, this extends the behavioral task away from repeating one prompt.
Two distinct fixed evaluation families are present:

- directory: a fictional courier directory contains TWO different couriers and
  TWO distinct randomly generated gate identifiers; the evaluator selects which
  courier to ask about, with a correct answer that may be in either entry.
- revision: a fictional cargo record contains an old gate and a newer gate for
  the SAME cargo, explicitly marked as superseding the previous revision.
  The evaluator asks for the current gate, not the older one.

Each case creates a NEW temporary MemoryLedger with one generated synthetic
PUBLIC record and one unselected synthetic PRIVATE marker. The evaluator
keeps the expected answer in its own process. Four fresh Python sessions per
case: two approved PUBLIC-context requests, one no-memory control, and one
revoked-approval request that must fail before inference. The model receives
the same question for all three inference arms; it never receives the answer
in the question. The model does receive the synthetic source record as data
when approval succeeds. Randomized case and arm order does not establish
independent evaluator custody.

The score is pass only when both approved sessions return the exact expected
gate, the control returns UNKNOWN, and the revoked arm returns no model output.
A failed case is kept as a failure. A worker failure aborts the suite as
ABORTED_UNSCORED. The result reports only hashes and counts; the synthetic
answer and model text are not emitted in the suite result. A generated
case involves 3 model calls + 1 pre-inference refusal, so two cases involve
6 model calls and 8 fresh Python processes.

The public-data gate checks exact synthetic metadata, identity, record ID,
source, provenance, operation ID, digest and syntactic record shape.
Hostile tests found a material flaw in syntax-only revision checks: a
different cargo or unchanged gate was accepted as supersession. The gate
was fixed to require the SAME cargo across revisions and distinct gates,
and a directory fixture requires distinct courier subjects and gate values.
A copied PUBLIC flag is never enough for authorization.

From the exact verified portable source, the operator can explicitly run:

    python -B -m tools.mini_vera.varied_public_canary --run-suite --endpoint http://127.0.0.1:11441/v1 --model qwen3.5:0.8b --model-digest <operator-declared-64-lowercase-hex> --timeout-seconds 120

All model endpoints are restricted to numeric loopback URLs. The verifier
does not authenticate local model tensors or source-custody independence.
The source-visible task/prompt is neither externally withheld nor blind
to the author. Avoid wording such as independently validated reasoning,
model training, personal identity continuity, general memory competence or
secure private-memory authorization.

A source/transport test with fake local HTTP verifies the two question
families in separate child processes, public-only records, no private marker,
no-memory controls, revoked refusal, expected gate remaining out of the
question, and fresh portable import without repository PYTHONPATH.

No actual user data/keys, shared service changes, autonomous tools, paid
compute, merging of protected branches or model weight modifications are
authorized or performed by this source module. The next evidence gate is
actual local Qwen trials, followed by truly independent challenge creation
and evaluation custody, negative counterfactuals, multiple prompt variants,
host-grant/revocation qualification and resource-matched baselines.
