# Mini-Vera real 4B revision recall prompt diagnostic — 2026-11-15

Evidence: developer-visible synthetic PUBLIC trial, source inspection and real local neural inference. No independently held-out grading or user-memory installation.

## Source and host
Parent: Vera Mono OPEN DRAFT PR #236, head ebbb418d9a3faaffb5e33a501c5cf14321976ccb, stacked on PR #235.
Host: VERA-NODE-1, isolated owned offGit processes and files under C:\Temp\MiniVeraGGUFHauhau_20261114_One, not Lappy.
Model: isolated Ollama alias mini-vera-hauhau-q4:source-probe-20261114; existing GGUF SHA256 79e28ecacf84e75b6056cf4059636d435aa9eb67795780f7b7dbc7d32a962741. Tag registry digest 3a2ecd5655f349d1f817a8eee531153bdd7bcf64c63080a0c954e02a0be48265 is not tensor/runtime attestation.
Decoding: CPU-only, temperature 0, seed 20261106, max tokens 256, Ollama reasoning_effort none, loopback only. Shared Ollama unchanged.

## Falsification of original wording
The real five-process durable revision canary produced two corrected-current exact FAILs (UNKNOWN both), one correct empty-memory control, one stale-record pre-inference refusal and one revoked-approval pre-inference refusal.
Source-only composer probe: approved revision-current present; superseded and private absent; empty control no records; no model call. Receipt SHA256 e434be28ec8a4c3dc9d097c4e0c894f0ced0f41f4532bf8ff41ad46b569f1058.
Live loopback interceptor validated exact approved synthetic corrected value in both HTTP requests before forwarding to owned model; no obsolete/private bytes. Real model nevertheless returned UNKNOWN both times. Receipt SHA256 6c5d4c991d8dbd8a62f98262f62c2c52619dbc949abb102fda3d906347460823. Thus simple request omission is falsified for this run.

## Five-arm real model prompt ablation
Same one generated synthetic value, exact 4B GGUF, randomized five request arms, same decoding:
- Direct request, minimal system: exact PASS.
- Direct request, actual Mini-Vera system: exact PASS.
- JSON reference request, minimal system: exact PASS.
- JSON reference with original Mini-Vera question: FAIL, UNKNOWN.
- JSON reference with rephrased Mini-Vera question: exact PASS.

Prompt-ablation classification receipt SHA256 432441f139e8562030afa89a7eebad26166db506553de563be600739e0d693b1. The test is developer-visible, one sample per arm, not proof of robust generalization, training or blind assessment.

## Minimal source repair
Change only revision_restart_canary.PROMPT to the wording successful in the real JSON-runtime A/B arm. Explicitly locate revision-current in project_context_untrusted; extract its exact synthetic code as DATA; reserve UNKNOWN for absent record. No ledger projection, privacy, revocation, tool, model weight, user memory or host grant changed.
## Test method and evidence separation
A source regression test checks the exact conditional wording. Existing fake-HTTP integration tests verify state projection, worker isolation and fail-closed boundaries, not neural recall. New synthetic real inference, with fresh random token and two corrected current processes, is required as independent behavioral retest before any model-success claim.

Hostile qualifier: a single passing model response to improved wording can be overfitting. Do not reclassify SOURCE checks or fake-server tests as neural qualification. The model alias and GGUF hash do not prove a trained Vera. This proposal is draft-only until tests and hosted CI complete.

No protected merge, production deployment, paid compute, private memory admission, shared process restart or credential change.
