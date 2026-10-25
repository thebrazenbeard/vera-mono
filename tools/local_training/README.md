# Local Vera private corpus preparation and gated LoRA training

The default **offline, opt-in corpus-preparation** commands do not train neural
weights, import PyTorch, download models, contact network services, start an
Ollama session, write an adapter, or change Vera memory/identity state. A
**separately gated experimental LoRA runner** can update a tiny model only after
an exact-input operator approval and explicit `--execute`; this source does not
prove a model was actually trained, evaluated, or installed. Both paths are
separate from the **public** `thebrazenbeard/model-training` ChatGPT identity
bootcamp, which does not train neural weights.

Do not place real personal conversations, examples, manifests, generated splits,
secrets, or model artifacts anywhere in this Git repository or a GitHub issue.
Prepare them in an independently secured, private local directory.
The tool rejects source/output paths inside any detected Git checkout as a
guard against accidentally committing private training material.

## Phase 1: reviewed Ingest-to-training corpus bridge

`ingest`'s locally adapted source is the provenance/CAS producer. Its
`ACCEPTED` status **does not** independently establish sample accuracy,
license, consent, permission to train, or any right to change Vera's memory,
identity, or model weights. The bridge requires a **separate** operator-authored
selection file with an explicit review reference for every accepted candidate.
It runs offline and reads only privately stored, normalized JSON candidates
of the exact form `{"messages":[{"role":"user","content":"..."},
{"role":"assistant","content":"..."}]}`. It checks raw and normalized
artifact SHA-256 bindings, record status, normalized/ready receipt digests,
normalization replay, reconstructed Ingest source identity, selected
example/group identities, and duplicate content. Source groups must
truthfully identify related examples; no semantic near-duplicate detector exists.

The private selection is UTF-8 JSONL, one record per candidate:

```json
{"ingest_id":"64-lowercase-hex","normalized_sha256":"64-lowercase-hex","example_id":"opaque-1","group_id":"source-family-1","consent":"owner-approved-local-training","approval_reference":"opaque-operator-review-1"}
```

The selection is an **operator declaration**, not independently verified consent.
Do not prepare it from unreviewed transcripts, third-party private content, or
public issues. Place selection, Ingest store, destination parent, and resulting
JSONL on a locally owned, private Linux filesystem (WSL ext4 can qualify),
outside any Git checkout; directories need owner-only `0700`, and files `0600`.
Ingest's default filesystem store does not assert those directory permissions,
so operators must verify and secure them before running the bridge. Windows
ACLs, network mounts, symlink paths, and Linux DrvFs are not accepted.

```bash
# Read-only source/receipt/sample validation; sanitized digests and counts only:
python -m tools.local_training.ingest_bridge plan /private/intake /private/reviews.jsonl

# Explicit export to a NEW owner-only file. No overwrite, training, or network:
python -m tools.local_training.ingest_bridge export /private/intake /private/reviews.jsonl /private/approved.jsonl
```

Use the reported `corpus_sha256` and exported private JSONL in the existing
manifest's `data` section below. The manifest/LoRA runner remains the separate
model-binding, split, accelerator and weight-update approval boundary. Bridge
receipt integrity checks are local byte-consistency checks, **not provenance
authenticity or independent human review**. The bridge prints no sample text or
private absolute paths in successful receipts.

## Phase 2 and Phase 3 gates

