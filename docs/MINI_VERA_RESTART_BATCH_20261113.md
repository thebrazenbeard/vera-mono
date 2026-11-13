# Mini-Vera repeated synthetic PUBLIC-memory restart A/B gate

Status: SOURCE CANDIDATE. Additive optional runner for existing restart_public_canary.py,
not production memory, independent heldout research, or a qualified model.

Invocation from a source checkout or verified portable package:
    python -B -m tools.mini_vera.restart_batch_canary --run-batch --endpoint http://127.0.0.1:11439/v1 --model qwen3.5:0.8b --model-digest <64-lowercase-hex> --cases 3 --timeout-seconds 90

The runner accepts 2–4 independent, newly generated synthetic test cases.
Each invokes the existing canary: one disposable memory ledger, one fresh random
PUBLIC token and unselected synthetic PRIVATE record, two independent model
sessions with approved memory, one no-memory control, one revoked worker
that must refuse before inference. No real user data/keys are admitted or read.

Result status is COMPLETED_SYNTHETIC_ALL_PASS only if **every** completed
case has approved exact token retrieval 2/2, no-memory control UNKNOWN and
revoked approval blocked. Any scored case failure makes the entire completed
batch COMPLETED_WITH_FAILURES. Worker failure, malformed results, suspicious
case score or repeated synthetic token digest yields ABORTED_UNSCORED, preserving
the earlier case summaries without interpreting them as an overall pass.
Only SHA-256 and per-case score summaries are copied into batch output;
model-response text and synthetic tokens are deliberately omitted.

The gate verifies a single numeric loopback endpoint, declared model identifier,
and declared 64-hex digest, limits cases, and never invokes arbitrary host tools.
No model identities or resident weights are independently authenticated. A
positive result means an engineering canary, *not* learned parameters, general
memory effectiveness, stable personal identity, or independently withheld data.
The prompt is source-visible and was tuned after an initial observed failure.

Tests include a fresh portable installation making two synthetic cases over
an actual fake HTTP endpoint (six HTTP calls, eight Python sessions), corrupted
score refusal, failed later case preservation, duplicate token digest refusal,
case-count/endpoint bounds, and mixed scored outcomes. These are deterministic
source/transport tests; they do not supply additional neural evidence.

Next qualification requires real model trials from the exact portable bundle,
multiple heldout question types, evaluator-controlled external records and
source custody, and protected host grants with independently verified revocation.
