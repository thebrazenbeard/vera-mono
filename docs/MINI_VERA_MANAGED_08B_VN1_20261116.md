# Mini-Vera managed 0.8B - actual VN1 CPU conversation (2026-11-16)

## Scope
Source-only improvement stacked on thebrazenbeard/vera-mono draft PR #252, parent ccbf86cc734a68534fed8777ecf9f04cf15dab76. Isolated VN1 branch bt2/mini-vera-managed-08b-20261116.

Explicit new CLI flag --small-08b selects the existing <=2 GiB console/model preflight instead of --candidate-4b. Without this flag, original 2-3 GiB managed candidate mode and compact default are unchanged. It keeps existing three opt-in permissions, tag digest comparison, private numeric loopback, no downloads or model changes, CPU-only server environment, Windows Job kill-on-close, volatile two-pair chat and source/persistence safeguards. The preflight is not an exclusive lease or model weight attestation.

## Observed environment and model
Windows VERA-NODE-1, current user VERA-NODE-1\Vera, Intel i7-6770HQ (8 logical threads), CPU load 1%, free RAM 11.66 GiB before the first live run. Local pre-existing installed Ollama and model qwen3.5:0.8b in C:\Users\Vera\.ollama\models. Observed registry tag digest de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c; expected manifest model, projector and draft layers total 1,322,057,600 bytes, before metadata. Registry digest is not tensor attestation.

Lappy was NOT accessed because a shared suspected host-trust/reimage hold remains open; no compromise is asserted as established.

## Actual local inference on VN1
1. One-turn CPU-only owned Ollama on unused port 11674, fictional prompt named spacecraft Lumen. Returned: "Vera> Lumen is the name of the fictional spacecraft you are referring to." Exit 0; 16.82 seconds. Stdout SHA256 D3AD8E8F3AD2F801CE8D97DD5994D28158CE192B8E71A37DE3082A0590074158; stderr SHA256 AEFCDCB2866E7308D42A21DA74461AE89923C2CB8FD7A0C670D1F6B96870E8FD. Private port closed after exit; no residual owned Ollama server detected.
2. Two-turn CPU-only session on unused port 11675. Invented ship named Firn; user corrected it to Lumen; then /quit. Actual stdout included "Vera> Firn." then "Vera> Lumen.". Exit 0; 8.37 seconds. Stdout SHA256 20FD8C45B011603498A6727EDD37A6AA2D75E19A3C533C231E439C8C11B67A1B; stderr SHA256 CE77AAC78F0E05935AFFE1CD3559F29639FC32F310B2E3346CCAD11187F14AF6. Private port closed after exit.

Both trials used the source-pinned CLI:
python -B -m tools.mini_vera.managed_ollama_session --ollama-exe C:\Users\Vera\AppData\Local\Programs\Ollama\ollama.exe --models-root C:\Users\Vera\.ollama\models --port 11674 --model qwen3.5:0.8b --expected-tag-digest de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c --small-08b --start-owned-server --confirm-host-idle --allow-cold-load --compact-dialogue --prompt "For this fictional exercise, I named the spacecraft Lumen. What is its name? Answer in a single sentence."

Port and workload checks must be repeated fresh; no autostart service is being proposed.

## Tests
New fake owned-session test was RED before CLI support, expected exit0 observed exit2 (assertion failure, exit1). Identical test GREEN after implementation, exit0. Six affected VN1 test modules (managed launcher, candidate4b console, Ollama preflight, ordinary console, local session, Windows owned job) ran 92 tests, 4 skipped, zero failures, exit0. Focused log SHA256 0854003607F3A5AEE55AC0645AB859D941C791201DAF7FF9B23277498BB07EF2. A known mock HTTP server WinError10053 appeared during teardown, not a failing assertion. Full VN1 suite first attempted under system Python 3.13, which lacks cryptography: 529 tests, 3 failures, 4 errors, 37 skipped, exit1; all 7 failures/errors were due to the Ed25519 dependency being absent. No production code correction was made for that interpreter setup. Under the existing isolated venv-mini-vera-candidate4b Python with cryptography 48.0.1, exact full discovery command python -B -m unittest discover -s tests -p test_mini_vera*.py -q returned 536 tests, 17 skipped, zero failures, exit0 in 132.632s (outer elapsed 133.503s). Full venv stderr SHA256 0BFC7DC2360F70328653761610C849FEE6726DC9EBA3A977BF10E44381C9F150; nonfatal Windows WinError10053 mock HTTP teardown occurred. No dependencies installed or changed. Hosted CI remains a separate gate.

## Limitations
No copy of ChatGPT neural weights, no LoRA, no qualification of Vera identity, no durable/private memory, no trained long-term learning, no host issuer, no independent reviewer, no Lappy installation, no protected merge, no shared service restart and no external trust grant. The PR #252 memory-write claim guard remains a narrow presentation filter. Current qualified Lantern runtime backend UNKNOWN.
