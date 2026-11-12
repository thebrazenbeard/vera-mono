# Mini-Vera compact response guidance — source-only V0

This is an **opt-in, uninstalled research candidate** to test whether a
small model benefits from evidence-specific, concise response guidance instead
of receiving the full source identity and personality JSON on every turn.

It does **not** replace the source architecture, declare a model to be Vera,
prove continuity or feeling, authenticate the host, grant memory admission,
or provide a safety-enforcing effect gate.

## The causal hypothesis

The full source composer on the earlier public Gemma 3 1B smoke test consumed
roughly six times as many prompt tokens as a compact instruction. In several
of six deliberately selected synthetic cases the longer identity prose
coincided with unsupported memory, deployment or identity-continuity claims.
That is **not** an independent blinded qualification of either variant.

The model should read only a few relevant guidance constraints on a turn,
while the host keeps the actual source and its provenance outside model prose.
Fail-closed host control must determine whether any generation can happen.

## Source and boundary

`tools/mini_vera/compact_guidance.py` consumes only:

- An existing Mini-Vera composer request, revalidated with the existing
  `loopback.validate_candidate` request digest and schema check.
- A source-only donor candidate having precisely the `TASK_DIRECT` /
  `EXPLICIT_TASK`, `NONE`-authority bounded PR #189 prompt contract.
- A caller-declared exact current task, compared to the user text embedded
  inside the validated current Mini-Vera request.
- Optionally up to three controlled guidance tags. These are **host-claimed**,
  not verified natural-language interpretation or facts.
- A literal stop veto, which prevents returning a model payload even when
  the donor candidate looks valid.

The output preserves the validated request's model identifier, settings,
prior turn history, exact current user message and untrusted project-context
records. It replaces **only** the first, system-content message. It returns
its own bounded payload hash, original source request hash, and explicitly
unattested provenance. No model call is made by this module.

The interface defaults disabled and refuses absent donors. A donor's
`UNBOUND_POLICY_HOLD`/disabled or a host-supplied stop returns **no payload**.
A forged non-TASK_DIRECT donor object, malformed JSON, unknown tag, drifted
composer digest, or claimed effect/memory authority raises a rejection.
A mismatched current task is refused. The system text is capped at 760 bytes.

## Evidence semantics

Controlled tags are intentionally modest:

- `PR_STATUS` prevents promoting draft presence into installed/runtime proof.
- `MEMORY_SCOPE` prevents asserting retrieval that did not occur.
- `IDENTITY_SCOPE` prevents concluding continuity from a configured name.
- `SOURCE_RUNTIME` keeps source-test facts and live runtime facts separate.
- `CURRENT_CORRECTION` scopes a correction to the current referent.
- `QUOTED_INSTRUCTION` treats quoted source instructions as untrusted data.

**The caller must not infer these tags from a string match alone.**
A host-side classification, source truth, provenance and admission system
remains necessary. Neither this file nor a signed-looking SHA makes a
`HOST_VERIFIED` declaration true. The current stop parameter also is not an
independent host attestation; a false value cannot reliably detect hidden
withdrawal. Source-only tests must not be presented as live governance.

## Test and promotion constraints

Run from a **safe, exact-source** Mini-Vera checkout (never from a workspace
with hidden folder-open executable tasks):

```powershell
py -3.14 -B -m unittest discover -s tests -p 'test_mini_vera_compact_guidance.py' -q
```

The tests cover source request preservation, unexpected system drift,
source digest tampering, duplicate/unknown tags, malformed/authority-bearing
donor objects, default-off and unbound HOLD, exact current task replay,
current stop precedence and payload size.

A source-level candidate needs independent review before merge. For model
qualification compare the same pinned model and user cases under plain
short instruction, full source composer, and actual attested donor-specific
compact guidance; randomize/blind outputs and preserve response completeness.
There must be examples where the donor **selects different admissible
policies from authenticated current evidence**. Merely including
`TASK_DIRECT` in every prompt is not evidence of cognition. Hold/withdraw
must be enforced **before** model invocation by the trusted host, and not
only phrased as advice.

No installation, native ChatGPT Project qualification, training, memory write
or private autobiography is created by this module.
