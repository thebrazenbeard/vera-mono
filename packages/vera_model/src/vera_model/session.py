from __future__ import annotations

from dataclasses import dataclass, field

from .model import NativeTransformer
from .tokenizer import BPETokenizer


@dataclass(frozen=True, slots=True)
class ChatTurn:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        if type(self.content) is not str:
            raise TypeError("content must be a string")


@dataclass(slots=True)
class NativeChatSession:
    model: NativeTransformer
    tokenizer: BPETokenizer
    system_prompt: str = "You are Vera."
    _history: list[ChatTurn] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    @property
    def history(self) -> tuple[ChatTurn, ...]:
        return tuple(self._history)

    @property
    def descriptor(self) -> str:
        c = self.model.config
        return (
            "VERA_NATIVE_TRANSFORMER_V1 "
            f"layers={c.n_layer} heads={c.n_head} "
            f"width={c.n_embd} vocab={c.vocab_size}"
        )

    def clear(self) -> None:
        self._history.clear()

    def _prompt(self, pending_user: str) -> str:
        parts = [
            "<|system|>\n",
            self.system_prompt.strip(),
            "\n",
        ]
        for turn in self._history:
            marker = (
                "<|user|>"
                if turn.role == "user"
                else "<|assistant|>"
            )
            parts.extend(
                [marker, "\n", turn.content, "\n"]
            )
        parts.extend(
            [
                "<|user|>\n",
                pending_user.strip(),
                "\n<|assistant|>\n",
            ]
        )
        return "".join(parts)

    def ask(
        self,
        text: str,
        *,
        max_new_tokens: int = 128,
        temperature: float = 0.8,
        top_k: int | None = 50,
        seed: int | None = None,
    ) -> str:
        if type(text) is not str or not text.strip():
            raise ValueError(
                "prompt must be a non-empty string"
            )
        prompt = self._prompt(text)
        prompt_ids = self.tokenizer.encode(prompt)
        generated = self.model.generate(
            prompt_ids,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
            seed=seed,
        )
        reply = self.tokenizer.decode(
            generated[len(prompt_ids) :]
        )
        for marker in (
            "<|end|>",
            "<|user|>",
            "<|system|>",
        ):
            if marker in reply:
                reply = reply.split(marker, 1)[0]
        reply = reply.strip()
        self._history.append(
            ChatTurn("user", text.strip())
        )
        self._history.append(
            ChatTurn("assistant", reply)
        )
        return reply
