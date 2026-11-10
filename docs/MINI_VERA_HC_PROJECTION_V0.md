# HC coalition → Mini-Vera public-context projection (source candidate)

Status: **SOURCE ONLY / NOT INSTALLED / NO MODEL CALLS**.

This is a narrow adapter, deliberately **not** another hyperconnectome or
reasoning scheduler. The source-first reference at `hc-brain` main
`4caabd3334f0d24e4d52123d9541928489a36536` already implements
`runtime/cognitive_core/cognitive_loop.py` coalitions, semantic arbitration,
current memory and metacognitive traces. `vera-mono` already has a Rezon
deterministic scheduler and a governed memory subsystem. The project source
`HYPERCONNECTOME_RUNTIME_MODEL.md` is conceptual, not live HC authority.

`tools/mini_vera/hc_projection.py` only accepts a **caller-exported bounded
snapshot** of an HC coalition and candidate records. It requires the HC's
actual member names, active cycle, typed epistemic class and memory projection
status, source-text SHA, privacy and effect boundary. It provides:

- no direct sibling-repository import (Vera Mono remains self-contained);
- no identity or tool-policy records from an HC text proposal;
- no nonpublic, stale, ambiguous or expired record promotion;
- contested current claims removed together regardless of salience;
- deterministic, bounded data-only records with typed origins, reproducible
  projection digest and explicit coalition-ablation controls;
- format-compatible `PUBLIC` / `WORKING_PROJECT` records for an **external
  host** to review, independently admit, revision-bind and HMAC-sign for the
  already-merged `tools/mini_vera/compose.py` from PR #194.

The adapter **does not create** a `MINI_VERA_OPERATOR_STATE_V1` state envelope,
know the host's secret, sign or attest source bytes, call a model, admit memory,
infer an actual current system state, apply weights, modify identity, execute a
tool, or grant effect authority. A SHA over caller-supplied bytes checks local
consistency; it is not external source authentication. Neither coalition
membership nor salience makes a claim true or grants permission. The exact
score only orders otherwise-admissible records under a bounded capacity.

The optional `ablate_members` is a **simulation of removing declared coalition
roles** for context-selection tests, not an HC runtime lesion or an identity
change. Removing `current memory storage` suppresses public-memory candidates;
removing `volitions-conations` suppresses goal candidates. Identity and effect
policy remain owned by the composer/host and cannot be ablated by this adapter.

## Contract and limitations

The input follows a deliberately narrow JSON-compatible projection of HC's
`Coalition`, `EpistemicClass` and `ProjectionStatus` types. The bridge from an
actually running HC instance, its trustworthy host currentness/provenance, and
its signer **do not exist here**. Names/digests/epoch/source refs are declared
by the caller. Source tests prove only local fail-closed projection behavior.

An HC `PUBLIC_MEMORY` candidate requires `current memory storage`; `GOAL`
requires `volitions-conations`; `UNCERTAINTY` requires both `semantics` and
`integration-arbitration`. Contradictory current records with the same
`(kind, claim_key)` are excluded together; a higher salience value cannot
resolve them. This is a conservative projection rule, **not** general semantic
equivalence or full provenance-lineage reconciliation. Future authenticated
bridges must supply explicit state-currentness, scope, source-recency and
consent evidence independently.

## Source-only checks

```shell
python -m unittest discover -s tests -p 'test_mini_vera_hc_projection.py' -q
python -O -m unittest discover -s tests -p 'test_mini_vera_hc_projection.py' -q
```

Tests include a signature round trip through the existing composer
`verify_state`, deliberately using a synthetic key to establish **format
compatibility only**. This is not an installed host bridge or signed live
state. No model, host, data provider, API or credentials are contacted.
