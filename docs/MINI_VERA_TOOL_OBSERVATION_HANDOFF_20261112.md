# Mini-Vera: one-turn host-observation delivery (SOURCE CANDIDATE)

Goal: make one explicitly operator-authorized, read-only source observation
available to the local model **as data**, not as an instruction or an authority
grant. The base implementation in Draft PR #206 could read compose.py and
report a client receipt but did not deliver the observation to the neural
model.

## Interface

With a separately resource-qualified Ollama host and model tag:

    mini-vera.cmd --endpoint http://127.0.0.1:11434/v1 --model qwen3.5:0.8b --allow-cold-load --execute --host-idle-confirmed --structured-output --host-read-probe --deliver-host-observation --prompt "What source SHA-256 did the host observe?"

The new --deliver-host-observation flag is opt-in; it requires all four other
execution and read-only flags and one explicit --prompt (no interactive
session or silent history replay). No model-issued arbitrary command is
recognized or executable.

Before one model call, the host composes the ordinary request and validates
it. The fixed read-only source probe then observes
tools/mini_vera/compose.py, validates the unsigned source manifest, and
produces a receipt bound to the **base** composed-request SHA-256.
The host creates a new canonical user JSON envelope containing a bounded,
typed host_tool_observation with source name, SHA-256, byte count, unsigned
manifest status, base-request binding, and exact composed turn SHA-256
to reject a prior-turn replay even when user text is identical.

The loopback validator independently reconstructs the base request by
removing only the observation field, recomputes its SHA-256, and re-reads
the fixed source and unsigned manifest. It rejects an observation that was
fabricated/rehashed, changed, mis-scoped or inserted into old history or
synthetic contexts. The final inference request hash commits to the actual
model-visible tool observation. The local server receives only one
source-controlled model request.

Output remains MINI_VERA_LOCAL_OUTPUT_V1, with independent client
and model fields.
Model text remains UNVERIFIED_GENERATIVE_TEXT. Client has one
READ_ONLY_SOURCE_SHA256 receipt, with its binding to the *base* request
and a distinct final model-visible request SHA-256. The client explicitly
reports host_observation_delivered=true, tool_actions_executed=1,
verified_external_effects=false, and host_attestation=NOT_PROVIDED.

Machine consumers must prefer client.source_answer for exact source names,
SHA-256 strings and byte counts rather than copying them from neural text.
That field is deterministically derived from the already checked client
receipt, labeled CLIENT_SOURCE_RECEIPT_NOT_MODEL and
LOCAL_UNSIGNED_CONSISTENCY_NOT_HOST_ATTESTATION. Even if the model produces
a false or abbreviated checksum, the client answer remains the observed
unsigned source data; this is not independent host attestation.

The typed observation is labeled
LOCALLY_OBSERVED_UNSIGNED_DATA and authority_effect=NONE.
It is source-created data that a model can use to answer factual questions;
the model cannot turn it into permission to execute a command or alter files.

## Failure behavior, privacy and ceilings

The missing source, changed manifest, symlink/reparse point, wrong hash,
unapproved delivery or malformed envelope cause refusal before inference.
The after-inference PUBLIC-memory approval/revision check runs before
emitting any model text or receipt. This still cannot retract public source
bytes already sent to the loopback model.

The host observation is from the same process/source trust domain. It
is neither independent third-party authority nor a digital signature.
A compromised local process can fabricate both source and manifest; a
nonce and self-hash do not prevent independent replay. No persistent
memory, private records, credentials, general shell commands or network
tool privileges have been added. No new neural weights were trained.
Model correctness on unseen questions remains an empirical issue.
