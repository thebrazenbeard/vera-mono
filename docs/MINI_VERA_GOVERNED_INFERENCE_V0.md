# Mini-Vera: host-scoped, source-executed donor routing (experimental V0)

**Not a deployed service, learned adapter, or qualified Vera model.**

This opt-in Python boundary is intended for a host that already has current,
authorized user/session evidence and **atomic, one-use invocation claims**.
The module itself cannot prove that its host callbacks are honest or that
a model, private memory, or repository source is actually installed/current.

## Purpose and contrast

The prior compact guidance candidate only exposed a model-request payload.
Six public-source tests showed an Empathy donor always returned TASK_DIRECT
when the host submitted only a task_request, so model answers could not be
attributed to policy differentiation.

`tools/mini_vera/governed_inference.py` now takes a **source-validated current
Mini-Vera request**, current host observations, a source-executed donor selector
and a bounded prompt candidate builder. It routes different Empathy results to
different model invocation outcomes *before* inference:

- TASK_DIRECT + EXPLICIT_TASK with an exact supporting task evidence ID:
  default-off source-verified compact request, preserving the same user text,
  public untrusted context, model, options and volatile turn history.
- STOP_PLAY or present direct withdrawal: no model payload/call.
- TRUTHFUL_CHALLENGE / unsupported external fact: no model call; retain the
  unsupported-claim status for a separate, reviewed response path.
- REPAIR_FIRST, CLARIFY_MEANING or any other non-task policy: no model
  call until a separately qualified response path is provided.
- Changed host revision/current evidence before invocation, including changes
  induced during one-use claim: HOLD with zero model calls.
- Changed source/evidence after inference: do **not** display or retain model
  output, though already transmitted context cannot be undone.
- A repeated current invocation nonce: REPLAY_HOLD with zero new model calls,
  **only if** the host's claim callback actually implements a global
  atomic consume. A local Python set is not a durable CAS or service receipt.

This is deliberately less ambitious than freely generating replies for every
policy. It is better to refrain from a model call than silently treat an
unsupported claim, correction or withdrawal as another generic task.

## Exact boundary requirements

`run_governed_turn` needs five independently supplied host callbacks:

1. `observe()`: current host-owned `HostObservation`, bound to the exact
   source-request and turn SHA, person, revision, nonce, immutable current
   same-person evidence tuple, and optional bounded host-fact tags.
2. `evaluate(assessment)`: actual source-executed donor selector, not a
   string constant or invented score. The returned policy must have
   no effect authority and cite exact supporting present evidence IDs.
3. `make_donor_candidate(assessment, current_text)`: existing PR #189
   source-bound Empathy bridge candidate for an ordinary task, then validated
   by the PR #202 compact guidance module.
4. `claim_invocation(observation)`: atomic, host-owned one-use lease/CAS
   invoked only after currentness admission and re-observed immediately
   afterward. A failed/false lease blocks transport. **This adapter does
   not implement persistent CAS, host identity, or exclusive synchronization.**
5. `transport(composed_request)`: existing `loopback.execute`, under the
   host's independently verified endpoint/resource/model ownership. Its
   structured output must match request digest and no-effect evidence.

In other words, the production host must supply **five** callbacks; they are
not silently inferred from user words, a Git SHA, or a model's assertion.
A callback injection is not proof of its external integrity. Concurrent
withdrawal cannot be made truly atomic by repeated unsynchronized reads; host
ownership/locking remains required. Private/autobiographical memory is not
admitted by this route.

## Test evidence and claim ceilings

TDD on Lappy source branch `feature/compact-admitted-guidance-20261111`:

- RED: tests failed when the route was absent.
- GREEN: actual route prevents calls under typed stop/unsupported policies.
- RED: replay test failed before adding host one-use claim.
- GREEN: repeated invocation becomes REPLAY_HOLD.
- RED: claim-triggered host revocation exposed one improper model call.
- GREEN: another host check after claim prevents that call.
- RED: an apparently TASK_DIRECT donor with no supporting task evidence IDs
  slipped through.
- GREEN: TASK_DIRECT must be backed by exact matching current-task evidence.
- Focused tests include pre/post-host drift, cross-person/turn mismatch, forged
  policy and source, transport-provenance mismatch, and default-off admission.

Two real model trials used isolated, verified copies of these sources and
exact pinned Empathy at `a115c675622662d1a7d58f58dbdb0eb9003d61b4`,
with PR #189 source-bound prompt builder and cached `gemma3:1b` on
VERA-NODE-1. **Actual network inference occurred for TASK_DIRECT**.
The other three synthetic current evidence types returned separate HOLD
statuses with zero calls, and the one-use iteration denied a replay.
The model replied `No.` to a public question about whether a draft PR
proved installed deployment. This is a *development smoke test*, not a
full Vera conversation, performance win, identity qualification, or proof
that text understanding creates these host observations automatically.

Source imports were restricted to individually SHA256-verified Python and
public JSON files. Neither the compromised Empathy workspace startup task
nor other unreviewed repository files were run. A separate, unrelated
Ollama server was present on VERA-NODE-1 port 11439; temporary tests used
a distinct loopback port 11441 and shut down only their own identified
process. The current Lappy model wasn't loaded.

**Promotion requirements:** a real host implementation that authenticates
person/currentness, source ownership, fact classes, and a cross-process atomic
one-use lease, an independent hostile source review, followed by blinded
Labyrinth comparisons where the same verified model receives genuinely
different donor policies from authenticated live evidence. Keep this disabled
until those checks pass. No merge, install, training, memory writes or native
Project changes are authorized by this file.
