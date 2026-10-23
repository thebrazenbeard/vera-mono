"""Gateway-process-only Ollama observation adapter; not an independently witnessed model."""
from __future__ import annotations

import json
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import URLError

from .sole_route import ModelObservation, GatewayHold

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GatewayHold("model service redirect rejected")


class OllamaMeasuredBackend:
    """Explicit model-server adapter; MUST NOT be reachable in learner process.

    Registry digest and token/duration fields are *provider self-reports*.
    Neither underlying model-weight hash nor gateway/evaluator custody is proven.
    """

    def __init__(self, *, model: str, registry_digest: str, port: int = 11434,
                 timeout: float = 10.0, opener=None):
        if type(model) is not str or _NAME.fullmatch(model) is None:
            raise ValueError("invalid model name")
        if type(registry_digest) is not str or _SHA.fullmatch(registry_digest) is None:
            raise ValueError("expected registry digest invalid")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid local port")
        if type(timeout) not in (int, float) or not 0 < timeout <= 15:
            raise ValueError("timeout exceeds bounded allowance")
        self.model = model
        self.registry_digest = registry_digest
        self.endpoint = f"http://127.0.0.1:{port}"
        self.timeout = timeout
        self.opener = opener if opener is not None else build_opener(ProxyHandler({}), _NoRedirect())

    def _read(self, request: Request) -> dict:
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise GatewayHold("provider non-200")
                body = response.read(16385)
            if len(body) > 16384:
                raise GatewayHold("provider response oversized")
            doc = json.loads(body.decode("utf-8"))
            if type(doc) is not dict:
                raise GatewayHold("provider response not object")
            return doc
        except GatewayHold:
            raise
        except (URLError, OSError, ValueError, TimeoutError, UnicodeError, TypeError) as exc:
            raise GatewayHold("provider outcome unknown") from exc

    def generate(self, prompt: str, *, model: str, max_tokens: int) -> ModelObservation:
        if model != self.model or type(prompt) is not str or not prompt or len(prompt.encode("utf-8")) > 4096:
            raise GatewayHold("selected provider request mismatch")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 128:
            raise GatewayHold("invalid token budget")
        tags = self._read(Request(self.endpoint + "/api/tags", method="GET",
                                  headers={"Accept": "application/json"}))
        items = tags.get("models")
        if type(items) is not list or len(items) > 256:
            raise GatewayHold("model inventory unbounded")
        matches = [x for x in items if type(x) is dict and x.get("name") == self.model]
        if len(matches) != 1 or matches[0].get("digest") != self.registry_digest:
            raise GatewayHold("provider registry digest mismatch")
        request = json.dumps({
            "model": self.model, "prompt": prompt, "stream": False,
            "keep_alive": 0, "options": {"num_predict": max_tokens, "temperature": 0},
        }, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        response = self._read(Request(self.endpoint + "/api/generate", data=request,
                                      method="POST", headers={"Content-Type": "application/json",
                                                              "Accept": "application/json"}))
        if (response.get("model") != self.model or response.get("done") is not True
                or type(response.get("response")) is not str
                or len(response["response"].encode("utf-8")) > 4096):
            raise GatewayHold("provider terminal data invalid")
        values = tuple(response.get(k) for k in
                       ("prompt_eval_count", "eval_count", "total_duration"))
        if any(type(v) is not int or v < 0 for v in values):
            raise GatewayHold("provider measured usage unavailable")
        if values[1] > max_tokens:
            raise GatewayHold("provider token limit not respected")
        return ModelObservation(text=response["response"], model=model,
                                prompt_tokens=values[0], output_tokens=values[1],
                                backend_wall_ms=values[2] // 1_000_000)
