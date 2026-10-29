"""Synthetic Goal 1 evaluator scaffold.

This is a falsification harness, not an independent trust service. It keeps
answer labels out of the learner-facing case object and scores only against
an evaluator-owned answer map. A hostile same-privilege process can still
inspect/alter this Python process or its storage; real independent custody
requires a separate controller/host security boundary.
"""
from __future__ import annotations
from dataclasses import dataclass
from contextlib import closing
import hashlib, json, sqlite3
from pathlib import Path
from typing import Iterable, Mapping


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PublicCase:
    case_id: str
    family: str
    features: tuple[str, ...]
    split: str
    rule_version: str

    def learner_view(self) -> dict[str, object]:
        # Evaluator-only metadata (family, split, rule version) must not leak
        # into the learner prompt. Case IDs are opaque and split-independent.
        return {"case_id": self.case_id, "features": list(self.features)}


@dataclass(frozen=True, slots=True)
class PredictionReceipt:
    case_id: str
    candidate_id: str
    prediction: str
    commit_sequence: int
    prompt_digest: str
    budget_units: int
    commitment_sha256: str


@dataclass(frozen=True, slots=True)
class CandidateScore:
    candidate_id: str
    scored_cases: int
    correct: int
    accuracy: float
    budget_units: int


def commit_prediction(*, case: PublicCase, candidate_id: str, prediction: str, commit_sequence: int, budget_units: int) -> PredictionReceipt:
    if not all(type(v) is str and v for v in (candidate_id, prediction)):
        raise ValueError("candidate_id and prediction must be non-empty strings")
    if type(commit_sequence) is not int or commit_sequence < 1:
        raise ValueError("commit_sequence must be a positive exact integer")
    if type(budget_units) is not int or budget_units < 0:
        raise ValueError("budget_units must be a non-negative exact integer")
    prompt_digest = hashlib.sha256(_canonical(case.learner_view())).hexdigest()
    body = {"case_id": case.case_id, "candidate_id": candidate_id, "prediction": prediction, "commit_sequence": commit_sequence, "prompt_digest": prompt_digest, "budget_units": budget_units}
    return PredictionReceipt(**body, commitment_sha256=hashlib.sha256(_canonical(body)).hexdigest())


class Evaluator:
    """Controller-side scorer; truth is not an argument to score().

    Python object privacy is not a security boundary against same-privilege
    hostile code. Do not represent this scaffold as independent custody.
    """
    def __init__(self, cases: Iterable[PublicCase], answer_key: Mapping[str, str], *, qualification_split: str = "qualification"):
        case_list = tuple(cases)
        self._cases = {case.case_id: case for case in case_list}
        if len(self._cases) != len(case_list) or not self._cases:
            raise ValueError("case IDs must be unique and non-empty")
        if type(qualification_split) is not str or not qualification_split:
            raise ValueError("qualification_split must be a non-empty exact string")
        if not any(case.split == qualification_split for case in case_list):
            raise ValueError("qualification_split must identify at least one evaluator-owned case")
        self.__qualification_split = qualification_split
        if set(answer_key) != set(self._cases):
            raise ValueError("answer key must exactly cover evaluator-owned cases")
        if any(type(v) is not str or not v for v in answer_key.values()):
            raise ValueError("answer labels must be non-empty exact strings")
        self.__answer_key = dict(answer_key)
        self._used_candidate_cases: set[tuple[str, str]] = set()

    def public_cases(self, *, split: str) -> tuple[PublicCase, ...]:
        return tuple(c for c in self._cases.values() if c.split == split)

    def score(self, receipts: Iterable[PredictionReceipt], *, outcome_sequence: int) -> CandidateScore:
        rows = tuple(receipts)
        if not rows:
            raise ValueError("at least one prediction receipt is required")
        if type(outcome_sequence) is not int or outcome_sequence < 1:
            raise ValueError("outcome_sequence must be a positive exact integer")
        # Receipt objects are untrusted inputs. Do not rely on the helper or
        # dataclass annotations to have validated their fields.
        for row in rows:
            if type(row) is not PredictionReceipt:
                raise ValueError("every receipt must be a PredictionReceipt")
            for name in ("case_id", "candidate_id", "prediction", "prompt_digest", "commitment_sha256"):
                value = getattr(row, name)
                if type(value) is not str or not value:
                    raise ValueError(f"{name} must be a non-empty exact string")
            if type(row.commit_sequence) is not int or row.commit_sequence < 1:
                raise ValueError("commit_sequence must be a positive exact integer")
            if type(row.budget_units) is not int or row.budget_units < 0:
                raise ValueError("budget_units must be a non-negative exact integer")
        candidate_ids = {r.candidate_id for r in rows}
        if len(candidate_ids) != 1:
            raise ValueError("one candidate per score batch")
        if len({r.case_id for r in rows}) != len(rows):
            raise ValueError("duplicate case/replay in score batch")
        if len({r.commit_sequence for r in rows}) != len(rows):
            raise ValueError("duplicate commit sequence in score batch")
        required_split = self.__qualification_split
        expected_cases = {c.case_id for c in self.public_cases(split=required_split)}
        if {r.case_id for r in rows} != expected_cases:
            raise ValueError("score batch must exactly cover evaluator's required split")
        candidate_id = next(iter(candidate_ids))
        candidate_cases = {(candidate_id, r.case_id) for r in rows}
        if self._used_candidate_cases.intersection(candidate_cases):
            raise ValueError("candidate/challenge replay denied by evaluator instance")
        correct = 0
        for row in rows:
            case = self._cases.get(row.case_id)
            if case is None or case.split != required_split:
                raise ValueError("unknown case or wrong split")
            if row.commit_sequence >= outcome_sequence:
                raise ValueError("prediction was not committed before scoring")
            body = {"case_id": row.case_id, "candidate_id": row.candidate_id, "prediction": row.prediction, "commit_sequence": row.commit_sequence, "prompt_digest": row.prompt_digest, "budget_units": row.budget_units}
            if hashlib.sha256(_canonical(body)).hexdigest() != row.commitment_sha256:
                raise ValueError("prediction commitment mismatch")
            if row.prompt_digest != hashlib.sha256(_canonical(case.learner_view())).hexdigest():
                raise ValueError("prediction is bound to a different public prompt")
            correct += row.prediction == self.__answer_key[row.case_id]
        self._used_candidate_cases.update(candidate_cases)
        return CandidateScore(next(iter(candidate_ids)), len(rows), correct, correct / len(rows), sum(r.budget_units for r in rows))


