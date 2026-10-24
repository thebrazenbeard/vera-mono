"""Read-only local Ollama observation for Rezon's bounded reasoning cascade.

This adapter observes a model response; it does not verify the response,
authorize effects, or turn model output into an executable action. A separate
review layer must resolve ``model_output_unverified`` before the cascade can
produce a dispatchable answer. An arbitrary callback clearing that marker is
not independent review or effect authorization. The research-only
``ClosedLoopFrontier.run_bounded`` currently persists the *caller-provided*
task semantic object even if reasoning later fails, so do not mistake a
blocked dispatch for proof that no persistent state changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
import json
import re

from rezon.cascade import LayerResult, LayerSpec, ReasoningRequest


_MODEL_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$")
_MAX_BODY = 1024 * 1024


@dataclass(frozen=True, slots=True)
class LocalOllamaReasoningLayer:
    """Query only 127.0.0.1; a model response remains an unverified candidate.

    The transport never accesses arbitrary hosts, follows redirects, uses proxy
    settings, reads credentials, or permits model-generated tool calls.
    ``model`` names the requested model and does not attest model weights.
    The response SHA-256 identifies received bytes only, not model identity
    or factual accuracy. The socket timeout is per operation, not an
    absolute wall-clock deadline for a drip-feed server.
    """

    model: str
    port: int = 11434
    timeout_seconds: float = 20.0
    max_output_bytes: int = 65536
    num_predict: int = 256
    num_ctx: int = 1024

    def __post_init__(self) -> None:
        if type(self.model) is not str or _MODEL_ID.fullmatch(self.model) is None:
            raise ValueError("model must be a bounded Ollama model name")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("port must be an exact integer in [1, 65535]")
        if type(self.timeout_seconds) not in (int, float) or not (
            0 < self.timeout_seconds <= 120
        ):
            raise ValueError("timeout_seconds must be in (0, 120]")
        if type(self.max_output_bytes) is not int or not (
            1 <= self.max_output_bytes <= _MAX_BODY
        ):
            raise ValueError("max_output_bytes must be a bounded exact integer")
        if type(self.num_predict) is not int or not 1 <= self.num_predict <= 4096:
            raise ValueError("num_predict must be an exact integer in [1, 4096]")
        if type(self.num_ctx) is not int or not 128 <= self.num_ctx <= 8192:
            raise ValueError("num_ctx must be an exact integer in [128, 8192]")

    def layer_spec(self, name: str = "local-ollama-candidate") -> LayerSpec:
        """Create a Rezon layer that cannot satisfy its resolution gate alone."""

        return LayerSpec(name=name, run=self.run, min_confidence=1.0)

    @staticmethod
    def _abstain(code: str) -> LayerResult:
        return LayerResult(
            answer=None,
            unresolved=("model_output_unverified",),
            confidence=0.0,
            evidence=(f"local-ollama:{code}",),
        )

    def run(self, request: ReasoningRequest) -> LayerResult:
        if type(request) is not ReasoningRequest:
            raise TypeError("request must be exact ReasoningRequest")
        if type(request.prompt) is not str or not request.prompt.strip():
            raise ValueError("prompt must be non-empty")
        if len(request.prompt) > 32768:
            return self._abstain("prompt_too_large")

        payload = json.dumps(
            {
                "model": self.model,
                "prompt": request.prompt,
                "stream": False,
                "options": {
                    "num_predict": self.num_predict,
                    "num_ctx": self.num_ctx,
                },
                "keep_alive": "0s",
            },
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        connection = HTTPConnection("127.0.0.1", self.port, self.timeout_seconds)
        try:
            connection.request(
                "POST", "/api/generate", body=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response = connection.getresponse()
            if response.status != 200:
                return self._abstain("http_error")
            raw = response.read(self.max_output_bytes + 1)
            if len(raw) > self.max_output_bytes:
                return self._abstain("response_too_large")
            decoded = json.loads(raw.decode("utf-8"))
            if type(decoded) is not dict:
                return self._abstain("invalid_response")
            if decoded.get("model") != self.model or decoded.get("done") is not True:
                return self._abstain("unconfirmed_model_response")
            candidate = decoded.get("response")
            if type(candidate) is not str or not candidate.strip():
                return self._abstain("empty_response")
            return LayerResult(
                answer=candidate.strip(),
                unresolved=("model_output_unverified",),
                confidence=0.0,
                evidence=("local-ollama:response-sha256:" + sha256(raw).hexdigest(),),
            )
        except (OSError, TimeoutError, UnicodeError, ValueError, HTTPException):
            return self._abstain("transport_or_decode_error")
        finally:
            connection.close()


__all__ = ["LocalOllamaReasoningLayer"]
