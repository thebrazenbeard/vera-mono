from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable


def _pair_counts(ids: list[int]) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = {}
    for a, b in zip(ids, ids[1:]):
        counts[(a, b)] = counts.get((a, b), 0) + 1
    return counts


def _merge_pair(ids: list[int], pair: tuple[int, int], new_id: int) -> list[int]:
    out: list[int] = []
    i = 0
    while i < len(ids):
        if i + 1 < len(ids) and ids[i] == pair[0] and ids[i + 1] == pair[1]:
            out.append(new_id)
            i += 2
        else:
            out.append(ids[i])
            i += 1
    return out


@dataclass(frozen=True, slots=True)
class BPETokenizer:
    """Trainable byte-level BPE tokenizer owned by Vera Mono.

    Byte ids 0..255 are always present. Learned merge ids are allocated in
    training order beginning at 256. This makes arbitrary UTF-8 input lossless
    without borrowing a pretrained vocabulary from another model.
    """

    merges: tuple[tuple[int, int], ...] = ()

    @classmethod
    def train(cls, text: str, *, vocab_size: int) -> "BPETokenizer":
        if type(text) is not str or not text:
            raise ValueError("training text must be a non-empty string")
        if type(vocab_size) is not int or vocab_size < 256:
            raise ValueError("vocab_size must be an integer >= 256")
        ids = list(text.encode("utf-8"))
        merges: list[tuple[int, int]] = []
        target_merges = vocab_size - 256
        for _ in range(target_merges):
            counts = _pair_counts(ids)
            if not counts:
                break
            pair, count = max(
                counts.items(),
                key=lambda kv: (kv[1], -kv[0][0], -kv[0][1]),
            )
            if count < 2:
                break
            new_id = 256 + len(merges)
            merges.append(pair)
            ids = _merge_pair(ids, pair, new_id)
        return cls(tuple(merges))

    @property
    def vocab_size(self) -> int:
        return 256 + len(self.merges)

    def encode(self, text: str) -> list[int]:
        if type(text) is not str:
            raise TypeError("text must be a string")
        ids = list(text.encode("utf-8"))
        for new_id, pair in enumerate(self.merges, start=256):
            ids = _merge_pair(ids, pair, new_id)
        return ids

    def _vocab(self) -> dict[int, bytes]:
        vocab: dict[int, bytes] = {i: bytes([i]) for i in range(256)}
        for new_id, (a, b) in enumerate(self.merges, start=256):
            vocab[new_id] = vocab[a] + vocab[b]
        return vocab

    def decode(self, ids: Iterable[int]) -> str:
        vocab = self._vocab()
        pieces: list[bytes] = []
        for token_id in ids:
            if type(token_id) is not int or token_id not in vocab:
                raise ValueError(f"unknown token id: {token_id!r}")
            pieces.append(vocab[token_id])
        return b"".join(pieces).decode("utf-8", errors="replace")

    def save(self, path: str | Path) -> None:
        payload = {
            "schema": "VERA_NATIVE_BPE_TOKENIZER_V1",
            "vocab_size": self.vocab_size,
            "merges": [[a, b] for a, b in self.merges],
        }
        Path(path).write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "BPETokenizer":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema") != "VERA_NATIVE_BPE_TOKENIZER_V1":
            raise ValueError("unsupported tokenizer schema")
        merges = tuple((int(a), int(b)) for a, b in payload.get("merges", []))
        tokenizer = cls(merges)
        if payload.get("vocab_size") != tokenizer.vocab_size:
            raise ValueError("tokenizer vocab_size does not match merges")
        return tokenizer
