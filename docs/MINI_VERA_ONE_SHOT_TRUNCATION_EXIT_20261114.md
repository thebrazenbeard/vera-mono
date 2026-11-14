# Mini-Vera one-shot completion truth — 2026-11-14

**Source/test increment, not a neural model improvement or memory installation.**

The original `local_session.main` already labeled a response with `finish_reason=length` as `TRUNCATED_UNVERIFIED_OUTPUT`, printed `Vera [incomplete reply]>`, and cleared volatile history. However, even a one-shot `--prompt` returned **process exit 0**. The `mini-vera-chat.cmd` launcher propagates that return code to callers, so health checks and automated runners could misinterpret a visibly incomplete response as completed.

**Fix:** one-shot `--prompt` returns exit **2** for `TRUNCATED_UNVERIFIED_OUTPUT` after preserving the explicit incomplete display and clearing history. A full finished reply still returns 0. Interactive mode keeps running after a truncated reply with history cleared. The underlying loopback transport, source pins, memory scopes, output trust labels, model weights, and server behavior remain unchanged.

TDD: four focused fake-server integration tests failed in RED (two failures: one-shot and chat launcher returned 0 for `finish_reason=length`). Following the one-line contract fix, the same tests GREEN in normal and optimized Python. The tests exercise actual loopback HTTP to a local fake model, prove exactly one call in one-shot cases, verify the incomplete label, and confirm interactive mode does not replay truncated assistant history. A visible model answer is not an external action receipt.

**Compatibility note:** The separate `ollama_preflight` experiment wrapper previously accepted exit 0 plus an incomplete display to publish a hash-only *unqualified* truncated-reply observation. Now an actual truncated one-shot local session returns 2 and that wrapper's existing failed-call path refuses a success receipt. This is a deliberate fail-closed change; no claim of zero attempted calls is made. Existing synthetic preflight tests that fake a 0 return remain valid simulations of the old path but do not represent a real truncated one-shot session under the changed code. Later work can add a distinct abort/attempt receipt, provided it cannot be mistaken for success.

### Research relevant to actual Qwen3.5 prompt behavior

Ollama's OpenAI-compatible `/v1/chat/completions` endpoint supports `reasoning_effort: "none"` to disable thinking; current source and 2026 issue discussion explain why sending native `think:false` in the OpenAI-compatible payload is not equivalent and can waste the entire completion budget on unreturned thinking content. See https://github.com/ollama/ollama/issues/14820 and https://github.com/odysseus-dev/odysseus/issues/5503. The existing Mini-Vera console already sets `--ollama-disable-thinking`; this fix does not silently change that default. Support is model/version-dependent and remains subject to actual local runtime testing.

In contrast, llama.cpp exposes `--control-vector`, `--control-vector-scaled` and `--control-vector-layer-range` in its server CLI (https://github.com/ggml-org/llama.cpp/blob/master/tools/completion/README.md), but their presence does **not** prove a Qwen3.5 steering vector exists or measurably improves Vera. Test only with a verified base and zero/sham controls, under a host resource preflight. No such vector was created by this PR.

**Evidence classes:** SOURCE/TEST for the code change; no fresh WEIGHT_UPDATE, neural identity transfer, real private-memory activation, blinded human assessment, or host installation is established by the source change alone.
