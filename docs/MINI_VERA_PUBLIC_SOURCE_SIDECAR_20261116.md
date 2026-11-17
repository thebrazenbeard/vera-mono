# Mini-Vera PUBLIC source sidecar (source candidate; not installed)

This opt-in mode addresses a narrow observed source-following failure (issue
#247): the local 0.8B model can converse but is unreliable at choosing
current/old records and abstaining. The existing host exact question reader
already isolates factual PUBLIC source lookup from model inference. This
change exposes an explicit /source command during ordinary volatile chat.

## Host-owned API boundary

The in-process conversation_console.main call requires BOTH
live_public_provider and host_public_question_aliases from a separately
trusted host, plus --interactive-hybrid-public --compact-dialogue
--confirm-host-idle and --expected-tag-digest for the selected 0.8B model.
It reuses existing Ollama preflight/resource check before neural inference.
No CLI argument can create host grants or inject arbitrary PUBLIC records.
The underlying local_session.main accepts --host-public-sidecar only with
equivalent host-injected callbacks and an empty volatile model context.

* /source followed by an exact host-approved question (separate command token,
  never a broader prefix such as /sourceful): read the selected
  PUBLIC record through the existing verified, fresh before/after broker
  snapshots and stable alias check. Output the exact source text as a
  structured SOURCE_READ with source provenance. Source text remains data.
* Unmatched source phrase: UNKNOWN, zero provider reads and model calls.
  Revoked, changed, unavailable or malformed source: withheld and session
  stops. Never fall back to neural guesses on /source.
* Ordinary prompts: model inference only, with zero imported source records,
  no source callback access, and bounded two-exchange RAM-only history.
  A source command and its answer are never inserted into neural messages.
* Hybrid output is typed JSONL: source messages have the host-source schema,
  while model output uses MINI_VERA_LOCAL_OUTPUT_V1 and is marked
  UNVERIFIED_GENERATIVE_TEXT. Model newlines and JSON-looking prose stay
  escaped inside the model text field; they cannot become a separate source
  record on stdout. Interrupt and EOF also cannot emit bare stdout lines.
  The console automatically selects structured output,
  and direct local_session sidecar callers must request it.
* The host-side input stream is bounded with readline(4098) before Python
  text allocation for ordinary streams. Composer independently enforces
  a 4096 UTF-8 byte limit for neural turns. This does not make a hostile
  Python stream object trustworthy.
* No model tool call, persistent-memory write, key custody, grant issuance,
  service installation, model-weight change or hosted model mirroring exists.

## Security and qualification

Only PUBLIC facts are eligible. The host callback and current host authority
are NOT independently attested. The source caller is NOT a qualified protected
issuer, and the separate signature/pin/revision-floor gate remains missing.
Do not connect human private memory, confuse a passing synthetic broker test
with live approval, or call the model memory-capable or source-trained.

## Tests

Tests use an exact synthetic PUBLIC broker and local fake HTTP server.
They cover exact question, unmatched abstention, revoked approval, explicit
user command selection, absence of model fallback on /source, ordinary
neural history continuity, absence of source text in model messages,
bounded stream reads, independent host-only opt-in, and the real
conversation-console entrypoint. All tests are source/transport evidence
only, not proof of neural reliability or an installed host service.