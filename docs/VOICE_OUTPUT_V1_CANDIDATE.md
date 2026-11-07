# Vera voice output V1 — candidate only

**Status:** source and synthetic unit tests only until a Windows host proves the
actual output. This is not a deployed voice service, reusable voice identity,
trained model, Suno voice extraction, or Matrix integration.

## The smallest lawful and operationally independent slice

`vera_core.voice_output_v1` exposes a bounded `SpeechRequest`, a default-denied
`render_sapi_wave`, and a `SpeechWave` containing in-memory WAV data and a
content digest. It invokes **Windows PowerShell 5.1** and the locally installed
**System.Speech** synthesis API. A caller must explicitly pass
`allow_local_synthesis=True`; this flag represents *caller intent*, not verified
authority. The function refuses genuine execution on non-Windows hosts.

This adapter does not write files, play sound, start a service, send a Matrix
message, open a socket, enumerate devices, select a default voice, or download
a model. A third-party installed SAPI voice engine has its own effects and
license; offline end-to-end behavior is not established by this wrapper.
The caller must specify an installed SAPI voice name. The unit-test runner
injection is explicitly marked `INJECTED_RUNNER_UNATTESTED`, never real audio
qualification. A real Windows SAPI result is only local WAV evidence, not
proof that a human heard it or that a target voice has been matched.

The PowerShell command line contains **fixed code only**; caller text and
voice identifiers cross subprocess stdin as base64-encoded UTF-8 lines. The
script reads them as literal data and uses `Speak($text)`, not a shell command.
This removes the obvious process-argument exposure but does not claim full
privacy against privileged local process, memory, telemetry or audio capture.
No transcript or raw stderr is included in normal Python exceptions.
400-character text, 96-character voice identifier, <=60-second subprocess
timeout, 12 MB WAV cap and PCM/RIFF shape verification bound this baseline.

## Separate responsibilities — do not conflate them

| Responsibility | Owner/interface | V1 status |
| --- | --- | --- |
| Reasoning | Caller/runtime chooses utterance text | Not changed |
| Voice identity | Private `VoiceProfile` research/provenance, permissions, QA | **Not implemented** |
| Synthesis | `render_sapi_wave` → in-memory PCM/WAV | Source candidate |
| Audio delivery | Explicit caller-controlled playback or file transport | **Not implemented** |
| Matrix/Element X | Later separately authorized voice-message adapter | **Not implemented** |

`ears` should not be treated as TTS by its name. `vera-mono` owns this small
runtime-neutral synthesis adapter because that code is an output capability,
not a hearing, identity, memory, or messaging system. This file must not be
wired to automatically speak responses until native/runtime admission and a
host-specific effect review are authorized.

## Voice research and rights gates

Patrick provided a Suno-generated **song** as a *private aesthetic reference*.
A singing performance is not a reusable speaking-voice model: harmony,
effects, accompaniment, pitch range and singing phonemes impair speaker
adaptation. No song, stem, singer embedding, private identifier, personal
audio, transcript, or voice clone belongs in this public repository.

Candidates require separate checks for **engine code**, **model weights**,
**voice packs**, **audio inputs**, and **redistribution/commercial use**:

| Candidate | Potential fit | Constraint / next gate |
| --- | --- | --- |
| Windows `System.Speech` / SAPI | No-download $0 local baseline on Lappy | Installed voices are generic; Windows-only |
| [OHF Piper](https://github.com/OHF-Voice/piper1-gpl) | Fast offline neural TTS | Current engine GPL-3.0-or-later; check each voice model card and deployment obligations |
| [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) | Lightweight higher-quality preset voices | Apache-2.0 weights; not proof of an adapted Suno voice |
| [OpenVoice V2](https://github.com/myshell-ai/OpenVoice) | Experimental tone-color adaptation with suitable voice speech | MIT repository code; clean authorized speaking reference and subjective/technical QA needed |
| [F5-TTS](https://github.com/SWivid/F5-TTS) | Advanced adapted speech experiments | Code MIT but pretrained model CC-BY-NC; do not imply unrestricted commercial use |
| [XTTS-v2](https://huggingface.co/coqui/XTTS-v2) | Adapted speech experiments | Coqui public model license restricts permitted use; check exact terms |

No candidate weights are bundled, installed, fetched or trained by V1.
Neither a Suno download nor Patrick's willingness to supply a song alone
settles downstream rights or extraction feasibility. The `VoiceProfile` phase
must first document authorized source, allowed derivative processing and
retention, then isolate a clean voice sample, compare speaking results with
blinded listeners and acoustic measurements, and reject mismatches. The
voice should be described as *inspired by* a reference, not a verified clone.

## Qualification instructions (not a claim of execution)

1. Run `tests/test_voice_output_v1.py` on a dependency-complete repository
   checkout, plus the ordinary affected package suite. Synthetic runner
   fixtures do **not** qualify Windows speech.
2. On a user-authorized Windows host with System.Speech installed, select a
   **verified installed** voice and render a nonpersonal synthetic phrase.
   Record host, exact source Git SHA, Python/PowerShell versions, voice name,
   exit status, SHA-256, sample rate, channels, duration, real WAV validator
   result; do not log voice text. Confirm a WAV file/playback only with
   target-specific authorization.
3. Explicitly stop at source-only review. Separate effect grants are required
   for file retention, playback, native installation, persistent service,
   training, publication, and Matrix posting.

## Known limits

- `subprocess.run` captures output before the Python 12 MB postcondition;
  the fixed child script caps emitted WAV at 12 MB, but hostile replacement
  binaries or upstream PowerShell failures are outside this sandboxing claim.
- `System.Speech` SAPI's installed voices are not Vera's distinctive target
  voice. No comparative audio test has been performed in V1 source tests.
- A content hash proves only the bytes returned by a synthesizer, not human
  perception or the execution permissions of a subsequent delivery stage.
