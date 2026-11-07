# Mini-Vera 0.8B Ollama launcher — resource preflight, not qualification

`tools/mini_vera/ollama_preflight.py` is an optional, zero-dependency Windows
launcher for the existing `local_session.py` bounded conversation shell. It
selects an installed Ollama alias, checks its server-declared manifest digest
and size, reads physical available RAM from Windows, checks loaded models and
rejects known contention before any model-loading chat request.

It is a *small runtime integration*, not a newly trained neural model,
permanent memory, model attestation, voice qualification, identity transfer,
training receipt or host-owned exclusive resource lease.

## What it actually checks

- Only canonical numeric loopback HTTP `/v1` endpoints are accepted.
- The preflight makes **only GET `/api/tags` and GET `/api/ps`** with a 2-second
  timeout and 64-KiB response cap. No prompt or private memory is sent.
- The selected model must be installed, have a well-formed server-declared tag
  digest and fit a **2 GiB Ollama model-size ceiling** for this 0.8B path.
- A *foreign resident Ollama model* causes refusal, even when RAM appears free.
- A model already resident needs at least **1 GiB Windows free physical RAM**;
  a cold load needs at least **model-size + 2 GiB** plus explicit cold-load
  authorization. These are conservative heuristics, not empirical peak RAM,
  GPU/VRAM or token-throughput validation.
- Real inference additionally needs `--execute`, a single `--prompt`, and a
  **fresh** `--host-idle-confirmed` operator assertion. Nothing starts
  Ollama, evicts a model or downloads weights automatically.

## Use on Lappy (from an isolated, verified checkout)

Read-only, no model load or inference:

```powershell
python -m tools.mini_vera.ollama_preflight --model qwen3.5:0.8b
```

If an earlier read-only probe yields `RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE`
and a person independently verifies the host is idle and a model is already
resident, **one opt-in inference**:

```powershell
python -m tools.mini_vera.ollama_preflight --model qwen3.5:0.8b --execute --host-idle-confirmed --prompt "Hello, Vera"
```

To permit a model that is *not* already resident, also require
`--allow-cold-load`. This can allocate several GiB of RAM: do **not** use
it during another user's work, on an unqualified or memory-constrained host,
or as a substitute for a real workload lease. To pin a previously independently
recorded Ollama tag manifest digest, provide `--expected-tag-digest` with 64
lowercase hex characters. A digest reported by the same server is merely a
**server declaration**, not proof of resident tensors or training ancestry.

The integrated local session checks identity/behavior resources against
**reviewed SHA-256 constants in Python source**, independently of the bytes
it just read. It refuses modified JSON files before inference. This does
**not** authenticate the installed Python code against a host-owned trust
anchor: an attacker who can replace both code and source can replace the
expected hashes. The launcher makes no claim about personal continuity or
transfer of ChatGPT identity.

## Receipt / refusal semantics

- `RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE` means the *observed* model and RAM
  pass those heuristics at the instant queried; unrelated processes may race.
- `COLD_MODEL_NOT_AUTHORIZED_TO_LOAD` means the memory estimate passes but
  the server does not currently have that model resident; no chat is sent.
- `REFUSED` means validation failed, a competing Ollama model is resident,
  model size/digest is invalid, or host RAM is too low. No chat is sent.

The receipt always marks `exclusive_host_lease: false`,
`identity_provenance: REVIEWED_CODE_SHA_PINS_NOT_HOST_ATTESTED`
and `digest_evidence: SERVER_DECLARED_NOT_WEIGHT_ATTESTATION`.

Tests use isolated synthetic Ollama HTTP fixtures and injected RAM samples;
they demonstrate **source behavior only**. They do not constitute Lappy host
qualification, real neural inference, GPU residency attestation, or blind
behavioral comparison with a bare Qwen model.
