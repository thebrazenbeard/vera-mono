"""Default-off, *synthetic-only* supervised feedback journal.

This journal does not train model weights, admit memories, capture conversations,
or authorize actions. A separately protected reviewer public key and a separately
protected journal-head checkpoint are mandatory trust anchors. The signer private
key MUST live in a broker outside the model process. Possession of that key is
NOT by itself evidence of human consent, identity, or privacy review.

This is an evaluation fixture; no production/private-data ingestion is enabled.
The caller's synthetic/consent/privacy/provenance assertions are not verified.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import hmac
import json
from pathlib import Path
import os
import secrets
import sqlite3
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .local_feedback_learning import (
    FeedbackSample, HeldoutCase, LearningBlocked, LocalFeedbackEvaluation,
    LocalFeedbackLearner,
)


_PROJECT_ID = "vera-mono"
_PURPOSE = "vera.synthetic-supervised-feedback.v1"
_ACTIONS = frozenset(("APPROVE", "ROLLBACK", "REVOKE"))
_MAX_EVENTS = 512


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(obj: object) -> str:
    return sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _text(value: str, name: str, limit: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit or any(
        0xD800 <= ord(c) <= 0xDFFF for c in value
    ):
        raise LearningBlocked(f"{name} must be a bounded non-empty Unicode scalar string")
    return value


def _event_hash(prior: str, kind: str, payload: dict[str, Any]) -> str:
    return _digest({"domain": _PURPOSE + ".event", "prior": prior, "kind": kind, "payload": payload})


def _evaluation_dict(evidence: LocalFeedbackEvaluation) -> dict[str, Any]:
    return json.loads(_canonical(asdict(evidence)))


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """Action-specific challenge; its signature is supplied by an external broker."""

    purpose: str
    project_id: str
    installation_id: str
    journal_id: str
    reviewer_key_sha256: str
    action: str
    candidate_revision: str
    baseline_revision: str
    heldout_sha256: str
    evaluation_sha256: str
    expected_journal_head: str
    approval_ref: str
    nonce: str
    issued_at: int
    expires_at: int
    signature: str = ""

    def signable_bytes(self) -> bytes:
        payload = {field.name: getattr(self, field.name) for field in fields(self) if field.name != "signature"}
        return _canonical(payload).encode("utf-8")


@dataclass(slots=True)
class _State:
    learner: LocalFeedbackLearner
    head: str
    journal_id: str
    pending_evaluation: LocalFeedbackEvaluation | None
    approved_order: list[str]
    revoked: set[str]
    used_refs: set[str]
    used_nonces: set[str]
    event_count: int


class SupervisedFeedbackJournal:
    """Review-gated retrieval correction, replayed from a bounded SQLite journal.

    An existing database *cannot* be opened without its out-of-band, trusted
    high-watermark checkpoint. Persist a new `head` in a differently protected
    control plane after every accepted operation; do not store it alongside this
    writable database or give the model write access to it. If the checkpoint
    update fails, do not regard the operation as durably committed.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        installation_id: str,
        trusted_reviewer_key: bytes,
        trusted_checkpoint_head: str | None = None,
        synthetic_fixture_mode: bool = False,
    ) -> None:
        if synthetic_fixture_mode is not True:
            raise LearningBlocked("production feedback is disabled; synthetic fixture only")
        self.installation_id = _text(installation_id, "installation_id", 128)
        if type(trusted_reviewer_key) is not bytes or len(trusted_reviewer_key) != 32:
            raise LearningBlocked("trusted review key must be a pinned raw 32-byte Ed25519 public key")
        self._key = trusted_reviewer_key
        self._reviewer = Ed25519PublicKey.from_public_bytes(self._key)
        self._fingerprint = sha256(self._key).hexdigest()
        self.path = Path(path).absolute()
        # Resolve nothing before checking: a symlink/junction in any ancestor
        # could redirect the journal outside the expected host-managed root.
        for component in (self.path, *self.path.parents):
            if component.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(component)):
                raise LearningBlocked("journal path/ancestor must not be a symlink or junction")
        if not self.path.parent.is_dir():
            raise LearningBlocked("journal parent must already exist")
        exists = self.path.exists()
        if exists and self.path.stat().st_nlink > 1:
            raise LearningBlocked("hard-linked journal is prohibited")
        if exists and trusted_checkpoint_head is None:
            raise LearningBlocked("existing journal requires externally pinned checkpoint")
        if not exists and trusted_checkpoint_head is not None:
            raise LearningBlocked("checkpoint supplied for missing journal")
        if exists and self.path.stat().st_size == 0:
            raise LearningBlocked("empty preexisting journal is not initialized")
        with closing(self._connection()) as db:
            if not exists:
                db.executescript("""
                    CREATE TABLE feedback_meta (name TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
                    CREATE TABLE feedback_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        kind TEXT NOT NULL,
                        prior_head TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        event_hash TEXT NOT NULL
                    );
                """)
                for name, value in {
                    "schema": "1", "project_id": _PROJECT_ID,
                    "installation_id": self.installation_id,
                    "journal_id": secrets.token_hex(16),
                    "reviewer_key_sha256": self._fingerprint,
                }.items():
                    db.execute("INSERT INTO feedback_meta VALUES (?,?)", (name, value))
                db.commit()
            self._state = self._replay(db, trusted_checkpoint_head)

    def _connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=10.0)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @property
    def head(self) -> str:
        return self._state.head

    @property
    def active_revision(self) -> str:
        return self._state.learner.active_revision

    @property
    def revoked_revisions(self) -> tuple[str, ...]:
        return tuple(sorted(self._state.revoked))

    def lookup(self, cue: str) -> str | None:
        """Exact-cue retrieval; deny stale resident state after external revocation.

        Replaying and comparing the locally cached checkpoint on *every read*
        prevents a long-lived model consumer from indefinitely serving a version
        revoked by another process. It is not an atomic downstream-generation
        lease: a writer can revoke immediately after this check. A production
        broker would need a separately protected operation/lease boundary.
        """
        with closing(self._connection()) as db:
            self._replay(db, self._state.head)
        return self._state.learner.lookup(cue)

    def _replay(self, db: sqlite3.Connection, checkpoint: str | None) -> _State:
        try:
            meta = dict(db.execute("SELECT name, value FROM feedback_meta").fetchall())
            required = {"schema", "project_id", "installation_id", "journal_id", "reviewer_key_sha256"}
            if set(meta) != required or meta["schema"] != "1" or meta["project_id"] != _PROJECT_ID:
                raise LearningBlocked("journal integrity: invalid metadata schema or project")
            if meta["installation_id"] != self.installation_id:
                raise LearningBlocked("journal scope/installation mismatch")
            if not hmac.compare_digest(meta["reviewer_key_sha256"], self._fingerprint):
                raise LearningBlocked("trusted review key mismatch; rotation requires external migration")
            journal_id = _text(meta["journal_id"], "journal_id", 128)
            if len(journal_id) != 32 or any(ch not in "0123456789abcdef" for ch in journal_id):
                raise LearningBlocked("journal integrity: invalid journal id")
            genesis = _digest({"domain": _PURPOSE + ".genesis", "journal_id": journal_id})
            state = _State(LocalFeedbackLearner(), genesis, journal_id, None, [], set(), set(), set(), 0)
            events = db.execute("SELECT sequence, kind, prior_head, payload_json, event_hash FROM feedback_events ORDER BY sequence").fetchall()
            if len(events) > _MAX_EVENTS:
                raise LearningBlocked("journal integrity: event bound exceeded")
            for seq, kind, prior, payload_json, event_hash in events:
                if type(seq) is not int or seq != state.event_count + 1 or kind not in ("STAGE", *_ACTIONS):
                    raise LearningBlocked("journal integrity: noncontiguous or unknown event")
                if type(payload_json) is not str or len(payload_json) > 300_000:
                    raise LearningBlocked("journal integrity: malformed payload size")
                payload = json.loads(payload_json)
                if type(payload) is not dict or _canonical(payload) != payload_json or prior != state.head:
                    raise LearningBlocked("journal integrity: noncanonical payload or broken link")
                if event_hash != _event_hash(prior, kind, payload):
                    raise LearningBlocked("journal integrity: event hash mismatch")
                self._apply_event(state, kind, payload, historical=True)
                state.head = event_hash
                state.event_count += 1
            if checkpoint is not None and not hmac.compare_digest(state.head, checkpoint):
                raise LearningBlocked("journal checkpoint mismatch: truncated, altered or stale history")
            return state
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            if isinstance(exc, LearningBlocked):
                raise
            raise LearningBlocked("journal integrity: invalid event, schema, or replay") from exc

    def _apply_event(self, state: _State, kind: str, payload: dict[str, Any], *, historical: bool) -> str | None:
        learner = state.learner
        if kind == "STAGE":
            if set(payload) != {"samples", "holdout", "evaluation"}:
                raise LearningBlocked("journal integrity: invalid stage fields")
            samples = tuple(FeedbackSample(**row) for row in payload["samples"])
            holdout = tuple(HeldoutCase(**row) for row in payload["holdout"])
            candidate = learner.stage(samples)
            evidence = learner.evaluate(candidate, holdout)
            if not evidence.qualified or _evaluation_dict(evidence) != payload["evaluation"]:
                raise LearningBlocked("journal integrity: staged evidence failed deterministic replay")
            state.pending_evaluation = evidence
            return candidate
        if set(payload) != {"review"} or type(payload["review"]) is not dict:
            raise LearningBlocked("journal integrity: review envelope missing")
        review = ReviewDecision(**payload["review"])
        self._verify_review(state, kind, review, historical=historical)
        if kind == "APPROVE":
            evidence = state.pending_evaluation
            if evidence is None:
                raise LearningBlocked("review lacks staged evaluation")
            learner.approve(evidence, approval_ref=review.approval_ref)
            state.approved_order.append(review.candidate_revision)
            state.pending_evaluation = None
        elif kind == "ROLLBACK":
            learner.rollback(review.candidate_revision, approval_ref=review.approval_ref)
            state.pending_evaluation = None
        else:  # REVOKE: cannot resurrect a revoked version with later rollback.
            state.revoked.add(review.candidate_revision)
            if learner.active_revision == review.candidate_revision:
                fallback = next(
                    (revision for revision in reversed(state.approved_order)
                     if revision not in state.revoked),
                    next(iter(learner._versions)),
                )
                learner.rollback(fallback, approval_ref=review.approval_ref)
            state.pending_evaluation = None
        state.used_refs.add(review.approval_ref)
        state.used_nonces.add(review.nonce)
        return learner.active_revision

    def _verify_review(self, state: _State, kind: str, review: ReviewDecision, *, historical: bool) -> None:
        if type(review) is not ReviewDecision or kind not in _ACTIONS or review.action != kind:
            raise LearningBlocked("review action mismatch")
        if (review.purpose, review.project_id, review.installation_id, review.journal_id) != (
            _PURPOSE, _PROJECT_ID, self.installation_id, state.journal_id,
        ) or review.reviewer_key_sha256 != self._fingerprint:
            raise LearningBlocked("review scope/key identity mismatch")
        if review.expected_journal_head != state.head or review.baseline_revision != state.learner.active_revision:
            raise LearningBlocked("review is stale or bound to another journal head")
        _text(review.approval_ref, "approval_ref")
        if review.approval_ref in state.used_refs:
            raise LearningBlocked("review reference has been consumed")
        if type(review.nonce) is not str or len(review.nonce) != 32 or any(c not in "0123456789abcdef" for c in review.nonce):
            raise LearningBlocked("review nonce is invalid")
        if review.nonce in state.used_nonces:
            raise LearningBlocked("review nonce has already been consumed")
        if type(review.issued_at) is not int or type(review.expires_at) is not int or not 0 < review.expires_at - review.issued_at <= 600:
            raise LearningBlocked("review timestamp window is invalid")
        if not historical:
            now = int(time.time())
            if review.issued_at > now + 30 or review.expires_at < now:
                raise LearningBlocked("review timestamp expired or from the future")
        if type(review.signature) is not str or len(review.signature) != 128:
            raise LearningBlocked("review signature missing or malformed")
        try:
            self._reviewer.verify(bytes.fromhex(review.signature), review.signable_bytes())
        except (InvalidSignature, ValueError) as exc:
            raise LearningBlocked("review signature verification failed") from exc
        if kind == "APPROVE":
            evidence = state.pending_evaluation
            if evidence is None or not evidence.qualified or review.candidate_revision != evidence.candidate_revision:
                raise LearningBlocked("review has no current qualified candidate")
            if review.heldout_sha256 != evidence.heldout_sha256 or review.evaluation_sha256 != _digest(_evaluation_dict(evidence)):
                raise LearningBlocked("review heldout/evaluation hash mismatch")
            if review.candidate_revision in state.revoked:
                raise LearningBlocked("revoked correction cannot be promoted")
        else:
            if review.heldout_sha256 or review.evaluation_sha256:
                raise LearningBlocked("rollback/revoke must not include stale evaluation")
            genesis = next(iter(state.learner._versions))
            allowed = review.candidate_revision in state.approved_order or (
                kind == "ROLLBACK" and review.candidate_revision == genesis
            )
            if not allowed or review.candidate_revision in state.revoked:
                raise LearningBlocked("target is not an unrevoked approved revision")
            if kind == "ROLLBACK" and review.candidate_revision == state.learner.active_revision:
                raise LearningBlocked("rollback must change active revision")

    def _append(self, kind: str, payload: dict[str, Any]) -> None:
        if self._state.event_count >= _MAX_EVENTS:
            raise LearningBlocked("journal event bound exceeded")
        prior = self._state.head
        event_hash = _event_hash(prior, kind, payload)
        with closing(self._connection()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current = self._replay(db, prior)
                if current.head != prior or current.event_count != self._state.event_count:
                    raise LearningBlocked("concurrent journal update; reopen from trusted checkpoint")
                self._apply_event(current, kind, payload, historical=False)
                db.execute(
                    "INSERT INTO feedback_events(kind,prior_head,payload_json,event_hash) VALUES(?,?,?,?)",
                    (kind, prior, _canonical(payload), event_hash),
                )
                db.commit()
                current.head = event_hash
                current.event_count += 1
                self._state = current
            except Exception:
                db.rollback()
                raise

    def stage(self, samples: tuple[FeedbackSample, ...], holdout: tuple[HeldoutCase, ...]) -> LocalFeedbackEvaluation:
        """Stage qualified synthetic samples; pending content cannot affect lookup."""
        # Work on a replayed copy: even exceptions from invalid samples must not
        # arm or replace a previously evaluated pending review in this process.
        with closing(self._connection()) as db:
            provisional = self._replay(db, self._state.head)
        candidate = provisional.learner.stage(samples)
        evidence = provisional.learner.evaluate(candidate, holdout)
        if not evidence.qualified:
            raise LearningBlocked("candidate failed holdout; no journal write or review allowed")
        payload = {
            "samples": [asdict(s) for s in samples],
            "holdout": [asdict(h) for h in holdout],
            "evaluation": _evaluation_dict(evidence),
        }
        self._append("STAGE", payload)
        return evidence

    def review_challenge(
        self,
        *,
        action: str,
        revision: str,
        approval_ref: str,
        expires_in_seconds: int = 300,
    ) -> ReviewDecision:
        """Prepare but do not sign an exact action/scope/revision bound challenge."""
        _text(approval_ref, "approval_ref")
        if approval_ref in self._state.used_refs:
            raise LearningBlocked("review reference already consumed")
        if action not in _ACTIONS or type(revision) is not str:
            raise LearningBlocked("unsupported review action or target")
        if type(expires_in_seconds) is not int or not 1 <= expires_in_seconds <= 600:
            raise LearningBlocked("review expiration must be 1..600 seconds")
        evidence = self._state.pending_evaluation
        if action == "APPROVE":
            if evidence is None or revision != evidence.candidate_revision or not evidence.qualified:
                raise LearningBlocked("review requires a qualified pending candidate")
            heldout_digest = evidence.heldout_sha256
            evaluation_digest = _digest(_evaluation_dict(evidence))
        else:
            genesis = next(iter(self._state.learner._versions))
            allowed = revision in self._state.approved_order or (action == "ROLLBACK" and revision == genesis)
            if not allowed or revision in self._state.revoked:
                raise LearningBlocked("review requires an unrevoked previously approved version")
            if action == "ROLLBACK" and revision == self.active_revision:
                raise LearningBlocked("rollback must change active version")
            heldout_digest = evaluation_digest = ""
        now = int(time.time())
        return ReviewDecision(
            purpose=_PURPOSE, project_id=_PROJECT_ID, installation_id=self.installation_id,
            journal_id=self._state.journal_id, reviewer_key_sha256=self._fingerprint,
            action=action, candidate_revision=revision, baseline_revision=self.active_revision,
            heldout_sha256=heldout_digest, evaluation_sha256=evaluation_digest,
            expected_journal_head=self.head, approval_ref=approval_ref,
            nonce=secrets.token_hex(16), issued_at=now, expires_at=now + expires_in_seconds,
        )

    def apply_review(self, signed_review: ReviewDecision) -> str:
        """Verify exact external signature, journal action, and replay constraints."""
        if type(signed_review) is not ReviewDecision:
            raise LearningBlocked("review must be an exact signed ReviewDecision")
        payload = {"review": asdict(signed_review)}
        self._append(signed_review.action, payload)
        return self.active_revision
