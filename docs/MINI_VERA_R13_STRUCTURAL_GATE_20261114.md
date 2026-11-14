# Mini-Vera R13 LoRA/HF base tensor structure — 2026-11-14

This is a **read-only structural examination** of locally present Hugging Face safetensors files, **not** neural inference, a model merge, a weight-identity proof or promotion authorization.

The new `tools/mini_vera/adapter_shape_gate.py` reads bounded safetensors JSON headers, explicit HF sharded-weight index, and the adapter configuration. It checks exact Qwen3.5 LoRA target-name mapping, paired A/B rank and dimensions against every referenced HF base tensor, and validates offsets/bounds without loading model tensors. It refuses invalid or oversized headers, unsafe shard names, incomplete pairs, invalid ranks, and malformed metadata. Hashes cover **headers and the index only**, not all the neural weights. The CLI intentionally exits **2 even when all shapes match** to avoid treating structural validity as model qualification.

## Actual Lappy observation

- Adapter: `D:\VERA\models\adapters\v10r3r13-vera-identity-judgment-qwen35-r12-resume-20261016-retry2\adapter`
- HF base: `D:\VERA\models\latest-trained\base`
- R13 adapter has **496 LoRA tensors / 248 A+B pairs**, rank 4; **248/248 shape pairs match**, 0 failures.
- Adapter config header SHA-256: `1a6fb92a29fa2af0d5f557ea61d6c49e6c58788f362d6ab60c5d4fb1ae5db4c1`
- Adapter tensor *header* SHA-256: `6b3dc153b8928487c14002f8c10ff72e401d983c00424c131999dd71c4323f41`
- HF base index SHA-256: `8166b7a5d1450740543caa25ddd6133c5f39fe6fa9b853f9e110ab2b938a25df`
- Base first shard *header* SHA-256: `8c7db4f00fff2e960f76c658d70609da09bc1039685dbf48f8951e47029f1341`
- Base second shard *header* SHA-256: `b8b9c5f2716d6f718ee5eec7b8ef85bef05bde8a8c3d512388ab625b5d1d7979`
- Status: `SHAPES_MATCH_ANCESTRY_UNKNOWN`, `proves_weight_ancestry=false`, `proves_gguf_equivalence=false`, `runtime_qualified=false`, `authority_effect=NONE`.

This positive **shape** result narrows the uncertainty in model-training issue #354: there is no observed rank/dimension obstacle to pairing R13 with the present HF base. But whether that base contains the exact trained-against weights remains **UNKNOWN**. Separately, the Qwen3.5-4B Q4_K_M GGUF may have been converted from a different source revision or publisher. Without independently anchored training-source hashes, conversion ancestry and controls, a LoRA/GGUF merge or qualified performance claim remains **on hold**.

Run from this source checkout using `py -3.14 -m tools.mini_vera.adapter_shape_gate --adapter-config <adapter_config.json> --adapter-file <adapter_model.safetensors> --hf-base <HF-base-directory>`. The returned exit code 2 is intentional and must not be interpreted as a failed shape check; inspect the JSON status. No model download, paid compute, GPU load, host services, weights, or private memory are involved.
