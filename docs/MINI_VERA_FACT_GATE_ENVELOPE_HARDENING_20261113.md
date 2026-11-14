# Mini-Vera Synthetic Fact Gate — Envelope Anti-Leak Hardening (2026-11-13)

Status: additional source-only guard stacked on Draft PR #213. This does
not install an authenticated host issuer or change Qwen3.5 model weights.

## Hostile red-team finding

A malformed caller could supply a self-consistent, synthetic fact result
with neural text copied into an extra top-level field or an extra client
field. The previous public_fact_guard.apply() nulled model.text but
propagated **record and **client. The client would therefore still expose
the copied text through those other fields. Reproducible focused TDD
returned six failed expectations against the original guard, including
raw text leakage in extras and acceptance of caller-controlled prior
conversation history.

The vulnerability is in the explicit guard function's input acceptance.
The normal local_session constructs its structured result itself, so this
does not establish that the observed production caller was exploited.
It does show the guard was unsafe to call with an untrusted result object.

## Narrow correction

The synthetic fact gate now requires exactly the four top-level fields
schema/request_sha256/model/client, exact model fields text/status/trust,
and a validated client shape. It accepts either the compact, synthetic
unit-test client receipt or the complete local_session client receipt.
Both require tool_actions_executed=0, tool_receipts=[], no delivered host
observation, no source tool answer, no externally verified effects, and
NO host attestation. Unexpected fields, privileged actions or claims of
attestation now fail closed as GuardRefused.

The synthetic gate also enforces exactly one system and one current user
message. It cannot accept caller-injected assistant history that the
general loopback component supports for other explicit use cases.

This hardening does not change the deterministic synthetic source lookup,
the memory-approval provider, resource limits or default unguarded CLI
behavior. A counterfeit public-like source with a matching self-hash
would still not constitute independently authorized host evidence.
Production host-grant and source-trust controls remain unqualified.

## Tests and evidence separation

Hostile tests attempt copied raw model text in top-level, client,
tool_receipts and model envelopes, forged nonzero tool actions, simulated
host-attestation and external-effects claims, and prior model-history
injection. These must all refuse. Existing real fake-loopback tests still
show client-generated UNKNOWN on no-source hallucination without calling
it neural abstention; source-matched release remains restricted to the
two synthetic record formats. Full regression and portable bundle must
be verified independently before publication.

The independent heldout evaluator and production source authority
remain future gates, not effects of this change. No user/private memory,
secrets, weight updates, shared service restart, deployment or protected
merge are authorized by this source patch.
