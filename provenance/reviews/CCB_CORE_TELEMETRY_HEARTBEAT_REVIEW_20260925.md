# CCB Base telemetry/heartbeat review

Subject: thebrazenbeard/ccb-core main at exact head 42e4409dff3baee4acb63b48c9f64c7367a4fd22.

Exact-head donor verification under its declared test environment: 192 passed.

## Useful mechanism

CCB makes routing health observable through durable routed/dropped/DLQ counters and scheduled heartbeat records. The transferable idea is that coordination needs a compact operational health view in addition to individual records.

## Why Vera does not copy CCB telemetry storage

Vera's qualified coordination path already has an integrity-checked CoordinationCommandJournal containing every bound command and every recorded result, including result_class, database_write_confirmed, event identity, and unresolved bindings.

Adding a second telemetry database would create a derived-state synchronization problem: journal evidence and counters could disagree. Vera therefore computes the health projection directly from the journal after verify_integrity().

Derived signals:
- total command bindings;
- recorded results;
- bindings without recorded results;
- confirmed database writes;
- results without confirmed writes;
- deterministic counts by result class;
- the journal projection digest that anchors the view.

## Heartbeat decision

CCB's durable 60-second heartbeat is appropriate for its continuously running Radar host. Vera Mono source does not itself prove that a persistent host is installed or selected. Installing a heartbeat scheduler here would therefore manufacture runtime continuity and introduce a sink/external-effect seam that is not currently justified.

No heartbeat scheduler or sink is imported. A future persistent host may consume the derived health projection and own heartbeat emission under its own runtime/effect contract.

## Failure semantics

An unresolved binding means result evidence is absent. It does not by itself prove failure, retryability, or permission to repeat the command.

A confirmed database write proves only the journaled coordination write. It does not prove target consumption, external effect, behavioral success, or system health.

## Non-equivalences

command health != runtime health
confirmed write != target consumption
result COMPLETE != behavioral success
unresolved binding != retry authority
health counter != currentness
health projection != independent attestation

Claim ceiling: source-level derived diagnostic projection only. No persistent-host, heartbeat, route, deployment, or behavioral qualification claim.