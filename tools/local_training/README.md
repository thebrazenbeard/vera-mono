# Local Vera adapter corpus preparation (source-only)

This is an **offline, opt-in corpus-preparation tool**, not a neural-weight
trainer. It does not import PyTorch, download models, contact network services,
start an Ollama session, write an adapter, or change Vera memory/identity state.
It is deliberately separate from the **public** `thebrazenbeard/model-training`
ChatGPT identity bootcamp, which does not train neural weights.

Do not place real personal conversations, examples, manifests, generated splits,
secrets, or model artifacts anywhere in this Git repository or a GitHub issue.
Prepare them in an independently secured, private local directory.
The tool rejects source/output paths inside any detected Git checkout as a
guard against accidentally committing private training material.

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
requires owner-only input file permissions and creates new output directories
and files with owner-only permissions. On Linux it also checks the backing
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

`train-plan` computes an offline, read-only, SHA-256-bound preflight. It does
**not** import PyTorch or load neural weights, and it writes nothing. The
optional `train` action requires an exact output- and input-bound approval
copied from that preflight **plus** `--execute`:

```bash
python -m tools.local_training train-plan /private/manifest.json /private/new-adapter --model-dir /private/model-snapshot
python -m tools.local_training train /private/manifest.json /private/new-adapter --model-dir /private/model-snapshot --execute --approval TRAIN_LOCAL_LORA:EXACT_DIGEST_FROM_PREFLIGHT --steps 1
```

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

The initial execution path accepts **only** the text-only
`Qwen/Qwen3-0.6B`/`qwen3` family, with CUDA BF16, three GiB of *currently free*
VRAM, and 1–32 small optimizer steps. It imports Transformers, PEFT and
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
local run later succeeds. The held-out split is excluded from optimizer steps;
no baseline-versus-adapter evaluation, dataset governance attestation,
hardware qualification, installation, or Vera identity/memory promotion is
automatically implied. On native Windows the private ACL hold still refuses
all private reads; a qualified owner-only WSL ext4 path is the likely first
training host, subject to actual host verification.
