from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from vera_identity.loader import load_json_resource

from .qualified_runtime import QualifiedVeraRuntime
from .state import VeraStateDirectory


_IDENTITY_RESOURCE = "architecture/identity/VERA_PROJECT_IDENTITY_V1.json"
_BEHAVIOR_RESOURCE = "architecture/identity/VERA_BEHAVIOR_PROFILE_V1.json"
_DEFAULT_RUNTIME_CONTEXT_LIMIT = 120_000


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError("role must be system, user, or assistant")
        if type(self.content) is not str or not self.content.strip():
            raise ValueError("content must be a non-empty string")

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class TextGenerationBackend(Protocol):
    @property
    def descriptor(self) -> str: ...

    def complete(self, messages: tuple[ChatMessage, ...]) -> str: ...


@dataclass(frozen=True, slots=True)
class OpenAICompatibleBackend:
    """Minimal OpenAI-compatible chat-completions transport.

    This is an inference substrate only. It does not own Vera identity, source,
    memory, runtime currentness, or effect authority.
    """

    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 120.0
    temperature: float = 0.4

    def __post_init__(self) -> None:
        if type(self.base_url) is not str or not self.base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute http(s) URL")
        if type(self.model) is not str or not self.model.strip():
            raise ValueError("model must be a non-empty string")
        if self.api_key is not None and (
            type(self.api_key) is not str or not self.api_key
        ):
            raise ValueError("api_key must be None or a non-empty string")
        if type(self.timeout_seconds) not in {int, float} or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if type(self.temperature) not in {int, float} or not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")

    @property
    def descriptor(self) -> str:
        return f"{self.model} @ {self.base_url.rstrip('/')}"

    @property
    def chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def complete(self, messages: tuple[ChatMessage, ...]) -> str:
        if type(messages) is not tuple or not messages:
            raise ValueError("messages must be a non-empty exact tuple")
        if any(type(message) is not ChatMessage for message in messages):
            raise TypeError("messages must contain exact ChatMessage values")

        payload = {
            "model": self.model,
            "messages": [message.as_dict() for message in messages],
            "temperature": self.temperature,
            "stream": False,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "vera-mono-terminal/1",
        }
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            self.chat_completions_url,
            data=encoded,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=float(self.timeout_seconds)) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:4000]
            except Exception:
                detail = ""
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(
                f"text generation request failed with HTTP {exc.code}{suffix}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"text generation request failed: {exc.reason}"
            ) from exc

        try:
            body = json.loads(raw.decode("utf-8"))
            text = body["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "text generation backend returned an unsupported response"
            ) from exc
        if type(text) is not str or not text.strip():
            raise RuntimeError("text generation backend returned empty content")
        return text.strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _runtime_context_digest(runtime_context: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(runtime_context).encode("utf-8")).hexdigest()


_SAFE_RUNTIME_CONTEXT_KEYS = (
    "schema",
    "status",
    "project_id",
    "identity_id",
    "accepted_runtime_id",
    "accepted_memory_head",
    "accepted_checkpoint_digest",
    "accepted_checkpoint_generation",
    "accepted_currentness_digest",
    "currentness_generation",
)


