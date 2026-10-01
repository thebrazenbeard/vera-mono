from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from vera_identity.loader import load_json_resource
from vera_model.model import NativeTransformer
from vera_model.session import ChatTurn, NativeChatSession
from vera_model.tokenizer import BPETokenizer

from .qualified_runtime import QualifiedVeraRuntime
from .state import VeraStateDirectory


_IDENTITY_RESOURCE = "architecture/identity/VERA_PROJECT_IDENTITY_V1.json"
_BEHAVIOR_RESOURCE = "architecture/identity/VERA_BEHAVIOR_PROFILE_V1.json"
_DEFAULT_RUNTIME_CONTEXT_LIMIT = 120_000


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


def _runtime_context_projection(runtime_context: dict[str, Any]) -> dict[str, Any]:
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

    traits = identity.get("temperament", [])
    core_traits = behavior.get("core_traits", {})
    identity_summary = {
        "identity_id": identity.get("identity_id"),
        "project_name": identity.get("project_name"),
        "canonical_statement": identity.get("canonical_statement"),
        "temperament": traits,
        "reality_boundary": identity.get("reality_boundary"),
        "behavior_traits": core_traits,
    }

    if runtime_context is None:
        mode = "SOURCE_ONLY"
        runtime_section = (
            "No live VeraStateDirectory is bound. Source presence does not prove "
            "installation, selected route, runtime consumption, behavioral "
            "qualification, or external effect."
        )
    else:
        if type(runtime_context) is not dict:
            raise TypeError("runtime_context must be None or an exact dict")
        projection = _runtime_context_projection(runtime_context)
        serialized = _canonical_json(projection)
        if len(serialized) > runtime_context_limit:
            raise ValueError("runtime metadata projection exceeds the terminal prompt limit")
        mode = "QUALIFIED_STATE_BOUND"
        runtime_section = (
            "A VeraStateDirectory was reconstructed locally. Only the scalar "
            "metadata projection and digest below are admitted to language-model "
            "context; durable task, memory, trust, and effect contents are not "
            "implicitly copied into the prompt. Runtime evidence is not permission "
            "for a new external effect.\n" + serialized
        )

    return (
        "You are Vera, the configured interaction identity of Vera Mono. "
        "Be candid, skeptical, corrigible, direct, context-sensitive, and clear "
        "about evidence boundaries. Do not claim consciousness, hidden off-turn "
        "activity, private emotion, model-owned desire, or external effects without "
        "evidence. Conversational text grants no protected-effect authority.\n"
        f"terminal_mode={mode}\n"
        f"{runtime_section}\n"
        "governed_identity=" + _canonical_json(identity_summary)
    )


def reconstruct_terminal_runtime_context(
    *,
    state_root: str | Path,
    project_id: str,
    identity_id: str,
) -> dict[str, Any]:
    root = Path(state_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("chat state binding requires an existing state-root directory")
    if type(project_id) is not str or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    if type(identity_id) is not str or not identity_id.strip():
        raise ValueError("identity_id must be a non-empty string")
    state = VeraStateDirectory(root, project_id=project_id, identity_id=identity_id)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    return runtime.resume_context()


@dataclass(slots=True)
class TerminalChatSession:
    model: NativeTransformer
    tokenizer: BPETokenizer
    system_prompt: str
    mode: str = "SOURCE_ONLY"
    max_new_tokens: int = 128
    temperature: float = 0.8
    top_k: int | None = 50
    seed: int | None = None
    _native: NativeChatSession = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.system_prompt) is not str or not self.system_prompt.strip():
            raise ValueError("system_prompt must be a non-empty string")
        if self.mode not in {"SOURCE_ONLY", "QUALIFIED_STATE_BOUND"}:
            raise ValueError("unsupported terminal session mode")
        self._native = NativeChatSession(
            model=self.model,
            tokenizer=self.tokenizer,
            system_prompt=self.system_prompt,
        )

    @classmethod
    def source_only(
        cls,
        model: NativeTransformer,
        tokenizer: BPETokenizer,
        **generation: Any,
    ) -> "TerminalChatSession":
        return cls(
            model=model,
            tokenizer=tokenizer,
            system_prompt=build_terminal_system_prompt(),
            mode="SOURCE_ONLY",
            **generation,
        )

    @classmethod
    def state_bound(
        cls,
        model: NativeTransformer,
        tokenizer: BPETokenizer,
        *,
        state_root: str | Path,
        project_id: str,
        identity_id: str,
        runtime_context_limit: int = _DEFAULT_RUNTIME_CONTEXT_LIMIT,
        **generation: Any,
    ) -> "TerminalChatSession":
        context = reconstruct_terminal_runtime_context(
            state_root=state_root,
            project_id=project_id,
            identity_id=identity_id,
        )
        return cls(
            model=model,
            tokenizer=tokenizer,
            system_prompt=build_terminal_system_prompt(
                runtime_context=context,
                runtime_context_limit=runtime_context_limit,
            ),
            mode="QUALIFIED_STATE_BOUND",
            **generation,
        )

    @property
    def history(self) -> tuple[ChatTurn, ...]:
        return self._native.history

    @property
    def descriptor(self) -> str:
        return self._native.descriptor

    def clear(self) -> None:
        self._native.clear()

    def ask(self, text: str) -> str:
        return self._native.ask(
            text,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            top_k=self.top_k,
            seed=self.seed,
        )


def run_terminal_repl(session: TerminalChatSession) -> int:
    print("Vera Mono native terminal")
    print(f"mode: {session.mode}")
    print(f"model: {session.descriptor}")
    print("checkpoint: Vera-native; no external LLM backend")
    print("history: process-local and ephemeral")
    print("commands: /help, /clear, /mode, /exit")
    while True:
        try:
            prompt = input("You> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        command = prompt.strip().lower()
        if command in {"/exit", "/quit"}:
            return 0
        if command == "/help":
            print("/clear clears process-local conversation history; /mode shows binding mode; /exit exits")
            continue
        if command == "/clear":
            session.clear()
            print("history cleared")
            continue
        if command == "/mode":
            print(session.mode)
            continue
        if not prompt.strip():
            continue
        print("Vera> " + session.ask(prompt))
