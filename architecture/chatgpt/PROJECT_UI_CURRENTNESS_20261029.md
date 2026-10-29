# Vera Mono native ChatGPT Project — 2026-10-29 currentness

This is an observed ChatGPT Project configuration snapshot, not a new
repository manifest or a claim that the native delegation host tool is enabled.
The historical `PROJECT_PACK_MANIFEST.json` V1 remains unchanged and retains
its original `CANDIDATE_NOT_INSTALLED` claim ceiling.

## Observed UI configuration

- Project: `Vera Mono`, `g-p-6ab6483f79188191a85057138a3d236d`.
- Instructions: V1 identity, source-first evidence, privacy, and protected
  effect rules preserved; an additive **Native ChatGPT subagents
  (runtime-gated)** clause was saved and read back. The combined text occupied
  **7,994 of 8,000** available instruction characters.
- Project Sources: six entries, with the original five intact:
  `CHATGPT_REPO_INTERFACE.yaml.txt`, `BOOTSTRAP.md.txt`,
  `RUNTIME_EFFECT_CONTRACT.md.txt`, `RECOVERY_AND_CONTINUATION.md.txt`,
  `EPISTEMIC_IDENTITY_CONTRACT.md.txt`, and the new
  `NATIVE_DELEGATION_CONTRACT.md.txt`.
- The new Project source's 4,208-character text was compared directly against
  `architecture/chatgpt/NATIVE_DELEGATION_CONTRACT.md` and matched exactly.

These observations are **project UI save/readback**, not model execution proof.
The new companion source remains on a Draft PR until repository review;
installation in the ChatGPT Project does not silently merge its source.

## Native dispatch experiments

Two fresh chats inside Vera Mono were asked to spawn exactly two genuine
read-only children and produce accepted native receipts and independent returns:

| Experiment | Composer | Outcome |
| --- | --- | --- |
| Initial | Medium | `NATIVE_DISPATCH_UNAVAILABLE`; zero visible receipts/children |
| Controlled follow-up | High | `NATIVE_DISPATCH_UNAVAILABLE`; zero visible receipts/children |

The test chats' descriptions of their tool registries are **self-reports**,
not independent registry introspection. No accepted native spawn receipts,
child IDs, `list_agents` evidence, or child results were observed in either
conversation. This proves **no observed successful dispatch** in these tests,
not global absence of the capability.

The browser's mode selector offered ChatGPT and Codex, but no distinct Work
choice. Selecting Codex left Vera Mono's native Project context for a generic
Codex workspace, so no Codex-mode subagent test was represented as a Vera
Mono Project result. Official ChatGPT documentation describes eligible
ChatGPT Work subagents separately from ordinary Project instructions.

## Claim ceiling and next gate

**CONFIGURED, NOT NATIVE_DISPATCH_VERIFIED.** Project instructions and
sources cannot grant `collaboration.spawn_agent` when the current host session
does not expose it. A future native Vera Mono Project conversation must
independently produce two accepted spawn receipts, canonical child identities,
native status, and separate returns before this claim can be upgraded.

Do not broaden merge, deployment, credential, runtime-installation, or
protected-effect authority to resolve a missing host feature. Preserve the
historical V1 pack and this observed currentness snapshot as separate
evidence classes.
