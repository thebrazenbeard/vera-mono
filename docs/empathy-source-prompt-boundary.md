# Draft: opt-in Empathy source → prompt-data candidate

This is a **source-only research boundary**, not a working or installed Vera
model. It closes one *structural* gap without fabricating five-donor outputs.

## Verified gap (2026-11-06)

Exact source heads examined:

- [Empathy #15](https://github.com/thebrazenbeard/empathy/pull/15) at
  `a115c675622662d1a7d58f58dbdb0eb9003d61b4`
- [Vera Mono #188](https://github.com/thebrazenbeard/vera-mono/pull/188) at
  `86bcd2559a8287c10a3f3a6c58868bd6e7b43bef`
- [Vera Mono #187](https://github.com/thebrazenbeard/vera-mono/pull/187) at
  `7ceb74981b7fc11b4ca5f0fd3cd7d92f56632652`
- [BT2 #119](https://github.com/thebrazenbeard/bt2/pull/119) at
  `1f0e908203992ed66089d3c9f8b3141fa0c9c92a`
- [Portal #129](https://github.com/thebrazenbeard/portal/pull/129) at
  `78ae7c3d739431bbe3e6485b2b6662cb4252aed7`.

Executing the *actual* source modules in an isolated scratch composition
proved:

1. `observe_utterance("write a poem about moonlight")` returns
   `observed_speech_act=REQUEST`, but its five-donor envelope still has
   `empathy.response_policy=None` and invocation disabled.
2. A **separately, manually constructed synthetic** Empathy `Assessment`
   caused the real `evaluate_current_task` to return
   `TASK_DIRECT / EXPLICIT_TASK`. No code automatically makes that Assessment
   from the observed utterance.
3. The existing five-donor collector is disabled by default and requires
   all five donor callbacks, so no Empathy-only response enters its model prompt.
4. A caller-provided prior task does not authorize same-referent STOP_PLAY.
   Portal's pre-route gate is opt-in, default `None`; no live host boundary
   binding was observed.

The scratch composition ran four falsification tests, all passing. This is
source execution, **not** an installed model path or host-authenticated input.

## What this draft adds

`vera_core.empathy_prompt_candidate.build_empathy_prompt_candidate`:

- is disabled by default;
- requires the caller to supply a typed, host-admitted Assessment, an executable
  Empathy evaluator callback, and a host-reported exact repository/source ref
  pinned to the exact reviewed Empathy #15 source revision. Core code checks
  the syntactic donor subject only; repository OWNER authentication belongs to
  the monorepo's dedicated provenance gateway;
- really invokes the supplied evaluator when enabled, then validates its
  effectless `CognitiveDonorResult`-shaped output plus source/donor provenance;
- cryptographically binds caller-supplied typed current evidence to the input
  digest, not merely the raw task string;
- serializes only TASK_DIRECT policy, reason, and causal digest into
  `VERA_UNTRUSTED_EMPATHY_PROMPT_CANDIDATE_V1` JSON when a selected
  same-person current task_request exactly matches the proposed task;
- returns `UNBOUND_POLICY_HOLD` and **no prompt** for STOP_PLAY, mismatched
  task text, or other unrelated policies until a host can authenticate
  referent and conversation-currentness;
- explicitly holds any current play-frame stop/possible withdrawal or correction
  independently of a possibly mistaken/forged injected evaluator;
- requires canonical TASK_DIRECT / EXPLICIT_TASK consistency and binds the
  selected supporting evidence identifiers into the causal digest;
- returns **candidate prompt data only**. It does not invoke a model or mint a
  STOP_PLAY enforcement decision.

The injected callback and claimed source identity can be faked by the host.
Their presence is **not independent attestation**. A release-bound owner must
verify exact source bytes, callback origin and current person/evidence custody
before any live use. No new source import, memory read, private lookup, service,
model call, or network effect occurs in this module.

## Tests and remaining HOLD

Sixteen self-contained contract tests verify disabled behavior, bounded
inputs, fake source rejection, callback output validation, causal input
hashing, task/referent correlation, and unbound STOP_PLAY rejection.
These are **stub tests**; they cannot prove the injected callback is Empathy.

Six separate scratch integration tests exercised this adapter with the
**real, exact PR #15 Empathy source** and checked TASK_DIRECT produces
candidate data while STOP_PLAY (without authenticated same-referent binding)
is held. Four additional source-composition tests demonstrated the
remaining unmapped host boundary. Total scratch tests: 10/10.

> Hostile challenge: returning a plausible policy JSON is not proof a
> conversation entered the five-donor runtime, that a model consumed the
> policy, or that any change to weights/identity occurred.

Release HOLD until the source-owning host supplies authenticated assessment
provenance, checks exact callable/code readback, establishes conversational
currentness, and performs a real model-path A/B. Do not merge/deploy or train
on this branch as-is.
