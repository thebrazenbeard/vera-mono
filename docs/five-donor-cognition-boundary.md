# Optional five-donor cognition boundary

This is a small source-only interface in `vera_core.five_donor_advisory`. It does
**not** install a service, activate a model, retrieve private memory, edit
weights, or grant tools/effect authority. The default call is disabled and
invokes no callbacks. A Vera conversation route does not consume it yet.

## Intended host wiring

An authorized host may opt in by providing the exact ordered donor bindings:
`noema`, `meso-crct`, `volition`, `empathy`, `pre-active`. Each binding contains
the canonical repository owner, an immutable commit, a normalized source path,
and SHA-256 of the source blob. All five source readbacks must match before any
donor callback is invoked.

The host must implement source readback from the repository's actual immutable
Git object, not from model output or a self-declared `verified=True` bit. The
returned `SourceReadback` is merely **host-reported**; this library cannot
authenticate the host, GitHub ownership, or the caller's authority.

The host injects callbacks that adapt actual donor APIs to five bounded scalar
signals. The library does not import external donor packages, perform network
I/O, or claim callback purity. Host adapters still need independent source and
effect review. Callback outputs are validated as bounded numbers, booleans, or
fixed symbolic enums, never arbitrary model-injected instructions.

The optional `untrusted_prompt_data()` field is JSON-labelled candidate data,
not an order to the language model. The caller should keep this information
separate from privileged system instructions and should never promote its
source claims to established self-identity, lived history, or permission.

## Falsifiers

- `enabled=False`: no verifier, donor, model, or memory callback executes.
- Any missing, duplicate, misordered, forged-owner, or mismatched source blocks.
- A boolean `True` returned as a source readback does **not** pass.
- Non-finite Noema values and nonliteral Volition booleans block.
- `STOP_PLAY` cannot coexist with an eligible Volition proposal.
- Tests are synthetic. Passing tests proves the adapter contract only; it does
  not prove real donor behavior, semantic correctness, or runtime consumption.

The isolated Lappy Portal → Vera Mono → five donor experiment at
`D:\VERA\experiments\vera-whole-qualify-20261105` remains research, not
native deployment. Its first genuinely generated answers showed prompt
conditioning without reliable identity or stable epistemic calibration. The
new interface is an incremental source boundary for future guarded integration.
