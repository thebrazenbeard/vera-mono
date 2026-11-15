# Social A/B raw-record parser ambiguity: fail-closed audit

Date: 2026-11-15. Source-only candidate stacked on Vera Mono Draft PR #214.
Base: `d8a7166267e62adddc7f11b0a6170a5e480a8335`.
No runtime install, model weights, memory admission, release or deployment.

## Reproduction and correction

The original transfer auditor accepted additional undeclared fields in each JSONL row,
including `model_response_authenticated: true`. Standard `json.loads`
silently accepted duplicate keys and returned the *last* response value;
the resulting row could pass all existing structural checks.
This is a provenance and downstream-consumer ambiguity, not proof of model forgery.

New synthetic hostile cases were committed only after a RED run:
`2 failed, 8 passed, 13 subtests passed; RED_EXIT=1` under Python 3.12.
The duplicate-key test failed because the strict parser did not exist;
the undeclared-attestation test failed because no error was raised.

The minimal repair uses duplicate-key-rejecting JSON parsing for fixture and
results, rejects non-standard JSON numeric constants, and rejects row keys outside
the runner's declared schema. A new parser rejects ambiguous raw bytes before
they become lossy dictionaries. The auditor still reports
`model_response_authenticated=false` and does not claim semantic validity.

## Validation / hard holds

Focused Lappy Python 3.12: 10 passed, 13 subtests, exit 0.
Original pinned Qwen3.5:0.8B and Qwen3:4B seed79 raw 48-row logs each
re-audited successfully against independently specified earlier SHA256 values,
with no changes to either archive; both report unauthenticated model responses.
Initial full-suite invocation: 1259 passed, 106 skipped, **7 failed**,
due to missing `portfolio_runtime` from subprocess PYTHONPATH (five cases)
and four archived review JSONL files silently CRLF-converted on Windows
checkout (two cases). The existing Git blob bytes were unchanged.
All four working-copy files were reconstructed from the exact original
Git blobs only after proving their differences were line endings.
`evaluations/.gitattributes` adds four filename-scoped `-text` entries;
staging the four artifacts changed no tracked blob.

With all `packages/*/src` paths and `scripts` on PYTHONPATH and the
four pinned bytes faithfully checked out, targeted re-run: 39 passed,
14 subtests, exit 0. Fresh full Lappy Python3.12 suite: **1266 passed,
106 skipped, 365 subtests passed**, one pre-existing collection warning,
exit 0, 112.01 seconds. Python3.14 focused: 10 passed, 1 unrelated
deprecation warning, exit0; compilation and diff checks exit0.
All are local tests, not independent behavioral qualification.

> Duplicate-key rejection prevents one ambiguous parsing route. An actor
> controlling the generator, expected digest, and audit arguments can still
> fabricate the whole record. No trusted model-execution attestation exists.

The experiments use fictional records only. No personal conversations,
consent, identity, current preferences, or private self-appraisal were copied.
