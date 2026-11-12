# Mini-Vera fixed read-only source observation — source candidate

This additive, opt-in Mini-Vera tool is deliberately **smaller than a general
host action broker**. It proves one local process read a fixed source file by
returning its SHA-256 and byte count through source-controlled structured JSON.
It does not execute shell commands, manage processes, run arbitrary user-
provided paths, install models, write memory or authorize external effects.

## How it works

With an explicitly qualified model server and operator host-idle check:

    mini-vera.cmd --endpoint http://127.0.0.1:11434/v1 --model qwen3.5:0.8b --allow-cold-load --host-idle-confirmed --execute --structured-output --host-read-probe --prompt "What can you verify locally?"

The preflight emits the usual observation, then Mini-Vera emits
MINI_VERA_LOCAL_OUTPUT_V1, containing separate model/client fields. The
host-read-probe flag is rejected without both --structured-output and --execute.

The model text remains UNVERIFIED_GENERATIVE_TEXT. A client receipt is present
only if the actual local Python process invoked the fixed read-only
host_read_probe.observe_source call and the result matched the current
composed-request hash. A tool_action count of 1 refers solely to this exact
read-only source observation; verified_external_effects remains false and
host_attestation remains NOT_PROVIDED. The host process's clock and PID are
observations, not externally signed or independently time-attested facts.

The file target is fixed in source: tools/mini_vera/compose.py. No CLI flag,
model instruction or donor record can select a different target. The probe
rejects symlinks/reparse paths and oversized or non-regular files, opens
read-only with a size/inode consistency check, and returns source_sha256,
source_size_bytes, source_name, issuer_process_id, observed_at_utc and a fresh
nonce. The receipt is bound to request_sha256 and carries its own canonical
SHA-256 for accidental tamper detection.

When INSTALL.json exists, the probe refuses if its locally unsigned
files_sha256 entry for compose.py differs from the observed bytes; the receipt
records MATCHED_UNSIGNED_LOCAL_MANIFEST and the exact local manifest hash.
When running from a Git source checkout, the receipt declares
SOURCE_TREE_NO_INSTALL_MANIFEST rather than pretending an installation exists.
A portable source directory with neither INSTALL.json nor .git is refused.

## Evidence and ceiling

The manifest, receipt and verifier all run in the same local software trust
domain. Their hashes are not digital signatures, and a local adversary able
to change source code/manifest or control the process can fabricate them.
The nonce does not provide replay protection outside an independently
managed verifier. A manifest match does not attest that Ollama loaded a
particular set of weights or that unrelated processes performed no actions.

The tool reads no private memory, credentials, user-selected files, other
processes or persistent state. It intentionally does not put probe output into
the neural prompt. A model may still fabricate a host-action assertion in
model.text; consumers must not turn that into a privileged receipt.

Current PUBLIC-memory revocation continues to be checked after inference and
before emitting structured output. Host-probe errors withhold model text.
An unsigned source observation is a stepping stone toward an independently
protected host-issuer boundary, not that boundary itself. Persistent governed
memory, signed action receipts and identity qualification remain separate work.
