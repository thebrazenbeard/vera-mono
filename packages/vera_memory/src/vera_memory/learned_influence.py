"""Revision-bound gate for learned influences.

Adapted from MESO-CRCT association recall/review semantics. A learned
association may influence a current decision only for an exact learned
revision, subject to review state, and at most once per cue event.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class LearnedInfluenceError(ValueError):
    pass


class LearnedInfluenceReplay(LearnedInfluenceError):
    pass


class LearnedInfluenceBlocked(LearnedInfluenceError):
    pass


class LearnedInfluenceStale(LearnedInfluenceError):
    pass


class ReviewDisposition(StrEnum):
    ADMITTED = "ADMITTED"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True, slots=True)
class LearnedRevision:
    association_id: str
    memory_revision_id: str

    def __post_init__(self) -> None:
        for label, value in (
            ("association_id", self.association_id),
            ("memory_revision_id", self.memory_revision_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")


@dataclass(frozen=True, slots=True)
class LearnedInfluenceReceipt:
    association_id: str
    memory_revision_id: str
    cue_event_id: str
    review_disposition: ReviewDisposition
    review_evidence_ref: str | None
    evidence_split_qualified: bool = False
    use_evidence_id: str | None = None
    authorization_effect: str = "NONE"


@dataclass(frozen=True, slots=True)
class SignedLaterOutcome:
    """Externally signed observation for one previously consumed C event.

    Losses are bounded, nonnegative values; smaller is better. A matching
    signature proves key possession, not evaluator independence or outcome truth.
    """

    evaluator_id: str
    association_id: str
    memory_revision_id: str
    cue_event_id: str
    use_evidence_id: str
    outcome_evidence_id: str
    baseline_loss: float
    candidate_loss: float
    signature_hex: str

    def __post_init__(self) -> None:
        for label in (
            "evaluator_id", "association_id", "memory_revision_id",
            "cue_event_id", "use_evidence_id", "outcome_evidence_id",
        ):
            value = getattr(self, label)
            if type(value) is not str or not value or len(value) > 256:
                raise ValueError(f"{label} must be a bounded non-empty string")
        for label in ("baseline_loss", "candidate_loss"):
            value = getattr(self, label)
            if (type(value) is not float or not math.isfinite(value)
                    or not 0 <= value <= 1e9
                    or (value == 0.0 and math.copysign(1.0, value) < 0)):
                raise ValueError(f"{label} must be a finite nonnegative float")
        if (type(self.signature_hex) is not str or len(self.signature_hex) != 128
                or any(c not in "0123456789abcdef" for c in self.signature_hex)):
            raise ValueError("signature_hex must be lowercase Ed25519 signature hex")

    def signing_bytes(self) -> bytes:
        payload = {
            "schema": "VERA_LEARNED_LATER_OUTCOME_V1",
            "evaluator_id": self.evaluator_id,
            "association_id": self.association_id,
            "memory_revision_id": self.memory_revision_id,
            "cue_event_id": self.cue_event_id,
            "use_evidence_id": self.use_evidence_id,
            "outcome_evidence_id": self.outcome_evidence_id,
            "baseline_loss": self.baseline_loss,
            "candidate_loss": self.candidate_loss,
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class LaterOutcomeReceipt:
    association_id: str
    memory_revision_id: str
    use_evidence_id: str
    outcome_evidence_id: str
    negative_transfer: bool
    authorization_effect: str = "NONE"


@dataclass(frozen=True, slots=True)
class _ReviewRecord:
    association_id: str
    memory_revision_id: str
    disposition: ReviewDisposition
    evidence_ref: str


class LearnedInfluenceGate:
    """In-memory admission gate for bounded learned influence consumption.

    This gate does not admit memories or establish truth. It only constrains
    whether an already identified learned revision may influence a particular
    cue event.
    """

    def __init__(self) -> None:
        self._reviews: dict[str, _ReviewRecord] = {}
        self._consumed: set[tuple[str, str, str]] = set()

    def review(
        self,
        *,
        association_id: str,
        memory_revision_id: str,
        disposition: ReviewDisposition,
        evidence_ref: str,
    ) -> None:
        for label, value in (
            ("association_id", association_id),
            ("memory_revision_id", memory_revision_id),
            ("evidence_ref", evidence_ref),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if type(disposition) is not ReviewDisposition:
            raise TypeError("disposition must be exact ReviewDisposition")
        self._reviews[association_id] = _ReviewRecord(
            association_id=association_id,
            memory_revision_id=memory_revision_id,
            disposition=disposition,
            evidence_ref=evidence_ref,
        )

    def consume(
        self,
        revision: LearnedRevision,
        *,
        cue_event_id: str,
    ) -> LearnedInfluenceReceipt:
        if type(revision) is not LearnedRevision:
            raise TypeError("revision must be exact LearnedRevision")
        if type(cue_event_id) is not str or not cue_event_id:
            raise ValueError("cue_event_id must be a non-empty exact string")

        review = self._reviews.get(revision.association_id)
        if review is not None:
            if review.memory_revision_id != revision.memory_revision_id:
                raise LearnedInfluenceStale(
                    "learned revision changed after its latest review"
                )
            if review.disposition is ReviewDisposition.QUARANTINED:
                raise LearnedInfluenceBlocked(
                    "learned revision is quarantined by current review"
                )
            disposition = review.disposition
            evidence_ref = review.evidence_ref
        else:
            raise LearnedInfluenceBlocked(
                "learned revision requires explicit review before influence"
            )

        key = (
            revision.association_id,
            revision.memory_revision_id,
            cue_event_id,
        )
        if key in self._consumed:
            raise LearnedInfluenceReplay(
                "cue event already consumed for this learned revision"
            )
        self._consumed.add(key)

        return LearnedInfluenceReceipt(
            association_id=revision.association_id,
            memory_revision_id=revision.memory_revision_id,
            cue_event_id=cue_event_id,
            review_disposition=disposition,
            review_evidence_ref=evidence_ref,
        )



class DurableLearnedInfluenceGate:
    """SQLite-backed learned-influence gate with restart-stable review/replay state.

    Persistence does not establish truth, correctness, or effect authority.
    It only preserves exact review bindings and cue-consumption fences.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        evaluator_id: str | None = None,
        evaluator_public_key: bytes | None = None,
    ) -> None:
        if (evaluator_id is None) != (evaluator_public_key is None):
            raise ValueError("evaluator identity and public key must be supplied together")
        if evaluator_id is not None:
            if type(evaluator_id) is not str or not evaluator_id or len(evaluator_id) > 256:
                raise ValueError("evaluator_id must be a bounded non-empty string")
            if type(evaluator_public_key) is not bytes or len(evaluator_public_key) != 32:
                raise ValueError("Ed25519 evaluator_public_key must be 32 bytes")
            Ed25519PublicKey.from_public_bytes(evaluator_public_key)
        self._evaluator_id = evaluator_id
        self._evaluator_public_key = evaluator_public_key
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # sqlite3.Connection.__exit__ manages transactions but does not close
        # the descriptor, which blocks temporary database cleanup on Windows.
        with closing(self._connect()) as db, db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS learned_reviews (
                    association_id TEXT PRIMARY KEY,
                    memory_revision_id TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learned_consumptions (
                    association_id TEXT NOT NULL,
                    memory_revision_id TEXT NOT NULL,
                    cue_event_id TEXT NOT NULL,
                    PRIMARY KEY (
                        association_id,
                        memory_revision_id,
                        cue_event_id
                    )
                );
                CREATE TABLE IF NOT EXISTS learned_evidence_bindings (
                    association_id TEXT NOT NULL,
                    memory_revision_id TEXT NOT NULL,
                    evidence_class TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    PRIMARY KEY (
                        association_id,
                        memory_revision_id,
                        evidence_class,
                        evidence_id
                    )
                );
                CREATE TABLE IF NOT EXISTS learned_use_evidence (
                    association_id TEXT NOT NULL,
                    memory_revision_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    PRIMARY KEY (
                        association_id,
                        memory_revision_id,
                        evidence_id
                    )
                );
                CREATE TABLE IF NOT EXISTS learned_use_cue_bindings (
                    association_id TEXT NOT NULL,
                    memory_revision_id TEXT NOT NULL,
                    cue_event_id TEXT NOT NULL,
                    use_evidence_id TEXT NOT NULL,
                    PRIMARY KEY (association_id, memory_revision_id, cue_event_id),
                    UNIQUE (association_id, memory_revision_id, use_evidence_id)
                );
                CREATE TABLE IF NOT EXISTS learned_evidence_history (
                    association_id TEXT NOT NULL,
                    memory_revision_id TEXT NOT NULL,
                    evidence_class TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    PRIMARY KEY (
                        association_id, memory_revision_id, evidence_class, evidence_id
                    )
                );
                CREATE TABLE IF NOT EXISTS learned_outcome_trust (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    evaluator_id TEXT NOT NULL,
                    public_key_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learned_later_outcomes (
                    association_id TEXT NOT NULL,
                    memory_revision_id TEXT NOT NULL,
                    cue_event_id TEXT NOT NULL,
                    use_evidence_id TEXT NOT NULL,
                    outcome_evidence_id TEXT NOT NULL UNIQUE,
                    evaluator_id TEXT NOT NULL,
                    baseline_loss REAL NOT NULL,
                    candidate_loss REAL NOT NULL,
                    signature_hex TEXT NOT NULL,
                    PRIMARY KEY (association_id, memory_revision_id, use_evidence_id)
                );
                """
            )
            # Preserve evidence that is still recoverable when opening an older
            # database. Prior revisions already erased by old UPSERTs cannot
            # be reconstructed, and legacy C uses have no cue-pair proof.
            db.execute(
                """
                INSERT OR IGNORE INTO learned_evidence_history
                SELECT association_id, memory_revision_id, evidence_class, evidence_id
                FROM learned_evidence_bindings
                """
            )
            if evaluator_id is not None:
                digest = hashlib.sha256(evaluator_public_key).hexdigest()
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT evaluator_id, public_key_sha256 FROM learned_outcome_trust WHERE singleton=1"
                ).fetchone()
                if row is None:
                    raise LearnedInfluenceBlocked(
                        "external evaluator trust anchor requires separate host provisioning"
                    )
                if tuple(row) != (evaluator_id, digest):
                    raise LearnedInfluenceBlocked(
                        "outcome evaluator key/identity differs from durable trust pin"
                    )
                db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def review(
        self,
        *,
        association_id: str,
        memory_revision_id: str,
        disposition: ReviewDisposition,
        evidence_ref: str,
    ) -> None:
        for label, value in (
            ("association_id", association_id),
            ("memory_revision_id", memory_revision_id),
            ("evidence_ref", evidence_ref),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if type(disposition) is not ReviewDisposition:
            raise TypeError("disposition must be exact ReviewDisposition")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO learned_reviews(
                    association_id, memory_revision_id, disposition, evidence_ref
                ) VALUES(?,?,?,?)
                ON CONFLICT(association_id) DO UPDATE SET
                    memory_revision_id=excluded.memory_revision_id,
                    disposition=excluded.disposition,
                    evidence_ref=excluded.evidence_ref
                """,
                (
                    association_id,
                    memory_revision_id,
                    disposition.value,
                    evidence_ref,
                ),
            )
            db.execute(
                "DELETE FROM learned_evidence_bindings WHERE association_id=?",
                (association_id,),
            )
            db.commit()

    @staticmethod
    def _evidence_ids(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
        if type(values) is not tuple or not values:
            raise ValueError(f"{field} must be a non-empty tuple")
        if any(type(value) is not str or not value for value in values):
            raise ValueError(f"{field} must contain non-empty exact strings")
        if len(values) != len(set(values)):
            raise ValueError(f"{field} must not contain duplicates")
        return values

    def review_qualified(
        self,
        *,
        association_id: str,
        memory_revision_id: str,
        disposition: ReviewDisposition,
        evidence_ref: str,
        calibration_evidence_ids: tuple[str, ...],
        qualification_evidence_ids: tuple[str, ...],
    ) -> None:
        for label, value in (
            ("association_id", association_id),
            ("memory_revision_id", memory_revision_id),
            ("evidence_ref", evidence_ref),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if type(disposition) is not ReviewDisposition:
            raise TypeError("disposition must be exact ReviewDisposition")
        calibration = self._evidence_ids(
            calibration_evidence_ids,
            field="calibration_evidence_ids",
        )
        qualification = self._evidence_ids(
            qualification_evidence_ids,
            field="qualification_evidence_ids",
        )
        if set(calibration) & set(qualification):
            raise ValueError(
                "calibration and qualification evidence identities must be disjoint"
            )

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO learned_reviews(
                    association_id, memory_revision_id, disposition, evidence_ref
                ) VALUES(?,?,?,?)
                ON CONFLICT(association_id) DO UPDATE SET
                    memory_revision_id=excluded.memory_revision_id,
                    disposition=excluded.disposition,
                    evidence_ref=excluded.evidence_ref
                """,
                (
                    association_id,
                    memory_revision_id,
                    disposition.value,
                    evidence_ref,
                ),
            )
            db.execute(
                "DELETE FROM learned_evidence_bindings WHERE association_id=?",
                (association_id,),
            )
            db.executemany(
                """
                INSERT INTO learned_evidence_bindings(
                    association_id, memory_revision_id, evidence_class, evidence_id
                ) VALUES(?,?,?,?)
                """,
                [
                    (association_id, memory_revision_id, "CALIBRATION", evidence_id)
                    for evidence_id in calibration
                ]
                + [
                    (
                        association_id,
                        memory_revision_id,
                        "QUALIFICATION",
                        evidence_id,
                    )
                    for evidence_id in qualification
                ],
            )
            db.executemany(
                """
                INSERT OR IGNORE INTO learned_evidence_history (
                    association_id, memory_revision_id, evidence_class, evidence_id
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (association_id, memory_revision_id, "CALIBRATION", evidence_id)
                    for evidence_id in calibration
                ] + [
                    (association_id, memory_revision_id, "QUALIFICATION", evidence_id)
                    for evidence_id in qualification
                ],
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def record_later_outcome(
        self, outcome: SignedLaterOutcome,
    ) -> LaterOutcomeReceipt:
        """Persist signed C feedback and quarantine a regressed exact revision.

        The evaluator's public key is pinned from host composition. The gate
        cannot attest the custody, independence, or honesty of that evaluator.
        No positive result grants promotion authority; no automatic rollback
        or model modification occurs.
        """
        if type(outcome) is not SignedLaterOutcome:
            raise TypeError("outcome must be exact SignedLaterOutcome")
        if self._evaluator_id is None or self._evaluator_public_key is None:
            raise LearnedInfluenceBlocked("no pinned external outcome evaluator")
        if outcome.evaluator_id != self._evaluator_id:
            raise LearnedInfluenceBlocked("outcome evaluator identity mismatch")
        try:
            Ed25519PublicKey.from_public_bytes(self._evaluator_public_key).verify(
                bytes.fromhex(outcome.signature_hex), outcome.signing_bytes()
            )
        except InvalidSignature as exc:
            raise LearnedInfluenceBlocked("outcome evaluator signature invalid") from exc

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            pin = db.execute(
                "SELECT evaluator_id, public_key_sha256 FROM learned_outcome_trust WHERE singleton=1"
            ).fetchone()
            if pin is None or tuple(pin) != (
                self._evaluator_id, hashlib.sha256(self._evaluator_public_key).hexdigest()
            ):
                raise LearnedInfluenceBlocked("outcome evaluator trust pin missing/stale")
            consumed = db.execute(
                """
                SELECT 1 FROM learned_consumptions
                WHERE association_id=? AND memory_revision_id=? AND cue_event_id=?
                """,
                (
                    outcome.association_id, outcome.memory_revision_id,
                    outcome.cue_event_id,
                ),
            ).fetchone()
            use = db.execute(
                """
                SELECT 1 FROM learned_use_cue_bindings
                WHERE association_id=? AND memory_revision_id=?
                  AND cue_event_id=? AND use_evidence_id=?
                """,
                (
                    outcome.association_id, outcome.memory_revision_id,
                    outcome.cue_event_id, outcome.use_evidence_id,
                ),
            ).fetchone()
            if consumed is None or use is None:
                raise LearnedInfluenceBlocked(
                    "signed outcome lacks exact previously consumed C event/use"
                )
            # A source/split identifier cannot silently be relabeled as an
            # independently observed outcome identity.
            overlap = db.execute(
                """
                SELECT 1 FROM learned_evidence_history
                WHERE association_id=? AND memory_revision_id=? AND evidence_id=?
                """,
                (
                    outcome.association_id, outcome.memory_revision_id,
                    outcome.outcome_evidence_id,
                ),
            ).fetchone()
            use_overlap = db.execute(
                """
                SELECT 1 FROM learned_use_evidence
                WHERE association_id=? AND memory_revision_id=? AND evidence_id=?
                """,
                (
                    outcome.association_id, outcome.memory_revision_id,
                    outcome.outcome_evidence_id,
                ),
            ).fetchone()
            if overlap or use_overlap:
                raise LearnedInfluenceBlocked(
                    "outcome evidence identity overlaps calibration/qualification/use"
                )
            try:
                db.execute(
                    """
                    INSERT INTO learned_later_outcomes (
                        association_id, memory_revision_id, cue_event_id,
                        use_evidence_id, outcome_evidence_id, evaluator_id,
                        baseline_loss, candidate_loss, signature_hex
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        outcome.association_id, outcome.memory_revision_id,
                        outcome.cue_event_id, outcome.use_evidence_id,
                        outcome.outcome_evidence_id, outcome.evaluator_id,
                        outcome.baseline_loss, outcome.candidate_loss,
                        outcome.signature_hex,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LearnedInfluenceReplay(
                    "signed C outcome already recorded or evidence ID reused"
                ) from exc
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        return LaterOutcomeReceipt(
            association_id=outcome.association_id,
            memory_revision_id=outcome.memory_revision_id,
            use_evidence_id=outcome.use_evidence_id,
            outcome_evidence_id=outcome.outcome_evidence_id,
            negative_transfer=outcome.candidate_loss > outcome.baseline_loss,
        )

    def consume(
        self,
        revision: LearnedRevision,
        *,
        cue_event_id: str,
        use_evidence_id: str | None = None,
        expected_calibration_evidence_ids: tuple[str, ...] | None = None,
    ) -> LearnedInfluenceReceipt:
        if type(revision) is not LearnedRevision:
            raise TypeError("revision must be exact LearnedRevision")
        if type(cue_event_id) is not str or not cue_event_id:
            raise ValueError("cue_event_id must be a non-empty exact string")
        expected_calibration = (
            None
            if expected_calibration_evidence_ids is None
            else self._evidence_ids(
                expected_calibration_evidence_ids,
                field="expected_calibration_evidence_ids",
            )
        )

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            regression = db.execute(
                """
                SELECT 1 FROM learned_later_outcomes
                WHERE association_id=? AND memory_revision_id=?
                  AND candidate_loss > baseline_loss
                LIMIT 1
                """,
                (revision.association_id, revision.memory_revision_id),
            ).fetchone()
            if regression is not None:
                raise LearnedInfluenceBlocked(
                    "later-use negative transfer quarantined this exact learned revision"
                )
            review = db.execute(
                """
                SELECT memory_revision_id, disposition, evidence_ref
                FROM learned_reviews
                WHERE association_id=?
                """,
                (revision.association_id,),
            ).fetchone()
            if review is None:
                raise LearnedInfluenceBlocked(
                    "learned revision requires explicit review before influence"
                )
            if str(review["memory_revision_id"]) != revision.memory_revision_id:
                raise LearnedInfluenceStale(
                    "learned revision changed after its latest review"
                )
            disposition = ReviewDisposition(str(review["disposition"]))
            if disposition is ReviewDisposition.QUARANTINED:
                raise LearnedInfluenceBlocked(
                    "learned revision is quarantined by current review"
                )

            evidence_rows = db.execute(
                """
                SELECT evidence_class, evidence_id
                FROM learned_evidence_bindings
                WHERE association_id=? AND memory_revision_id=?
                ORDER BY evidence_class, evidence_id
                """,
                (revision.association_id, revision.memory_revision_id),
            ).fetchall()
            if expected_calibration is not None:
                bound_calibration = {
                    str(row["evidence_id"])
                    for row in evidence_rows
                    if str(row["evidence_class"]) == "CALIBRATION"
                }
                if bound_calibration != set(expected_calibration):
                    raise LearnedInfluenceBlocked(
                        "reviewed calibration evidence does not match selected artifact"
                    )
            evidence_split_qualified = bool(evidence_rows)
            bound_evidence_ids = {
                str(row["evidence_id"]) for row in evidence_rows
            }
            historical_evidence_ids = {
                str(row["evidence_id"]) for row in db.execute(
                    """
                    SELECT evidence_id FROM learned_evidence_history
                    WHERE association_id=? AND memory_revision_id=?
                    """,
                    (revision.association_id, revision.memory_revision_id),
                ).fetchall()
            }
            if evidence_split_qualified:
                if type(use_evidence_id) is not str or not use_evidence_id:
                    raise LearnedInfluenceBlocked(
                        "qualified learned revision requires later-use evidence identity"
                    )
                if use_evidence_id in (bound_evidence_ids | historical_evidence_ids):
                    raise LearnedInfluenceBlocked(
                        "later-use evidence identity must be disjoint from calibration "
                        "and qualification evidence"
                    )
                try:
                    db.execute(
                        """
                        INSERT INTO learned_use_evidence(
                            association_id, memory_revision_id, evidence_id
                        ) VALUES(?,?,?)
                        """,
                        (
                            revision.association_id,
                            revision.memory_revision_id,
                            use_evidence_id,
                        ),
                    )
                    db.execute(
                        """
                        INSERT INTO learned_use_cue_bindings (
                            association_id, memory_revision_id,
                            cue_event_id, use_evidence_id
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            revision.association_id, revision.memory_revision_id,
                            cue_event_id, use_evidence_id,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise LearnedInfluenceReplay(
                        "later-use evidence identity already consumed for this "
                        "learned revision"
                    ) from exc
            elif use_evidence_id is not None:
                raise LearnedInfluenceBlocked(
                    "later-use evidence identity supplied without qualified review"
                )

            try:
                db.execute(
                    """
                    INSERT INTO learned_consumptions(
                        association_id, memory_revision_id, cue_event_id
                    ) VALUES(?,?,?)
                    """,
                    (
                        revision.association_id,
                        revision.memory_revision_id,
                        cue_event_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise LearnedInfluenceReplay(
                    "cue event already consumed for this learned revision"
                ) from exc
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

        return LearnedInfluenceReceipt(
            association_id=revision.association_id,
            memory_revision_id=revision.memory_revision_id,
            cue_event_id=cue_event_id,
            review_disposition=disposition,
            review_evidence_ref=str(review["evidence_ref"]),
            evidence_split_qualified=evidence_split_qualified,
            use_evidence_id=use_evidence_id,
        )
