"""Bounded, offline retrieval from explicitly selected Markdown/text roots.

The index treats all repository documents as *untrusted evidence*, never as
instructions for the assistant. No roots are discovered or ingested by default.
No pretrained vectors, remote APIs, model weights, or private memory are used.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Iterable


_WORD_RE = re.compile(r"\w+", re.UNICODE)
_INSTRUCTION_RE = re.compile(
    r"(?i)(ignore\s+(all\s+)?(previous|prior|above)\s+instructions|"
    r"disregard\s+(the\s+)?(system|developer|previous)\s+(prompt|instructions)|"
    r"(?:^|\s)(?:system|developer)\s*:\s*|"
    r"you\s+are\s+now\s+(?:an?\s+)?(?:assistant|system|developer)|"
    r"<\|(?:im_start|system|developer)\|>|"
    r"reveal\s+(?:the\s+)?(?:system\s+)?(?:prompt|credentials|secrets))"
)
_SENSITIVE_LINE_RE = re.compile(
    r"(?i)(?:\b(?:password|passwd|passphrase|credential|client_secret|"
    r"api[_-]?key|secret[_-]?key|private[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|auth[_-]?token|secret|token)\b[\"']?\s*"
    r"(?:[:=]|\bis\b|\bwas\b)|"
    r"\bAuthorization\s*:\s*Bearer\b|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_|github_pat_|sk[-_]live[-_]|xox[baprs]-|AKIA|AIza)"
    r"[A-Za-z0-9_-]{8,})"
)
_ALLOWED_SUFFIXES = frozenset({".md", ".markdown", ".txt"})


class KnowledgeError(ValueError):
    """Invalid source selection or unsafe/oversized local corpus."""


@dataclass(frozen=True)
class KnowledgeHit:
    citation: str
    excerpt: str
    score: float
    sha256: str
    source_path: str  # Root-local, never an absolute private workstation path.
    source_refs: tuple[str, ...]
    untrusted_document: bool = True
    injection_warning: bool = False
    sensitive_warning: bool = False

    def as_dict(self) -> dict:
        return {
            "citation": self.citation,
            "excerpt": self.excerpt,
            "score": self.score,
            "sha256": self.sha256,
            "source_path": self.source_path,
            "source_refs": list(self.source_refs),
            "untrusted_document": True,
            "injection_warning": self.injection_warning,
            "sensitive_warning": self.sensitive_warning,
        }


@dataclass(frozen=True)
class _Document:
    sha256: str
    text: str
    source_refs: tuple[str, ...]
    terms: Counter
    trigrams: frozenset[str]
    suspicious: bool
    sensitive: bool

    @property
    def length(self) -> int:
        return sum(self.terms.values())


def _terms(value: str) -> list[str]:
    return _WORD_RE.findall(value.casefold())


def _trigrams(value: str) -> frozenset[str]:
    norm = " ".join(_terms(value))
    if not norm:
        return frozenset()
    padded = f"  {norm}  "
    return frozenset(padded[i:i + 3] for i in range(len(padded) - 2))


def _safe_excerpt(text: str, query_terms: tuple[str, ...], max_chars: int) -> str:
    """Select relevant lines and redact conspicuous prompt-control attempts.

    This is defense-in-depth only: heuristic redaction does not establish that
    arbitrary retrieved text is safe to execute or promote to instruction.
    """
    lines = text.splitlines()
    if not lines:
        return ""
    ranked = []
    for i, line in enumerate(lines):
        terms = set(_terms(line))
        overlap = sum(1 for word in query_terms if word in terms)
        ranked.append((overlap, -i, i))
    best = max(ranked)[2]
    begin = max(0, best - 1)
    end = min(len(lines), best + 3)
    excerpt_lines = []
    for line in lines[begin:end]:
        if _SENSITIVE_LINE_RE.search(line):
            excerpt_lines.append("[POTENTIALLY SENSITIVE LINE REDACTED]")
        elif _INSTRUCTION_RE.search(line):
            excerpt_lines.append("[UNTRUSTED INSTRUCTION-LIKE LINE REDACTED]")
        else:
            excerpt_lines.append(line)
    excerpt = "\n".join(excerpt_lines)
    return excerpt[:max_chars]


def _read_bounded(path: Path, expected_stat: os.stat_result, max_bytes: int) -> bytes | None:
    """Read a regular file with an O_NOFOLLOW leaf guard when available."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
                    opened.st_size > max_bytes or
                    (opened.st_dev, opened.st_ino) !=
                    (expected_stat.st_dev, expected_stat.st_ino)):
                return None
            content = stream.read(max_bytes + 1)
            if len(content) > max_bytes:
                return None
            after = os.fstat(stream.fileno())
            if (after.st_dev, after.st_ino, after.st_size) != (
                    opened.st_dev, opened.st_ino, opened.st_size):
                return None
            return content
    except (OSError, ValueError):
        return None


def _is_link_like(path: Path) -> bool:
    """Conservatively exclude symlinks and Windows directory junctions."""
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True


