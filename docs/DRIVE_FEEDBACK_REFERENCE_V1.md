# DRIVE Feedback Reference V1 — Inert Outcome Custody Substrate

**Status: source-only, NOT runtime-installed, NOT an independent witness.**

Coordination: [BT2 AI psychology issue #61](https://github.com/thebrazenbeard/bt2/issues/61),
`event_id: bt2_coordination_ai_psychology`.

Implementation: `packages/vera_core/src/vera_core/drive_feedback.py`.
Tests: `tests/test_drive_feedback.py` (`python -m unittest discover -s tests -p test_drive_feedback.py -v`).

## Why this exists

An agent claiming to have performed an action does **not** mean a need was
physically corrected, nor that a goal is complete. A callback, action result,
synthetic projection, `source_kind='observer'`, SHA-256 hash, or apparently
plausible need delta is **not** independent measurement. Before measured
outcomes affect motivation or completion, the host needs an independently
custodied observation, unique effect identity, exact current-goal binding,
durable replay control, and one atomic commit.

This reference implements the durable decision **after** an outside qualified
host supplies a verifier. It does not itself supply credentials, a sensor, a
credential vault, an authenticated transport, or a runtime integration.

## Reference invariants

| Boundary | V1 behavior |
| --- | --- |
| No externally supplied verifier | `HOLD`, no receipt, projection, or outbox write |
| Claim says observer or includes digest | Still untrusted until host verifier returns structurally bound `DriveWitness`; callback may lie |
| Absolute need measurement | `normalized` level in [0,1], never additive caller-provided `claimed_need_change` |
| Need freshness | Exact `need_id` and expected need revision; `BEGIN EXCLUSIVE` blocks readers before post-lock admission freshness checks |
| Effect replay | Unique event, attempt, physical effect, evidence digest, witness attestation ID, and `(observer_id, source_sequence)` |
| Observer clock | Fresh bounded timestamp; source sequences strictly increasing; later sequence cannot move observation time backwards |
| Goal satisfaction | Same need, goal ID, choice ID, goal revision, `ACTIVE` and not vetoed, verified `EFFECT`, actual level improvement and target reached |
| Replaced/vetoed goal | Fresh verified need-only measurement can still update need; **cannot** credit the replacement or vetoed goal |
| Failed/no-op effect | Cannot claim increased need level; does not satisfy goal |
| Atomicity | Receipt, need projection, optional exact goal credit, and outbox in one SQLite `BEGIN EXCLUSIVE` admission transaction |
| Crash/replay | Precommit failure rolls back every table; postcommit restart has one durable pending outbox row; replay reports `goal_credit=False` |
| Concurrent first-open | Schema and `user_version` committed together under `BEGIN IMMEDIATE`; an interrupted bootstrap can safely retry |
| Database schema drift | Reject unknown version, partial/unversioned preexisting database, missing constraints/index, and foreign tables/triggers/views |
| Feedback freshness | Validate before verifier, after exclusive reader/writer lock acquisition, and immediately before commit; no SQLite reader-lock wait follows the final clock check. Scheduler and filesystem latency are not time-attested |
| POSIX state privacy | Require an owner-only state directory, private database file, no path symlinks, and DELETE journal mode; reject rather than alter permissions on existing user files |
| Runtime side effects | None. No `QualifiedVeraRuntime` registration, device action, host automation, or message dispatch |

The witness binding is only a structural gate for an explicitly **host-owned**
`DriveWitnessVerifier` protocol. Injecting a model-controlled or compromised
verifier would defeat the trust assumption. A digest proves no physical fact
without independently custodied evidence and key/source validation.

## Source contract

- `DriveObservation` carries immutable event/attempt/physical-effect/observer
  identities, observer sequence, measurement timestamp, exact need revision,
  post-measurement absolute level, goal/choice/revision binding, effect status,
  and evidence digest.
- `DriveWitness` binds verifier-issued attestation identity to the complete
  SHA-256 of the observation, the physical observer identity, and verification
  time. **The host** must authenticate the source and attestation itself.
- `DriveFeedbackStore.admit(...)` returns `HOLD`, `ADMITTED`, or `REPLAY_NOOP`
  with whether *this invocation* created goal credit. A replay never claims a
  new credit, even if its historical receipt originally credited a goal.
- `NeedProjection` is absolute level + revision. `GoalProjection` holds exact
  goal/choice identity, revision, target, state, and credited event.
- `DriveOutboxItem` is the pending-record view returned to consumers. The
  SQLite `drive_outbox.delivered` column, **not a `DriveOutboxItem` field**,
  records the host's claimed delivery; it does not attest that another process
  applied the projection. Consumers require independent idempotency.
  `pending_outbox(limit=...)` reads oldest undelivered rows in bounded batches
  of 1 to 1000; consumers acknowledge individual events after handling them.

For safety, `admit()` requires a currently fresh observation and host verifier
**even for historical replays**. A stale replay yields `HOLD` rather than a
new or historical credit. Pending outbox rows remain durable and independently
readable after restart; outbox recovery must not depend on re-admitting old
observations.

POSIX state directories newly created by the reference have mode `0700` and
new database files `0600`; existing owner/group/world-readable directories
or database files are rejected, not silently modified. SQLite rollback journals
remain within that private directory. Symlinked path components are refused.
These mode/path checks assume a trusted host filesystem and do **not** solve
same-owner adversarial file replacement races, untrusted mount points, or
Windows ACL enforcement. A Windows live host must supply and verify its own
private storage ACL policy before installation.

`register_need`, `register_goal`, `replace_goal`, and `veto_goal` are **reference
fixture/bootstrap/admin methods**. They are not authenticated user-goal or
sensor ingestion APIs. Never expose them as unguarded model tools.

## Why a single database

SQLite atomicity covers one database transaction, not independent MESO,
Volition, behavior, and message-bus database files. V1 therefore keeps all
four projections in one self-contained file. It does **not** claim an atomic
commit across existing separate stores. A future runtime adapter must either
declare this single store authoritative and project via an idempotent outbox,
or design a separately reviewed transactional coordination protocol.

## Before any live installation

1. Specify and implement independently auditable observer/witness identity,
   source authentication, attestation replay protection and key custody outside
   model control. Host callback injection alone does not satisfy this gate.
2. Map MESO absolute need-axis semantics and goal/choice/revision/veto
   invariants to an explicit versioned adapter; never import sibling runtimes
   directly into the self-contained Qualified Vera runtime.
3. Define consumer idempotency, end-to-end outbox delivery/acknowledgment,
   database backup/migration/recovery and operational availability gates.
4. Run cross-process concurrency, power-loss/recovery, corruption, malicious
   observer, revoked credential, and integration tests against a real host.
5. Obtain explicit architecture and security review before runtime wiring.

No credentials, deployments, schema migrations on deployed databases, or
protected device effects are performed by this reference.
