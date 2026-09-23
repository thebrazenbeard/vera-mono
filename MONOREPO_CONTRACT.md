# Vera Mono Contract

`vera-mono` is the self-contained implementation repository for Vera.

## Hard invariants

1. Runtime code lives in this repository.
2. No Git submodules.
3. No runtime `git clone`, sibling-repository checkout, or GitHub-source fetch is required to run Vera.
4. External repositories are donors/research labs. Once a mechanism is admitted, its implementation is copied or reimplemented here and becomes Vera-owned source.
5. Every absorbed donor mechanism keeps exact provenance: donor repository, exact ref, source path/blob where available, target path, and whether the import is byte-preserving or derived.
6. Provider services (model APIs, databases, operating systems, devices) may remain external infrastructure. Their adapters and contracts live here.
7. Identity-specific state is not silently generalized. Generic mechanisms and Vera-specific bindings are separate modules.
8. Source presence is not installation, runtime consumption, authority, or behavioral qualification.

## Internal shape

- `packages/vera_core/` — composition root, identity-neutral runtime contracts, routing, governance.
- `packages/rezon/` — absorbed reasoning kernel.
- `packages/*/` — future absorbed capability modules.
- `provenance/donors/` — exact donor bindings.
- `provenance/plans/` — historical/import planning evidence, never runtime dependencies.
- `architecture/` — current monorepo manifests and contracts.
- `tests/` — repository-level invariants.

External donor repositories remain useful for experimentation, comparison, and provenance. They are not required at runtime.
