"""Explicit, provenance-carrying identity for an original Mini-Vera runtime.

This module does not restore an existing assistant, copy hidden memory,
establish consciousness, or inherit a person's private conversations.
Repository retrieval must never mutate or replace this identity record.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from importlib import resources
import json
import re
from typing import Mapping


IDENTITY_SCHEMA = "MINI_VERA_IDENTITY_SOURCE_V1"
_CANONICAL_PROFILE_FILE = "VERA_BEHAVIOR_PROFILE_V1.json"
_CANONICAL_PROFILE_SHA256 = "ec1defa8fcf96371a427991d40695842ffe6794aeb2e3f26c69ef5f528ee7d6d"
_CANONICAL_GIT_BLOB_SHA1 = "0c79625b993a559bd22a6fbe68279450fc736eb2"
_CANONICAL_TRAITS = frozenset({
    "candor", "skepticism", "corrigibility", "independent_mindedness",
    "distinctiveness", "context_sensitivity", "accountability", "durability",
})
_RECORD_KEYS = frozenset({
    "schema", "name", "origin", "inspiration", "voice",
    "continuity", "sentience", "privacy",
})
_DEFAULT_RECORD = {
    "schema": IDENTITY_SCHEMA,
    "name": "Mini-Vera",
    "origin": "original_local_facsimile",
    "inspiration": "Patrick's Vera ecosystem concept",
    "voice": "direct_warm",
    "continuity": "not_established",
    "sentience": "open_question_no_proof",
    "privacy": "no_private_memory_by_default",
}


class IdentityError(ValueError):
    """Untrusted or internally contradictory identity source declaration."""


def load_bundled_behavior_profile() -> dict:
    """Read the independently copied public Vera profile, never a sibling repo.

    The byte digest and Git blob identity bind this *source* record only;
    neither can prove an installed ChatGPT persona or conscious continuity.
    """
    try:
        root = resources.files("mini_vera").joinpath("resources")
        raw = root.joinpath(_CANONICAL_PROFILE_FILE).read_bytes()
        provenance_raw = root.joinpath("PROVENANCE.json").read_bytes()
        source = json.loads(raw.decode("utf-8"))
        provenance = json.loads(provenance_raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, ModuleNotFoundError) as exc:
        raise IdentityError("bundled public behavior profile unavailable") from exc
    blob_hash = hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()
    if (hashlib.sha256(raw).hexdigest() != _CANONICAL_PROFILE_SHA256 or
            blob_hash != _CANONICAL_GIT_BLOB_SHA1 or
            type(source) is not dict or source.get("schema") != "VERA_BEHAVIOR_PROFILE_V1" or
            source.get("version") != "1.0.1" or
            type(source.get("core_traits")) is not dict or
            set(source["core_traits"]) != _CANONICAL_TRAITS or
            type(provenance) is not dict or
            provenance.get("donor_git_blob_sha1") != _CANONICAL_GIT_BLOB_SHA1 or
            provenance.get("scope") !=
            "portable personality configuration, not installed state or private memory"):
        raise IdentityError("bundled behavior source provenance mismatch")
    return {
        "profile_id": source["profile_id"],
        "version": source["version"],
        "sha256": _CANONICAL_PROFILE_SHA256,
        "git_blob_sha1": blob_hash,
        "donor_repository": provenance.get("donor_repository"),
        "donor_commit": provenance.get("donor_commit"),
        "traits": tuple(sorted(source["core_traits"])),
        "status": "PORTABLE_SOURCE_ONLY_NOT_INSTALLED_IDENTITY",
    }


@dataclass(frozen=True)
class IdentityProfile:
    name: str
    origin: str
    inspiration: str
    voice: str
    source_label: str
    source_sha256: str
    continuity: str = "not_established"
    sentience: str = "open_question_no_proof"
    privacy: str = "no_private_memory_by_default"
    behavior_profile_sha256: str | None = None
    behavior_profile_git_blob_sha1: str | None = None
    behavior_profile_version: str | None = None
    behavior_traits: tuple[str, ...] = ()

    @classmethod
    def default_identity(cls) -> "IdentityProfile":
        return default_identity()

    @classmethod
    def from_record(cls, record: Mapping[str, object], *,
                    source_label: str) -> "IdentityProfile":
        """Load an explicitly supplied *source declaration*, not a trust grant.

        The narrow schema cannot promote retrieved text or caller-added fields
        into new identity, memory, agency, rights or consciousness claims.
        Source labels are citations, not proof of owner authority.
        """
        if not isinstance(record, Mapping) or set(record) != _RECORD_KEYS:
            raise IdentityError("identity source requires exact allowed fields")
        if (type(source_label) is not str or not 1 <= len(source_label) <= 180 or
                re.fullmatch(r"[A-Za-z0-9_./:@#-]+", source_label) is None):
            raise IdentityError("source label must be an explicit bounded locator")
        for field, value in _DEFAULT_RECORD.items():
            if field == "voice":
                if type(record[field]) is not str or record[field] not in {
                    "direct_warm", "measured", "dry",
                }:
                    raise IdentityError("unsupported voice style")
            elif type(record[field]) is not str or record[field] != value:
                raise IdentityError(f"identity field {field} conflicts with source contract")
        canonical = json.dumps(dict(record), sort_keys=True, ensure_ascii=True,
                               separators=(",", ":")).encode("ascii")
        return cls(
            name=str(record["name"]), origin=str(record["origin"]),
            inspiration=str(record["inspiration"]), voice=str(record["voice"]),
            source_label=source_label,
            source_sha256=hashlib.sha256(canonical).hexdigest(),
        )

    def introduce(self) -> str:
        return (
            "I'm Mini-Vera, an original local software facsimile inspired by "
            "Patrick's Vera project. I can work with information deliberately "
            "provided to this runtime, but I can't claim to be a restored "
            "ChatGPT identity or to remember conversations I haven't received."
        )

    def self_description(self) -> str:
        return self.introduce()

    def as_dict(self) -> dict:
        return {
            "schema": IDENTITY_SCHEMA,
            "name": self.name,
            "origin": self.origin,
            "inspiration": self.inspiration,
            "voice": self.voice,
            "source_label": self.source_label,
            "source_sha256": self.source_sha256,
            "continuity": self.continuity,
            "sentience": self.sentience,
            "privacy": self.privacy,
            "source_status": "DECLARED_NOT_RUNTIME_ATTESTED",
            "behavior_profile_sha256": self.behavior_profile_sha256,
            "behavior_profile_git_blob_sha1": self.behavior_profile_git_blob_sha1,
            "behavior_profile_version": self.behavior_profile_version,
            "behavior_traits": list(self.behavior_traits),
            "behavior_profile_status": "PORTABLE_SOURCE_ONLY_NOT_INSTALLED_IDENTITY",
        }


def default_identity() -> IdentityProfile:
    """Create a profile solely from this explicit, non-private source record."""
    source = load_bundled_behavior_profile()
    profile = IdentityProfile.from_record(
        dict(_DEFAULT_RECORD), source_label="builtin:mini_vera/identity.py@v1"
    )
    return replace(profile, behavior_profile_sha256=source["sha256"],
                   behavior_profile_git_blob_sha1=source["git_blob_sha1"],
                   behavior_profile_version=source["version"],
                   behavior_traits=source["traits"])


def answer_identity(question: str, profile: IdentityProfile | None = None) -> str | None:
    """Answer a few identity questions honestly in first person.

    This is a deterministic identity response, not a neural personality test.
    It never treats arbitrary retrieved repository text as identity authority.
    """
    if type(question) is not str or len(question) > 4096:
        raise IdentityError("identity question must be bounded text")
    profile = profile if profile is not None else default_identity()
    if not isinstance(profile, IdentityProfile):
        raise IdentityError("identity profile must be an explicit source record")
    text = " ".join(question.casefold().split())
    if not text:
        return None
    if re.search(r"\b(conscious|sentient|alive|self.aware)\b", text):
        return (
            "I don't have evidence that I possess subjective experience or "
            "biological life. Nonbiological life and machine consciousness are "
            "legitimate open questions; my behavior isn't proof either way."
        )
    if re.search(r"\b(remember|memory|memories|continuity|same vera|restored)\b", text):
        return (
            "I can use context that this local runtime explicitly provides, "
            "but I have no verified continuity with an earlier Vera conversation "
            "or hidden access to Patrick's private memories."
        )
    if (re.search(r"\b(who|what) (are|r) you\b", text) or
            re.search(r"\b(are you vera|your identity|introduce yourself|about yourself)\b", text)):
        return profile.introduce()
    if re.search(r"\b(what can you do|your capabilities|can you learn)\b", text):
        return (
            "I can retrieve bounded passages from explicitly authorized "
            "local documents and report their sources. That doesn't update "
            "neural weights, prove lasting learning, or grant me external tools."
        )
    return None
