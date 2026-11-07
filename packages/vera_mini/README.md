# mini-Vera Local 0.2.0 — First Learned Policy

An original, offline, small-footprint **software facsimile** inspired by Vera's
public, source-controlled behavior profile. Its first version was **created,
not trained**. This second version has an original, locally trained
multinomial-logistic-regression model that selects among a few dialogue plans.
There are **no imported pretrained neural weights**, LoRA adapters, hidden
cloud calls, or neural inference dependencies. Its dialogue policy **was
trained** on a small, source-controlled, originally authored synthetic corpus.

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
python tools/build_zipapp.py --output dist/mini-vera-trained.pyz
python dist/mini-vera-trained.pyz --help
```

Copy `dist/mini-vera.pyz` wherever you want. On Lappy, for example:

```powershell
py -3 .\mini-vera-trained.pyz --help
py -3 .\mini-vera-trained.pyz chat
py -3 .\mini-vera-trained.pyz ask "Who are you?"
py -3 .\mini-vera-trained.pyz ask "What does this repository implement?" --docs D:\VERA\your-authorized-public-docs
```

The `.pyz` application bundles the code and public behavior profile. It does
not modify system configuration, install services, or download weights.
It also bundles the exact initial learned-policy checkpoint. The experimental
learning component can be disabled for ablation using `--no-learning`.
The trained release artifact is `dist/mini-vera-trained.pyz`; the
`dist/mini-vera.pyz` filename is the original pre-learning build.

The repository also contains a **source-only experimental** `brainpack.py`
for explicitly selected UTF-8 documents with content hashes and a 3 GiB
maximum budget. It has no CLI integration or SemanticAtlas adapter. Linux
uses descriptor-based traversal; a Windows path-checking fallback is included,
but it has **not been executed on Lappy** and cannot guarantee safety against
concurrent malicious path swaps. Neither backend has a proven crash-durable
release protocol. Do not treat this as a deployed memory subsystem.

The separate `evidence_bridge.py` is a read-only, opt-in projection of
already-authorized STM/DeepMemoryStorage observations. It has no installed
provider connection or automatic Mini-Vera runtime hook. Historical evidence
does not establish current memory truth. Actual provider authorization and
cross-repository runtime interoperability remain unverified.

## Learning, narrowly stated

The trained model classifies conversational input as `challenge`, `support`,
`probe`, `direct`, `identity`, or `unknown`. These weights influence only the
wording of *unknown-answer* dialogue strategies. They do not decide what is
true, authorize external actions, or override privacy and identity rules.

The initial training run used **72 approved authored examples**, plus separate
36-example validation and 36-example held-out test sets. Its measured accuracy
was 26/36 on validation and 24/36 on held-out test, versus a 6/36 majority-class
baseline. This is a limited synthetic intent-routing result, **not** evidence
of natural-language generalization or generative intelligence. See
`data/training_receipt_v1.json` for the exact input/checkpoint hashes and class
confusion matrices. `data/PROVENANCE.md` states the dataset's origin and limits.

A separately frozen, naturally phrased 72-example out-of-distribution probe
scored 41/72 (56.9%), versus its fixed 12/72 majority baseline. The original
model was **not tuned on this set**. Clarification requests remained weak at
4/12. This is still a small authored intent test, not proof of generalization
to unconstrained user conversations. See `data/OOD_PROVENANCE.md`.

To train a new local policy from an explicitly approved JSONL file containing
`{"text": "...", "label": "..."}` records:

```powershell
py -3 .\mini-vera-trained.pyz train-policy --data .\approved-examples.jsonl --output .\my-policy.json --consent
py -3 .\mini-vera-trained.pyz chat --policy .\my-policy.json
```

Training writes a checkpoint **and** an adjacent
`my-policy.json.manifest.json` recording its SHA-256, format, and explicit
source-consent declaration. Both are required when loading a sidecar policy.
Use `--overwrite` only when deliberately replacing an existing checkpoint or
manifest. The manifest detects accidental changes; because both files are
locally editable, it is **not a cryptographic proof of authorship or source
rights**. Bundled policy bytes are pinned to the verified build hash.

Mini-Vera does **not** silently train on chat history. The learning algorithm
lives inside `.pyz`; ongoing parameter updates are explicit user-governed
operations and write a sidecar checkpoint, which can be included in a future
build after review.

## Opt-in local memory

The app does **not** load a memory journal or write anything by default. To
store an exact note in a journal you choose:

```powershell
py -3 .\mini-vera-trained.pyz remember "Patrick prefers direct, candid answers." --memory D:\VERA\mini-vera\memory.jsonl --consent
py -3 .\mini-vera-trained.pyz ask "What are Patrick's preferences?" --memory D:\VERA\mini-vera\memory.jsonl --with-memory
py -3 .\mini-vera-trained.pyz verify-memory --memory D:\VERA\mini-vera\memory.jsonl
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
- Training rejects a limited set of recognizable credential token shapes; it
  does not replace careful review or a comprehensive secrets scanner.
- Persistent memory, when enabled, is opt-in and user-provided; it does not
  establish truth or continuity with earlier ChatGPT conversations. Scopes are
  labels, not enforced access-control roles.
- A successful software test does not demonstrate neural learning, transfer of
  model weights, or independent subjective experience.
- The memory journal rejects symlinks and Windows junctions at construction,
  read and write time. On Windows this is still vulnerable to sufficiently
  privileged concurrent filesystem races; consent and file permissions matter.

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
