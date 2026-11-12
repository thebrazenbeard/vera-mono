# Mini-Vera bounded conversation output — source candidate

Status: opt-in runtime integration, SOURCE/TEST qualified only until exact
new-code inference on an independently qualified host. Stacked on
vera-mono Draft PR #203 (portable bundle), not merged to main.

## Observed motivating failure (2026-11-12)

On VERA-NODE-1, isolated loopback Ollama process, Qwen3.5:0.8b Ollama tag
digest de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c
matched the already installed Lappy tag. The public Mini-Vera one-turn identity
question through the actual old launcher returned a truncated, otherwise relevant
response under the previous 128-token output cap. The local session properly
cleared volatile history. No private data or project memory was loaded.

A DIRECT, UNQUALIFIED experimental HTTP request with the same public composed
prompt and num_predict 256 yielded finish_reason=stop after ~33.26 seconds
on CPU; that is an experimental transport result, NOT proof the previous
Mini-Vera bounded local protocol or the new committed implementation ran it.

The old composer pinned num_predict=128 and loopback.validate_candidate
translated it into a hardcoded wire max_tokens=128. A model that needed
more tokens therefore produced incompletes, which cleared volatile history.

## Patch

- Source composer explicitly permits **only 128 or 256**, as exact integer
  types; defaults remain 128 for callers using existing APIs.
- The local-session CLI accepts --max-output-tokens 128/256; canonical
  request SHA-256 includes the selection, preventing silent wire alteration.
- Loopback validates the bounded selection and sends the same value in
  OpenAI-compatible max_tokens; 257/4096/booleans are refused even if rehashed.
- Portable Ollama preflight defaults to 256 for new conversational trials.
- A bounded 30/60-second deadline is forwarded explicitly (default 60 seconds
  through portable preflight, unchanged default 30 in direct local_session).
- No change to model weights, public identity JSON, tool authority, memory
  write capability, release process or private data ingestion.

## Evidence ceiling and risks

A larger output cap does not imply better reasoning, identity, memory,
truthfulness or sustained Lappy performance. It may raise latency and resource
use; the output still has to stop normally. A 256-token response can still
truncate and correctly clears conversation history. Full blind behavioral
qualification, cold-start durable memory, and separate host memory grants
remain unfinished. The model may hallucinate action receipts or leak synthetic
revoked-context descriptions if asked hypothetically; the model text is never
an authorized tool execution record.

Do not use this candidate to bypass the existing physical-RAM/cold-load
preflight, to infer on a busy Lappy, or to promote PR #203/#201 to main without
applicable review. Runtime remains governed PUBLIC/ephemeral only.
