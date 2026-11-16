# Mini-Vera: interactive host-approved PUBLIC question loop

Status: SOURCE-ONLY HOST-EMBEDDED INTERACTIVE CLIENT. No qualified independent host memory issuer, no live human-private memory, and no neural qualification.

Parent: thebrazenbeard/vera-mono draft PR #248 exact head 02ce3af77889e8e00e866d909810c661b8fc433c. This feature is stacked on that existing draft. The separate 0.8B neural failures and formatting confounds remain in issue #247.

## Behavior and authority

The existing in-process conversation_console.main entrypoint accepts live_public_provider=trusted_host_callback and host_public_question_aliases=literal_question_to_record_id_map. It now supports an additional host-embedded flag --interactive-host-questions when no one-shot --prompt is present. The same separately trusted host provides the authority-bearing callable and bounded exact question allowlist; this module **cannot issue** a PUBLIC grant, sign memory, select an exact record on its own, or attest an issuer.

Interactive turns are prompted on stderr; each answer is one JSON object on stdout, preserving machine-readable distinction between SOURCE_READ and UNKNOWN, source digests/revision, origin, not-independently-attested authority, and model_http_calls:0, writes:0. /quit, /exit and EOF stop the loop without source or model calls. Unapproved question strings are UNKNOWN, not prompts to a model or unrestricted search.

Each nonempty user question calls local_session.main with exactly one structured source-only prompt and the injected host callback. That delegates to the existing exact question allowlist and exact PUBLIC record reader. There is **no cache or reuse** of previous approved answers. A revocation between turns must refuse the next source read; earlier printed answers cannot be withdrawn. Host authority can also change after the last check; this is not a process-level lock.

## Bounded controls

- The new flag is rejected if the Python caller did not inject host_public_question_aliases.
- Interactive mode is rejected if paired with --prompt, model override, resource confirmation, cold-load permission, model-preflight --check, candidate-4B mode, compact neural dialogue, or other previously forbidden options.
- The older one-shot host-approved question path retains its existing schema and option restrictions.
- No direct CLI option supplies an authority key, imports a grant, permits model HTTP, opens a file-backed private memory source, persists a chat, or modifies host settings.

The correct test scope is synthetic PUBLIC ledger data with a separately constructed in-process provider. A Python runner without a qualified trusted issuer **cannot** deploy this as approved personal memory. No installation of independent issuer/protected signer/revision floor follows from running the code.

## Measured source-only tests

1. New top-level interactive client behavior test was created first, and exited **1 / FAIL** because --interactive-host-questions did not yet exist (argparse exit 2 inside assertion). After implementation it passed unchanged (**0 / OK**).
2. Controlled synthetic PUBLIC SQLite ledger tests cover approved answer then unapproved UNKNOWN, zero Ollama preflight/model HTTP, revocation after a successful first turn withholding the second answer, CLI direct option rejection, conflicting model options, and /quit, /exit, EOF.
3. Focused question suite after implementation: **16 tests, exit 0** on VN1.
4. Full VN1 Mini-Vera regression: **519 tests, 17 skipped, OK**, 123.324 seconds; stderr SHA256 3452701E44738D76FC1F479ECE2ADA6888124B441BBA6D0D1DBD6EB76EEDE3F4. The existing nonfatal Windows socket abort test fixture trace occurred. Lappy cross-host verification is a separate requirement.

## Hostile residual challenge

> An externally compromised or unqualified host can forge its own callback, signing material, mapping, or revision sequence, even if the interactive loop rechecks on every turn. The deterministic source reader cannot cure a bad trust root. A local model can still hallucinate in separate neural sessions. This loop provides approved **source lookup**, not neural episodic memory, learning, model identity, autonomous tool use, or independent human-private memory qualification.

Do not merge or deploy as private memory on the strength of these synthetic tests. Do not treat a clean GitHub workflow as a physical host authorization probe.
## Bounded stdin hardening (stacked follow-up)

Interactive host questions now use a 162-character maximum read from stdin, sufficient only for the existing 160-character ASCII allowlist and a two-character Windows CRLF. Previously unbounded builtins.input() called readline(-1), allocating the entire oversized upstream line before validation. Oversized or unterminated-at-limit input fails closed with stderr and exit 2 before any provider or model access, even for untrusted piped stdin. Exactly 160 ASCII question characters plus CRLF remain permitted (unapproved matches return UNKNOWN). This is a **resource bound**, not an issuer, neural, privacy, or revocation guarantee. The normal neural console input path is unchanged.

TDD: a newly added 100000-character piped input behavioral test failed RED before the fix because stdin.readline(-1) was called rather than the 162-character bound (unittest exit 1). After the input change and replacement of interactive-test builtins.input mocks with actual text stdin fixtures, 18/18 focused questions passed. Full VN1 Python3.13 regression: 521 tests, 17 skipped, OK, 123.895 seconds; stderr SHA256 55527A2092D93AEC6696192797D34D7E84A112D8BD489405F0801C08BCADBE48. One known nonfatal Windows socketserver WinError 10053 test-fixture trace. This does not qualify an external host issuer or neural behavior. Do not infer a complete installed runtime from this patch.
