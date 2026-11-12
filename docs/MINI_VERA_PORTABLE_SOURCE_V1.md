# Mini-Vera portable 0.8B source bundle v1

Status: built and source-tested on Windows. NOT neural/identity qualified,
not a host resource lease, not a signed installation, and not a standalone
neural-weight distribution. Builds from the integrated Mini-Vera PR #201 source
without starting or downloading any model.

## Contents and semantics

- Copies tools/mini_vera/*.py, the public Vera identity/behavior JSON,
  the verifier, and the repository's LICENSE/NOTICE.
- Adds mini-vera.cmd and INSTALL.json with SHA-256 hashes of every shipped file.
- Does not copy Ollama weights, adapters, memory, credentials,
  chat exports, Git metadata, editor startup tasks, or private data.
- Uses the already-installed local Ollama alias qwen3.5:0.8b; model inventory
  and physical RAM are checked by the existing read-only preflight.
- The launcher verifies file inventory (including directories and redirections)
  before probing Ollama. Verification only detects divergence from a manifest
  controlled by the same folder; this is NOT signed provenance or protection
  against an adversary who can replace both the verifier and manifest.

## Build on Windows, without inference

From a verified checkout containing scripts/mini_vera_portable.py:

    C:\Windows\py.exe -3.14 scripts\mini_vera_portable.py build --source D:\VERA\experiments\mitosis-runtime-bundle-20261111 --output D:\VERA\mini-vera\mitosis-0.8b-source-v2-20261111 --source-sha a27c9098b9766fa669f1ee35de5193b257957081

The --source-sha is a declared base checkpoint, not proof that all bundle
bytes were committed at that revision; SHA-256 of the copied actual bytes
is in INSTALL.json. Publication and signed provenance are separate.

Verify the resulting folder:

    C:\Windows\py.exe -3.14 scripts\mini_vera_portable.py verify --output D:\VERA\mini-vera\mitosis-0.8b-source-v2-20261111

Run read-only installed preflight:

    D:\VERA\mini-vera\mitosis-0.8b-source-v2-20261111\mini-vera.cmd

The launcher does not load a model unless both --execute and explicit
operator confirmation are supplied through the existing preflight logic.
The existing preflight also requires a cold-load opt-in and sufficient RAM.
Do not supply those flags on a busy Lappy or treat free GPU memory as
substitute for a physical RAM/resource qualification.

## Evidence ceiling and rollback

Test the builder with:

    C:\Windows\py.exe -3.14 -m unittest discover -s tests -p test_mini_vera_portable.py

The builder's own tests create disposable synthetic source directories and
perform no HTTP or neural inference. The installed launcher was also probed
with Ollama in read-only mode on Lappy; insufficient physical RAM returned a
safe refusal with zero model inference calls. The existing Mini-Vera local
session can compose and validate a request without sending any HTTP calls.

This is a Windows Python-source runtime plus an external pre-installed
local 0.8B model, not a 3 GB single GGUF, newly trained Vera, general tool
operator, autonomously persistent memory, or established identity continuity.
Any later neural and behavioral qualification needs actual output, adversarial
heldout comparison, cold-restart testing and independent review.

Rollback is non-destructive: stop using the new mini-vera.cmd and return
to the existing checkout/zipapp. No existing model, checkpoint, service,
user record or old installation is deleted or replaced by this builder.
