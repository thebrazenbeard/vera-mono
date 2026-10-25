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
and files with owner-only permissions. Windows private ACL verification is not
implemented; private sample access deliberately fails closed on Windows.

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

The next separately reviewed implementation would load a pinned Hugging Face
base snapshot locally, verify its actual tokenizer/chat template/GGUF binding,
run a hardware-qualified LoRA/QLoRA adapter training process offline, evaluate
the resulting adapter against held-out tests and baseline, and require explicit
activation approval. None of those effects occur in this tool.
