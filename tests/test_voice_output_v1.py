"""Synthetic evidence only; actual Windows SAPI is qualified separately."""

import base64
import hashlib
import io
import subprocess
import unittest
import wave

from vera_core.voice_output_v1 import (
    MAX_TEXT_CHARS,
    SpeechRequest,
    _command,
    _stdin_payload,
    render_sapi_wave,
)


def silent_wave() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return stream.getvalue()


class VoiceOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = SpeechRequest("A small synthetic test phrase.", "Microsoft Zira Desktop")

    def test_default_denial_prevents_invocation(self) -> None:
        called = []

        def runner(*a, **kw):
            called.append(True)
            raise AssertionError("must not run")

        with self.assertRaises(PermissionError):
            render_sapi_wave(self.request, runner=runner)
        self.assertEqual([], called)

    def test_bounded_input_and_exact_type(self) -> None:
        for text in ("", "  ", "a" * (MAX_TEXT_CHARS + 1), 0):
            with self.subTest(text=str(text)[:12]), self.assertRaises(ValueError):
                SpeechRequest(text, "Microsoft Zira Desktop")
        for voice in ("", "foo\nbar", "Zira;Remove-Item", "A" * 97, None):
            with self.subTest(voice=str(voice)[:15]), self.assertRaises(ValueError):
                SpeechRequest("Hello", voice)
        class Subclass(SpeechRequest):
            pass
        with self.assertRaises(TypeError):
            render_sapi_wave(Subclass("Hello", "Microsoft Zira Desktop"), allow_local_synthesis=True, runner=lambda *a,**k:None)

    def test_forged_frozen_object_revalidated(self) -> None:
        forged = object.__new__(SpeechRequest)
        object.__setattr__(forged, "text", "")
        object.__setattr__(forged, "voice_name", "Microsoft Zira Desktop")
        with self.assertRaises(ValueError):
            render_sapi_wave(forged, allow_local_synthesis=True, runner=lambda *a,**k:None)

    def test_untrusted_text_never_in_command_or_script(self) -> None:
        text = 'Hello; \"; Remove-Item C:\\ | `$(bad)` 😀'
        request = SpeechRequest(text, "Microsoft Zira Desktop")
        argv = _command(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
        self.assertEqual(argv[1:3], ["-NoProfile", "-NonInteractive"])
        self.assertTrue(argv[0].lower().endswith(r"\windowspowershell\v1.0\powershell.exe"))
        for unsafe in ("powershell.exe", r".\powershell.exe", ""):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                _command(unsafe)
        self.assertNotIn(text, repr(argv))
        script = base64.b64decode(argv[-1]).decode("utf-16-le")
        self.assertNotIn("Remove-Item", script)
        self.assertIn("[Console]::In.ReadLine()", script)
        data = _stdin_payload(request).splitlines()
        self.assertEqual(base64.b64decode(data[0]).decode("utf-8"), text)
        self.assertEqual(base64.b64decode(data[1]).decode("utf-8"), request.voice_name)

    def test_injected_runner_receipt_is_not_real_system_proof(self) -> None:
        wav = silent_wave()
        seen = []
        def runner(*args, **kwargs):
            seen.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, stdout=wav, stderr=b"")
        receipt = render_sapi_wave(self.request, allow_local_synthesis=True, runner=runner)
        self.assertEqual(receipt.wav_bytes, wav)
        self.assertEqual(receipt.sha256, hashlib.sha256(wav).hexdigest())
        self.assertEqual((receipt.sample_rate, receipt.channels, receipt.frames), (16000, 1, 1600))
        self.assertEqual(receipt.evidence_class, "INJECTED_RUNNER_UNATTESTED")
        self.assertEqual(receipt.effect_scope, "LOCAL_SUBPROCESS_TO_IN_MEMORY_AUDIO_ONLY")
        self.assertFalse(seen[0][1]["check"])
        self.assertTrue(seen[0][1]["capture_output"])
        self.assertIsInstance(seen[0][1]["input"], bytes)

    def test_bad_wav_is_rejected(self) -> None:
        full = silent_wave()
        truncated = full[:44]
        # A header that promises 1600 frames but contains no PCM must fail,
        # even if the caller forged the declared RIFF length to 36 bytes.
        corrected_header_only = truncated[:4] + (36).to_bytes(4, "little") + truncated[8:]
        for payload in (b"", b"RIFF" + b"0"*100, b"not a wave"*10,
                        b"a"*(12_000_001), truncated, corrected_header_only):
            with self.subTest(length=len(payload)), self.assertRaises(ValueError):
                render_sapi_wave(self.request, allow_local_synthesis=True,
                    runner=lambda *a, **k:subprocess.CompletedProcess(a,0,stdout=payload,stderr=b""))

    def test_nonzero_exit_and_timeout_do_not_leak_text(self) -> None:
        def fail(*a, **kw):
            return subprocess.CompletedProcess(a, 2, stdout=b"", stderr=self.request.text.encode())
        with self.assertRaisesRegex(RuntimeError, "local SAPI synthesis failed") as ctx:
            render_sapi_wave(self.request, allow_local_synthesis=True, runner=fail)
        self.assertNotIn(self.request.text, str(ctx.exception))
        def timeout(*a, **kw):
            raise subprocess.TimeoutExpired(a[0],kw["timeout"])
        with self.assertRaises(TimeoutError):
            render_sapi_wave(self.request, allow_local_synthesis=True, runner=timeout)

    def test_timeout_bounds_and_bool_rejected(self) -> None:
        for seconds in (0, 61, -1, True, float('nan'), "5"):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                render_sapi_wave(self.request, allow_local_synthesis=True, runner=lambda *a,**k:None,timeout_s=seconds)


if __name__ == "__main__":
    unittest.main()
