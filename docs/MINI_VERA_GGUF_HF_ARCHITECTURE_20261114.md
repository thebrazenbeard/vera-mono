# Mini-Vera GGUF/HF architecture gate — 2026-11-14

**Subject:** The actual 2,707,513,696-byte local Qwen3.5-4B Q4_K_M GGUF against the current Hugging Face base configuration at `D:\VERA\models\latest-trained\base`. This is a **metadata-only** check; no model weights are loaded or hashed, no neural inference, and no LoRA pairing or promotion is authorized.

## Result

The real GGUF is version **3**, with **426** declared tensors and **34** key-value metadata entries. The new `tools/mini_vera/gguf_architecture_gate.py` parses its bounded header and metadata streams without loading tensors. All six basic architectural values agree with the HF `text_config`: **32** layers, **2560** embedding width, **9216** feed-forward width, **16** query heads, **4** KV heads, and full-attention interval **4**; 32 distinct layer indices 0–31 are present. The GGUF tensor embedding shape agrees with the HF vocabulary/width fields when available. There are **zero metadata architecture mismatches**.

- GGUF **header-only** SHA-256: `054115bf3bfb63d331f45cb0b9637350735b4372b05d00ccaf6f03085830db48` (10,967,378 bytes of metadata).
- Actual report: `D:\VERA\experiments\mini-vera-gguf-architecture-evidence-20261114\real_gguf_architecture.json`; SHA-256 `9e398e835791efe61d99dcf1023b882e6ce943415249e1e4f400e5bbf7dd5d40`.
- Status: **`ARCHITECTURE_MATCH_ANCESTRY_UNKNOWN`**, with `proves_weight_ancestry=false`, `proves_gguf_conversion_equivalence=false`, `runtime_qualified=false`, and `authority_effect=NONE`.
- The GGUF contains no recorded `general.source.url`, `general.source.huggingface.repository` or `general.source.huggingface.revision` metadata. This means the file's exact trained-against base provenance and conversion origin remain **unknown**, not verified compatible.

**EOS distinction:** GGUF reports `tokenizer.ggml.eos_token_id=248046`, which matches the local HF `tokenizer_config.json` mapping for `<|im_end|>`. The HF `text_config.eos_token_id=248044` instead maps to `<|endoftext|>`; report labels the model-config/ GGUF relation `MISMATCH` and tokenizer-config/GGUF relation `MATCH`. This difference may reflect model/tokenizer configuration conventions and is **not** by itself evidence of wrong neural weights. Do not silently normalize or claim it resolved.

## Implemented check and limits

Source-only GGUF-v3 parser follows official `ggml-org/llama.cpp` header specification: https://github.com/ggml-org/llama.cpp/blob/master/ggml/include/gguf.h . It bounds metadata/array sizes, handles strings and GGUF value types, rejects malformed/duplicate entries, unsupported versions, invalid tensor ranks/dimensions and file redirects, verifies layer coverage, and keeps source claims separate from actual authority. Its JSON is a diagnostic; the command **intentionally exits 2 even on architecture match**. It cannot distinguish two different checkpoints having the same architecture and cannot infer quantized-tensor equivalence by filename or header shape.

The official llama.cpp `convert_lora_to_gguf.py` accepts a base configuration but must still map this adapter correctly for the exact Qwen3.5 revision. A published upstream Qwen3.5 LoRA conversion failure involved `LoraTorchTensor.reshape()` during head reorder (https://github.com/ggml-org/llama.cpp/issues/21125); that report is a compatibility risk to investigate, **not a verified failure on this local R13 adapter**. No adapter GGUF conversion was performed here.

Use the sealed portable wrapper `mini-vera-gguf-check.cmd --hf-config <path> --hf-tokenizer <path> --gguf <path>` so `PYTHONDONTWRITEBYTECODE=1` and bundle verification protect the portable folder. Do not run plain `python -m` in a sealed package; it would create unlisted `__pycache__` files.

**Next qualification gate:** locate independently anchored R13 training-base shard hashes and the GGUF publisher/converter's exact source weights/revision. Then run bounded offloaded baseline-vs-correct-adapter-vs-sham controls and independent held-out dialogue only when host RAM/VRAM permits, with no forced service eviction.
