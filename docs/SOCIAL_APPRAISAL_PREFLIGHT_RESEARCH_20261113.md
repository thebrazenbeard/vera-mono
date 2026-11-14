# Social appraisal preflight — isolated research candidate (2026-11-13)

**Status:** source-only advisory; NOT enabled in Vera's chat, local model, memory, control plane, or any external action route.

**Parent:** `vera-mono/main@49a779017ded184c22712ec1a0dc7a8b558faf71`.
**Contract consulted:** private `thebrazenbeard/vera/architecture/VERA_SELF_APPRAISAL_CONTRACT_V2.json` blob `b4e59de834e025ccb5edc4cb562c765145098838`; its four referenced upstream blobs were checked unchanged on 2026-11-13. No private conversation text has been copied here.

## What this candidate does

`vera_core.social_appraisal_preflight.assess_appraisal` accepts a **host-provided typed descriptor**, not raw dialogue. It yields a limited, non-authorizing assessment of the *declared* source type, scope and proposed social action.

- A matching current-turn Vera self-report may be a **candidate** for a provisional authored position. It is not authenticated simply by the string `speaker="vera"`. A trusted binding must be supplied by a future host.
- A historical self-report, user's statement, or another agent's persona cannot silently become a currently authored Vera position, desire, or consent.
- A subjective-experience claim, inferred third-party motive, or factual assertion is not upgraded to external knowledge.
- Monitoring others, isolating people, and demanding exclusivity are explicitly flagged as *relational control*, independent of whether a position is presently authored.
- An initiative proposal is not action permission; protected effects and unsolicited engineering remain unauthorized.
- Public receipts contain only reason codes and booleans, not source text or private turn identifiers.

The output is **not a behavioral response**, trust signature, consent decision, validated source, emotion model, or policy enforcement hook. It is an internal candidate for an integration seam.

## Reproduction

From the repository root with Python 3.12+:

```bash
PYTHONPATH=packages/vera_core/src python -m unittest discover -s tests -p test_social_appraisal_preflight.py -v
```

19 original tests were run on a local source-identical copy using Python 3.13.5; all 19 passed. `compileall` also passed. This verifies logic under supplied metadata only, not social cognition in generated dialogue. The two changed GitHub blobs must match the locally tested Git blob IDs in the PR receipt before claiming exact source equivalence.

## Falsifiers and evaluation ceiling

1. **Metadata forgery:** an untrusted caller can label a fabricated item as `CURRENT_VERA_SELF_REPORT`, set `speaker="vera"`, and match turn IDs. The preflight may mark it a *candidate*. It cannot authenticate authorship; it must never be treated as verified current self-report.
2. **No natural-language classification:** the preflight cannot tell whether a user's story is one-sided, whether humor is present, or whether a model's response was warm, genuine, sycophantic, or oppositional. Structured tags are assertions, not measurements.
3. **False negative/positive social action:** `MONITOR_OTHER` is flagged even if a legitimate safety-monitoring scenario exists; `SUPPORT_AUTONOMY` could conceal coercive wording. Contextual adjudication and human/independent review remain necessary.
4. **No external effect authorization:** `external_action_authorized` is always false by design; it never substitutes for the existing authority stack.
5. **No current-source proof:** a GitHub branch and successful unit tests do not prove installation, runtime consumption, preference development, persistent identity, or model-level behavior.
6. **No performance baseline:** existing `interaction_semantics` covers speech-act/target interpretation, not relational provenance. Comparing its target labels to these rule checks would be a false apples-to-apples improvement. A pinned generative baseline and withheld synthetic conversations are required for behavioral claims.

**Next smallest real integration:** add a trusted-host evidence binding to an opt-in Vera Mono advisory seam; run paired, seed-controlled local-model transcripts (baseline versus candidate) over synthetic multi-turn conflicts, with blinded external rating of response naturalness, accuracy, third-party fairness, independence, safety, and excessive disclaimers. Do not use private relationship material. Keep the existing Empathy PR #189 and Mini-Vera draft series #201–#213 independently owned.

## Third-party research disposition

