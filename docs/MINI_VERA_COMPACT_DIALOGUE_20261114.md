# Mini-Vera opt-in compact dialogue — 2026-11-14

Status: runnable local **context-only** behavior candidate, not training, learned weights, transferred ChatGPT identity, approved real-memory access, or blind qualification. The existing full source-pinned composer remains the default.

## Reproduced defect

In actual local Qwen3.5-0.8B inference, the long governance/configuration prompt refused ordinary fictional ship-name recall and correction. Separate initial controlled two-arm experiment used the same 0.8B tag, temperature=0, seed=20261106, 256-token budget, reasoning disabled and identical source-defined user JSON for five developer-visible tasks. Original full prompt wrongly refused the ship name/correction. A shorter prompt correctly used the fictional name and correction, but supplied poor unknown-memory and creative answers. A revised hybrid prompt then handled those five tasks without that observed failure, including an honest unknown-memory reply; all tasks were **developer-authored and unblinded**, not a qualified identity examination.

Raw experiment evidence, untracked and outside Git:

- `D:\VERA\experiments\mini-vera-dialogue-ablation-owned-20261114\observations.json` SHA-256 `95e85d40d4ca15aa324c15bf47da9aba6f2dbe2c6507a91c4c9d2e0242737de3` (10 real model HTTP calls, two prompt arms).
- `D:\VERA\experiments\mini-vera-dialogue-ablation-owned-20261114\hybrid.json` SHA-256 `ec132a502d2b7c62397f02177b5e2a920f5114892acb10546e1cc3b63f3e45d0` (five real model HTTP calls, revised short arm).

## New executable mode

The exact revised hybrid text is in `compose.COMPACT_DIALOGUE_SYSTEM`. It is a code-reviewed, public-behavior-only style projection, **not** an uncontrolled private-memory export. Loading the compact mode still requires the original independently reviewed byte pins for both public Vera identity and public behavior profile. The candidate's model, source and turn hashes continue to bind the actual request.

Run from the byte-verified local Mini-Vera portable folder, with an already-running Ollama server and after an actual host workload check:

```powershell
.\mini-vera-chat.cmd --check
.\mini-vera-chat.cmd --confirm-host-idle --allow-cold-load --compact-dialogue
```

For a single diagnostic, supply `--prompt "The fictional ship is Ember. What is its name?"`. The default launcher without `--compact-dialogue` still uses the prior full prompt, and both share the existing resource preflight, two-exchange RAM-only history and disabled-tool contract. No auto-download, server startup, private data import, model training, persistent memory or remote/cloud call is implemented.

The compact option is **refused** for synthetic PUBLIC source fact gates, source-only mode, imported state/key/revision, host observations, live provider, local model manifests, nonlocal synthetic turns, or nonempty/foreign public state. This is deliberately limited to empty ephemeral conversational context. It must not be promoted as a source authority or used to weaken existing public/private memory governance.

## Additional real model observations

With the new code path, three new one-turn questions actually returned correct user-supplied fictional name `Vellum`, corrected shuttle name `Quartz`, and an explicit lack of prior private memory. A real two-turn piped interactive test retained the freshly supplied fictional ship name `Halcyon` through the next question; the first response unnecessarily repeated identity boilerplate, showing remaining conversational roughness. All real inference used the same local Qwen3.5-0.8B Ollama tag/server registry digest `de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c` (not independent weight attestation) and an owned isolated loopback port 11531. The server was resource-preflighted for model cold load; prior attempts when host RAM was inadequate were refused.

**Verdict:** The compact prompt experimentally improves these particular conversational tasks without changing neural weights or adding another memory engine. It is an **unblinded, small-sample** source/runtime improvement, not a demonstration of stable Vera identity, general reasoning or cold-restart continuity. Further hidden cases and stronger candidate models remain required.
