# Local social model generation: fail-closed response metadata boundary

Date: 2026-11-16. Source-only candidate stacked on vera-mono Draft PR #241,
which is itself stacked on Draft PR #214. No runtime or model installation.

## Observed weakness and hostile test

Before this change, the A/B generator used the requested model tag and a
separately fetched /api/tags digest when constructing every output JSONL row,
but accepted /api/chat content without checking that the response claimed the
same model. A mocked /api/chat response claiming a different model was
written under the requested tag, demonstrating false attribution potential.
Other fields (done marker, assistant role, done_reason, token count, and
unexpected tool_calls) were not validated on receipt.

Test-first baseline Python 3.12: **14 failed, 3 passed, exit 1**; failures
include the actual generator silently logging a wrong-model response and
the absence of a strict reply-validation function. These were synthetic
transport substitutions, not proof Ollama actually substituted models.

## Bounded correction

The generator now checks the response's self-reported model against selected
tag, done is exactly true, done_reason is stop or length, eval_count is a
nonnegative integer, message.role is assistant, content is nonempty, and
no tool calls were emitted. It validates before writing each row.
The existing output schema is preserved; historical logs remain untouched.

Focused green: **19 tests and 26 subtests passed**, Python 3.12, exit 0.
The six-row synthetic positive control uses a fake local transport; it
asserts that no field pretending independent model authentication is logged.

## Direct host observation and limits

A real local HTTP POST to Lappy's 127.0.0.1:11434/api/chat using installed
qwen3.5:0.8b and a fictional correction prompt reported model
qwen3.5:0.8b, done=true, done_reason=stop, message.role=assistant, and
eval_count=36. That is observation of a local endpoint, not independent
attestation. Its answer stated Kira was the corrected pilot.

The tag digest read from /api/tags was
de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c.
Neither a matching self-reported tag nor a locally reported digest proves
specific weights or independent generation custody. A malicious endpoint
could forge both. No external trust anchor, cross-host witness, independent
review, semantic scoring, personal data, canonical memory, consent, native
installation, merge, or protected change was established.

## Verification

Fresh complete Lappy Windows Python 3.12 suite with all packages/*/src and
scripts on PYTHONPATH: **1270 passed, 106 skipped, 378 subtests passed**,
one preexisting PytestCollectionWarning, exit 0, 133.07 seconds. Four more
tests passed than the parent candidate; neither this full-suite result nor
the live local API sample proves neural social-judgment improvement.
Existing archived raw model logs are not modified.