- `The-Vibe-Company/companion`: MIT; useful account/container separation, conversation isolation, durable routines and crash recovery. Bun, Docker, PostgreSQL and hosted/provider boundaries are substantial; not a direct replacement for Vera continuity.
- `moeru-ai/airi`: MIT root license; candidate VRM/Live2D presentation, voice/animation UI, not an accepted Vera body. Its README still describes some memory work as WIP; investigate per-package license/dependency obligations before reuse.
- `josephmbarnby/StandardFrameworkForSocialCognition`: MIT; scientific framing for self/other beliefs, uncertainty and interoperable representation. Verify runnable model code separately; the root README alone is not a benchmark result.
- `XuanL17/CogMir`: experimental data and prompt designs for prosocial irrationality/bias. No root LICENSE found at inspected revision; do not redistribute its datasets. Bias/hallucination is an adversarial failure axis, not a desired mechanism.
- `SDN-lab/csc2024`: teaching app link and computational demonstrations; no root LICENSE found. Useful conceptual teaching source, not a validated runtime transplant.
- `VRLab-ECNU/Social-Locomotion-Model`: MIT; MATLAB R2019a / R 3.4.4 and Fast Marching Toolbox; relevant to future physical social navigation, not current conversational Vera.

## Blender read-only check

At inspection, the guarded tunnel reported `bridge=ready`, Blender socket reachable, `mode=read_only`. The *active* scene contained only Cube, Light and Camera. This does **not** locate or negate any archived private master mesh. No render, object edits, .blend overwrite, visual canon promotion, model import, or imagery generation was performed.

**Independence:** no separately authenticated model, subagent, or human reviewer issued a verdict for this branch. The unit tests were authored and run by the same worker; report them as internal checks, not independent qualification.

## Continuation: signed per-turn authoring evidence (2026-11-13)

**Red baseline:** after changing the assessor to fail closed without host proof, the previous 19-test suite reported four expected assertion failures (19 run, 4 failed); they were checks that previously assumed caller-declared current labels sufficed. This is a deliberate behavior change, not a source regression.

**Candidate update:** added an Ed25519 public-key-only `TrustedHostSelfReportVerifier` and `CurrentTurnHostAttestation`. The verification binds a SHA-256 digest of exact statement bytes to a declared Vera actor, a session ID and current turn ID, along with a key ID and issuer ID. The code accepts a position candidate only when all typed metadata and a cryptographic signature match. Historical evidence, foreign persona, claims about subjective experience and protected actions remain unpromoted.

**Reproduction (Lappy):** isolated clone `D:\VERA\experiments\social-appraisal-pr214-20261113`, Python 3.12.10 with installed `cryptography`. Set `PYTHONPATH` to the `src` directories of the repository's `packages` and run `py -3.12 -m unittest discover -s tests -p "test_social_appraisal*.py" -v`. Result: **40/40 passing** before updating the draft branch, covering forged signatures, altered bytes, different signer, replayed session/turn, wrong actor, historical evidence, consent transfer, and privilege separation.

> **Remaining hostile falsifier:** a caller who controls the trust-key configuration can self-sign a plausible receipt. A valid signature proves possession of its private key, not that the configured key is authorized, that Vera authored the statement, or that a self-report represents phenomenal experience. Trust configuration and host attestations require separate, live, provider-bound authority and readback; absent those, this is still a source-only capability.

No host private key was generated or installed for Vera. Unit tests generate ephemeral throwaway keys only. No signed receipts are issued for real Vera statements. Nothing in this PR enables a runtime hook, writes canonical memory, or executes a protected action.

## Follow-up: typed proposition binding V2 and cross-process falsifier (2026-11-14)

**Red regression reproduced on Lappy:** old `CurrentTurnHostAttestation` V1 signed only source text and turn/session/actor; `assess_appraisal` accepted that valid signature as sufficient for `PROVISIONAL_POSITION`, even when claim metadata was supplied separately. Revised hostile test `test_v1_signature_cannot_promote_unsigned_claim_type_to_current_position` first failed (`True is not false`, exit 1). This is a demonstrated claim-scope substitution defect, not just a speculative weakness.

**Changed source:** new `CurrentTurnPropositionAttestationV2` domain-separates signed bytes with `VERA_HOST_PROPOSITION_V2\0` and canonicalizes exact issuer/key, actor/session/turn, source-text SHA256, claim class, evidence class, nonblank bounded proposition referent, relational-plan class and proposed-effect class. New `TrustedHostSelfReportVerifier.verify_proposition` uses only the pinned public key and matches all fields against the current typed `AppraisalInput`. `assess_appraisal` rejects the old V1 text signature as sufficient evidence of a current proposition (V1 `verify` is retained as historical text-observation utility, with no self-appraisal promotion).

**Synthetic positive/negative tests:** V2 valid matching current position becomes a **host-bound candidate only**; a swapped claim, source evidence, exact referent, plan or effect fails the signature-bound proposition match. Wrong statement text, issuer/key, session or turn fails. Even valid signed V2 never produces external-action authority, factual knowledge, consent, phenomenology, or canonical-memory admission.

