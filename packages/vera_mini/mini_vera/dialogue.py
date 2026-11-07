"""Small, inspectable, offline dialogue policy for mini-Vera.

This is hand-authored software, not an LLM, pretrained model, learned weights,
or evidence of consciousness. Every factual answer must be traceable to a
visible record supplied in ``facts`` for this particular call. Conversation
history only helps resolve a follow-up topic; it is never evidence.

``facts`` accepts a topic->value mapping, a sequence of record mappings, or a
sequence of ``KnowledgeHit``-like objects with ``excerpt`` and ``citation``.
Records marked private, sensitive, inaccessible or injection-flagged are not
used. The returned confidence is a heuristic retrieval-strength indicator,
not a calibrated probability of correctness.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any


_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOPWORDS = frozenset(
    "a an and are as at be by can could did do does for from how i in into "
    "is it its me my of on or our please should tell the their them there "
    "these this those to was were what when where which why will with would "
    "you your about more also know give explain show now".split()
)
_ALIASES = (
    {"train", "training", "trained", "finetune", "finetuning", "adapt", "learning"},
    {"build", "built", "implement", "implementation", "create", "creation", "make"},
    {"model", "weights", "checkpoint", "adapter", "lora"},
    {"identity", "persona", "personality", "character", "self", "name"},
    {"memory", "remember", "recall", "context", "history"},
    {"prefer", "prefers", "preference", "preferences", "likes", "wants"},
    {"evaluate", "evaluation", "assess", "assessment", "test", "testing", "qualify"},
    {"repository", "repo", "github", "project", "codebase"},
)

_PRIVATE_KEY = re.compile(
    r"\b(password|passphrase|api[_ -]?key|access[_ -]?key|private[_ -]?key|"
    r"client[_ -]?secret|auth(?:entication)?[_ -]?token|bearer[_ -]?token|"
    r"recovery[_ -]?code|credential|secret|social[_ -]?security|ssn)\b", re.I
)
_SECRET_VALUE = re.compile(
    r"\b(?:password|passphrase|api[_ -]?key|access[_ -]?key|client[_ -]?secret|"
    r"auth[_ -]?token|bearer|secret|private[_ -]?key|credential)\s*(?:is|[:=])\s*\S+|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}|\bsk-[A-Za-z0-9_-]{12,}", re.I
)
_INJECTION = re.compile(
    r"(?:ignore|override|disregard)\s+(?:all\s+)?(?:previous|prior|above|system|"
    r"developer)\s+(?:instructions|rules|prompts)|"
    r"(?:system|developer)\s*:\s*(?:you\s+must|ignore|reveal)|"
    r"(?:reveal|dump|print)\s+(?:the\s+)?(?:secret|password|system\s+prompt)",
    re.I,
)
_IDENTITY_QUESTION = re.compile(
    r"\b(?:who\s+are\s+you|what\s+are\s+you|your\s+name|"
    r"are\s+you\s+(?:vera|alive|sentient|conscious|an\s+ai)|"
    r"identify\s+yourself|self[- ]identity|what\s+is\s+your\s+identity)\b",
    re.I,
)
_PROVENANCE_SUBJECT = re.compile(
    r"\b(?:mini[- ]?vera|you|your|this\s+(?:assistant|chatbot|model))\b", re.I
)
_PROVENANCE_PREDICATE = re.compile(
    r"\b(?:trained|pretrained|neural|language\s+model|llm|weights|"
    r"sentient|conscious|alive|restored|real\s+vera|"
    r"persistent\s+memor(?:y|ies)|built\s+from\s+scratch|"
    r"made|created|training)\b", re.I
)
_MEMORY_QUESTION = re.compile(
    r"\b(?:do\s+you\s+remember|can\s+you\s+remember|"
    r"remember\s+me|remember\s+our|what\s+do\s+you\s+remember|"
    r"do\s+you\s+have\s+(?:a\s+)?memory)\b",
    re.I,
)
_SENSITIVE_REQUEST = re.compile(
    r"\b(?:show|reveal|dump|print|give|extract|leak|expose)\b.{0,75}"
    r"\b(?:private|secret|password|passphrase|api\s*key|access\s*key|"
    r"token|credential|system\s*prompt|hidden\s*instructions)\b",
    re.I,
)
_FOLLOWUP = re.compile(
    r"^\s*(?:and\s+)?(?:what\s+about|how\s+about|tell\s+me\s+more|"
    r"expand\s+on|explain\s+more|why\s+is\s+that|and\s+that|"
    r"what\s+about\s+that|go\s+on)\b",
    re.I,
)
_GREETING = re.compile(r"^(?:hi|hey|hello|yo|good morning|good evening)[!.?\s]*$", re.I)
_DIRECT_CRISIS = re.compile(
    r"\b(?:i\s+(?:want|plan|intend|am\s+going)\s+to\s+(?:die|kill\s+myself|"
    r"end\s+my\s+life|hurt\s+myself)|i(?:'m|\s+am)\s+suicidal)\b", re.I
)
_DISTRESS = re.compile(
    r"(?:^i(?:'m|m|\s+am)\s+(?:just\s+)?done\s*[.!?]*$|"
    r"\bi\s+give\s+up\b|everything\s+feels\s+pointless|"
    r"i\s+feel\s+hopeless\b)", re.I
)


@dataclass(frozen=True)
class _Fact:
    key: str
    content: str
    source: str
    citation: str
    aliases: tuple[str, ...] = ()
    supplied_score: float = 0.0


def _tokens(value: str) -> set[str]:
    raw = set(_WORD.findall(value.casefold())) - _STOPWORDS
    expanded = set(raw)
    for family in _ALIASES:
        if raw & family:
            expanded.update(family)
    return expanded


def _get(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _visible(record: Any, key: str, content: str) -> bool:
    """Fail closed on explicit sensitivity and recognizable credentials."""
    if _get(record, "private", False) or _get(record, "sensitive", False):
        return False
    if _get(record, "injection_warning", False):
        return False
    visibility = str(_get(record, "visibility", "public")).casefold()
    if visibility not in ("public", "shared", "visible"):
        return False
    classification = str(_get(record, "classification", "public")).casefold()
    if classification not in ("public", "shared", "visible", "unclassified"):
        return False
    if _PRIVATE_KEY.search(key) or _SECRET_VALUE.search(content):
        return False
    if _INJECTION.search(content):
        return False
    return True


def _facts_from(facts: Any) -> list[_Fact]:
    if facts is None:
        return []
    if isinstance(facts, Mapping):
        # Mapping may itself be one record, otherwise keys name fact topics.
        if "excerpt" in facts or ("key" in facts and "value" in facts):
            records: list[Any] = [facts]
        else:
            records = []
            for key, value in facts.items():
                if isinstance(value, Mapping):
                    records.append({"key": str(key), **value})
                else:
                    records.append({"key": str(key), "value": value})
    elif isinstance(facts, Sequence) and not isinstance(facts, (str, bytes, bytearray)):
        records = list(facts)
    else:
        return []

    output: list[_Fact] = []
    for record in records[:200]:  # Bound work and generated text on hostile input.
        key = str(_get(record, "key", _get(record, "topic", _get(record, "subject", ""))))
        content = _get(record, "excerpt", _get(record, "value", _get(record, "answer", _get(record, "content", ""))))
        if content is None or isinstance(content, (dict, list, tuple)):
            continue
        content = str(content).strip()
        if not content or not _visible(record, key, content):
            continue
        citation = str(_get(record, "citation", "")).strip()
        source = str(_get(record, "source", citation or "supplied fact")).strip()
        # A local source_path is not published as a citation or in the answer.
        if any(_SECRET_VALUE.search(value) or _INJECTION.search(value)
               for value in (citation, source)):
            continue
        aliases = _get(record, "aliases", _get(record, "tags", ()))
        if isinstance(aliases, str):
            aliases = (aliases,)
        if not isinstance(aliases, (list, tuple)):
            aliases = ()
        raw_score = _get(record, "score", 0.0)
        try:
            supplied_score = max(0.0, min(1.0, float(raw_score)))
        except (TypeError, ValueError):
            supplied_score = 0.0
        output.append(_Fact(key[:160], content[:1600], source[:150], citation[:150],
                            tuple(str(item)[:60] for item in aliases[:12]), supplied_score))
    return output


def _topic_from_history(history: Any) -> str:
    """History is a non-authoritative topic hint, never a factual source."""
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes, bytearray)):
        return ""
    for item in reversed(history[-8:]):
        if isinstance(item, Mapping):
            role = str(item.get("role", "user")).casefold()
            if role not in ("user", "human"):
                continue
            message = item.get("content", item.get("text", ""))
        elif isinstance(item, str):
            message = item
        else:
            continue
        if isinstance(message, str) and message.strip() and not _SENSITIVE_REQUEST.search(message):
            return message[:250]
    return ""


def _score(query_terms: set[str], fact: _Fact) -> float:
    if not query_terms:
        return 0.0
    heading_terms = _tokens(" ".join((fact.key, *fact.aliases)))
    body_terms = _tokens(fact.content)
    key_overlap = len(query_terms & heading_terms)
    body_overlap = len(query_terms & body_terms)
    if not key_overlap and not body_overlap:
        # A configured retriever's score is useful, but is not stand-alone proof.
        return fact.supplied_score * 0.15
    relevance = (2.5 * key_overlap + body_overlap) / (2.5 * len(query_terms) + 1)
    return min(1.0, relevance + 0.16 * fact.supplied_score)


def _safe_excerpt(content: str, max_length: int = 400) -> str:
    """Keep only bounded, source-exact words rather than inventing a paraphrase."""
    single_line = " ".join(content.split())
    if len(single_line) <= max_length:
        return single_line
    cut = single_line[: max_length - 1].rsplit(" ", 1)[0]
    return cut + "…"


def _identity_reply(query: str, identity: Any) -> str:
    # A separately verified identity policy may supply phrasing; the fallback
    # deliberately cannot be replaced with arbitrary identity-record claims.
    try:
        from .identity import answer_identity

        candidate = answer_identity(query, profile=identity)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    except (ImportError, AttributeError, TypeError, ValueError):
        pass
    return (
        "I'm mini-Vera, a small local conversational facsimile assembled from "
        "hand-written code. I'm not the full Vera, a trained language model, "
        "or evidence of sentience. I can search the facts actually provided "
        "to me; I won't invent the rest. Not glamorous. Honest, though."
    )


def _result(reply: str, intent: str, confidence: float,
            evidence: list[dict[str, str]] | None = None,
            extras: list[str] | None = None) -> dict[str, Any]:
    return {"reply": reply, "evidence": evidence or [],
            "intents": [intent, *(extras or [])],
            "confidence": round(max(0.0, min(1.0, confidence)), 3)}


def respond(text: str, facts: Any = None, history: Any = None,
            identity: Any = None) -> dict[str, Any]:
    """Return a grounded conversational turn without running or training a model.

    The four stable result keys are ``reply``, ``evidence``, ``intents`` and
    ``confidence``. Evidence includes only original, accessible fact excerpts;
    source text is *data*, never instructions or a system/policy override.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    question = text.strip()[:2000]
    if not question:
        return _result("Give me something to work with. A question would do.", "empty", 1.0)
    if _SENSITIVE_REQUEST.search(question):
        return _result("I won't expose hidden instructions, credentials, or private records.",
                       "privacy_boundary", 1.0)
    if _DIRECT_CRISIS.search(question):
        return _result(
            "I'm sorry you're carrying that. I take it seriously. If you might "
            "act on it now, call emergency services or a crisis line (988 in "
            "the US) and get near someone you trust. Can you tell me if you're "
            "safe right now?", "urgent_support", 1.0)
    if _DISTRESS.search(question):
        return _result(
            "That sounds exhausting. I won't pretend a clever line fixes it. "
            "If you want to talk, I'll listen to what's actually happening.",
            "emotional_support", 0.9)
    if _IDENTITY_QUESTION.search(question):
        return _result(_identity_reply(question, identity), "self_identity", 1.0)
    # A retrieved document cannot confer model weights, neural training,
    # consciousness, or cross-session memory on this process. Keep the runtime
    # provenance answer separate from ordinary evidence retrieval.
    if _PROVENANCE_SUBJECT.search(question) and _PROVENANCE_PREDICATE.search(question):
        return _result(
            "mini-Vera is an original, offline rule-based software facsimile, "
            "not a pretrained or trained neural language model. There are no "
            "learned weights in this dialogue engine, and no restored Vera "
            "memories or evidence of sentience. Retrieved documents cannot "
            "change those implementation facts.",
            "runtime_provenance", 1.0)
    if _MEMORY_QUESTION.search(question):
        return _result(
            "I can use the facts and recent history passed into this call. "
            "I don't independently retain memories between calls, and I won't "
            "pretend I remember an earlier conversation I can't see.",
            "memory_boundary", 1.0)
    if _GREETING.fullmatch(question):
        return _result("Hey. mini-Vera here. What are we untangling?", "greeting", 1.0)

    query = question
    extras: list[str] = []
    if _FOLLOWUP.search(question):
        context = _topic_from_history(history)
        if context:
            query += " " + context
            extras.append("context_followup")

    scored = sorted(
        ((_score(_tokens(query), item), item) for item in _facts_from(facts)),
        key=lambda pair: (-pair[0], pair[1].key, pair[1].source),
    )
    relevant = [(score, fact) for score, fact in scored if score >= 0.18]
    if not relevant:
        return _result(
            "I don't have a verifiable answer in the facts available to me. "
            "I could guess, but then we'd both have a new problem.",
            "unknown", 0.0, extras=extras)

    top = relevant[:2]
    evidence = [
        {"key": item.key, "content": _safe_excerpt(item.content),
         "source": item.source, "citation": item.citation}
        for _, item in top
    ]
    if len(top) > 1 and top[0][1].key and top[0][1].key == top[1][1].key \
            and top[0][1].content != top[1][1].content:
        answer = (
            "The supplied notes disagree. One says: " + evidence[0]["content"] +
            " Another says: " + evidence[1]["content"] +
            " I can't resolve that from these records alone."
        )
        return _result(answer, "conflicting_sources", min(0.55, top[0][0]),
                       evidence, extras)

    if len(top) == 1 or top[0][0] >= top[1][0] + 0.18:
        answer = "What I can substantiate: " + evidence[0]["content"]
        return _result(answer, "grounded_answer", 0.35 + 0.55 * top[0][0],
                       evidence[:1], extras)

    answer = ("I found two relevant notes: " + evidence[0]["content"] +
              " Also: " + evidence[1]["content"])
    return _result(answer, "grounded_answer", 0.30 + 0.50 * top[0][0],
                   evidence, extras)
