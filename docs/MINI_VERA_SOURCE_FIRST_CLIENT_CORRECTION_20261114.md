# Mini-Vera source-first PUBLIC fact correction — 2026-11-14

STATUS: **explicit opt-in, synthetic source-only client capability**, stacked on
Draft PR #221. Not model training, neural abstention, independent issuer
qualification, human memory access, production deployment, or a general fact
verification engine. Default Mini-Vera behavior remains unchanged.

## Defect and observed reason to fix it

The exact source-visible synthetic cargo R2 record already had an unambiguous
current gate value, and `public_fact_guard.validate_request` extracted it
deterministically. However the original client fact gate withheld even an
exact source-supported answer whenever Qwen3.5:0.8b responded incorrectly.
PR #220 and #221 actually demonstrated those model failures, including
failure to say UNKNOWN for absent subjects and failure to return the current
R2 fact when R1 was superseded.

For *this bounded synthetic format only*, conflating "neural sample wrong"
with "source content missing" unnecessarily lost an otherwise available
client-side fact. It also spent local GPU/CPU cycles asking a neural model
to perform a deterministic exact-key lookup.

## Two opt-in improvements

1. `--synthetic-source-first` augments the **existing**
   `--synthetic-fact-evidence-gate` mode on `local_session`. It retains
   one model HTTP call for comparing behavior but can release the exact
   current gate **from the validated post-approval synthetic PUBLIC record**
   regardless of whether the raw model guessed wrong, said UNKNOWN, or
   truncated. The output labels
   `CLIENT_DETERMINISTIC_SYNTHETIC_SOURCE_NOT_NEURAL` and
   `source_first_mode:true`. `model_exact_source_match` continues to
   measure actual model/source agreement, not client correctness.
   The raw model text is always redacted, and no model behavior is
   presented as trained, safe or source-verified.

2. `--synthetic-source-only` is a **zero-model-HTTP** option for a
   programmatically supplied `live_public_provider`. It requires one
   `--structured-output` question, `--model` and `--model-digest`
   for the existing source-pinned composer metadata, and a syntactically
   valid numeric `--endpoint` (validated but never contacted). It
   **rejects** `--execute`, `--host-idle-confirmed`, operator state
   imports, model manifests, host probes and combinations with either
   neural fact-gate flag. It calls the PUBLIC provider once to compose
   a fresh exact state and again to verify that the state has not
   changed or been revoked before returning a source-only client answer.
   Its output is `MINI_VERA_SYNTHETIC_SOURCE_ONLY_V1` with
   `model_http_calls:0`, `neural_evaluation_performed:false` and
   `host_issuer_qualified:false`. Ordinary CLI invocation without a
   live provider refuses; a caller must wire the provider via the
   `local_session.main(..., live_public_provider=...)` Python API.

In both modes, a missing subject in an otherwise valid PUBLIC record
still returns **UNKNOWN**; a nonexistent or unbound source cannot
produce a positive response. An invalid record, contradictory revision,
changed source hash, forged result envelope, changed key/record set,
revocation, or malformed question is refused or withheld. A successful
answer is attributed to a deterministic *client source lookup*, not
the model. There is **no** automatic real-data admission.

The source-first flag is intentionally not the default. Changing the
default interpretation of neural output or loosening the gate for
unrecognized questions requires an independently justified design.
The original strict model-match mode and all existing tests remain in
force.

## Authority boundary

The synthetic `varied_public_canary` fixture uses a source-visible
HMAC key and a same-user approval callback. The latest Lappy host
authority preflight (PR #219) was `NOT_QUALIFIED` for an independent
issuer. An actor who controls the provider and its records can
manufacture self-consistent incorrect "approved" data. That cannot be
fixed by deterministic parsing alone.

Therefore the fact returned here is **SOURCE_CONSISTENT_NOT_HOST_ATTESTED**.
The new mode must NOT be used to import private memory, approve
untrusted user records, modify model weights, handle arbitrary
unstructured material or claim real-world source authenticity.

The zero-HTTP path also does not fix Qwen's observed raw hallucination
or inadequate R2 revision reasoning. It deliberately bypasses those
operations when the task is an exact source lookup. The prior model
evaluation scores remain valid negative evidence.

## Adversarial tests

- TDD RED: both the `source_first` API and new CLI flags absent,
  so exact source facts were withheld when simulated Qwen returned
  a wrong gate and a zero-HTTP mode was impossible.
- Source-first fact is released despite incorrect/UNKNOWN/truncated
  neural text; the neural source-match indicator remains false.
- Same revision and directory fixture with missing subject/irrelevant
  PUBLIC reference stays UNKNOWN.
- Without a live, matching approval binding, neither mode can
  release a positive fact.
- Fake one-request HTTP test proves strict default and source-first
  opt-in differ without neural-text leakage or forged client fields.
- Fake zero-request HTTP test demonstrates the source-only path makes
  **no** model request, even while the specified endpoint would
  otherwise return a hallucination.
- Approval removed or source changed on the second provider call
  stops the session without a partial JSON answer.
- Source-only with `--execute`, source state file imports, or no
  live provider is rejected before any HTTP.

These are internal synthetic SOURCE/TEST claims, not independent
review or general semantic reliability. Verify the exact installed
portable source and actual run outcomes separately before claiming
the code works on Lappy.