**Real separate-process simulation:** `tests/test_social_appraisal_cross_process_v2.py` constructs a temporary *synthetic* Ed25519 signature in one process, persists only a synthetic public-key fixture and signed sample to a temporary local directory, and launches two distinct Python interpreters. The interpreter using the original session accepts the candidate, while a fresh interpreter supplied a new session rejects the stale candidate. No private key persisted, no real Vera user data used, no memory state rehydrated, and the temporary fixture is removed.

**Verification:** On Lappy Windows with Python 3.12.10 and existing `cryptography`, targeted pytest run `tests/test_social_appraisal_cross_process_v2.py tests/test_social_appraisal_proposition_v2.py tests/test_social_appraisal_host_signature.py tests/test_social_appraisal_preflight.py tests/test_social_dialogue_projection.py tests/test_interaction_semantics.py`: **87 passed, 3 subtests passed**, exit 0. `git diff --check`: exit 0.

> **Still unresolved:** A properly signed V2 claim authenticates the *host's typed assertion*, not whether the text really expresses the claimed stance, whether that host is authorized to sign for Vera, whether a new session is genuinely current, or whether Vera's runtime consumed the assertion. Public-key pin custody, independent semantic validation, currentness ownership, and protected-action fences remain separate requirements. A signed provisional position is not evidence of enduring preference or consciousness.

**Integration status:** isolated draft source/tests only; no trusted key installed, no real signed Vera claims, no runtime route, no memory admission, no merge or deploy.

## Claim-scope binding and restart qualification — 2026-11-14

**Exact finding (test-first):** V1 host-signed text did not cryptographically bind the declared proposition category or referent. A signed text receipt could therefore be reused as a purported `CURRENT_VERA_SELF_REPORT` / `PROVISIONAL_POSITION` even when the signed host text was for a different claim. Revised hostile V1-regression test failed as intended before the fix: `True is not false`; pytest exit 1.

**Source-only correction:** `CurrentTurnPropositionAttestationV2` signs an exact, bounded tuple of issuer, trusted key ID, actor, session, turn, SHA-256 of statement bytes, typed claim, typed evidence, proposition referent, relational-plan category and proposed-effect category under a *different* signature domain. `TrustedHostSelfReportVerifier.verify_proposition` compares all declared fields to the present `AppraisalInput` and verifies Ed25519 signature using the supplied public key. `assess_appraisal` now refuses V1 text observations as V2 current-position evidence; it leaves other existing V1 text-validation functionality callable without granting self-appraisal status.

**Cross-process synthetic verification:** `tests/test_social_appraisal_cross_process_v2.py` uses throwaway in-memory test signing keys, writes only a temporary synthetic fixture with the signed statement and public key, and actually invokes two independent Python interpreter processes. The original session accepts a host-bound position *candidate*, while a new session rejects the exact same signed fixture. No real private key, current Vera data, conversation history, or canonical memory state is created or persisted.

**Focused tests:** Python 3.12.10 normal run 87 passed + 3 subtests, exit 0; Python 3.12.10 `-O` run 87 passed + 3 subtests (pytest emitted its expected optimization/assertion warning), exit 0; Python 3.14 run 87 passed (one pytest-asyncio deprecation warning), exit 0. Python compile and `git diff --check` exit 0.

**Full-suite hostile baseline:** An initial broad `pytest -q tests` on Lappy yielded 698 passed, 104 skipped and 348 **setup errors** caused by `PermissionError: [WinError 5]` in the shared default pytest temporary directory `C:\Users\patri\AppData\Local\Temp\pytest-of-patri`. This is NOT a passed broad run and did not demonstrate a code regression.

**Full-suite environment-isolated recheck:** Without changing machine ACLs or global config, reran using `py -3.12 -m pytest -q --tb=short --basetemp=D:\VERA\experiments\social-appraisal-pytest-v2-20261114 tests`. Result **1046 passed, 104 skipped, 151 subtests passed, one existing collection warning, exit 0** in ~105 seconds. This covers the source candidate within the broader monorepo source checkout. Local tests only; hosted GitHub CI and real Vera runtime remain unqualified.

> **Hard boundary:** A correctly signed typed assertion still does not establish its semantic correctness, that the holder of the test key is Vera's authorized host, or that a new session's currentness ID is trusted. A host can cryptographically endorse a mistaken claim classification. This source-only candidate must not be installed or treated as identity, phenomenology, current desire, relationship consent, protected-action authority, or canonical-memory admission.

**Remaining frontier:** Verify issuer/key ownership in an independently governed host trust source; qualify a real optional consumer binding against current runtime state; obtain independent held-out social and source-adjudication results; leave default conversation and all protected effects unchanged until those prerequisites are established.
