"""Process-isolated synthetic challenge custodian for Goal 1 experiments.

The JSON-line CLI is intended to be called by a separate learner process. It
keeps labels out of issue responses, assigns commit order itself, returns
training feedback only after a committed prediction, and persists one-use
state in SQLite. This is a protocol prototype, NOT a security boundary against
a same-user/same-host process that can read or rewrite the database.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import random
import secrets
import sqlite3
import sys
from typing import Any

TRAIN_BITS = ("000", "100", "010", "001")
HOLDOUT_BITS = ("110", "101", "011", "111")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def connect(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS challenge (
            challenge_id TEXT PRIMARY KEY,
            ordinal INTEGER NOT NULL UNIQUE,
            phase TEXT NOT NULL CHECK(phase IN ('train','holdout')),
            feature_bits TEXT NOT NULL,
            expected_label TEXT NOT NULL CHECK(expected_label IN ('A','B')),
            state TEXT NOT NULL CHECK(state IN ('NEW','ISSUED','COMMITTED','FEEDBACK','SCORED')),
            candidate_id TEXT,
            prediction TEXT,
            p_a REAL,
            commit_seq INTEGER,
            feedback_seq INTEGER
        );
        CREATE TABLE IF NOT EXISTS event (
            seq INTEGER PRIMARY KEY,
            event_json TEXT NOT NULL,
            previous_digest TEXT NOT NULL,
            digest TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    return db


def append_event(db: sqlite3.Connection, event: dict[str, Any]) -> int:
    last = db.execute("SELECT seq, digest FROM event ORDER BY seq DESC LIMIT 1").fetchone()
    seq = 1 if last is None else int(last["seq"]) + 1
    previous = "0" * 64 if last is None else str(last["digest"])
    digest = hashlib.sha256(canonical({"seq": seq, "event": event, "previous_digest": previous})).hexdigest()
    db.execute(
        "INSERT INTO event(seq,event_json,previous_digest,digest) VALUES(?,?,?,?)",
        (seq, canonical(event).decode("utf-8"), previous, digest),
    )
    return seq


def initialize_if_empty(db: sqlite3.Connection, test_seed: int | None) -> None:
    if db.execute("SELECT 1 FROM challenge LIMIT 1").fetchone() is not None:
        return
    seed = secrets.randbits(64) if test_seed is None else test_seed
    rng = random.Random(seed)
    mask = rng.randrange(1, 8)
    bias = rng.randrange(2)
    specs = [("train", bits) for bits in TRAIN_BITS] + [("holdout", bits) for bits in HOLDOUT_BITS]
    truth_digest_rows = []
    for ordinal, (phase, bits) in enumerate(specs):
        parity = sum(int(bit) * ((mask >> i) & 1) for i, bit in enumerate(bits)) % 2
        label = "B" if (parity ^ bias) else "A"
        challenge_id = secrets.token_hex(16)
        db.execute(
            "INSERT INTO challenge(challenge_id,ordinal,phase,feature_bits,expected_label,state) VALUES(?,?,?,?,?,'NEW')",
            (challenge_id, ordinal, phase, bits, label),
        )
        truth_digest_rows.append((challenge_id, label))
    truth_digest = hashlib.sha256(canonical(sorted(truth_digest_rows))).hexdigest()
    db.execute("INSERT INTO meta(key,value) VALUES('truth_digest',?)", (truth_digest,))
    append_event(db, {"kind": "suite_initialized", "challenge_count": len(specs), "truth_digest": truth_digest})


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_request_json(line: str) -> object:
    return json.loads(line, object_pairs_hook=reject_duplicate_keys)


def validate_request(request: object) -> dict[str, Any]:
    if type(request) is not dict or type(request.get("op")) is not str:
        raise ValueError("request must be an object with string op")
    op = request["op"]
    allowed = {
        "issue": {"op"},
        "commit": {"op", "challenge_id", "candidate_id", "prediction", "p_a"},
        "feedback": {"op", "challenge_id"},
        "score_holdout": {"op"},
    }
    if op not in allowed:
        raise ValueError("unknown operation")
    if set(request) != allowed[op]:
        raise ValueError("unexpected or missing request fields")
    if op in ("commit", "feedback"):
        if type(request["challenge_id"]) is not str or not request["challenge_id"]:
            raise ValueError("challenge_id must be a non-empty string")
    if op == "commit":
        if type(request["candidate_id"]) is not str or not request["candidate_id"]:
            raise ValueError("candidate_id must be a non-empty string")
        if request["prediction"] not in ("A", "B", "ABSTAIN"):
            raise ValueError("prediction must be A, B, or ABSTAIN")
        p_a = request["p_a"]
        if type(p_a) not in (int, float) or not math.isfinite(p_a) or not 0 <= p_a <= 1:
            raise ValueError("p_a must be a finite probability in [0,1]")
    return request


def verify_integrity(db: sqlite3.Connection) -> None:
    previous = "0" * 64
    for expected_seq, row in enumerate(db.execute("SELECT seq,event_json,previous_digest,digest FROM event ORDER BY seq"), start=1):
        event = json.loads(row["event_json"])
        computed = hashlib.sha256(canonical({"seq": row["seq"], "event": event, "previous_digest": previous})).hexdigest()
        if row["seq"] != expected_seq or row["previous_digest"] != previous or row["digest"] != computed:
            raise ValueError("controller event-journal integrity failure")
        previous = row["digest"]
    truth_rows = db.execute("SELECT challenge_id,expected_label FROM challenge ORDER BY challenge_id").fetchall()
    actual_truth_digest = hashlib.sha256(canonical(sorted((row["challenge_id"], row["expected_label"]) for row in truth_rows))).hexdigest()
    stored = db.execute("SELECT value FROM meta WHERE key='truth_digest'").fetchone()
    if stored is None or stored["value"] != actual_truth_digest:
        raise ValueError("controller truth-store integrity failure")


def handle(db_path: str | Path, raw_request: object, *, test_seed: int | None = None) -> dict[str, Any]:
    request = validate_request(raw_request)
    if test_seed is not None and os.environ.get("VERA_EVAL_TEST_MODE") != "1":
        raise ValueError("--test-seed is only allowed when VERA_EVAL_TEST_MODE=1")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        initialize_if_empty(db, test_seed)
        verify_integrity(db)
        op = request["op"]

        if op == "issue":
            # The controller, not the caller, owns phase order. Do not issue a
            # second training case until the prior case's feedback is consumed.
            pending_train = db.execute(
                "SELECT * FROM challenge WHERE phase='train' AND state IN ('ISSUED','COMMITTED') ORDER BY ordinal LIMIT 1"
            ).fetchone()
            if pending_train is not None:
                if pending_train["state"] == "COMMITTED":
                    raise ValueError("training feedback must be consumed before the next challenge")
                row = pending_train
                phase = "train"
            else:
                remaining_train = db.execute(
                    "SELECT COUNT(*) FROM challenge WHERE phase='train' AND state!='FEEDBACK'"
                ).fetchone()[0]
                if remaining_train:
                    row = db.execute(
                        "SELECT * FROM challenge WHERE phase='train' AND state='NEW' ORDER BY ordinal LIMIT 1"
                    ).fetchone()
                    phase = "train"
                else:
                    pending_holdout = db.execute(
                        "SELECT * FROM challenge WHERE phase='holdout' AND state='ISSUED' ORDER BY ordinal LIMIT 1"
                    ).fetchone()
                    if pending_holdout is not None:
                        row = pending_holdout
                        phase = "holdout"
                    else:
                        row = db.execute(
                            "SELECT * FROM challenge WHERE phase='holdout' AND state='NEW' ORDER BY ordinal LIMIT 1"
                        ).fetchone()
                        phase = "holdout"
            if row is None:
                raise ValueError("no unused challenge remains")
            if row["state"] == "NEW":
                append_event(db, {"kind": "challenge_issued", "challenge_id": row["challenge_id"], "phase": phase})
                db.execute("UPDATE challenge SET state='ISSUED' WHERE challenge_id=?", (row["challenge_id"],))
            return {"ok": True, "challenge_id": row["challenge_id"], "features": [f"bits:{row['feature_bits']}"]}

        if op == "commit":
            row = db.execute("SELECT * FROM challenge WHERE challenge_id=?", (request["challenge_id"],)).fetchone()
            if row is None or row["state"] != "ISSUED":
                raise ValueError("unknown, unissued, or already-used challenge")
            existing = db.execute("SELECT value FROM meta WHERE key='candidate_id'").fetchone()
            if existing is not None and existing["value"] != request["candidate_id"]:
                raise ValueError("candidate identity is fixed for this evaluator run")
            db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('candidate_id',?)", (request["candidate_id"],))
            commit_seq = append_event(db, {"kind": "prediction_committed", "challenge_id": row["challenge_id"], "candidate_id": request["candidate_id"], "prediction": request["prediction"], "p_a": float(request["p_a"])})
            db.execute(
                "UPDATE challenge SET state='COMMITTED',candidate_id=?,prediction=?,p_a=?,commit_seq=? WHERE challenge_id=? AND state='ISSUED'",
                (request["candidate_id"], request["prediction"], float(request["p_a"]), commit_seq, row["challenge_id"]),
            )
            return {"ok": True, "commit_sequence": commit_seq, "budget_units": 1}

        if op == "feedback":
            row = db.execute("SELECT * FROM challenge WHERE challenge_id=?", (request["challenge_id"],)).fetchone()
            if row is None or row["phase"] != "train" or row["state"] != "COMMITTED":
                raise ValueError("training feedback requires one committed training prediction and is one-use")
            feedback_seq = append_event(db, {"kind": "training_feedback_released", "challenge_id": row["challenge_id"], "label_digest": hashlib.sha256(row["expected_label"].encode()).hexdigest()})
            db.execute("UPDATE challenge SET state='FEEDBACK',feedback_seq=? WHERE challenge_id=? AND state='COMMITTED'", (feedback_seq, row["challenge_id"]))
            return {"ok": True, "label": row["expected_label"], "feedback_sequence": feedback_seq}

        if op == "score_holdout":
            rows = db.execute("SELECT * FROM challenge WHERE phase='holdout' ORDER BY ordinal").fetchall()
            if not rows or any(row["state"] != "COMMITTED" for row in rows):
                raise ValueError("all held-out predictions must be committed before aggregate scoring")
            correct = sum(row["prediction"] == row["expected_label"] and row["prediction"] != "ABSTAIN" for row in rows)
            answered = sum(row["prediction"] != "ABSTAIN" for row in rows)
            brier = sum((float(row["p_a"]) - (1.0 if row["expected_label"] == "A" else 0.0)) ** 2 for row in rows) / len(rows)
            budget = db.execute("SELECT COUNT(*) FROM challenge WHERE commit_seq IS NOT NULL").fetchone()[0]
            score = {
                "ok": True,
                "scored_cases": len(rows),
                "correct": correct,
                "accuracy": correct / len(rows),
                "coverage": answered / len(rows),
                "selective_accuracy": (correct / answered) if answered else None,
                "brier_score": brier,
                "budget_units": budget,
            }
            append_event(db, {"kind": "holdout_batch_scored", **score})
            db.execute("UPDATE challenge SET state='SCORED' WHERE phase='holdout' AND state='COMMITTED'")
            return score
    raise ValueError("unreachable operation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--test-seed", type=int, default=None, help="test-only deterministic suite seed")
    args = parser.parse_args()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = parse_request_json(line)
            result = handle(args.db, request, test_seed=args.test_seed)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, sqlite3.Error) as exc:
            result = {"ok": False, "error": str(exc)}
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
