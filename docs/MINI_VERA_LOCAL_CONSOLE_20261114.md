# Mini-Vera local conversational console — 2026-11-14

Status: opt-in source/runtime increment. **Not** behavioral qualification, neural weight training, independently authenticated source memory, an identity transfer, or a background service.

The existing `local_session` already supports an interactive RAM-only session with up to two exchange pairs. This increment makes it reachable through `mini-vera-chat.cmd`, using the existing `ollama_preflight.probe` and source-pinned composer; the original `mini-vera.cmd` single-turn preflight remains unchanged. No private memory or tool capability is installed.

From the byte-verified portable folder with an **already running local Ollama server**:

```powershell
.\mini-vera-chat.cmd --check
.\mini-vera-chat.cmd --confirm-host-idle --allow-cold-load
```

The first command performs bounded read-only model inventory and memory checks. The second requires a fresh operator workload check and opt-in to cold-loading the already installed local Qwen3.5-0.8B model. Use `--endpoint http://127.0.0.1:11521/v1` only for a separately owned loopback server. For a one-turn diagnostic add `--prompt "Introduce yourself"`; otherwise talk interactively and type `/quit` to exit. No models are downloaded, server processes created or stopped, external cloud APIs called, or real user memories imported.

Build from exact reviewed source with `python scripts/mini_vera_portable.py build --source <absolute-checkout> --output <new-absolute-folder> --source-sha <exact-40-hex-commit>`; verify with `python scripts/mini_vera_portable.py verify --output <folder>`. The portable source contains a hashed manifest and launcher, **not neural model weights**. The model resides in the existing Ollama store; the server-supplied registry digest is not weight attestation. The current Windows invocation relies on Python 3 installed and a running local Ollama service.

Limits: preflight is a resource snapshot, not a lease; other processes could consume resources after it. The underlying `local_session` deliberately keeps only volatile, noncanonical conversation history, has no durable cold-restart continuity, no host tool privileges, and no independently protected issuer, key pin, or revision store. No synthetic PUBLIC fact-gate mode is silently enabled by this chat launcher.

Observed local inference (owned isolated Ollama on Lappy): the existing 0.8B model correctly denied being a continuation of ChatGPT weights/memory on one prompt. In a later two-turn conversation it incorrectly refused to name the explicitly fictional ship **Ember** and repeated the refusal on recall. An additional identical-input raw-composer probe also refused, while a one-line explicit fiction-permission clarification failed to correct it. A bare-model test did not make that refusal but rambled and truncated. These are **small, developer-visible negative tests**, not a blinded comparative qualification; the console launch improvement does not fix the underlying model's conversational reasoning or creative suitability.

Prior source-first synthetic PUBLIC exact-key lookup in Draft PR #222 remains opt-in and is not evidence that Qwen learned to reason about missing facts. Do not promote a source answer into a neural answer or grant host action/memory authority from this package.
