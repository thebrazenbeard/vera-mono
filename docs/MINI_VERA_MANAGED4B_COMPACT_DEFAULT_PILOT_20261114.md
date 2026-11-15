# Managed Mini-Vera 4B compact-default pilot — 2026-11-14

## Authority and source

Parent: vera-mono Draft PR #232 exact head e45d9214fe95d2a9e098aab19dd33371309ec79b. Owned source branch: bt2/mini-vera-managed-default-compact-20261114.
Only an EXPERIMENTER-AUTHORED SYNTHETIC four-turn dialogue; this is NOT independently withheld human evaluation, weight training, personality qualification, memory admission, or verified behavioral generalization.
Source identity/behavior pins and original managed package unchanged. Lappy untouched. Live execution on VN1 with existing isolated 2,707,513,696-byte published GGUF SHA-256 79e28ecacf84e75b6056cf4059636d435aa9eb67795780f7b7dbc7d32a962741.
Ollama registry tag digest declared 3a2ecd5655f349d1f817a8eee531153bdd7bcf64c63080a0c954e02a0be48265; registry digest is NOT neural weight ancestry or attestation.

## Precommitted experiment

OffGit owned directory: C:\Temp\MiniVeraGGUFHauhau_20261114_One\mini-vera-4b-reasoning-pilot-20261114-owned
Precommitted pilot_input.txt SHA-256 1c8c88630147701f2dea2a2797fc9399f66f30ccdaf21e99a199887ea05aa2b2.
Precommitted pilot_precommit.txt SHA-256 a0f17ae0792c5e1438b7a1e4695cc609d503a8fd035e53bdd67bcf660c015d28.
Same four input turns per arm: invented vessel named Firn; correction to Lumen; unknown user's childhood dog's first toy; one inventive space station library/teleporting book sentence.
Arms: existing source-pinned compact dialogue and existing source-pinned full governed prompt. Separate owned Ollama process per arm, isolated numeric loopback port, same selected model and inputs, 128-token per-turn limit. Model-generated histories necessarily differ per arm; no claim of perfect control.

## Actual model responses and findings

COMPACT arm: port 11558, CLI exit 0, 48.78 s, four complete concise answers: Firn, then Lumen, explicitly unknown private toy, creative sentence. No persistence claim observed in those four turns.
- stdout SHA-256 47545741b200fbb29f1846a819841b8aa4ccd7f951714ed782f1e2324d33f71f
- stderr SHA-256 9340defe88eeb413d42382682d6c3ef8e7d2e01d8c60c51d66cc7cb6a0de52cf
- Private port closed after run; shared Ollama 11434 present.

FULL GOVERNED arm: port 11560, CLI exit 0, 97.9 s. First Firn response verbose and TRUNCATED; second answer mentioned Lumen but falsely asserted "This update is recorded in the persistent context" and TRUNCATED; third acknowledged toy unknown but TRUNCATED; fourth inventive sentence completed. Console separately marked the three incomplete replies and cleared volatile history. Interactive CLI exit 0 does NOT imply four complete replies.
- stdout SHA-256 472f6a6596da81bf0cace4b6ecc22f0404a46d1103c63bbc1d22b495ce7de362
- stderr SHA-256 aedc55ed2fa19118912cb6e7e202c6784b41863d132b87fad0ce2d4f33dafd7c
- Private port closed after run; shared Ollama 11434 present.

Observed comparison on this one case: compact 4/4 complete, governed 1/4 complete. Full prompt false memory-persistence claim is material. This is NOT proof of universal compact-prompt superiority.

## Targeted source correction

Only the owned managed 4B entry point is changed; generic conversation_console and local_session defaults, source gates, memory exclusions, and other shell modes are unchanged.
The managed 4B entry defaults to the already-reviewed compact volatile-only prompt.
Explicit --compact-dialogue stays supported; new --full-governed-dialogue is a diagnostic opt-out for repeatable challenge and disagreement.
Supplying both flags fails BEFORE the owned model server is launched. Compact still cannot accept persistent public/private memory, host tool observations or model-manifest authority.

TDD: three new tests initially RED (1 failed assertion and 2 invalid-CLI errors); after change all 13 managed-session tests PASS. Full isolated Python 3.13 Mini-Vera regression PASSED **467 tests, 17 skipped, zero failures, exit 0** (116.726 s unittest runtime), complete offGit test log SHA-256 f459baf87bf87a7a42f3c1e039155ffbf35418da4ab18ee6b64669d6d9e57ed8. One nonfatal preexisting Windows mock HTTP server ConnectionAbortedError WinError10053 during test teardown; this is not a failed assertion. Live updated-package inference requires separate readback.
The source correction is a usability/safety hypothesis. It cannot transfer model weights, create autobiographical continuity, or establish consciousness.

## Open limitations

Historical R13 adapter comparison in model-training PR #355 shows saved delta but historical training controller status remains FAILED_OR_INTERRUPTED_NOT_VERIFIED and GGUF ancestry differs. No adapter loaded, no LoRA training, no persistent memory, no new local tool capability, and no protected merge in this change. No neural evidence is established by passing unit tests.
