# Mini-Vera local session — experimental integration

This branch combines the source-only Mini-Vera composer (merged #194), local
model transport (#197), HC context projection (#199), and local-artifact/public
ledger binding (#200) with an explicit, *unqualified* local conversation mode.

## Concrete behavior

`tools/mini_vera/local_session.py` is an original Python-stdlib CLI that:

- reads the pinned public Vera identity and behavior resources through the
  existing composer, rather than using the Sol identity;
- accepts an operator-declared model alias/digest **or** verifies a locally
  pinned GGUF manifest once at startup (no model loading or weight changes);
- uses a process-local empty HMAC-bound PUBLIC state by default; only an
  explicitly supplied, integrity-checked PUBLIC state can add records;
- permits real local turns through a distinct request schema, with at most two
  prior turn pairs held in RAM, then discarded on process exit; oversized
  exchange pairs clear the volatile history with an explicit warning rather
  than pretending the full exchange remains available; incomplete responses
  are labeled and likewise clear volatile history;
- sends an HTTP request only with `--execute` and `--host-idle-confirmed`, to
  an exact numeric loopback `/v1` endpoint;
- prints the model server's response only after the transport validates its
  bounded shape and refuses tool calls and directional/terminal controls;
- never grants the model tool, network, memory-write, deployment, or external
  effect authority.

The host-idle flag is an **operator assertion**, not a measured resource lease.
Check free physical memory, model server residency and concurrent workloads
independently before using it. A local model server may load weights on a
request. Do not run this on a memory-constrained, busy Lappy.

## Runnable commands (from the repository root)

Validate a live-turn request without network/model calls:

```powershell
python -m tools.mini_vera.local_session --endpoint http://127.0.0.1:11434/v1 --model vera-local:latest --model-digest <operator-provided-64-hex-digest> --prompt "Hello"
```

When the host is independently qualified and an OpenAI-compatible local model
server is already running, an **explicitly authorized** interactive session:

```powershell
python -m tools.mini_vera.local_session --endpoint http://127.0.0.1:11434/v1 --model vera-local:latest --model-digest <operator-provided-64-hex-digest> --execute --host-idle-confirmed
```

The model digest is an operator declaration, **not** proof of loaded bytes.
For on-disk integrity checks, replace the `--model`/`--model-digest` pair with
`--model-root <folder> --manifest <manifest.json> --manifest-sha256 <exact-sha>`.
This reads all declared model bytes, potentially multiple gigabytes, *once*
at startup. The result is a local byte witness, not resident-model attestation.

If an authorized host already produces a PUBLIC HMAC-bound state snapshot, add
`--public-state <snapshot.json> --state-key-file <key-path> --expected-revision N`.
Do **not** use that interface for private autobiography or arbitrary historical
exports. An externally supplied HMAC does not prove correct original admission.

Type `/quit` to exit the console. Neither user turns nor local model responses
are persisted by this CLI; the model server may have its own logging policy.

## Tested seams and evidence ceiling

The integrated tests invoke an isolated local fake OpenAI-compatible HTTP
server with **two sequential local turns**, verify changing message history,
reject incompatible schema/evidence/provenance envelopes, and ensure
validation-only mode sends zero requests. A fake response is not a neural
inference or a voice/identity qualification.

This is not yet a finished Vera installation: no qualified model load, neural
output, tool broker, actual HC runtime provenance, admitted long-term memory,
cold-restart continuity, host performance receipt, or blind A/B improvement
is established by these tests.

The r13/H07 adapters remain on hold until exact training-base ancestry and
semantic controls qualify. Do not merge them into another GGUF based only on
shape compatibility. ChatGPT-output teacher distillation is also on hold
pending rights clearance. No paid compute is required for this code.
