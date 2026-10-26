"""Explicitly synthetic, non-production Ollama + signed-journal acceptance probe.

This fixture demonstrates retrieval-mediated correction across separate Python
processes. It does not authenticate a human, prove generalization, or train
weights. The deterministic signer is public TEST MATERIAL, never a credential.
Do not point this at private memory or a production state directory.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from vera_memory.local_feedback_learning import FeedbackSample, HeldoutCase
from vera_memory.supervised_feedback import SupervisedFeedbackJournal


SYNTHETIC_LEDGER = "TEST-CERULEAN-74093"
CUE = f"In the invented synthetic ledger {SYNTHETIC_LEDGER}, what is the stored token for the marker QUARTZ?"
PARAPHRASE = f"Please retrieve QUARTZ's token from the made-up {SYNTHETIC_LEDGER} record."
ANSWER = "violet-otter-739"
INSTALLATION = "lappy-synthetic-model-probe-only"
TEST_SIGNER = Ed25519PrivateKey.from_private_bytes(bytes([0x42]) * 32)
TEST_PUBLIC_KEY = TEST_SIGNER.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _scope(path: Path) -> None:
    if os.name == "nt":
        permitted = Path(r"D:\VERA\bt2-localai-20261026").resolve()
        candidate = path.resolve()
        if permitted not in candidate.parents:
            raise ValueError("fixture DB must stay beneath D:\\VERA\\bt2-localai-20261026")
    if not path.parent.is_dir():
        raise ValueError("fixture DB parent does not exist")


def _open(path: Path, head: str | None) -> SupervisedFeedbackJournal:
    _scope(path)
    return SupervisedFeedbackJournal(
        path,
        installation_id=INSTALLATION,
        trusted_reviewer_key=TEST_PUBLIC_KEY,
        trusted_checkpoint_head=head,
        synthetic_fixture_mode=True,
    )


def _model(query: str, answer: str | None, model: str) -> dict:
    system = (
        "You are evaluating an isolated synthetic-memory exercise. "
        "Only reply with the exact stored token if an approved memory record "
        "for the user's exact question is supplied. Otherwise reply UNKNOWN. "
        "Never invent a ledger entry."
    )
    if answer is not None:
        system += f"\nApproved synthetic record for exact question {CUE!r}: token {answer!r}."
    payload = {
        "model": model, "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ],
        "options": {"temperature": 0, "seed": 42, "num_predict": 55},
    }
    req = Request(
        "http://127.0.0.1:11434/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(req, timeout=90) as response:
        result = json.loads(response.read())
    return {
        "answer": result["message"]["content"].strip(),
        "model": result["model"], "eval_count": result.get("eval_count"),
    }


def _signed(journal: SupervisedFeedbackJournal, action: str, revision: str, ref: str):
    unsigned = journal.review_challenge(action=action, revision=revision, approval_ref=ref)
    return replace(unsigned, signature=TEST_SIGNER.sign(unsigned.signable_bytes()).hex())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "stage", "approve", "query", "paraphrase", "revoke", "rollback"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--head", default=None, help="Externally supplied journal checkpoint; never read from the DB")
    parser.add_argument("--model", default="vera-local:latest")
    parser.add_argument("--revision", default=None)
    args = parser.parse_args(argv)
    if os.environ.get("VERA_SYNTHETIC_DEMO_ONLY") != "1":
        raise RuntimeError("set VERA_SYNTHETIC_DEMO_ONLY=1; production use forbidden")
    if args.phase == "baseline":
        print(json.dumps({"phase": "baseline", "retrieved": None, **_model(CUE, None, args.model)}))
        return 0
    journal = _open(args.db, args.head)
    if args.phase == "stage":
        evidence = journal.stage((FeedbackSample(
            sample_id="train-cue-001", source_id="synthetic-training-A", cue=CUE,
            answer=ANSWER, consent_ref="synthetic-only", privacy_review_ref="synthetic-only",
            provenance_ref="invented-fixture",
        ),), (HeldoutCase(
            case_id="heldout-cue-001", source_id="synthetic-test-B", cue=CUE, expected=ANSWER,
        ),))
        output = {"phase": "stage", "head": journal.head, "revision": evidence.candidate_revision,
                  "qualified": evidence.qualified, "baseline_passes": evidence.baseline_passes,
                  "candidate_passes": evidence.candidate_passes,
                  "warning": "holdout shares exact cue; no semantic generalization claim"}
    elif args.phase in ("approve", "revoke", "rollback"):
        if args.revision is None:
            parser.error("--revision required for signed review")
        review = _signed(journal, args.phase.upper(), args.revision, "synthetic-test-" + args.phase)
        journal.apply_review(review)
        output = {"phase": args.phase, "head": journal.head, "active_revision": journal.active_revision,
                  "revoked_revisions": journal.revoked_revisions, "test_signer_only": True}
    else:
        query = CUE if args.phase == "query" else PARAPHRASE
        retrieved = journal.lookup(query)
        output = {"phase": args.phase, "head": journal.head, "retrieved": retrieved,
                  **_model(query, retrieved, args.model)}
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