Phase 2: run the existing `train_doctor` preflight in the **actual intended WSL
training environment** with a qualified private output parent. Verify the
exact BF16-capable GPU's **currently free** VRAM, dependencies, original
full-model safetensors snapshot, tokenizer/format binding, and independently
reviewed licensing. A GGUF inference file or a specialist adapter for a
different base (e.g., SPM's Qwen2.5-1.5B specialist) cannot substitute.

Phase 3: take an immutable held-out baseline before any adapter update; after
fresh operator approval bound to the exact `train-plan`, evaluate the bounded
candidate against the same held-out cases and predefined SPM-style
memory-currentness and LGCM-style predict-before-update checks. Keep any
candidate **uninstalled** until it beats the baseline without leakage or
regression. Neither these documents nor the corpus bridge claims training or
behavioral qualification has happened.

## Operator-authored manifest

All source, license, provenance and consent fields are **claims supplied by the
operator**, not third-party verified facts. A later independent gate must
verify the actual base/tokenizer/chatform/GGUF source bindings, licensing,
Windows filesystem ACLs, and whether source-group splitting is sufficient to
prevent semantic leakage before any real training or activation.

```json
{
  "schema_version": 1,
  "base_model": {
    "hf_repo": "OWNER/MODEL",
    "revision_sha": "0000000000000000000000000000000000000000",
    "tokenizer_revision_sha": "0000000000000000000000000000000000000000",
    "chat_template_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "gguf_base_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "license_review": "operator-review-reference"
  },
  "data": {
    "path": "/private/path/approved_examples.jsonl",
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "classification": "private-local-only",
    "approval_reference": "operator-consent-reference"
  },
  "split": {"seed": 12345, "evaluation_fraction": 0.2},
  "execution": {"allow_network": false, "allow_weight_update": false}
}
```

Fill in actual immutable identifiers/digests, never branches or model aliases
such as `latest`. The private dataset is newline-delimited JSON with each line:

```json
{"example_id":"opaque-1","group_id":"same-original-source-1","provenance":"review-id","consent":"owner-approved-local-training","messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

`group_id` must identify examples that could leak the same underlying source;
the algorithm holds out whole groups. Exact duplicate conversations are
rejected, but **near-duplicates and incorrectly assigned groups are not
independently detected**.

The strict manifest and data-file parser verifies source bytes against the
declared SHA-256, validates a pinned model/tokenizer/template/GGUF declaration,
and requires explicit local-only classifications. On POSIX it additionally
requires owner-only input file permissions, an owner-only output parent, and
creates new output directories and files with owner-only permissions. On Linux
it also checks the backing
filesystem for private-POSIX-permission compatibility; WSL-mounted Windows
drives such as `/mnt/c` (DrvFs/9p/NTFS), network mounts, and unknown backing
filesystems are refused even if a file *appears* to have mode `0600`. Use a
qualified Linux filesystem such as WSL's internal ext4 disk for private
preparation. Native Windows private ACL verification is not implemented;
private sample access deliberately fails closed on Windows.

From the repository root:

```bash
python -m tools.local_training plan /private/path/manifest.json
python -m tools.local_training prepare /private/path/manifest.json /private/path/new-run
python -m unittest tests.test_local_training_prep -v
```

`plan` only prints non-sample digests/counts. `prepare` explicitly writes
`train.jsonl`, `eval.jsonl`, and `PLAN.json` under a **new** private output
directory; it refuses overwrites. The `PLAN.json` binds the exact manifest,
full declared model identity, and split digests. It is not an authorization
receipt and provides no confidentiality or model-safety proof.

## Experimental text-only LoRA entrypoint (separately gated)

### Read-only local training host preflight

Before preparing any private model or asking for weight-update approval, inspect
the **actual** local WSL/Linux host from the terminal where the training would
run. The path must be an existing owner-only directory on a qualified Linux
filesystem (WSL's internal ext4 can qualify; `/mnt/c`, DrvFs, network shares,
Git worktrees and native Windows private paths cannot):

```bash
python -m tools.local_training.train_doctor --output-parent /private/training-outputs
```

`train-doctor` prints a sanitized JSON receipt with
`HOST_PREFLIGHT_PASS_NOT_TRAINING_AUTHORIZATION` (exit 0) or `HOST_HOLD`
(exit 2). It reads only path metadata and Linux mount information, installed
package versions and current CUDA capability; it does **not** open model or
sample files, install/download anything, make network calls, train weights or
create output files. The torch import/CUDA query may initialize CUDA runtime
state. The check requires Python 3.12+, installed `torch`, `transformers`,
`peft`, native CUDA BF16 (explicitly excludes emulation) and 3 GiB **currently
free** VRAM. An API missing native-BF16 capability or a failed GPU query holds.
Versions are reported as inventory, **not** verified as a compatible or pinned
dependency lock. No path, username, file content or raw exception appears in
the receipt. PASS is a technical preflight only, **never** a model, data,
license, consent, adapter-quality, hardware-load or training authorization.

`train-plan` computes an offline, read-only, SHA-256-bound preflight. It does
**not** import PyTorch or load neural weights, and it writes nothing. The
optional `train` action requires an exact input-, output-, step-count-, and
training-recipe-bound approval
copied from that preflight **plus** `--execute`:

```bash
python -m tools.local_training train-plan /private/manifest.json /private/new-adapter --model-dir /private/model-snapshot --steps 1
python -m tools.local_training train /private/manifest.json /private/new-adapter --model-dir /private/model-snapshot --execute --approval TRAIN_LOCAL_LORA:EXACT_DIGEST_FROM_PREFLIGHT --steps 1
```

Changing `--steps` requires a fresh `train-plan` approval. The plan and
candidate status include the fixed recipe digest and requested optimizer step
count. Recipe revision must advance when fixed hyperparameters or their
behavior change; this digest is a source/configuration binding, not proof of a
particular environment or training result.

**Never run the second command until the base, license, consent, architecture,
host, hardware and private data are independently qualified.** The approval
string is an explicit operator action, not a cryptographic signature or
verification of authority. It is not authorization for any ChatGPT agent to
train on private data remotely or install the result.

The model directory must be an owner-only, non-symlink, non-Git local folder
containing a complete pinned Hugging Face **safetensors** checkpoint and a
private `VERA_SOURCE.json` alongside its tokenizer and config. This JSON has
exactly the fields `schema_version:1`, `hf_repo`, `revision_sha`,
`tokenizer_revision_sha`, `chat_template_sha256`, and `files_sha256` mapping
**every** other flat-directory filename to its actual SHA-256 digest. Its
source and revision values must match the private corpus manifest. The tool
verifies bytes, not an upstream publisher signature; independent trusted
origin and licensing review remain mandatory. The declared GGUF digest is
intended inference lineage only: it is never used as a trainable base.

### Offline source binding of an already-downloaded original-format base

After an operator independently obtains and reviews the official *unquantized*
`Qwen/Qwen3-0.6B` Transformers source, stage **copies** of its flat checkpoint
files (`config.json`, `tokenizer.json`, `tokenizer_config.json`,
`model.safetensors`, and any of `generation_config.json`, `merges.txt`,
`vocab.json`, `special_tokens_map.json`) in a **new** local Linux directory
with owner-only `0700` mode and all individual files `0600`. Do not point this
tool at a Hugging Face cache (normally symlinked/hardlinked), a Git checkout,
an existing model folder with unreviewed contents, a WSL Windows drive, or a
GGUF quantization. No model download, credential use, network call, training,
or installation is performed. The private staging directory is separate from
the original source/cache and from any future training output directory.

Record the independently reviewed publisher/revision evidence **outside**
the model directory (for example, a reviewed origin record in an operator-only
location). Calculate the SHA-256 of that *separate record*, and supply
`sha256:<64-lowercase-hex>` as its reference. Separately declare the pinned
40-character model and tokenizer revision hashes and the expected SHA-256 of
the exact UTF-8 `chat_template` value in `tokenizer_config.json`:

```bash
python -m tools.local_training.bind_source \
  --model-dir /private/local/model-staging \
  --hf-repo Qwen/Qwen3-0.6B \
  --revision-sha REPLACE_WITH_40_LOWERCASE_HEX \
  --tokenizer-revision-sha REPLACE_WITH_40_LOWERCASE_HEX \
  --chat-template-sha256 REPLACE_WITH_64_LOWERCASE_HEX \
  --origin-evidence-ref sha256:REPLACE_WITH_64_LOWERCASE_HEX
```

The command creates **only** `VERA_SOURCE.json`, with exclusive `0600`
creation, streaming local file digests, strict private-path checks, bounded
safetensors-header checks, exact schema compatibility, and a follow-up
`lora_runner._model_snapshot` verification. It cannot overwrite an existing
binding. On validation failure it leaves no newly created binding; it never
edits, replaces, or uploads weights. A successful machine-readable receipt
says `DECLARED_ORIGIN_BYTES_HASHED_ONLY`. This means the *operator-declared*
revision claims are tied to the local bytes, **not** that official publisher
authenticity, all checkpoint tensor shapes, model completeness, license,
consent, training hardware, or independently retained evidence authenticity
has been established. Do not treat the supplied evidence digest as a verified
remote signature. Continue with independent source/legal review and the
separate corpus/training-approval gates; this command does not make an adapter
or permit weight updates.

The initial execution path accepts **only** the text-only
`Qwen/Qwen3-0.6B`/`qwen3` family, with CUDA **native hardware BF16**
(emulated BF16 does not qualify), three GiB of *currently free*
VRAM, and 1–32 small optimizer steps. The accelerator check explicitly calls
`torch.cuda.is_bf16_supported(including_emulation=False)`; an older
incompatible PyTorch signature fails closed rather than silently accepting
emulation. It imports Transformers, PEFT and
PyTorch only after the approval and GPU preflight, forces Hugging Face offline
environment flags before imports, forbids remote code and pickle checkpoint
loading, and writes an adapter to a new private output folder. Even that path
has **not been host-tested or behaviorally qualified** on Lappy. PyTorch and
model dependencies must already be installed locally and pinned/reviewed;
installation is a separate operator action.

**Qwen3.5-4B is explicitly held:** official source cards use a multimodal
architecture, not the generic causal-LM loader used here. A current Qwen3.5
fine-tuning guide advises against 4-bit QLoRA and estimates about 10 GB VRAM
for 4B BF16 LoRA. A historical 4 GB card must not be treated as qualified.
The selected community GGUF, including a reconversion from quantized weights,
is an *inference* artifact, not an original trainable safetensors checkpoint.

Outputs remain **TRAINED_ADAPTER_UNQUALIFIED_UNEVALUATED_NOT_ACTIVATED** even if an actual
local run later succeeds. The marker is refused unless the training routine
reports an integer optimizer-step count exactly matching the approved plan;
partial or malformed receipts leave no trained-status marker and need deliberate
operator review. The held-out split is excluded from optimizer steps;
no baseline-versus-adapter evaluation, dataset governance attestation,
hardware qualification, installation, or Vera identity/memory promotion is
automatically implied. On native Windows the private ACL hold still refuses
all private reads; a qualified owner-only WSL ext4 path is the likely first
training host, subject to actual host verification.
