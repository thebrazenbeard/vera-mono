# Semantic speech plan V0 — source candidate

**Scope:** structured, bounded text data from a local language model into an
existing strict in-memory WAV synthesizer. Not Vera identity qualification,
subjective affect, a speaking persona, audio delivery, or recipient authority.

This draft is stacked on `vera-mono` voice Draft PR #191 at
`c00de340bc8f65cc5ac7613551e266adf9d24ab9`; it adds only
`vera_core.speech_plan_v0`, tests and this note. It does not edit #191.

## Boundary

1. A model may supply **text**. `plan_from_model_text` does not execute, parse
   as instructions, or delegate effects from that text.
2. The host supplies the installed voice name and one of three semantic intent
   tags: `inform`, `question`, or `reflect`. These tags describe the message,
   not emotions or mental states. Text and tags are not durable memory.
3. A plan records proposed `delivery_style`; V0 SAPI admits only `neutral` as
   the **absence of explicit prosody control**, not a verified acoustic tone.
   Requests for `warm`, `dry`, or `deliberate` fail *before* rendering rather
   than being silently advertised as applied prosody. The result explicitly
   reports `prosody_control_applied=False`.
4. `render_speech_plan_v0` remains default-denied. When explicitly enabled,
   it delegates to #191's `render_sapi_wave` with `require_voice_wav_v0=True`.
   Only in-memory RIFF/WAV PCM16 is returned. No playback, file, transport,
   call, message, notification, recipient, or authorization is implemented.
5. `SpeechPlanResult` preserves the underlying `SpeechWave.evidence_class`:
   an injected subprocess runner is **synthetic**, not proof of Windows audio.

The text is bounded to 400 characters and printable, single-line Unicode;
control/format/separator/surrogate characters are rejected to prevent hidden
or direction-spoofed utterances, and at least one visible L/N/P/S character
is required. V0 locale is `en-US`. New voices, languages, and acoustic styles need their
own backend-specific qualification. An external TTS implementation such as
speech.cpp must be separately evaluated; a GGUF extension is not itself a
compatible waveform decoder.

## Executable source test

`tests/test_speech_plan_v0.py` demonstrates host-selected voice, default
denial, a real call chain into the strict WAV producer under a synthetic
subprocess, forged-object rejection, control-character/enum rejection,
unsupported-prosody refusal, and treatment of malicious-looking model text
as inert data. Companion `test_voice_output_v1.py` remains unchanged.

No real Qwen model answer, local SAPI process, physical speaker, Android
device, or private song is exercised by these synthetic tests. Meaning and
voice quality require separate human evaluation, and a first Vera-initiated
phone message requires Vera 1's authenticated APK inbox/delivery gate.
