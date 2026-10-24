"""Opt-in Goal 1 gateway-side dispatch fence; never a learner-side Ollama client.

A separately administered endpoint MUST authenticate the gateway and atomically
claim an evaluator-held RESERVED row. This module accepts that selected endpoint
claim callable; it cannot itself authenticate or protect the model-server socket.
All local records are same-host research records, NOT independent testimony.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Callable, Protocol

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = (
    "reservation_id", "run_id", "arm", "challenge_id", "challenge_view_digest",
    "model_prompt_sha256", "model_identity", "model_artifact_sha256",
)
_ARMS = frozenset({"FROZEN", "LEARNED", "PLACEBO", "SHUFFLED"})


def _canonical(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ident(value: str, name: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")


def _sha(value: str, name: str) -> None:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class GatewayHold(RuntimeError):
    """No dispatch, or ambiguous outcome: never retry this invocation."""


@dataclass(frozen=True)
class ModelObservation:
    """Backend observations; model-byte provenance is NOT established here."""
    text: str
    model: str
    prompt_tokens: int
    output_tokens: int
    backend_wall_ms: int


class RawModelBackend(Protocol):
    """Only the isolated gateway process may possess this adapter."""
    def generate(self, prompt: str, *, model: str, max_tokens: int) -> ModelObservation: ...


class TerminalSigner(Protocol):
    """Host-supplied signer; key custody MUST be separate from learner identity."""
    @property
    def key_id(self) -> str: ...
    def sign(self, message: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class GatewaySignedTerminal:
    """Exact bytes emitted by the gateway, not independent claim custody."""
    invocation_id: str
    claim_id: str
    status: str
    payload_bytes: bytes
    payload_sha256: str
    signature: bytes
    qualified: bool = False
    independent_claim_verified: bool = False


class GatewayAttemptStore:
    """SQLite reservation-before-claim, non-replayable even across process exits.

    A RESERVED row may already have been remotely claimed and dispatched.
    Reopen never infers absence of inference or grants re-dispatch.
    """
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                invocation_id TEXT PRIMARY KEY, reservation_id TEXT UNIQUE NOT NULL,
                run_id TEXT NOT NULL, arm TEXT NOT NULL, challenge_id TEXT NOT NULL,
                binding_sha256 TEXT NOT NULL, gateway_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('RESERVED','CLAIMED','COMPLETED','OUTCOME_UNKNOWN')),
                claim_id TEXT UNIQUE, terminal_json TEXT, signature_hex TEXT,
                reserved_utc TEXT NOT NULL, terminal_utc TEXT,
                UNIQUE(run_id, arm, challenge_id)
            )""")
            # Historical terminal_json was locally canonicalized, not a
            # preserved exact signed-byte handoff. Do not upgrade old rows'
            # authority or reconstruct missing original wire bytes.
            cols = {row[1] for row in db.execute("PRAGMA table_info(attempts)")}
            if "terminal_bytes" not in cols:
                db.execute("ALTER TABLE attempts ADD COLUMN terminal_bytes BLOB")
            if "terminal_sha256" not in cols:
                db.execute("ALTER TABLE attempts ADD COLUMN terminal_sha256 TEXT")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def reserve(self, reservation: dict[str,str], gateway_id: str, invocation_id: str) -> None:
        _binding(reservation, gateway_id, invocation_id)
        try:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""INSERT INTO attempts (
                    invocation_id,reservation_id,run_id,arm,challenge_id,binding_sha256,
                    gateway_id,status,reserved_utc) VALUES (?,?,?,?,?,?,?,'RESERVED',?)""",
                    (invocation_id,reservation["reservation_id"],reservation["run_id"],
                     reservation["arm"],reservation["challenge_id"],_digest(_canonical(reservation)),
                     gateway_id,_utc()))
        except sqlite3.IntegrityError as exc:
            raise GatewayHold("invocation, reservation, or run-arm-challenge already reserved") from exc

    def claim(self, invocation_id: str, claim_id: str) -> None:
        _ident(invocation_id,"invocation_id")
        _ident(claim_id,"claim_id")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            try:
                result=db.execute("UPDATE attempts SET claim_id=?,status='CLAIMED' WHERE invocation_id=? AND status='RESERVED'",(claim_id,invocation_id))
                if result.rowcount!=1:
                    raise GatewayHold("local claim is already consumed or missing")
            except sqlite3.IntegrityError as exc:
                raise GatewayHold("claim identity reused") from exc

    def terminal(self, invocation_id: str, payload: dict, signature: bytes,
                 *, payload_bytes: bytes) -> None:
        if type(signature) is not bytes or not signature:
            raise ValueError("unsigned terminal")
        if (type(payload_bytes) is not bytes or not payload_bytes
                or type(payload) is not dict
                or payload_bytes != _canonical(payload)):
            raise ValueError("original canonical signed terminal bytes required")
        if payload.get("invocation_id") != invocation_id:
            raise ValueError("terminal invocation mismatch")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            updated=db.execute("""UPDATE attempts SET status=?,terminal_json=?,
                terminal_bytes=?,terminal_sha256=?,signature_hex=?,terminal_utc=?
                WHERE invocation_id=? AND status='CLAIMED' AND claim_id=?""",
                (payload["status"],payload_bytes.decode("utf-8"),
                 sqlite3.Binary(payload_bytes),_digest(payload_bytes),
                 signature.hex(),_utc(),invocation_id,payload["claim_id"]))
            if updated.rowcount!=1:
                raise GatewayHold("terminal replay or wrong local claim")

    def signed_terminal(self, invocation_id: str) -> GatewaySignedTerminal:
        """Fail closed if the gateway did not persist its ORIGINAL signed bytes.

        Local SQLite is same-user mutable: consumers MUST independently verify
        detached signature, pinned gateway signer, and evaluator-held claim.
        """
        _ident(invocation_id,"invocation_id")
        with closing(self._connect()) as db:
            row=db.execute("""SELECT status,claim_id,terminal_json,terminal_bytes,
                terminal_sha256,signature_hex,reservation_id,run_id,arm,challenge_id,
                binding_sha256,gateway_id FROM attempts WHERE invocation_id=?""",
                (invocation_id,)).fetchone()
        if row is None or row["status"] not in ("COMPLETED","OUTCOME_UNKNOWN"):
            raise GatewayHold("no terminal signed outcome available")
        wire=row["terminal_bytes"]
        if type(wire) is not bytes or not wire:
            raise GatewayHold("original signed terminal bytes unavailable")
        try:
            parsed=json.loads(wire.decode("utf-8"))
            signature=bytes.fromhex(row["signature_hex"])
        except (ValueError,TypeError,UnicodeError) as exc:
            raise GatewayHold("terminal wire or signature invalid") from exc
        if (type(parsed) is not dict or wire!=_canonical(parsed)
                or wire.decode("utf-8")!=row["terminal_json"]
                or _digest(wire)!=row["terminal_sha256"]
                or parsed.get("invocation_id")!=invocation_id
                or parsed.get("claim_id")!=row["claim_id"]
                or parsed.get("status")!=row["status"]
                # Local reservation readback is a consistency check, NOT
                # independently authenticated evaluator claim evidence.
                or any(parsed.get(k)!=row[k] for k in (
                    "reservation_id","run_id","arm","challenge_id","gateway_id"))
                or _digest(_canonical({k:parsed.get(k) for k in _FIELDS}))
                    !=row["binding_sha256"]
                or not signature):
            raise GatewayHold("stored signed terminal bytes inconsistent")
        return GatewaySignedTerminal(
            invocation_id=invocation_id,claim_id=row["claim_id"],
            status=row["status"],payload_bytes=wire,
            payload_sha256=_digest(wire),signature=signature,
        )

    def history(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY rowid")]

    def recovery(self) -> list[dict]:
        return [{"invocation_id":r["invocation_id"],"status":r["status"],
                 "remote_claim_or_inference_may_have_occurred":True,
                 "automatic_retry_allowed":False,"independently_attested":False}
                for r in self.history()]


def _binding(reservation: dict, gateway_id: str, invocation_id: str) -> None:
    if type(reservation) is not dict or tuple(sorted(reservation)) != tuple(sorted(_FIELDS)):
        raise ValueError("reservation shape invalid")
    for key in _FIELDS:
        if type(reservation[key]) is not str or not reservation[key]:
            raise ValueError(f"missing {key}")
        if key.endswith("sha256") or key.endswith("digest"):
            _sha(reservation[key],key)
        elif key!="model_identity":
            _ident(reservation[key],key)
    if reservation["arm"] not in _ARMS:
        raise ValueError("invalid arm")
    _ident(gateway_id,"gateway_id")
    _ident(invocation_id,"invocation_id")


def verify_terminal(payload: dict, signature: bytes, *, pinned_public_key: bytes, expected_key_id: str) -> bool:
    """Cryptographically verify without trusting keys supplied in a receipt."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if type(payload) is not dict or payload.get("key_id") != expected_key_id:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(pinned_public_key).verify(signature,_canonical(payload))
    except (ValueError, TypeError, Exception) as exc:
        # Cryptographic failure must never become accepted evidence.
        return False
    return True


