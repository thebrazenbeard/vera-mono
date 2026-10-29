# Goal 1 QVR outbound-attempt reservation contract

**Status:** independent source review and corrective contract, not an Integration implementation. Applies to the source reviewed at Vera Mono PR #82 head `26271c5d69dee4663e07d4dbcf63efcf033626e8`, where `QualifiedVeraRuntime.consume_local_cognition` calls `journal.require_unused(invocation_id)`, then invokes `transport.generate(...)`, then appends the receipt. Do not edit the Integration-owned branch.

## Reproduced contract gap

The current order is check-unused → outbound call → append. There is no durable state recording that an invocation was reserved before the call. If the transport sends the request and then raises a timeout, the journal may contain no row even though the model server received the request. A retry with the same invocation ID can therefore make a second outbound call. `require_unused` and `append` are separate operations, so concurrent processes can both pass the initial check before either append succeeds. A hash chain cannot represent an attempt that was never written.

A missing completion receipt must mean **outcome unknown**, not “no inference occurred.” A same-user SQLite file and unkeyed event digest do not provide independent custody.

## Required state machine

- `NEW → RESERVED → COMPLETED` for a verified response receipt.
- `NEW → RESERVED → OUTCOME_UNKNOWN` when dispatch may have occurred but the response/receipt is unavailable.
- `RESERVED → REJECTED_PRE_DISPATCH` only if the transport can prove no request crossed the dispatch boundary.
- `OUTCOME_UNKNOWN` is terminal for automatic retry. Reconciliation is a separate audited operation; it must not reuse the original attempt ID or silently convert uncertainty into success/failure.

## Required transaction and dispatch ordering

1. Validate exact permit, selected route, candidate/runtime build, model identity verification level, prompt digest, invocation ID, and bounded budget before dispatch.
2. In a durable atomic transaction, allocate a controller-issued attempt ID, enforce a unique constraint on invocation/attempt identity, record `RESERVED`, route/build bindings, prompt digest, limits, and sequence; commit this transaction **before** any outbound request.
3. Only a transport/gateway that requires this reservation may dispatch. If callers can bypass the gateway, reservation does not prove invocation control.
4. On a successful, validated response, atomically record the response digest and `COMPLETED` receipt. On timeout/disconnect/crash after dispatch may have begun, durably record `OUTCOME_UNKNOWN` (recovery must conservatively classify a surviving `RESERVED` record as unknown).
5. Enforce uniqueness and state transitions under database transaction/locking across processes. Never implement the fence as separate `require_unused` and `append` checks.
6. Measure tokens/calls/elapsed/compute at the trusted transport or gateway; do not count one caller-selected `budget_units` as actual model cost.
7. Keep model-reported tag/digest distinct from verified weight bytes and external attestation. Never mark the latter true based on a self-report or hash string.
8. Test timeout-after-dispatch, crash between reservation and completion, two-process duplicate reservation, same-ID retry, malformed receipt, swapped route/model, and restart recovery. Each uncertain case must fail closed without a second unaccounted dispatch.

## Independent custody boundary

The evaluator's truth, reservation store, signing keys, trusted clock/sequence, and audit retention must be administered outside the candidate's write authority. Use an authenticated evaluator service or separately controlled security principal/host only when that infrastructure is actually provisioned and verified. A subprocess, separate file, branch, signature, or hash on the same user-controlled host is not independent custody.

## Current evidence boundary

This is a corrective acceptance contract, not proof that #82 implements it. The focused QVR source/test run and an intentionally failing timeout/reservation reproducer are recorded separately; no #82 source, service, provider route, credentials, or protected state are modified here.