def make_reversal_suite() -> tuple[tuple[PublicCase, ...], dict[str, str]]:
    """Tiny deterministic rule-reversal sanity fixture, not qualification data."""
    rows, truth = [], {}
    case_number = 0
    for split, family, version, values in (
        ("calibration", "seen-family", "v1", (("red", "A"), ("blue", "B"))),
        ("qualification", "novel-family", "v1", (("circle", "A"), ("square", "B"))),
        ("reversal", "novel-family", "v2", (("circle", "B"), ("square", "A"))),
    ):
        for feature, label in values:
            case_id = f"case-{case_number:03d}"
            case_number += 1
            rows.append(PublicCase(case_id, family, (feature,), split, version))
            truth[case_id] = label
    return tuple(rows), truth


class EventJournal:
    """Restart-readable local journal; its hash chain is not tamper-proof.

    A writer with database access can rewrite rows and recompute the chain.
    This supports reproducibility and cold-reopen testing only.
    """
    def __init__(self, path: str | Path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, event_json TEXT NOT NULL, previous_digest TEXT NOT NULL, digest TEXT NOT NULL)")
        self.read_all()

    def append(self, event: Mapping[str, object]) -> dict[str, object]:
        event_json = _canonical(dict(event)).decode("utf-8")
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute("SELECT seq, digest FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            seq = 1 if last is None else last[0] + 1
            prior = "0" * 64 if last is None else last[1]
            digest = hashlib.sha256(_canonical({"seq": seq, "event": json.loads(event_json), "previous_digest": prior})).hexdigest()
            db.execute("INSERT INTO events(seq,event_json,previous_digest,digest) VALUES(?,?,?,?)", (seq, event_json, prior, digest))
        self.read_all()
        return {"seq": seq, "event": json.loads(event_json), "previous_digest": prior, "digest": digest}

    def read_all(self) -> list[dict[str, object]]:
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT seq,event_json,previous_digest,digest FROM events ORDER BY seq").fetchall()
        prior = "0" * 64
        output = []
        for expected, (seq, event_json, previous, digest) in enumerate(rows, start=1):
            event = json.loads(event_json)
            computed = hashlib.sha256(_canonical({"seq": seq, "event": event, "previous_digest": prior})).hexdigest()
            if seq != expected or previous != prior or digest != computed:
                raise ValueError("evaluation event journal integrity failure")
            output.append({"seq": seq, "event": event, "previous_digest": previous, "digest": digest})
            prior = digest
        return output
