# DRIVE → MESO / Volition synthetic consumer contract V0

**Status: offline SOURCE-only negative qualification; runtime/effect HOLD.**

Coordination: [BT2 AI psychology #61](https://github.com/thebrazenbeard/bt2/issues/61),
`event_id: bt2_coordination_ai_psychology`.

Files: `research/drive_feedback/synthetic_consumer_review.py` and
`tests/test_drive_synthetic_consumer_contract.py`. The helper is deliberately
outside all installable `packages/` trees. It never imports or calls MESO,
Volition, Pre-Active, PORTAL, a sensor, or a production writer. Its only
decision state is `HOLD`; its optional need candidate is untrusted review data.

## Directly inspected sibling source (2026-10-25)

| Contract | Source head read | Required boundary |
| --- | --- | --- |
| [MESO need observation](https://github.com/thebrazenbeard/meso-crct/blob/main/src/meso_crct/need_observation.py) | `951fe3f8a0089998006e674cfd96918b86fc179f` | Typed `NeedObservation`, externally supplied UTC `AdmissionClock`, caller allowlist, in-memory `NeedObservationLedger` with event/time replay control; caller admission is **not** independent custody. |
| [Volition goal completion](https://github.com/thebrazenbeard/volition/blob/main/src/volition/goal_completion.py) | `53570902890852845599df9b997bad5fa68ac2f3` | Typed `GoalCompletionClaim` with exact current `goal_id`, `choice_id`, *positive* goal revision, target, outcome ID, result receipt, source/evidence references, current-source provenance; caller allowlist is **not** independent custody. |
| [Vera DRIVE feedback](../packages/vera_core/src/vera_core/drive_feedback.py) | `vera-mono/main@d56f057f8fcff5c67093b665a6d90847ba8830ad` | Durable one-SQLite transaction with external verifier **injected** by caller. Nothing authenticates that verifier's host custody. `DriveOutboxItem` is an undelivered snapshot, not a cross-system receipt. |

This review maps only the shared normalized need level `[0,1]`. MESO hedonic
valence `[-0.1, 10]` is an independent pleasure channel, **not** the DRIVE need
level, and is never an adapter target. MESO `NeedAxis.setpoint` and
`sensitivity` remain unchanged. A DRIVE `need_id` matching a MESO label does
not authenticate an external measurement or establish event replay custody.

## Why the current outbox must not be consumed directly

`DriveOutboxItem` contains `event_id`, claim hash, need ID/revision and whether
the DRIVE transaction credited a goal. It omits at least these required
consumer facts:

1. The **historical absolute post-level** for that event. Reading the current
   need projection after a later event returns a different level; even a valid
   old outbox row is not safe to reconstruct from current state.
2. The witness evidence/source authentication and independently administered
   verifier/key/clock custody. A SHA-256 digest, a typed `source_kind`, or a
   synthetic verifier proves none of these.
3. The exact goal/choice identity, the Volition target string, and an explicit
   revision mapping. DRIVE starts a new goal at revision **0**; Volition's
   `GoalCompletionClaim` requires revision **≥1**. Incrementing silently or
   selecting the current target by name would be a fabrication of linkage.
4. Durable per-consumer apply/replay/acknowledgment semantics. DRIVE
   `ack_outbox()` records only a host claim of delivery, not MESO/Volition
   acceptance, and cannot atomically commit independent database stores.

## Executable negative review

`review_synthetic_outbox(...)` takes a caller-supplied DRIVE outbox item,
original observation, admission and integer clock/current-need revision. It
checks the canonical complete-observation hash, IDs, revisions and credit
binding. It suppresses even a synthetic need candidate on missing data, stale
or future observations, replay/HOLD admissions, mismatched event/digest/need,
or later need projection revisions. A matching synthetic specimen produces a
typed data-only `SyntheticNeedCandidate` with `effect_authority=False`, but
**always** returns `status='HOLD'` and never a MESO/Volition admission.

The tests exercise real `DriveFeedbackStore` SQLite receipts using an openly
named **synthetic verifier test double**, old-outbox supersession and replay,
plus malformed and expired negatives. Passing does not establish physical
observation, host runtime installation, cross-process delivery, or model
learning. It is explicitly neither an independent security review nor a
production adapter.

Run from the Vera Mono repository root:

```bash
python -m unittest discover -s tests -p test_drive_synthetic_consumer_contract.py -v
```

## Promotion gates (all HOLD)

- Authenticated external witness source and independent verifier/key custody,
  including revocation, time and signature/replay policy; no model-controlled
  verifier or LLM-produced effect admission.
- Versioned evidence-bearing event envelope with historical measured level,
  exact goal mapping, result receipt, source provenance and revision-domain
  translation reviewed jointly with MESO and Volition owners.
- Crash/restart-safe, idempotent consumer projections and independent
  application acknowledgements for each store; explicit rollback/recovery
  tests, no guessed cross-DB atomicity.
- Host-specific private storage/access policy, Windows ACL/path swap review,
  fault injection, expiry and replay tests, and independent hosted/security
  qualification of the **exact** proposed release artifact.

No deployed model, physical observer, active drive or protected effect is
created by this source-only review.
