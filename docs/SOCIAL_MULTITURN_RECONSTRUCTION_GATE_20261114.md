# Synthetic multi-turn audit: source reconstruction gate (2026-11-14)

Status: source-only change on existing unmerged Vera Mono Draft PR #214.
No private conversations, actual current Vera self-report, deployment, canonical
memory write, host credential, protected action or paid model inference.

## Falsifier (observed RED)
The original auditor checked fixture/generation SHA256 references, A/B swap
symmetry, label balance and duplicate identities. It did **not** derive each
blinded response from the actual recorded model generation. Thus adversarial
fictional data could replace the third response of case one in both blinded
packets; recomputing the judge packet-reference digests preserved a passing audit.
It also accepted a forged model digest in the mapping. These are deterministic
synthetic input mutations, not evidence of a real attack on a deployed system.

Reproduction (Windows Lappy Python 3.12):
`py -3.12 -m pytest tests/test_social_multiturn_review_contract.py -q -k 'fabricated_blind_answer or mapping_digest_tampering' --basetemp D:\\VERA\\experiments\\social-review-red2-20261114`
Result before implementation: 2 FAILED, 15 deselected, exit1,
both tests failing because ValueError was NOT raised.

## Implementation
`scripts/audit_social_multiturn_review.py` now calls the existing
`prepare_social_multiturn_blind.build_pairs` on recorded generations and exact
fixture bytes, and compares full case/turn answer packets, deterministic
A/B assignment, both model digests, and the exact reversed A/B packet.

## Observed GREEN and baseline replay
The same two adversarial tests pass only after rejecting the mutations.
Focused complete module, Python 3.12: 17 passed, 4 subtests, exit0;
Python 3.12 -O: 17 passed, 4 subtests, exit0 (pytest optimization
warning); Python 3.14: 17 passed, exit0 (pytest-asyncio warning).
Full correctly configured Python3.12 Vera Mono suite with all repository
packages/*/src on PYTHONPATH and isolated D: basetemp: **1185 passed,
104 skipped, 280 subtests passed, one existing PytestCollectionWarning,
FULL_EXIT=0**, 147.82s. Original 12-case/72-generated-response
benchmark replay: exit0;
8/8 comparable reviewer decisions still selected the same letter
despite swapped answers; 0 position-invariant concrete model wins.
The original response data, judge votes, and baseline result were unchanged.

## Trust ceiling and hostile challenge
Reconstruction checks *consistency* of recorded source, mapping and packets.
It does not cryptographically authenticate the data generator, independent
reviewer, hosted model identity, host key, or the accuracy of judge decisions.
A colluding actor with write access to every source and digest reference could
rewrite all records consistently. A biased reviewer can still supply valid
yet unreliable judgments. Therefore the existing behavioral qualification
hold remains, and no runtime, autonomy, memory or personhood conclusion follows.

## Next action
Require separately owned immutable review evidence, independent A/B reviewer,
multiple seeds, rubric-anchored human or rigorously validated judgments,
then a real opt-in consumer behind Vera control release/currentness authority.
