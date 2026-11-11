# Goal 1 — FULL QVR → exact Gateway #95 → exact Evaluator V2 #87

Status: **SOURCE + PHYSICAL EXPERIMENT PASS / PRODUCTION HOLD**. UTC date 2026-10-24.

## Frozen source and reproducible subject

- Vera Mono `main@64c4a756a8c4d6fc791787de80303f7ee0f64869`.
- Vera-owned research PR #89 after implementation `ac200eb47407f5f24d4bb884c622890600916586` before adding this evidence document.
- Frozen Integration #82 `26271c5d69dee4663e07d4dbcf63efcf033626e8`: exact three PR82 modules staged by hash in clean build context.
- Frozen Integration #95 `7c191b2a97063ccc5821f3f274fb4f5e47ff99ed`: actual `sole_route.py`, SHA256 `ba20f64cf92dc6e58f4c82cecbe85963a6895ab97d5a3d4abfa961708945558d`.
- Frozen Malaphor #87 `d3784d9886a5cb071aed38fbe6b91f8ac1d6bbcf`: actual `terminal_v2.py` SHA256 `153aed3f37e013f9fbb213af2539a1984bebf3086a1d77544d189e0c8104d187` and `reservation_status_contract.py` SHA256 `eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc`.
- Lappy experimental image `sha256:61f0481288d22df1071745463d83cedbf29489f8d71338dd09f9110357405c94`, Python 3.12.15, whole QVR inside networkless Docker; source staged from PR89's earlier clean commit with exact #82 source (image not rebuilt to include host-side adapter; host adapter is a separate process).
- Exact host-side change: `gateway_terminal_text_bridge.py` captures a single PR95 backend `ModelObservation` while GatewayDispatch writes durable reservation, claims through exact #87 helper, generates and stores original signed terminal bytes. Bridge reopens PR95 terminal, invokes actual #87 V2 verifier against a pinned gateway key and separately supplied claim-evidence verifier, compares the signed response hash to the captured text, and **only then** hands bounded text over stdio to the container QVR. No second backend invocation and no direct learner model-network path. The independent custodian is a fake in this research test and no effect qualification is inferred.

## Physical Lappy acceptance

One isolated replayable test entrypoint: `python -m research.goal1_acceptance_bridge.full_qvr_gateway_v2_physical_probe --repo <PR89-checkout-with-PR95-PR87-commits-fetched> --image-id <immutable-local-image-id> --volume-prefix <fresh-goal1-qvr-volume-name>`.

Initial run failed closed due to a mistyped exact V2 source SHA before dispatch. Python subprocess `git show` SHA256 verification identified one wrong character; repaired pin at `505c62b9...`. No bypass of pin. A subsequent four-case attempt failed before Docker in case four because unsafe underscore volume name was correctly rejected by the named-volume regex; test-only name normalized without widening validation. Fresh `goal1-qvr-v2-20261024e` case volumes used for successful final execution.

Final physical result: process exit **0**; four cases:

| Case | PR95 gateway durable state | Actual PR87 V2 verifier called | Backend calls (synthetic) | QVR cold journal | Result |
| --- | --- | ---: | ---: | ---: | --- |
| Simulated independently claimed COMPLETED | COMPLETED | 1 | 1 | 1 | Original signed bytes and digest accepted, response handed to QVR |
| Denied/mismatched evaluator claim | RESERVED | 0 | 0 | 0 | No backend call or QVR text |
| Simulated model timeout | OUTCOME_UNKNOWN | 0 | 1 (raised) | 0 | Non-scoring, no QVR text |
| Substituted gateway public key | COMPLETED | 1 (rejected) | 1 | 0 | Signature failure prevented QVR text |

Fresh QVR Docker processes attempted same identity again after each negative; gateway-local durable reservation blocked new claim/backend, QVR journal remained empty. At no point did any fake backend call issue an Ollama request or independent claim service request.

Lappy Windows Python 3.14 focused tests in this exact PR89 source `test_goal1_full_qvr_containment_probe.py`, `test_goal1_full_qvr_stdio_contract.py`, `test_goal1_gateway_terminal_text_bridge.py`: **39 passed, one pre-existing pytest-asyncio deprecation warning**. The TDD sequence first observed 6 failures from missing bridge implementation; green 6/6. A second negative test first failed (plain object improperly accepted as evaluator claim verifier); corrected and green 7/7. VN2 Linux Python 3.12.3 compiled `research/goal1_acceptance_bridge` and the added bridge test successfully at exact source head `ac200eb47407f5f24d4bb884c622890600916586`; Docker unavailable there, no independent physical positive inferred.

## Hostile review and remaining blockers

> **SUSTAINED:** Same-process fake evaluator claim responses and fake `verify_claim_evidence` do **not** prove atomic independently administered CLAIMED custody, even though the real #87 verifier runs. No independently authenticated and durable claim retrieval is deployed or tested here.
>
> **SUSTAINED:** The host can still reach Ollama at `127.0.0.1:11434` and could run another unrestricted QVR. The selected production service/cutover identity has not been inspected at this new physical test head.
>
> **SUSTAINED:** The text bridge is a callback injected on the host, not a sealed production gateway composition root. Caller-controlled pinned signer bytes/evidence verifier cannot themselves prove trust separation; independent provisioning/readback required.
>
> **SUSTAINED:** Gateway status COMPLETED and ephemeral signed terminal are not model-weight byte attestation, independently attested tokens/duration, private holdout, or measured learning. Docker named volume is host-controlled, not an independent witness.
>
> **SUSTAINED:** Research Docker build base manifest and package versions are pinned, but wheel hashes, reproducible image provenance, current selected executable route and runtime service identity remain to qualify.

Next smallest real frontier: physically join the outside broker to **an independently operated evaluator claim service using Integration's actual mTLS client**, with evaluator custody and pinned trust configured by its responsible owner. Use original signed V2 bytes + independently authenticated durable claim readback; real provider inference only after those controls pass. Do not make service/ACL/key/production changes or merge main on the strength of this experiment.

No production deployment, paid compute, model call, controlled provider mutation, canonical memory, or main merge. PR #89 stays Draft/HOLD. Blotter central URL/token absent from current Lappy/VN1/VN2 shells; do not represent GitHub coordination as authenticated central Blotter writer activity.
