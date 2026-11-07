# Windows Mini-Vera readiness display — source-only

The tiny `tools.mini_vera.windows_readiness` entry point gives a quiet,
non-effectful view of the existing 0.8B Ollama resource preflight. It is not a
launcher and does not confer a model-loading or resource lease capability.

From a trusted Vera Mono checkout on Lappy:

```powershell
python -m tools.mini_vera.windows_readiness --model qwen3.5:0.8b
python -m tools.mini_vera.windows_readiness --model qwen3.5:0.8b --json
```

It only calls the existing bounded `ollama_preflight.probe`, which reads
Windows physical free RAM and local Ollama `/api/tags`, `/api/ps`. **No POST,
model download, service launch, model load, credential lookup, private memory,
or local filesystem write occurs.** It does not accept `--execute`.

The output distinguishes:

- `RESOURCE_REFUSED`: observed resources fail conservative model/RAM checks;
  exit code 2, no model inference.
- `COLD_MODEL_NOT_AUTHORIZED`: selected model is installed but nonresident;
  this display never grants a cold load.
- `RESOURCE_OBSERVED_NO_HOST_LEASE`: point-in-time model/RAM checks pass,
  **without** a host-exclusive lease or proof that CPU/disk/user workloads
  are safe. No inference is launched.
- `UNKNOWN_PREFLIGHT_STATUS`: an unfamiliar source contract fails closed.

Every output reports `host_lease: NOT_BOUND`, `launch_allowed: false`,
`model_inference_calls: 0` and
`cpu_disk_workload_qualification: NOT_PERFORMED`. The launcher cannot claim
an authenticated production host grant; PR #201 currently documents that gap.
The Ollama digest remains a server declaration rather than model tensor
attestation, and reviewed code pins are not signed host binary provenance.

The intended usage is to display why no neural inference can safely run on a
busy Lappy, and to preserve a clear separation between HOST_PROBE and
MODEL_INFERENCE. All tests run with synthetic RAM/Ollama reports and are
**source tests**, not evidence of behavior on the real machine.

Historical `D:\VERA\models\vera.kcpps` is not read or executed. Its obsolete
`C:\VERA` model location and automatic launch/tunnel flags are incompatible
with this governed readiness path.
