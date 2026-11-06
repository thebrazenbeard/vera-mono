# Presence V2: dormant source-and-proposal vertical slice

Status: **isolated scratch candidate; not installed, registered, activated, deployed, merged, or runtime-qualified**. This file is a design/test handoff, not an authority receipt.

This first V2 slice adds exactly two pure Python entry points in `vera_core.presence_v2` without modifying or registering the fixed stdio MCP Presence V1 ABI:

- `presence_capabilities_v2()` returns a fresh, read-only-to-the-caller JSON-compatible **fixed source inventory**. Its two entries are `pre_active_observation` and `conations_appraisal`; both are marked `SOURCE_INSPECTED`, `available_to_route=false`, and `UNKNOWN` for provider install, activation, runtime probe and behavioral qualification. The isolated router itself reports `host_binding=NOT_INSTALLED`.
- `presence_propose_v2(observation, *, opt_in=False)` requires explicit Boolean opt-in and exactly four typed fixture fields: `origin=SYNTHETIC_TEST_FIXTURE`, `subject=Vera`, `kind=PENDING_WORK|NO_PENDING_WORK`, and a bounded opaque `event_id`. It returns either `PROPOSED_ONLY` with the static action label `REQUEST_HOST_REVIEW_OF_WORK_FRONTIER`, or `NO_PROPOSAL`. Both have `effect=NONE`, `authority=NONE`, `persistence=NONE`, and explicit lack of consent/runtime binding.

The two pinned source-review inputs (not implied installed states) were:

- [`thebrazenbeard/pre-active@e306c251`](https://github.com/thebrazenbeard/pre-active/tree/e306c251a4da44125ee58c311a35120084da8e4b)
- [`thebrazenbeard/conations@73295039`](https://github.com/thebrazenbeard/conations/tree/73295039e7a1710c5bb73666e665cef80c40aa5d)

The runtime manifest deliberately exposes only the short project slugs
(`pre-active`, `conations`) and exact inspected source commits. This document
is the provenance mapping to the canonical GitHub repository identities; the
runtime does not contain cross-repository URLs or full sibling-repository IDs.
Its JSON key is `source_repository_slug`, not a claim of a globally qualified
repository identifier. The provenance document is not installed in the wheel,
so a consumer cannot derive full repository provenance from the runtime alone.

The Conations **main** source pinned above is `history_only`. A separate agent has opened [Conations Draft PR #12](https://github.com/thebrazenbeard/conations/pull/12) with an unmerged current-state candidate. That draft is **not imported, bundled, certified, installed, or treated as main**. The proposal's synthetic appraisal label is not a measured present conation, desire, feeling, consent, autobiographical memory, or Brigit state. No `brigit-unbound`, empathy, sexuality, pleasure, volition, meso-crct, memory, or other donor is loaded, and none gains identity or effect authority by source presence. A future adapter must have a distinct host-owned allowlist, exact source/build digest, explicit release binding, provider authorization and runtime qualification. No generic module loading, command invocation, network access, file I/O, or external state mutation is present in this slice.

## Evidence ladder and first executable oracle

Source inspection, built package, installed provider, active binding, observed runtime consumption, and behavior qualification are separate states. There is no automatic promotion between them. The current evidence is **SOURCE/CODE + isolated local TEST only**. A Python unit test is not host proof.

Run in a Python 3.12 environment with pytest:

```bash
python -m pytest -q tests/test_presence_v2.py
```

Expected invariant checks: immutable-to-caller manifest, no source-to-host promotion, proposal off by default, synthetic pending-work/no-work outcomes, strict exact input schema, identity-isolation rejection, desire/consent spoofing rejection, no caller-supplied path/command/URL/host/install/qualification, and bounded event IDs. Results must be newly executed for each source change.

## Deliberate limits

This is **not** an MCP tool exposed in any running Presence Bridge, autonomous scheduling, a persisted intent queue, local model review, a qualified Conations integration, or canonical memory admission. `opt_in=True` only allows an in-process synthetic test transformation; it is not user consent for an effect. All host binding/policy/admission work requires separately owned implementation and test evidence. The existing V1 stdio tools remain untouched.
