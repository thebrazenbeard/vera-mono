# Vera Native Model donor research — 2026-10-01

This record captures design research used for the first Vera-native tokenizer, transformer, checkpoint, training, and inference implementation. Donor repositories are research/provenance inputs only; Vera Mono does not import them as runtime dependencies and does not adopt their pretrained weights.

- `karpathy/minbpe@1acefe89412b20245db5a22d2a02001e547dc602` — MIT. Used as a conceptual reference for a minimal trainable byte-level BPE vocabulary/merge pipeline. Vera Mono implements its own tokenizer code and trains its own merges.
- `karpathy/nanochat@92d63d4e8bb4df75c3b71618f31ddde2378b2bcd` — MIT. Used as a current reference for a complete tokenizer → pretraining → checkpoint → inference/chat lifecycle. Vera V1 intentionally uses a smaller conventional decoder-only transformer instead of copying nanochat's full modern stack.
- `karpathy/nanoGPT` — MIT. Used as a conceptual reference for the classic decoder-only causal GPT training/inference shape. Its README now points users toward nanochat; it remains useful as a simplicity reference.
- `karpathy/llama2.c@350e04fe35433e6d2941dce5a1f53308f87058eb` — MIT. Used as a conceptual reference for explicit checkpoint-driven autoregressive next-token inference.
- `ggml-org/llama.cpp@e358d59178377be4c58ba567925e05faadbccb57` — MIT. Reviewed as a future performance/quantization reference. It is not a Vera Mono runtime dependency in V1.
- `tinygrad/tinygrad` — MIT. Reviewed as a possible self-contained tensor/autograd substrate. Not adopted in V1 because NumPy inference plus optional PyTorch training keeps the initial boundary smaller.
- `openai/tiktoken` — MIT. Reviewed for BPE implementation practice. Not adopted because Vera's bootstrap and future checkpoints should own/train their vocabulary rather than select a pretrained encoding.

The adopted V1 design is intentionally conservative: Vera-owned byte BPE, a conventional decoder-only causal transformer, a safe `.npz` checkpoint, NumPy next-token inference, and optional PyTorch only for gradient-based training/export. No third-party pretrained model or pretrained checkpoint is used as Vera's language generator.

The packaged 620-parameter checkpoint is a smoke artifact, not a capability claim. It exists to prove the complete native path can load and execute from the repository/wheel. General language competence requires a substantially larger model, a much larger appropriately licensed corpus, and materially more training compute.
