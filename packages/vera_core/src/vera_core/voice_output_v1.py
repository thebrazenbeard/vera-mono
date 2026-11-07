"""Default-denied Windows SAPI speech to in-memory WAV bytes.

This is an ordinary operating-system voice baseline, NOT a reconstructed Vera
voice identity, Suno voice, installed runtime, or messaging capability.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import io
import ntpath
import os
import re
import subprocess
import sys
import wave
from typing import Callable


MAX_TEXT_CHARS = 400
MAX_WAV_BYTES = 12_000_000
_VOICE_NAME = re.compile(r"[A-Za-z0-9 ._()'-]{1,96}\Z")


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    """Text and a caller-selected *installed* Windows voice name."""

    text: str
    voice_name: str

    def __post_init__(self) -> None:
        if type(self.text) is not str or not self.text.strip() or len(self.text) > MAX_TEXT_CHARS:
            raise ValueError("text must be nonempty and bounded")
        if type(self.voice_name) is not str or _VOICE_NAME.fullmatch(self.voice_name) is None:
            raise ValueError("voice_name must be a bounded platform voice identifier")


@dataclass(frozen=True, slots=True)
class SpeechWave:
    """Unplayed audio bytes, not a proof of speaker identity or permission."""

    wav_bytes: bytes
    sha256: str
    sample_rate: int
    channels: int
    frames: int
    evidence_class: str
    effect_scope: str = "LOCAL_SUBPROCESS_TO_IN_MEMORY_AUDIO_ONLY"


_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Speech
    $encodedText = [Console]::In.ReadLine()
    $encodedVoice = [Console]::In.ReadLine()
    $text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedText))
    $voiceName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedVoice))
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $synth.SelectVoice($voiceName)
        $memory = New-Object System.IO.MemoryStream
        try {
            $synth.SetOutputToWaveStream($memory)
            $synth.Speak($text)
            $synth.SetOutputToNull()
            $bytes = $memory.ToArray()
            if ($bytes.Length -gt 12000000) { throw 'WAV_TOO_LARGE' }
            [Console]::OpenStandardOutput().Write($bytes, 0, $bytes.Length)
        } finally { $memory.Dispose() }
    } finally { $synth.Dispose() }
} catch {
    [Console]::Error.WriteLine('LOCAL_SYNTHESIS_FAILED')
    exit 2
}
""".strip()


def _system_powershell() -> str:
    """Bind real execution to the Windows-reported system directory.

    A relative executable name would allow process-search-order planting.
    Test injections deliberately bypass host resolution, never attest a host.
    """
    if sys.platform != "win32":
        raise RuntimeError("Windows SAPI requires an authorized Windows host")
    import ctypes

    directory = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(directory, len(directory))
    if length <= 0 or length >= len(directory):
        raise RuntimeError("unable to resolve Windows system directory")
    executable = ntpath.join(directory.value, "WindowsPowerShell", "v1.0", "powershell.exe")
    if not os.path.isfile(executable):
        raise RuntimeError("system Windows PowerShell is unavailable")
    return executable


def _command(executable: str) -> list[str]:
    """Produce a fixed argv vector without caller text or voice data."""
    if type(executable) is not str or not ntpath.isabs(executable):
        raise ValueError("Windows PowerShell requires an absolute executable path")
    encoded = base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii")
    return [executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def _stdin_payload(request: SpeechRequest) -> bytes:
    """Keep untrusted utterance and voice out of command-line process listings."""
    request.__post_init__()  # Defensive revalidation of frozen-object bypasses.
    text_b64 = base64.b64encode(request.text.encode("utf-8")).decode("ascii")
    voice_b64 = base64.b64encode(request.voice_name.encode("utf-8")).decode("ascii")
    return (text_b64 + "\n" + voice_b64 + "\n").encode("ascii")


def _verified_wave(data: bytes) -> tuple[int, int, int]:
    if not isinstance(data, bytes) or not 44 <= len(data) <= MAX_WAV_BYTES:
        raise ValueError("renderer did not produce bounded WAV bytes")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("renderer output is not RIFF/WAVE")
    declared_riff_bytes = int.from_bytes(data[4:8], "little") + 8
    if declared_riff_bytes != len(data):
        raise ValueError("renderer output has inconsistent RIFF length")
    try:
        with wave.open(io.BytesIO(data), "rb") as stream:
            if stream.getcomptype() != "NONE":
                raise ValueError("renderer WAV is compressed")
            channels, rate, frames = stream.getnchannels(), stream.getframerate(), stream.getnframes()
            if channels not in (1, 2) or not 8000 <= rate <= 48000 or frames <= 0:
                raise ValueError("renderer WAV metadata out of bounds")
            sample_width = stream.getsampwidth()
            if sample_width not in (1, 2, 3, 4):
                raise ValueError("renderer WAV sample width unsupported")
            samples = stream.readframes(frames)
            if len(samples) != frames * channels * sample_width:
                raise ValueError("renderer WAV PCM payload is truncated")
            return rate, channels, frames
    except (EOFError, wave.Error) as exc:
        raise ValueError("renderer output is malformed WAV") from exc


def render_sapi_wave(
    request: SpeechRequest,
    *,
    allow_local_synthesis: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
    timeout_s: float = 45.0,
) -> SpeechWave:
    """Render to memory; wrapper adds no playback, files, network or Matrix.

    The opt-in flag is a local caller assertion, not authenticated authority.
    A supplied runner is test/integration injection and cannot attest effects.
    """
    if type(request) is not SpeechRequest:
        raise TypeError("exact SpeechRequest required")
    request.__post_init__()
    if allow_local_synthesis is not True:
        raise PermissionError("local synthesis is default-denied")
    if type(timeout_s) not in (float, int) or not 0 < timeout_s <= 60:
        raise ValueError("timeout_s must be between 0 and 60")
    if runner is None and sys.platform != "win32":
        raise RuntimeError("Windows SAPI requires an authorized Windows host")
    invoke = runner if runner is not None else subprocess.run
    # The fake path is observable synthetic test data only; real calls use the
    # Windows API for an absolute system executable, never PATH/CWD search.
    executable = (
        _system_powershell() if runner is None else
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )
    try:
        result = invoke(
            _command(executable), input=_stdin_payload(request), capture_output=True,
            check=False, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("local SAPI synthesis timed out") from exc
    if type(result.returncode) is not int or result.returncode != 0:
        raise RuntimeError("local SAPI synthesis failed")
    data = result.stdout
    rate, channels, frames = _verified_wave(data)
    return SpeechWave(
        wav_bytes=data,
        sha256=hashlib.sha256(data).hexdigest(),
        sample_rate=rate,
        channels=channels,
        frames=frames,
        evidence_class=("INJECTED_RUNNER_UNATTESTED" if runner is not None else "WINDOWS_SAPI_LOCAL_WAV"),
    )
