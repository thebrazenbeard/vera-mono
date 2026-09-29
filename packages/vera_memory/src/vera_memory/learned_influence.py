"""Revision-bound gate for learned influences.

Adapted from MESO-CRCT association recall/review semantics. A learned
association may influence a current decision only for an exact learned
revision, subject to review state, and at most once per cue event.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import sqlite3


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

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
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
                """
            )

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
        with self._connect() as db:
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
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def consume(
        self,
        revision: LearnedRevision,
        *,
        cue_event_id: str,
        use_evidence_id: str | None = None,
    ) -> LearnedInfluenceReceipt:
        if type(revision) is not LearnedRevision:
            raise TypeError("revision must be exact LearnedRevision")
        if type(cue_event_id) is not str or not cue_event_id:
            raise ValueError("cue_event_id must be a non-empty exact string")

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
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
            evidence_split_qualified = bool(evidence_rows)
            bound_evidence_ids = {
                str(row["evidence_id"]) for row in evidence_rows
            }
            if evidence_split_qualified:
                if type(use_evidence_id) is not str or not use_evidence_id:
                    raise LearnedInfluenceBlocked(
                        "qualified learned revision requires later-use evidence identity"
                    )
                if use_evidence_id in bound_evidence_ids:
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
