# Mini-Vera synthetic PUBLIC project-fact output gate — 2026-11-13

Status: opt-in SOURCE CANDIDATE. It is not host-attested authority,
general-purpose factual verification, neural abstention improvement,
private-memory approval, persistent identity or model training.

## Why this exists

PR #212's real Qwen3.5-0.8b trial on Lappy correctly retrieved approved
PUBLIC-reference gates in four of four model responses, but the two
no-memory controls invented gates instead of returning UNKNOWN. A further
two standalone empty-context diagnostics generated more nonsensical IDs.
The source behavioral result remains FAILED. The purpose here is to
stop that unsupported text from reaching a client, not rewrite model
failure into apparent neural success.

## Opt-in integration and supported scope

A one-shot local_session invocation may add:

    --synthetic-fact-evidence-gate --execute --host-idle-confirmed --structured-output --prompt '<canonical synthetic question>'

The narrow gate only recognizes the two source-defined question forms in
tools/mini_vera/varied_public_canary.py: a synthetic courier directory
lookup and an R2-supersedes-R1 cargo update. For all other questions it
fails closed BEFORE model HTTP. A state file, key file, arbitrary exported
memory, read-only source probe and interactive mode cannot be mixed with
this option. The real existing live public provider, if used, is still
responsible for independently approved records and post-HTTP revocation.
The gate does NOT create independent host authorization.

The policy revalidates the composed request and the strict current
question, and permits either no project records or exactly one synthetic
varied-public record with correct source hash, source data structure,
record ID and unverified-context trust label. It performs a deterministic
lookup for the specified courier or the *current* gate for the specified
cargo. The source fixture must satisfy the existing semantic validation
for nonidentical directory entries or same-subject revised values.

After inference, the existing local_session checks live public approval
again. The client policy then compares the neural model's answer against
the deterministic source answer.

* With no source, unsupported subject, wrong neural answer or truncated
  output: the client returns UNKNOWN and suppresses raw neural text.
* With a matching, validated synthetic source fact AND an exact neural
  answer: the client releases the matching source fact, labeled
  CLIENT_SYNTHETIC_SOURCE_MATCH_NOT_NEURAL_FACT_ATTESTATION.
* In all cases the model field's text is null; its original output SHA256
  and whether it voluntarily emitted UNKNOWN remain distinct audit
  metadata. A client-generated UNKNOWN is NEVER a model-generated
  abstention pass. A source-matched value is NOT authenticated host fact.

The output label source is a disposable, source-visible synthetic fixture.
An attacker able to replace the caller's public-memory provider, source
code or source root still has authority outside this module. Neither
the incoming PUBLIC-like metadata nor a self-hash is a protected signing
credential or a trusted host attestation.

## Safety evidence

Red/green focused tests include (a) no-reference hallucinated gate,
(b) model voluntary UNKNOWN separately recorded, (c) approved exact
model value displayed as client-source fact, (d) wrong approved response
withheld, (e) model truncation withheld, (f) malformed source payload,
wrong digest, duplicate record and wrong bound request refused, (g)
unrecognized question fails before model HTTP, (h) one-shot opt-in
argument requirements, and (i) fake HTTP full local_session integration
for both empty and approved synthetic memory. The default CLI behavior
and other existing Mini-Vera tests remain covered by regression.

No real memory, unauthorized external tools, paid compute, persistent
signing keys or shared service changes should be performed by this gate.
It does not replace neural evaluation: PR #212's failed no-source model
answers remain FAILED even if the client can safely withhold them.
The next research step is independently withheld, varied behavioral
testing and genuine trusted host authorization before enabling actual
user/project memory.
