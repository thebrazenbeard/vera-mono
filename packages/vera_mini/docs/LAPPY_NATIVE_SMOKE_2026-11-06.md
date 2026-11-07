# Mini-Vera Lappy native smoke receipt — 2026-11-06 local / 2026-11-07 UTC

Evidence class: **REAL_SYSTEM_PROBE**, limited to the commands and observed
outputs recorded below. This is not a security audit, independent attestation,
neural inference qualification, or continuous-service installation.

## Bound artifacts and host

- GitHub draft PR: `thebrazenbeard/vera-mono#193`, branch
  `bt2/original-mini-vera-local-20261106`, exact source commit
  `12b3a6f9fc64be95815b34dd64295d6ace5852ce`.
- Final release zipapp SHA-256:
  `0a2171752e813264a07b691919672d510cf01f46b5f71c913da337d8fd83e2e9`.
- Target: connected Executor Lappy Dedicated device `Lappy`; Windows hostname
  `LAPPY`, Python Windows launcher `C:\Windows\py.exe`, `py -3 --version`
  returned Python 3.14.5.
- Host query returned physical RAM 34,069,069,824 bytes; named GPU
  `NVIDIA GeForce RTX 3050 Laptop GPU`, reported AdapterRAM 4,293,918,720
  bytes, plus integrated Intel GPU. No VRAM inference allocation was measured.
- `D:\VERA` existed; `D:` reported 456,932,388,864 bytes free during probe.
  No model service was stopped, restarted or installed.

## First run exposed a real Windows bug

An earlier release SHA
`533216ec5bb1e026929248168d5e3952d76f2c0b80371236e61885cccd7ee287`
ran the Mini-Vera identity CLI successfully. An actual Windows temporary
`build_brainpack` on an explicitly selected 15-byte source completed, but
`BrainPack.verify()` raised:

`BrainPackError: invalid physical manifest or blob directory`

at `mini_vera/brainpack.py` line 463 of that release. Native Windows
`Path.lstat()` on the generated manifest showed a regular file, one hardlink,
408 bytes; the `blobs` entry was a directory. The code's `DirEntry.stat()`
directory-enumeration metadata check was too strict for Windows.

## Patched artifact and result

The Windows fallback now gathers actual path `lstat()` metadata for physical
package enumeration. On the same Windows host, a new clean temporary package
of a 15-byte UTF-8 text source was built, reopened and verified:

```
sha256=0a2171752e813264a07b691919672d510cf01f46b5f71c913da337d8fd83e2e9
{'verified_documents': 1, 'source_bytes': 15}
```

After SHA verification, the previous Mini-Vera file was preserved with an
atomic Windows `System.IO.File.Replace` backup and the new verified zipapp
was installed at:

`D:\VERA\mini-vera\mini-vera-trained.pyz`

The previous release remained at:

`D:\VERA\mini-vera\mini-vera-trained-prev-20261106.pyz`

Readback confirmed exact current and backup SHA-256 values above,
`mini-vera 0.2.0` from `--version`, and this source-backed identity reply:

> I'm Mini-Vera, an original local software facsimile inspired by Patrick's
> Vera project. I can work with information deliberately provided to this
> runtime, but I can't claim to be a restored ChatGPT identity or to remember
> conversations I haven't received.

Only the base64 transfer staging files and the exact temporary directory
created by the earlier failed smoke were removed afterwards. The installed
binary and recoverable previous version were preserved.

## What this did **not** establish

- The CPU-only stdlib identity and BrainPack smoke is not a generative-model
  benchmark; no GPU memory, token/sec, load curve or 3 GB artifact was tested.
- No malicious NTFS junction, alternate data stream, simultaneous path-swap,
  adversarial concurrent writer, crash durability or revocation exercise ran
  on Windows. Source tests and a positive native smoke do not prove those.
- No authenticated STM, DeepMemoryStorage or SemanticAtlas provider readback
  ran on Lappy. The opt-in evidence bridge is still an API, not an installation.
- The frozen OOD learned-intent measurement was executed in the scratch Python
  environment, not independently adjudicated or replicated on Lappy.
- No long-running process, service, scheduled task, shared port or network
  endpoint was started.