class GatewayDispatch:
    """Only server-side dispatch. Never give learner the raw-model adapter.

    The independently authenticated endpoint's claim helper is supplied by the
    gateway's trusted composition root, using Malaphor #87 contract. A Python
    fake client is NOT a trust boundary, hence all host-level authority claims
    remain HOLD until independently measured process isolation.
    """
    def __init__(self, *, store: GatewayAttemptStore, gateway_id: str,
                 endpoint_client: object, claim_authorization: Callable,
                 backend: RawModelBackend, signer: TerminalSigner):
        _ident(gateway_id,"gateway_id")
        if not callable(claim_authorization) or not callable(getattr(endpoint_client,"claim_reservation",None)):
            raise ValueError("authenticated endpoint adapter required")
        if not callable(getattr(backend,"generate",None)) or not callable(getattr(signer,"sign",None)):
            raise ValueError("backend and signer required")
        _ident(signer.key_id,"signer key_id")
        self.store,self.gateway_id=store,gateway_id
        self.endpoint_client,self.claim_authorization=endpoint_client,claim_authorization
        self.backend,self.signer=backend,signer

    def execute(self, *, reservation: dict[str,str], invocation_id: str,
                prompt: str, max_tokens: int) -> tuple[dict,bytes]:
        _binding(reservation,self.gateway_id,invocation_id)
        if type(prompt) is not str or not prompt or len(prompt.encode("utf-8"))>4096:
            raise ValueError("invalid prompt")
        if _digest(prompt.encode("utf-8"))!=reservation["model_prompt_sha256"]:
            raise ValueError("reserved prompt mismatch")
        if type(max_tokens) is not int or not 1<=max_tokens<=128:
            raise ValueError("invalid max tokens")
        self.store.reserve(reservation,self.gateway_id,invocation_id)
        # From this point even unexpected exceptions/crashes are non-retryable.
        claim_id=None
        try:
            claim=self.claim_authorization(self.endpoint_client,reservation=dict(reservation),
                        gateway_id=self.gateway_id,invocation_id=invocation_id)
            expected={**reservation,"gateway_id":self.gateway_id,
                      "invocation_id":invocation_id,"status":"CLAIMED"}
            if (type(claim) is not dict or frozenset(claim)!=frozenset((*expected,"claim_id"))
                    or any(claim.get(k)!=v for k,v in expected.items())):
                raise GatewayHold("endpoint claim binding invalid")
            claim_id=claim.get("claim_id")
            _ident(claim_id,"claim_id")
            self.store.claim(invocation_id,claim_id)
            start=time.monotonic_ns()
            observation=self.backend.generate(prompt,model=reservation["model_identity"],max_tokens=max_tokens)
            elapsed_ns=max(1,time.monotonic_ns()-start)
            elapsed_ms=max(1,(elapsed_ns+999_999)//1_000_000)
            if (type(observation) is not ModelObservation
                    or observation.model!=reservation["model_identity"]
                    or type(observation.text) is not str
                    or len(observation.text.encode("utf-8"))>4096
                    or any(type(v) is not int or v<0 for v in
                        (observation.prompt_tokens,observation.output_tokens,observation.backend_wall_ms))
                    or observation.output_tokens>max_tokens):
                raise GatewayHold("backend observation invalid; outcome uncertain")
            payload={**reservation,"gateway_id":self.gateway_id,"invocation_id":invocation_id,
                     "claim_id":claim_id,"status":"COMPLETED","response_sha256":_digest(observation.text.encode("utf-8")),
                     "prompt_tokens":observation.prompt_tokens,"output_tokens":observation.output_tokens,
                     "gateway_wall_ms":elapsed_ms,"backend_wall_ms":observation.backend_wall_ms,
                     "key_id":self.signer.key_id,"terminal_utc":_utc(),
                     "model_identity_scope":"BACKEND_REPORTED_NOT_WEIGHT_ATTESTED"}
            payload_bytes=_canonical(payload)
            signature=self.signer.sign(payload_bytes)
            self.store.terminal(invocation_id,payload,signature,payload_bytes=payload_bytes)
            return payload,signature
        except BaseException:
            # A failed/timeout claim might have succeeded remotely. Do not
            # issue another claim or inference; source-local reserved holds.
            if claim_id is not None:
                try:
                    payload={**reservation,"gateway_id":self.gateway_id,"invocation_id":invocation_id,
                             "claim_id":claim_id,"status":"OUTCOME_UNKNOWN","response_sha256":None,
                             "prompt_tokens":None,"output_tokens":None,"gateway_wall_ms":None,
                             "backend_wall_ms":None,"key_id":self.signer.key_id,
                             "terminal_utc":_utc(),"model_identity_scope":"UNKNOWN"}
                    payload_bytes=_canonical(payload)
                    signature=self.signer.sign(payload_bytes)
                    self.store.terminal(invocation_id,payload,signature,payload_bytes=payload_bytes)
                except BaseException:
                    # At minimum durable RESERVED or CLAIMED is non-retryable.
                    pass
            raise
