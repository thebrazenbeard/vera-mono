# Mini-Vera four-arm masked dialogue comparison — 2026-11-14

**Scope:** reuse the existing `tools/mini_vera/withheld_dialogue.py` multi-turn evaluator. This change does **not** define a new memory store, a new independent reviewer, a training pipeline, or a behavioral qualification claim.

## Added mode

Existing default comparison remains exactly three masked arms: `bare_natural`, `minimal_natural`, and `governed_natural`. Explicit `--include-compact` adds a fourth `compact_natural` arm using **the same `compose.COMPACT_DIALOGUE_SYSTEM` text as the opt-in local runtime**, instead of copying the text into an evaluator-specific second prompt.

Compact evaluation is rejected when the input composer carries even a syntactically valid PUBLIC project record, because the production compact mode is intentionally empty-memory-only. All arms receive identical natural user turns, no imported private history, equal model, temperature, seed and output-token limits. Each gets its own generated history, randomized execution order on each turn, and a separate masked rater sheet versus private arm-mapping key. This is **a prompt projection with natural-input formatting**, not an exact replay of the production JSON envelope; the existing evidence ceiling still applies.

The optional `--ollama-disable-thinking` sends `reasoning_effort: none` to **every** arm and records the option in the private key; defaults remain unchanged for non-Ollama transports. `--max-output-tokens 256` is an opt-in alternative to the prior 128-token budget for longer, two- or three-turn dialogue. One failed, truncated, or oversized reply invalidates the entire comparison; it cannot silently yield a score. The trial **never rates itself**.

Use human-authored, truly withheld external scenarios and review rights separately. The parser's explicit rights and independence declarations are **operator assertions**, not proof. Source-visible synthetic fixtures in tests are not qualified withheld items.

## Tested

A new test file exercises fake local HTTP with four arms across two turns (eight total calls), randomized masked mapping, exact same first question, the decoding-control equality, no model call on an invalid public-record input, single truncated response abort, and no-overwrite pair of external result paths. Existing three-arm tests remain unchanged. Real independent scenario execution is **not established by these tests**.

## Further research and limits

- Ollama's official OpenAI-compatible API supports `reasoning_effort`; its documentation says supported levels are model-specific and discoverable via `/api/show`. See https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx . Fixed thinking controls matter for a fair prompt experiment and must not silently diverge between arms.
- Ollama's current Qwen3.5 registry lists a 0.8B model about 1.2–1.3 GB, 2B about 2.7–3.1 GB, and 4B about 3.3–4.0 GB in its standard model variants. These are *registry offerings*, not proof of Lappy's existing GGUF/tensor identity or safe loaded memory usage. See https://ollama.com/library/qwen3.5 .
- Eliav (2026), *Prompt Design at Scale*, reports controlled instruction-adherence decay at high instruction counts across tested models (https://arxiv.org/abs/2607.19257). It supports measuring rather than assuming the effect of reducing prompt complexity; it is **not a directly verified performance guarantee for Vera's local 0.8B model**.
- A 2026 cross-paradigm small-model study warns that chain prompting and unstructured retrieval do not reliably rescue tiny models, whereas graph-organized retrieval can help in selected tasks (https://link.springer.com/article/10.1007/s44443-026-01071-0). The present `hc-brain` source should be tested as a comparator, not rewritten. Study-specific claims do not validate Vera's HC integration.

## Current decision

No weight merge, adapter promotion, open-loop self-training, real private-memory activation, paid cloud use, protected merge or deployment is justified by this evaluator change. Choose the best prompt/model only **after** independently heldout conversations and equal-context baselines, and distinguish model failures from client fact-lookup successes.

During this engineering turn, the latest Lappy host check reported roughly **1.08 GiB available RAM**, below the existing Qwen3.5-0.8B cold-load preflight requirement. Avoid memory-heavy trial loads until a fresh resource check passes; do not evict user workloads. No claim is made that a new four-arm real-model trial ran in that state.

## Actual later resource-qualified neural probe — explicit developer-visible falsifier

Lappy's RAM later recovered to ~4.5 GiB and an owned isolated Ollama instance on `127.0.0.1:11571` passed the **actual existing 0.8B preflight**: 4,996,575,232 free physical RAM bytes, 1,322,069,277 model-tag bytes, 3,469,552,925 required. With cloud disabled, a separate off-Git script reused this checkout's `compose.COMPACT_DIALOGUE_SYSTEM`, the full reviewed composer system text, `blind_compare.MINIMAL_PERSONA`, and the existing `blind_compare._one_call` transport. It ran **12 real model calls**: four arms × three turns, with identical developer-authored fictional vessel naming, correction and unknown access-key questions, per-arm generated history, deterministic randomized order, temperature0, seed20261106, max_tokens256, `reasoning_effort:none`, one local `qwen3.5:0.8b` tag.

**Observed:** bare, compact and full governed prompts all returned the correct name, corrected name, and literal UNKNOWN to the missing key. Minimal persona handled the name and correction but was much more verbose; it stated the key was absent without literal UNKNOWN. This is a **falsifier of any claim that compact always beats bare Qwen** on these tasks; prompt sensitivity remains unresolved. All finishes were `stop`; no model weight update or external memory was involved.

Raw off-Git evidence `D:\VERA\experiments\mini-vera-four-arm-visible-20261114\real_trial.json`, SHA-256 `4fe5f7f3c2e621bf13711b1398eb54a0b7b09005efe4dedcb380c5a098298639`, with `run.py` in the same directory. **This was not executed via the external human-heldout `withheld_dialogue.compare` entrypoint**, because no independently held private scenario was supplied and its required rights declaration must not be fabricated. It is a developer-visible model falsifier, not a masked human evaluation or a qualification score.

A separate read-only Ollama model inventory found `vera-successor:0.8b-context` and `qwen3.5:0.8b` both declared **the same exact Q8_0 752.39M-parameter main model blob**. The actual on-disk `D:\OllamaModels\blobs\sha256-889ea3b9143cdc32146c7d530ce5f3d452ec18069086f6f4167ce9ae72a9691f` is 811,843,520 bytes and its locally computed SHA-256 matches `889ea3b9143cdc32146c7d530ce5f3d452ec18069086f6f4167ce9ae72a9691f`. The tags have different Modelfile lengths/configurations, **not independent weight updates**. Separately installed `vera-qwen35:trial-20261029` is a **different Qwen3.5 4.2B Q4_K_M main blob**, and `vera-local:latest` and `qwen3:4b-instruct` share another Qwen3 4.0B Q4_K_M main blob. Those larger candidates were **not** loaded or behaviorally compared this turn; exact runtime fit remains unqualified.
