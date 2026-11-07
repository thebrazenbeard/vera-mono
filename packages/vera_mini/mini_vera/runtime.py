"""Offline coordinator for the original non-neural Mini-Vera engine."""

from __future__ import annotations

from pathlib import Path
import re
from importlib import resources
import hashlib
import json
from typing import Iterable

from .dialogue import respond
from .identity import default_identity
from .knowledge import KnowledgeIndex
from .memory import MemoryJournal
from .learning import IntentLearner


_MAX_CHECKPOINT_BYTES = 4_000_000
_MAX_MANIFEST_BYTES = 16_384
_POLICY_MANIFEST_SCHEMA = "mini-vera-policy-manifest-v1"
# Pinned to data/training_receipt_v1.json. That source receipt is not included
# in the single-file zipapp, so checking the packaged policy needs this anchor.
_BUNDLED_POLICY_SHA256 = "f2ee0f51aab5c10fdede34c691128bf9ae73d83d0344638f44ed860227fc08c0"


def _read_limited(file, maximum: int, label: str) -> bytes:
    if not file.is_file():
        raise ValueError(f"{label} missing")
    with file.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"{label} exceeds size limit")
    return data


def _read_json(data: bytes, label: str) -> object:
    def reject_nonfinite(_value: str) -> None:
        raise ValueError(f"{label} contains a nonfinite JSON number")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate JSON keys")
            result[key] = value
        return result

    try:
        return json.loads(data.decode("utf-8"), parse_constant=reject_nonfinite,
                          object_pairs_hook=reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is malformed JSON") from exc


def _verified_model(file, expected_sha256: str) -> IntentLearner:
    # Parse exactly the bytes whose digest was checked. Loading the path again
    # after hashing it would leave a time-of-check/time-of-use substitution gap.
    checkpoint = _read_limited(file, _MAX_CHECKPOINT_BYTES, "policy checkpoint")
    if hashlib.sha256(checkpoint).hexdigest() != expected_sha256:
        raise ValueError("policy checkpoint SHA-256 does not match its provenance")
    return IntentLearner.from_dict(_read_json(checkpoint, "policy checkpoint"))


def _external_policy(file: str | Path) -> IntentLearner:
    checkpoint = Path(file)
    manifest_path = checkpoint.with_name(checkpoint.name + ".manifest.json")
    manifest = _read_json(_read_limited(manifest_path, _MAX_MANIFEST_BYTES,
                                        "policy manifest"), "policy manifest")
    if (type(manifest) is not dict or
            set(manifest) != {"schema", "sha256", "consent", "checkpoint", "created_by"} or
            manifest["schema"] != _POLICY_MANIFEST_SCHEMA or
            type(manifest["sha256"]) is not str or
            re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]) is None or
            manifest["consent"] is not True or
            manifest["checkpoint"] != checkpoint.name or
            manifest["created_by"] != "mini-vera train-policy"):
        raise ValueError("invalid policy manifest: explicit consent, provenance and matching filename required")
    # A sibling manifest records a user's claim of consent and file integrity;
    # it is not an independent signature or proof of rights to training data.
    return _verified_model(checkpoint, manifest["sha256"])


def _bundled_policy() -> IntentLearner | None:
    """Verify the released policy against its pinned source-receipt digest."""
    file = resources.files("mini_vera").joinpath("resources/INTENT_POLICY_V1.json")
    if not file.is_file():
        return None
    return _verified_model(file, _BUNDLED_POLICY_SHA256)


class MiniVera:
    """A transparent, limited conversational local program, not an LLM."""

    def __init__(self, *, docs: Iterable[str | Path] = (),
                 memory_file: str | Path | None = None, use_memory: bool = False,
                 policy_file: str | Path | None = None, use_learning: bool = True):
        self.identity = default_identity()
        roots = tuple(docs)
        self.knowledge = KnowledgeIndex.from_roots(roots) if roots else None
        if use_memory and memory_file is None:
            raise ValueError("--with-memory requires --memory FILE")
        self.memory = MemoryJournal(memory_file) if memory_file is not None else None
        self.use_memory = use_memory
        self.policy = ((_external_policy(policy_file) if policy_file is not None
                       else _bundled_policy()) if use_learning else None)
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
        if self.policy is not None and question.strip():
            recommendation = self.policy.predict(question)
            # A learned intent can vary an unknown-answer conversational plan,
            # NEVER privacy, identity, crisis handling, evidence, or authority.
            if result["intents"] == ["unknown"]:
                if recommendation["label"] == "challenge":
                    result["reply"] = (
                        "That deserves a stress test. What observation would "
                        "falsify the central assumption? I don't have evidence "
                        "to settle it yet.")
                elif recommendation["label"] == "probe":
                    result["reply"] = (
                        "I need one more concrete detail before I can answer "
                        "reliably. Which specific outcome are we testing?")
                elif recommendation["label"] == "support":
                    result["reply"] = (
                        "I hear you. I won't invent an answer or pretend "
                        "there's an easy fix. Tell me which part matters most.")
            result["learned_policy"] = recommendation
        self.history.append({"role": "user", "content": question[:500]})
        self.history = self.history[-16:]
        return result