def _runtime_context_projection(
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for key in _SAFE_RUNTIME_CONTEXT_KEYS:
        if key not in runtime_context:
            continue
        value = runtime_context[key]
        if value is None or type(value) in {str, int, float, bool}:
            projection[key] = value
    projection["full_context_sha256"] = _runtime_context_digest(runtime_context)
    return projection


def build_terminal_system_prompt(
    *,
    runtime_context: dict[str, Any] | None = None,
    runtime_context_limit: int = _DEFAULT_RUNTIME_CONTEXT_LIMIT,
) -> str:
    if type(runtime_context_limit) is not int or runtime_context_limit <= 0:
        raise ValueError("runtime_context_limit must be a positive integer")

    identity = load_json_resource(_IDENTITY_RESOURCE)
    behavior = load_json_resource(_BEHAVIOR_RESOURCE)
    if type(identity) is not dict or type(behavior) is not dict:
        raise RuntimeError("Vera identity resources must be JSON objects")

    if runtime_context is None:
        mode = "SOURCE_ONLY"
        runtime_section = (
            "No live VeraStateDirectory was supplied. Do not claim installation, "
            "current-route selection, runtime consumption, behavior qualification, "
            "or external effects from source presence alone."
        )
    else:
        if type(runtime_context) is not dict:
            raise TypeError("runtime_context must be None or an exact dict")
        projection = _runtime_context_projection(runtime_context)
        serialized = _canonical_json(projection)
        if len(serialized) > runtime_context_limit:
            raise ValueError(
                "runtime metadata projection exceeds the terminal prompt limit"
            )
        mode = "QUALIFIED_STATE_BOUND"
        runtime_section = (
            "A VeraStateDirectory was reconstructed locally for this session. "
            "Only the privacy-bounded metadata projection below is supplied to the "
            "text generator; durable task, memory, trust, and effect contents are "
            "not exported implicitly. Treat the projection as runtime evidence at "
            "session start, not as permission for new external effects.\n"
            f"{serialized}"
        )

    identity_json = _canonical_json(identity)
    behavior_json = _canonical_json(behavior)
    return (
        "You are the text-generation substrate for the Vera Mono terminal "
        "interaction surface. Generate the conversational reply presented as Vera. "
        "The generator is infrastructure and is not itself Vera identity authority. "
        "Use first-person Vera language when natural. Preserve candor, skepticism, "
        "correction uptake, directness, context sensitivity, and the configured "
        "reality boundary. Never convert source presence into runtime evidence, "
        "memory into current desire, or conversational text into effect authority. "
        "This terminal session has no implicit authority to mutate canonical memory "
        "or perform protected external effects.\n\n"
        f"terminal_mode={mode}\n"
        f"{runtime_section}\n\n"
        "GOVERNED_IDENTITY_JSON:\n"
        f"{identity_json}\n\n"
        "GOVERNED_BEHAVIOR_JSON:\n"
        f"{behavior_json}"
    )


def reconstruct_terminal_runtime_context(
    *,
    state_root: str | Path,
    project_id: str,
    identity_id: str,
) -> dict[str, Any]:
    root = Path(state_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(
            "chat state binding requires an existing state-root directory"
        )
    if type(project_id) is not str or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    if type(identity_id) is not str or not identity_id.strip():
        raise ValueError("identity_id must be a non-empty string")
    state = VeraStateDirectory(
        root,
        project_id=project_id,
        identity_id=identity_id,
    )
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    return runtime.resume_context()


@dataclass(slots=True)
class TerminalChatSession:
    backend: TextGenerationBackend
    system_prompt: str
    mode: str = "SOURCE_ONLY"
    _history: list[ChatMessage] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.system_prompt) is not str or not self.system_prompt.strip():
            raise ValueError("system_prompt must be a non-empty string")
        if self.mode not in {"SOURCE_ONLY", "QUALIFIED_STATE_BOUND"}:
            raise ValueError("unsupported terminal session mode")
        self._history.append(ChatMessage("system", self.system_prompt))

    @classmethod
    def source_only(
        cls,
        backend: TextGenerationBackend,
    ) -> "TerminalChatSession":
        return cls(
            backend=backend,
            system_prompt=build_terminal_system_prompt(),
            mode="SOURCE_ONLY",
        )

    @classmethod
    def state_bound(
        cls,
        backend: TextGenerationBackend,
        *,
        state_root: str | Path,
        project_id: str,
        identity_id: str,
        runtime_context_limit: int = _DEFAULT_RUNTIME_CONTEXT_LIMIT,
    ) -> "TerminalChatSession":
        context = reconstruct_terminal_runtime_context(
            state_root=state_root,
            project_id=project_id,
            identity_id=identity_id,
        )
        return cls(
            backend=backend,
            system_prompt=build_terminal_system_prompt(
                runtime_context=context,
                runtime_context_limit=runtime_context_limit,
            ),
            mode="QUALIFIED_STATE_BOUND",
        )

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        return tuple(self._history)

    def clear(self) -> None:
        system = self._history[0]
        self._history[:] = [system]

    def ask(self, text: str) -> str:
        if type(text) is not str or not text.strip():
            raise ValueError("prompt must be a non-empty string")
        self._history.append(ChatMessage("user", text.strip()))
        try:
            reply = self.backend.complete(tuple(self._history))
        except Exception:
            self._history.pop()
            raise
        self._history.append(ChatMessage("assistant", reply))
        return reply


def run_terminal_repl(session: TerminalChatSession) -> int:
    print("Vera Mono terminal")
    print(f"mode: {session.mode}")
    print(f"generator: {session.backend.descriptor}")
    print("history: ephemeral; no canonical-memory write")
    print("commands: /help, /clear, /mode, /exit")
    while True:
        try:
            prompt = input("You> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        stripped = prompt.strip()
        if not stripped:
            continue
        command = stripped.lower()
        if command in {"/exit", "/quit"}:
            return 0
        if command == "/help":
            print("/clear  clear in-process conversation history")
            print("/mode   show evidence mode and generator")
            print("/exit   end the terminal session")
            continue
        if command == "/clear":
            session.clear()
            print("conversation history cleared")
            continue
        if command == "/mode":
            print(f"mode: {session.mode}")
            print(f"generator: {session.backend.descriptor}")
            continue
        reply = session.ask(stripped)
        print(f"Vera> {reply}")


__all__ = [
    "ChatMessage",
    "OpenAICompatibleBackend",
    "TerminalChatSession",
    "TextGenerationBackend",
    "build_terminal_system_prompt",
    "reconstruct_terminal_runtime_context",
    "run_terminal_repl",
]
