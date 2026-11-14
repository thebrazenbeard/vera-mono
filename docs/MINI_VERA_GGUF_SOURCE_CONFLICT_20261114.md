# Mini-Vera R13/GGUF declared source conflict — 2026-11-14

This is source-identity and claims-comparison evidence, not trained-weight identity, adapter compatibility, neural improvement, or runtime qualification. A matching architecture does not imply matching base tensors.

## Real GGUF — locally verified complete file, compared to independent published checksum

- Local model: D:\VERA\models\gguf\vera-qwen35-4b-q4-k-m-candidate-20261029\Qwen3.5-4B-Q4_K_M.gguf
- Length 2,707,513,696 bytes; locally computed full-file SHA-256 25082a7dd3776cc3c741c6347d3bd04523f05796607b3fbc32fa3a25dfa1418c, not just the older 10.97MB header.
- Local huggingface_hub download sidecar names revision f9f88ac3e234be915e23811a6d28ea287bdb927e and the same digest; the sidecar alone does not attest origin.
- Public immutable publisher file: https://huggingface.co/lmstudio-community/Qwen3.5-4B-GGUF/blob/f9f88ac3e234be915e23811a6d28ea287bdb927e/Qwen3.5-4B-Q4_K_M.gguf — matching SHA-256 and length.
- Publisher card: https://huggingface.co/lmstudio-community/Qwen3.5-4B-GGUF/blob/f9f88ac3e234be915e23811a6d28ea287bdb927e/README.md — identifies Qwen/Qwen3.5-4B as original upstream, quantized with llama.cpp b8185. This is a publisher declaration: a matching GGUF digest proves identity with the published quantization, not independent BF16-to-GGUF tensor provenance.

## The R13 base reference — not a shard-hash attestation

- R13 adapter_config.json at D:\VERA\models\adapters\v10r3r13-vera-identity-judgment-qwen35-r12-resume-20261016-retry2\adapter points to D:\VERA\models\latest-trained\base.
- Local D:\VERA\models\latest-trained\MODEL_MANIFEST.json names base repository rodrigomt/Qwen3.5-4B-Uncensored-Aggressive revision d61dd146c8fd44c9a49cdb7f59f34e17b61902d8. But that manifest describes historical H07 R4, not R13, and includes obsolete C:\Vera paths. It must not be elevated to verified R13 training-base revision.
- The public rodrigomt repository describes an uncensored derivative: https://huggingface.co/rodrigomt/Qwen3.5-4B-Uncensored-Aggressive/tree/d61dd146c8fd44c9a49cdb7f59f34e17b61902d8
- Prior 248/248 R13 LoRA A/B shape pairs matched local HF tensor dimensions. Neither tensor dimensions nor historical metadata establish exact training-weight identity.

## Executable optional source-claim gate

tools/mini_vera/gguf_architecture_gate.py now accepts these four all-or-none optional flags: --hf-package-manifest, --adapter-config, --publisher-base-repository, --expected-gguf-sha256. Old metadata-only callers remain unchanged. With all four inputs, it resolves the adapter's local HF base path, hashes the ENTIRE GGUF, and compares declared upstream repository IDs. It refuses incomplete inputs, mismatched file digests, mismatched adapter local path, or invalid source-repository syntax. Matching repository declarations still do not qualify weights.

Observed status: DECLARED_UPSTREAM_CONFLICT_ANCESTRY_UNKNOWN. The reported repository relation is MISMATCH, R13 local base path is MATCH, the whole-GGUF hash is verified, and proves_training_base_revision, proves_different_neural_weights, proves_weight_ancestry and runtime_qualified are all false. The command deliberately returns 2, not successful model qualification; authority_effect remains NONE.

OffGit real-file JSON report: D:\VERA\experiments\mini-vera-gguf-source-conflict-evidence-20261114\real_gguf_source_conflict.json
Its SHA-256 is f2fdd28f984781f65a1408cb49d80ce0e3f8892b7abd0f8deab020eb6ad6b4f9.

HOLD: Do not merge R13 into this published official-Qwen GGUF. Recover independently anchored R13 training-base shard hashes, compare actual local HF full-weight hashes, and if needed quantize the exact trained-against base with converter custody. Only then consider controlled baseline/correct-adapter/sham evaluation under safe host preflight. No private memory or neural training was changed here.
