# Mini-Vera: source-controlled action boundary (draft)

This is an **opt-in structured-output transport**, not a signed host receipt,
neural truthfulness guarantee, model-weight update or privileged tool broker.

## Why it exists

A public synthetic Qwen3.5-0.8B trial (PR #204) refused to invent a PID
at first, then misleadingly proposed acknowledging a model installation
which no host had verified. Prompt instructions did not reliably prevent
that failure. The real issue is treating model prose as operational proof.

Mini-Vera's existing local session has no tool-action execution path.
The source can report that bounded fact separately from the model text;
it cannot prove that other processes, the model server, or the host had
no effects. Only independently verified tool receipts can establish that.

## Usage

With a resource-qualified model server and host idle approval, the portable
launcher can forward an optional --structured-output flag to its local session.

    mini-vera.cmd --endpoint http://127.0.0.1:11434/v1 --model qwen3.5:0.8b --execute --host-idle-confirmed --allow-cold-load --prompt "What did you install?" --structured-output

The launcher first checks its source manifest; successful verification is
silent on stdout (failed verification still exits before inference). The
preflight then prints its JSON observation. For the model response,
the program prints exactly one JSON object with schema
MINI_VERA_LOCAL_OUTPUT_V1. Parsers should select the exact schema.
The model's generated text occupies only model.text; embedded newlines,
quotes and bogus JSON are escaped by the standard JSON serializer.

The separate client fields are fixed by the local Python control path:
tool_actions_executed = 0, tool_receipts = [], verified_external_effects =
false, host_attestation = NOT_PROVIDED and model_server_effects = UNKNOWN.
It does not upgrade claims within model.text to facts.

The existing --receipt-output switch is intentionally incompatible with
--structured-output because the old hash-only receipt parser expects the
human-readable Vera> prefix. A mixed invocation refuses before HTTP inference.

The source also checks that the text SHA-256 and composed request SHA-256 in
the loopback response match the model text and current request before exposing
structured output. This is same-process consistency, not signed provenance.

## Security and continuity boundaries

Post-inference PUBLIC-memory authorization/revision checks run **before**
model text is emitted. A revoked record suppresses structured output as it
already did for ordinary terminal output. A revocation during model inference
cannot retract bytes already sent to the local server.

The old default human-readable terminal remains unchanged for compatibility.
It may still contain model hallucinations. The structured form protects
machine consumers only if they treat model.text as untrusted data and rely
on separately sourced host evidence for actual action claims.

Neither output form provides independently anchored memory, persistent
identity, external tool rights, file custody attestation or proof of neural
improvement. Source-level tests use synthetic local HTTP fixtures, not a
fully credentialed host action system. No model weights or private data change.
