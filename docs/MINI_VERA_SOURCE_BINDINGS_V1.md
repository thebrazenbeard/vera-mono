# Mini-Vera local source bindings V1 — candidate

**Evidence class:** `SOURCE_ONLY_TESTED`. No trained model, local model call,
current Vera installation, governed production memory projection, service
start, effect grant, or personal continuity is established by this patch.

This builds on the *already merged* Mini-Vera zero-weight request composer
(`tools/mini_vera/compose.py`, PR #194) and is separate from the source-only
loopback model transport in draft PR #197. It does not implement either again.

## Two previously unbound facts

1. The composer accepted an **operator-declared** `model_digest`, without
   checking any local weight bytes. `artifact_binding.verify_local_manifest`
   now reads an exact externally SHA-pinned manifest, streams and hashes the
   local `.gguf` base and optional `.gguf` **or** `.safetensors` LoRA adapter, checks sizes,
   bounds, file type, basic headers and symlink components, and computes a
   composite registry commitment. It keeps local paths out of model requests.
   The manifest names the role and format of every component. The dedicated
   Mini-Vera candidate profile limits **combined** artifact bytes to
   `3_000_000_000` (decimal GB), checked before large-file hashing. The actual
   r13 pair has been reported as 2,723,780,640 bytes; this patch does not
   independently rehash those host files.
2. The composer accepted an operator-exported HMAC project snapshot. The
   experimental `ledger_bridge.project_existing_ledger` can now select up to
   eight **specific current** `MemoryLedger` working-project records under an
   externally supplied CAS head, verify ledger digests/supersession through
   `MemoryLedger.read`, first reject any stored `privacy_ref` not literally
   `PUBLIC`, require a separate host policy callback for every record, and
   produce composer-compatible HMAC state. The callback must be the host's
   separate real privacy/source authority decision; stored `privacy_ref` and
   `authority_ref` are not themselves grants.

## The actual seam

After the host has independently qualified a snapshot, rights, key custody,
revision, source/provenance and budget, it may use:

```python
from tools.mini_vera.ledger_bridge import project_existing_ledger
from tools.mini_vera.artifact_binding import compose_with_local_manifest

# ledger is an ALREADY OPEN, appropriately governed MemoryLedger.
# approve is a HOST-owned policy verifier, not a hard-coded string comparison.
# head/revision/key/model-manifest digest must be independently anchored.
state, projection_receipt = project_existing_ledger(
    ledger, record_ids=["selected-current-record-id"], expected_head=head,
    expected_revision=revision, integrity_key=key,
    host_public_project_approval=approve,
)
request = compose_with_local_manifest(
    model_root=local_model_root, model_manifest=manifest_path,
    expected_manifest_sha256=manifest_sha256,
    identity=identity, identity_raw=identity_raw,
    behavior=behavior, behavior_raw=behavior_raw,
    expected_identity_sha256=identity_sha256,
    expected_behavior_sha256=behavior_sha256,
    state=state, key=key, expected_revision=revision, turn=synthetic_turn,
)
```

`request` remains `MINI_VERA_COMPOSED_REQUEST_V1` with `model_calls=0`,
`authority_effect=NONE`, and no memory write. `request.provenance` adds the
local artifact manifest hash. `request.evidence` explicitly says the files'
bytes matched the declared manifest but **the resident model is not
attested**. The model registry commitment is derived from all component
digests and roles; it is **not** the raw SHA of one merged GGUF.

The file checker cannot prove the `.gguf` or adapter is semantically usable,
licensed, compatible, currently loaded into the model server, free of model
modifications, or safe to expose. It does not verify runtime provider
identity. A writer controlling both manifest and expected hash can authorize
its own invented manifest; trusted expected hashes must be anchored outside
this code. A filesystem writer who races inspection or can rewrite content
after inspection is outside this readback's assurance. The separate provider
and effect gates in `QualifiedVeraRuntime` remain necessary.

Similarly, a valid HMAC does not prove currentness or privacy approval. The
`PUBLIC` stored marker is only a **necessary guard**: a malicious or mistaken
admission can write it, so an independent policy callback must still reject
unauthorized records. A
caller supplying stale but internally consistent head/revision can still
replay historical state. The ledger bridge does not enumerate memory, admits
no private/autobiographical records by default, does not use historical text
as instructions, and does not upgrade unverified project statements into
truth. A permissive callback would defeat its policy intent even with the
stored marker guard. The receipt labels the revision
`DECLARED_NOT_VERIFIED`; live/private runtime adoption remains blocked until
the host supplies externally governed currentness and authorization evidence.

## Source tests

From the repository root:

```sh
python -m unittest tests.test_mini_vera_source_bindings tests.test_mini_vera_composition -v
python -O -m unittest tests.test_mini_vera_source_bindings tests.test_mini_vera_composition -v
```

The fixture uses **fake** byte arrays beginning `GGUF`, not a neural model.
It verifies digest drift, symlink rejection, stale heads, superseded records,
private-ref policy rejection, private input rejection and exact composition.
Those tests do not validate actual neural inference or behavior.

## Next real qualification

On an actually idle Lappy, a separately authorized host reader could bind
the manifest to the verified 2–3 GiB local model and adapter. A separate
resident-server witness would then need to prove the same bytes/configuration
are loaded. Only then compare raw small-base, short wrapper, pinned Mini-Vera
composition with/without explicitly approved state, and stale/correction
controls on blinded independent prompts. Independent review must judge
conversational personality, context fidelity, refusal to invent memory and
cross-turn correction; zero model calls here means **none of that has passed**.