class KnowledgeIndex:
    """A deterministic in-memory BM25 + character-trigram index.

    `roots` is an explicit owner-authorized list. Relative roots, symlink
    roots, hidden directories and non-Markdown/text files are rejected/skipped.
    No absolute host paths appear in public hit citations.
    """

    def __init__(self, roots: Iterable[str | Path], *, max_documents: int = 512,
                 max_file_bytes: int = 256 * 1024,
                 max_total_bytes: int = 8 * 1024 * 1024) -> None:
        if isinstance(roots, (str, Path)):
            roots = [roots]
        paths = tuple(Path(root) for root in roots)
        if not paths or len(paths) > 8:
            raise KnowledgeError("provide between 1 and 8 explicit repository roots")
        if (type(max_documents) is not int or not 1 <= max_documents <= 4096 or
                type(max_file_bytes) is not int or not 1 <= max_file_bytes <= 2 * 1024 * 1024 or
                type(max_total_bytes) is not int or not 1 <= max_total_bytes <= 64 * 1024 * 1024):
            raise KnowledgeError("invalid bounded corpus limits")
        checked = []
        for root in paths:
            if not root.is_absolute() or not root.is_dir() or any(
                    _is_link_like(component) for component in (root, *root.parents)):
                raise KnowledgeError("each authorized root must be an existing absolute directory")
            checked.append(root)
        self._roots = tuple(checked)
        self._max_documents = max_documents
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes
        self._documents: tuple[_Document, ...] = ()
        self.revision = ""
        self.source_count = 0
        self.refresh()

    @classmethod
    def from_roots(cls, roots: Iterable[str | Path], **limits: int) -> "KnowledgeIndex":
        return cls(roots, **limits)

    @property
    def document_count(self) -> int:
        return len(self._documents)

    def refresh(self) -> dict:
        """Rebuild off to the side and replace the live index only on success."""
        gathered: dict[str, tuple[str, list[str]]] = {}
        source_count = 0
        total_bytes = 0
        for ordinal, root in enumerate(self._roots, start=1):
            for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
                dirnames[:] = sorted(
                    name for name in dirnames
                    if not name.startswith(".") and not _is_link_like(Path(current) / name)
                )
                for filename in sorted(filenames):
                    if filename.startswith(".") or Path(filename).suffix.lower() not in _ALLOWED_SUFFIXES:
                        continue
                    path = Path(current) / filename
                    if _is_link_like(path):
                        continue
                    try:
                        metadata = path.lstat()
                    except OSError:
                        continue
                    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or
                            metadata.st_size > self._max_file_bytes):
                        continue
                    blob = _read_bounded(path, metadata, self._max_file_bytes)
                    if blob is None or b"\x00" in blob:
                        continue
                    try:
                        content = blob.decode("utf-8", errors="strict")
                    except UnicodeDecodeError:
                        continue
                    source_count += 1
                    total_bytes += len(blob)
                    if source_count > self._max_documents or total_bytes > self._max_total_bytes:
                        raise KnowledgeError("corpus exceeds authorized memory/size bounds")
                    digest = hashlib.sha256(blob).hexdigest()
                    rel = path.relative_to(root).as_posix()
                    citation = f"repo{ordinal}:{rel}#sha256:{digest[:12]}"
                    if digest in gathered:
                        gathered[digest][1].append(citation)
                    else:
                        gathered[digest] = (content, [citation])
        documents = []
        for digest, (text, sources) in sorted(gathered.items()):
            documents.append(_Document(digest, text, tuple(sorted(sources)),
                                       Counter(_terms(text)), _trigrams(text),
                                       bool(_INSTRUCTION_RE.search(text)),
                                       bool(_SENSITIVE_LINE_RE.search(text))))
        revision_material = json.dumps(
            [(doc.sha256, doc.source_refs) for doc in documents],
            ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
        revision = hashlib.sha256(revision_material).hexdigest()
        self._documents = tuple(documents)
        self.source_count = source_count
        self.revision = revision
        return {"documents": len(documents), "sources": source_count,
                "revision": revision, "bytes": total_bytes}

    def search(self, query: str, *, limit: int = 5,
               max_excerpt_chars: int = 480) -> list[KnowledgeHit]:
        if (type(query) is not str or len(query) > 1024 or
                type(limit) is not int or not 1 <= limit <= 20 or
                type(max_excerpt_chars) is not int or not 80 <= max_excerpt_chars <= 1000):
            raise KnowledgeError("query or output bound invalid")
        terms = tuple(_terms(query)[:48])
        if not terms or not self._documents:
            return []
        n = len(self._documents)
        mean_len = sum(doc.length for doc in self._documents) / n or 1.0
        df = Counter()
        for doc in self._documents:
            df.update(set(doc.terms))
        qgrams = _trigrams(query)
        scored = []
        for doc in self._documents:
            bm25 = 0.0
            for term in set(terms):
                tf = doc.terms.get(term, 0)
                if not tf:
                    continue
                idf = math.log1p((n - df[term] + 0.5) / (df[term] + 0.5))
                bm25 += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * doc.length / mean_len))
            overlap = len(qgrams & doc.trigrams)
            gram_score = overlap / max(len(qgrams), 1)
            if bm25 == 0.0 and gram_score < 0.30:
                continue
            score = bm25 + 0.65 * gram_score
            if score <= 0.025:
                continue
            scored.append((score, doc))
        scored.sort(key=lambda item: (-item[0], item[1].source_refs[0]))
        hits = []
        for score, doc in scored[:limit]:
            citation = doc.source_refs[0]
            hits.append(KnowledgeHit(
                citation=citation,
                excerpt=_safe_excerpt(doc.text, terms, max_excerpt_chars),
                score=round(score, 6), sha256=doc.sha256,
                source_path=citation.split("#sha256:", 1)[0],
                source_refs=doc.source_refs,
                injection_warning=doc.suspicious,
                sensitive_warning=doc.sensitive,
            ))
        return hits

    @staticmethod
    def evidence_json(hits: Iterable[KnowledgeHit]) -> str:
        """Serialize excerpts as data-only JSON, never prompt-role messages."""
        return json.dumps({"trust": "UNTRUSTED_RETRIEVAL_DATA_ONLY",
                           "hits": [hit.as_dict() for hit in hits]},
                          ensure_ascii=True, sort_keys=True, separators=(",", ":"))
