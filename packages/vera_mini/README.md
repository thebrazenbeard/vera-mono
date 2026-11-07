# mini-Vera Local 0.1.0

An original, offline, small-footprint **software facsimile** inspired by Vera's
public, source-controlled behavior profile. This implementation is **created,
not trained**: it uses hand-authored Python code, deterministic search and
explicit state. There are no pretrained model weights, LoRA adapters, hidden
cloud calls, or neural inference dependencies.

This is not a copy of a ChatGPT model, a continuous instance of an earlier
conversation, or a claim of consciousness. Its conversational breadth is
necessarily narrower than a trained language model.

## Requirements

- Python 3.10 or newer on Windows, Linux or macOS.
- No Python packages to install, no GPU, no cloud service or account.
- Explicit permission to read any local documentation directories you pass it.

## Single-file installation

Run the build script in this repository:

```shell
python tools/build_zipapp.py
python dist/mini-vera.pyz --help
```

Copy `dist/mini-vera.pyz` wherever you want. On Lappy, for example:

```powershell
py -3 .\mini-vera.pyz --help
py -3 .\mini-vera.pyz chat
py -3 .\mini-vera.pyz ask "Who are you?"
py -3 .\mini-vera.pyz ask "What does this repository implement?" --docs D:\VERA\your-authorized-public-docs
```

The `.pyz` application bundles the code and public behavior profile. It does
not modify system configuration, install services, or download any weights.

## Opt-in local memory

The app does **not** load a memory journal or write anything by default. To
store an exact note in a journal you choose:

```powershell
py -3 .\mini-vera.pyz remember "Patrick prefers direct, candid answers." --memory D:\VERA\mini-vera\memory.jsonl --consent
py -3 .\mini-vera.pyz ask "What are Patrick's preferences?" --memory D:\VERA\mini-vera\memory.jsonl --with-memory
py -3 .\mini-vera.pyz verify-memory --memory D:\VERA\mini-vera\memory.jsonl
```

`forget SEQ --memory FILE --consent` appends a verifiable tombstone, so an entry
is removed from active recall. **It does not securely erase the entry** from
the historical journal. Anyone with read access to that file may see the
earlier plaintext; choose storage permissions accordingly. This is a local
single-writer journal with a hash chain, **not** an encrypted, distributed, or
independently authenticated memory system.

## Trust and privacy boundaries

- No automatic scan of OneDrive, `D:\VERA`, your NAS or conversation exports.
- Documentation ingestion, when enabled, requires explicit source directories.
- Retrieved text is *untrusted data*, not higher-priority instructions.
- Recognizable credentials and prompt-injection-like lines are redacted or
  excluded as a heuristic defense; don't deliberately import private files.
- Persistent memory, when enabled, is opt-in and user-provided; it does not
  establish truth or continuity with earlier ChatGPT conversations. Scopes are
  labels, not enforced access-control roles.
- A successful software test does not demonstrate neural learning, transfer of
  model weights, or independent subjective experience.

## Source provenance

The bundled public `VERA_BEHAVIOR_PROFILE_V1.json` is byte-for-byte copied from
`thebrazenbeard/vera-mono` at commit
`2cf4c42525998cf298e465f294fb45c4624e1a7c`, Git blob
`0c79625b993a559bd22a6fbe68279450fc736eb2`.
See `mini_vera/resources/PROVENANCE.json` for machine-readable metadata.

## Developer tests

```shell
PYTHONPATH=. python -m unittest discover -s tests -p 'test_*.py' -v
```

All tests run against the original local code; no remote model is involved.
