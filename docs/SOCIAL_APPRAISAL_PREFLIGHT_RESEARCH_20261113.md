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
