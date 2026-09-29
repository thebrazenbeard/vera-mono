# CCB Base retry-dedupe exact-head review

Subject: thebrazenbeard/ccb-core main at exact head 42e4409dff3baee4acb63b48c9f64c7367a4fd22.

## Verification

The repository uses a src-layout and its README requires installing the test extra before pytest. A raw uninstalled pytest invocation produced import-collection errors and is not treated as repository failure.

Under the repository's declared environment (`pip install -e .[test]`), exact-head local verification completed with 192 passed.

## Surviving delta

Vera Coordination already owns append-only receipted events, actor/workstream permission checks, lineage, digest-chained SQLite persistence, temporal controls, and provider-neutral repository contracts. CCB is therefore not imported as another coordination runtime.

The missing Vera mechanism is the short-window retry gate. Current Vera event identity includes event sequence, so an exact immediate retry becomes a second valid event. CoordinationBus already states that retry idempotency remains a runtime/storage gate.

CCB contributes four useful invariants:
- a short deterministic retry window;
- explicit monotonic-time regression rejection;
- rollback of a reservation if downstream admission fails;
- serialization of dedupe reservation with downstream admission so a concurrent retry cannot race an unresolved first attempt.

## Rejected donor semantic: payload-only cross-route dedupe

CCB intentionally derives its V1 idempotency key from canonical payload bytes. Its own exact-head tests require the same payload to dedupe even when audience/route context changes.

That rule is not safe for Vera Coordination. In Vera, target workstream, thread, event status, lineage references, payload, and reference data are semantically material. Two posts carrying the same payload to different targets are not duplicates.

Vera therefore computes the retry key from the actor workstream plus the entire canonical CoordinationEventDraft.

## Bounded integration

The adapted guard is process-local and wraps only coordination_post. It does not alter the persistent event ID, does not claim durable replay suppression after restart, and does not claim exactly-once delivery or target consumption.

A failed/denied post releases the exact reservation. A successful confirmed write retains it for the configured short window. The same exact post is valid again outside the window.

## Deferred CCB deltas

The following remain independently reviewable and were not imported in this work unit:
- durable dead-letter queue and applicability/replay state;
- priority queue and priority-zero dispatch;
- node leases/subscriptions/routing;
- routed/dropped/DLQ accounting;
- durable 60-second heartbeat scheduling.

These may be useful later, but bundling them into retry idempotency would create unnecessary ownership and state coupling.

## Non-equivalences

retry suppression != exactly-once delivery
process-local dedupe != durable restart dedupe
write confirmed != target consumed
retry key != event ID
same payload != same coordination event
suppression != authorization

Claim ceiling: bounded source mechanism and local tests only; no provider deployment, delivery qualification, or runtime activation claim.