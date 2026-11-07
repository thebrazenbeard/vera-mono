# Native ChatGPT Project pack source gate

This standard-library gate checks repository pack bytes, not a live
ChatGPT Project. It is not an installer, memory writer, training tool,
migration utility, or runtime activation mechanism.

Example from repository root:

    python tools/verify_native_project_pack.py --source-root architecture/chatgpt --observed-git-head FRESH_40_SHA --expected-manifest-blob FRESH_40_BLOB_SHA

Obtain the live exact Git head and manifest blob through an authenticated
GitHub read. This CLI checks the local manifest against the supplied blob
identifier and each member against the manifest's size and SHA-256.
It does NOT independently authenticate GitHub or the caller's pin.

## Results

- Exit 2: report was produced, but native binding remains HOLD.
- SOURCE_PACK_INTEGRITY_PASS_NATIVE_BINDING_HOLD: all local members match.
- SOURCE_PACK_INTEGRITY_HOLD: a listed member was missing or mismatched.
- Exit 3: invalid or unsafe manifest, malformed JSON, duplicate keys,
  directory traversal, case-folded duplicates, oversize contents, or
  unexpected status/authority field.

The existing VERA_MONO_CHATGPT_PROJECT_PACK_V1 manifest declares
CANDIDATE_NOT_INSTALLED. Even seven fully matching members do not establish
the live logical owner VERA_NATIVE_PROJECT_INTERFACE. A future successor
requires an independently verified Project source binding and current release
contract. A filename or Project display name cannot supply that binding.

Every result preserves native_project_owner_binding=UNRESOLVED,
native_project_installation=UNVERIFIED, runtime_consumption=UNVERIFIED,
memory_authority=false and effect_authority=false.

## Hostile limits

> Matching a pack to a supplied Git blob cannot attest a provider-side
> Project readback. A dishonest caller can supply a different pack and its
> own internally consistent pin. Pin authority is external to this tool.

> A local source snapshot could change after the check. This is not immutable
> host-owned custody or a live runtime attestation.

Tests:

    python -m unittest discover -s tests -p test_verify_native_project_pack.py -q

No private chats, Project source files, credentials, host changes or paid
compute are required.
