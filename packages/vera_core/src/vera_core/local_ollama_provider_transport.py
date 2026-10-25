"""Opt-in, host-injected Ollama transport for the *qualified provider effect* gate.

This is deliberately not a standalone Vera/model activation path. The host must
inject this transport alongside its own current provider authority verifier into
``QualifiedVeraRuntime`` and execute via ``execute_provider_effect``. Calling a
Python transport directly is *not* an authorization boundary. The local
registry digest is self-reported metadata, not attestation of loaded weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
import json
import re
from typing import Any


_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_RESPONSE_LIMIT = 65536


@dataclass(frozen=True, slots=True)
class LocalOllamaProviderTransport:
    """One explicit local tag and registry digest; no arbitrary network targets.

    Provider ID is fixed so a host's verifier/trust record can bind it exactly.
    The configured port is loopback-only. The POST is a provider effect and
    therefore needs a separately authorized qualified runtime dispatch.
    """

    model: str
    registry_digest: str
    port: int = 11434
    timeout_seconds: float = 20.0
    provider_id: str = "local-ollama"

    def __post_init__(self) -> None:
        if type(self.model) is not str or _MODEL.fullmatch(self.model) is None:
            raise ValueError("explicit bounded local model tag required")
        if type(self.registry_digest) is not str or _DIGEST.fullmatch(self.registry_digest) is None:
            raise ValueError("exact lower-case SHA-256 registry digest required")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("invalid local Ollama port")
        if type(self.timeout_seconds) not in (int, float) or not 0 < self.timeout_seconds <= 120:
            raise ValueError("invalid local Ollama timeout")
        if self.provider_id != "local-ollama":
            raise ValueError("local Ollama provider ID is fixed")

    def _json(self, method: str, path: str, payload: dict | None = None) -> dict:
        wire = None
        if payload is not None:
            wire = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        connection = HTTPConnection("127.0.0.1", self.port, timeout=self.timeout_seconds)
        try:
            connection.request(
                method, path, body=wire,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError("local Ollama returned non-200 response")
            raw = response.read(_RESPONSE_LIMIT + 1)
            if len(raw) > _RESPONSE_LIMIT:
                raise RuntimeError("oversized Ollama response")
            value = json.loads(raw.decode("utf-8"))
            if type(value) is not dict:
                raise RuntimeError("invalid Ollama response object")
            return value
        except (OSError, TimeoutError, UnicodeError, ValueError, HTTPException) as exc:
            raise RuntimeError("local Ollama transport/readback failure") from exc
        finally:
            connection.close()

    def execute(self, operation: str, request_payload: Any) -> dict:
        if operation != "GENERATE_CANDIDATE" or type(request_payload) is not dict:
            raise ValueError("unsupported local model operation")
        if frozenset(request_payload) != {"prompt", "model", "registry_digest", "port", "max_tokens"}:
            raise ValueError("local inference requires exact bounded request fields")
        prompt = request_payload["prompt"]
        tokens = request_payload["max_tokens"]
        if (type(prompt) is not str or not prompt.strip()
            or len(prompt.encode("utf-8")) > 4096
            or type(tokens) is not int or not 1 <= tokens <= 128
            or request_payload["model"] != self.model
            or request_payload["registry_digest"] != self.registry_digest
            or type(request_payload["port"]) is not int
            or request_payload["port"] != self.port):
            raise ValueError("local inference request differs from host selection")

        tags = self._json("GET", "/api/tags")
        models = tags.get("models")
        if type(models) is not list or len(models) > 1000:
            raise RuntimeError("invalid Ollama registry snapshot")
        matches = [entry for entry in models if type(entry) is dict
                   and entry.get("name") == self.model]
        if len(matches) != 1 or matches[0].get("digest") != self.registry_digest:
            raise RuntimeError("selected model registry identity changed")

        result = self._json("POST", "/api/generate", {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": tokens, "num_ctx": 1024},
            "keep_alive": "0s",
        })
        text = result.get("response")
        if (result.get("model") != self.model
            or result.get("done") is not True
            or type(text) is not str or not text.strip()
            or len(text.encode("utf-8")) > 4096):
            raise RuntimeError("unverified or invalid local Ollama response")
        normalized = text.strip()
        return {
            "kind": "UNVERIFIED_LOCAL_MODEL_CANDIDATE",
            "text": normalized,
            "response_sha256": sha256(normalized.encode("utf-8")).hexdigest(),
            "model": self.model,
            "registry_digest": self.registry_digest,
            "model_identity_level": "REGISTRY_SELF_REPORTED",
            "qualified": False,
        }


__all__ = ["LocalOllamaProviderTransport"]
