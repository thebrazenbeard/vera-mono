"""Offline coordinator for the original non-neural Mini-Vera engine."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from .dialogue import respond
from .identity import default_identity
from .knowledge import KnowledgeIndex
from .memory import MemoryJournal


class MiniVera:
    """A transparent, limited conversational local program, not an LLM."""

    def __init__(self, *, docs: Iterable[str | Path] = (),
                 memory_file: str | Path | None = None, use_memory: bool = False):
        self.identity = default_identity()
        roots = tuple(docs)
        self.knowledge = KnowledgeIndex.from_roots(roots) if roots else None
        if use_memory and memory_file is None:
            raise ValueError("--with-memory requires --memory FILE")
        self.memory = MemoryJournal(memory_file) if memory_file is not None else None
        self.use_memory = use_memory
        self.history: list[dict[str, str]] = []

    def ask(self, question: str) -> dict:
        if not isinstance(question, str):
            raise TypeError("question must be text")
        if len(question) > 1024:
            raise ValueError("question exceeds 1024-character limit")
        if self.use_memory and self.memory is not None and re.search(
                r"\b(?:what do you remember|list (?:my |our )?memories|show (?:my |our )?memories)\b",
                question, flags=re.I):
            entries = self.memory.read()
            if not entries:
                return {"reply": "This explicitly selected local journal has no active memories.",
                        "evidence": [], "intents": ["local_memory_read"], "confidence": 1.0}
            evidence = [{"key": f"local memory {item['seq']}",
                         "content": item["content"], "source": "consented local journal",
                         "citation": f"memory:seq:{item['seq']}"}
                        for item in entries[:10]]
            return {"reply": "In this local journal, you explicitly saved: " +
                    " | ".join(item["content"] for item in evidence),
                    "evidence": evidence, "intents": ["local_memory_read"],
                    "confidence": 1.0}
        # Retrieval output is untrusted; don't elevate suspicious documents
        # into dialogue evidence simply because they match a query.
        facts = [item.as_dict() for item in self.knowledge.search(question)
                 if not (item.injection_warning or item.sensitive_warning)] \
                if self.knowledge else []
        if self.use_memory and self.memory is not None:
            for record in self.memory.read():
                facts.append({
                    "key": f"user-provided memory {record['seq']}",
                    "value": record["content"],
                    "source": "explicitly consented local journal",
                    "citation": f"memory:seq:{record['seq']}",
                })
        result = respond(question, facts, history=self.history, identity=self.identity)
        self.history.append({"role": "user", "content": question[:500]})
        self.history = self.history[-16:]
        return result
