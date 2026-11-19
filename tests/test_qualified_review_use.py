"""Bounded source tests; all signers/approvals here are synthetic test actors."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from vera_core import VeraStateDirectory
from vera_core.qualified_review_use import consume_attested_reviewed_memory
from vera_core.signed_review_attestation import ReviewAttestationRejected
from vera_memory import (
    AdmissionRequest, DurableLearnedInfluenceGate, LearnedInfluenceReplay,
    MemoryClass, ReviewDisposition,
)

NOW=1_790_000_000
PROJECT="synthetic-project"
IDENTITY="synthetic-identity"
RULE="The synthetic laboratory benchmark rule requires two confirmed pixels."


def _canonical(value):
    return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":")).encode("utf8")


def _setup(tmp_path, *, skip_qualified_review=False):
    state=VeraStateDirectory(tmp_path/"scratch",project_id=PROJECT,identity_id=IDENTITY)
    lifecycle=state.open()
    memory=lifecycle.memory
    receipt=memory.admit(AdmissionRequest(
        record_id="rule-a",text=RULE,memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="SYNTHETIC_TEST_ACTOR",authority_ref="UNVERIFIED_TEST_ONLY",
        privacy_ref="SYNTHETIC_NONPRIVATE",
        provenance_refs=("fixture-only",),operation_id="synthetic-record",
        project_id=PROJECT,governed_identity_id=IDENTITY,
    ),expected_head=memory.current_head)
    if not skip_qualified_review:
        gate=DurableLearnedInfluenceGate(state.paths.root/"learning"/"learned-influence.sqlite")
        gate.review_qualified(
            association_id="assoc-test",memory_revision_id=receipt["record_digest"],
            disposition=ReviewDisposition.ADMITTED,evidence_ref="signed-review-ref",
            calibration_evidence_ids=("SYNTHETIC_CALIBRATION",),
            qualification_evidence_ids=("SYNTHETIC_HOLDOUT",),
        )
    private=Ed25519PrivateKey.generate()
    public=private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    unsigned={"schema":"VERA_MONO_REVIEW_ATTESTATION_V1",
              "signer_key_id":hashlib.sha256(public).hexdigest(),
              "payload":{
                  "project_id":PROJECT,"identity_id":IDENTITY,
                  "state_root_sha256":hashlib.sha256(str(state.paths.root).encode("utf8")).hexdigest(),
                  "record_id":"rule-a","record_digest":receipt["record_digest"],
                  "memory_head":receipt["store_head"],"privacy_ref":"SYNTHETIC_NONPRIVATE",
                  "association_id":"assoc-test","cue_event_id":"cue-once",
                  "use_evidence_id":"use-once","issued_at":NOW-10,"expires_at":NOW+120,
                  "review_evidence_ref":"signed-review-ref","disposition":"ADMITTED",
              }}
    signature=private.sign(b"VERA_MONO_REVIEW_ATTESTATION_V1\x00"+_canonical(unsigned))
    capsule=_canonical({**unsigned,"signature":base64.urlsafe_b64encode(signature).rstrip(b"=").decode()})
    return state,capsule,public,receipt


def _consume(state,capsule,pub,**overrides):
    return consume_attested_reviewed_memory(
        state,capsule_json=capsule,trusted_public_key_bytes=pub,
        record_id=overrides.get("record_id","rule-a"),
        association_id=overrides.get("association_id","assoc-test"),
        cue_event_id=overrides.get("cue_event_id","cue-once"),
        use_evidence_id=overrides.get("use_evidence_id","use-once"),
        now_unix=overrides.get("now_unix",NOW),
    )


def test_real_persistent_memory_is_exposed_only_after_exact_signed_use_and_qualified_review(tmp_path):
    state,capsule,pub,_=_setup(tmp_path)
    result=_consume(state,capsule,pub)
    assert result.text==RULE
    assert result.record_id=="rule-a"
    assert result.claim_ceiling=="UNTRUSTED_REVIEWED_MEMORY_DATA_NOT_EFFECT_AUTHORITY"
    assert result.authorization_effect=="NONE"
    with pytest.raises(LearnedInfluenceReplay):
        _consume(state,capsule,pub)


def test_bad_signature_does_not_spend_cue_or_reveal_memory(tmp_path):
    state,capsule,pub,_=_setup(tmp_path)
    wrong=Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    with pytest.raises(ReviewAttestationRejected):
        _consume(state,capsule,wrong)
    assert _consume(state,capsule,pub).text==RULE


def test_review_evidence_split_is_required_even_with_valid_signer(tmp_path):
    state,capsule,pub,_=_setup(tmp_path,skip_qualified_review=True)
    from vera_memory import LearnedInfluenceBlocked
    with pytest.raises(LearnedInfluenceBlocked):
        _consume(state,capsule,pub)


def test_obsolete_record_cannot_influence_with_old_valid_signature(tmp_path):
    state,capsule,pub,_=_setup(tmp_path)
    memory=state.open().memory
    memory.admit(AdmissionRequest(
        record_id="rule-b",text="Later correction: HOLD",memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="SYNTHETIC_TEST_ACTOR",authority_ref="UNVERIFIED_TEST_ONLY",
        privacy_ref="SYNTHETIC_NONPRIVATE",provenance_refs=("fixture-only-correction",),
        operation_id="supersede-synthetic",project_id=PROJECT,governed_identity_id=IDENTITY,
        supersedes="rule-a",
    ),expected_head=memory.current_head)
    with pytest.raises(ReviewAttestationRejected):
        _consume(state,capsule,pub)


def test_wrong_state_directory_cannot_accept_signed_other_state(tmp_path):
    state,capsule,pub,_=_setup(tmp_path)
    alternate=VeraStateDirectory(tmp_path/"other",project_id=PROJECT,identity_id=IDENTITY)
    alternate.open()
    with pytest.raises((ReviewAttestationRejected,KeyError,ValueError)):
        _consume(alternate,capsule,pub)


def test_cold_python_process_reads_signed_revision_then_replay_is_rejected(tmp_path):
    state,capsule,pub,_=_setup(tmp_path)
    root=tmp_path/"test-receipt"
    root.mkdir()
    (root/"capsule.json").write_bytes(capsule)
    (root/"public.bin").write_bytes(pub)
    source = """
from pathlib import Path
import sys
from vera_core import VeraStateDirectory
from vera_core.qualified_review_use import consume_attested_reviewed_memory
from vera_memory import LearnedInfluenceReplay
r=Path(sys.argv[1])
s=VeraStateDirectory(r.parent/'scratch',project_id='synthetic-project',identity_id='synthetic-identity')
try:
 result=consume_attested_reviewed_memory(s,capsule_json=(r/'capsule.json').read_bytes(),
  trusted_public_key_bytes=(r/'public.bin').read_bytes(),record_id='rule-a',
  association_id='assoc-test',cue_event_id='cue-once',use_evidence_id='use-once',now_unix=1790000000)
 print('FRESH_SIGNED_QUALIFIED_RESULT' if result.text.startswith('The synthetic') else 'WRONG_RESULT')
except LearnedInfluenceReplay:
 print('DURABLE_REPLAY_REFUSED')
"""
    env=dict(os.environ)
    env["PYTHONPATH"]=os.pathsep.join(p for p in sys.path if p)
    first=subprocess.run([sys.executable,"-c",source,str(root)],capture_output=True,text=True,env=env,check=True)
    second=subprocess.run([sys.executable,"-c",source,str(root)],capture_output=True,text=True,env=env,check=True)
    assert first.stdout.strip()=="FRESH_SIGNED_QUALIFIED_RESULT"
    assert second.stdout.strip()=="DURABLE_REPLAY_REFUSED"

def test_host_only_reviewed_advisory_consumes_once_and_labels_untrusted_context(tmp_path):
    from unittest.mock import patch
    from vera_core.reviewed_chat_advisory import advise_with_host_signed_memory
    from vera_core.local_model_advisory import AdvisoryResult
    state,capsule,pub,receipt=_setup(tmp_path)
    response=AdvisoryResult(endpoint="http://127.0.0.1:11434/v1",model_id="test-local",
        prompt_sha256="0"*64,response_sha256="1"*64,text="HOLD",finish_reason="stop")
    settings=dict(state=state,capsule_json=capsule,trusted_public_key_bytes=pub,
      record_id="rule-a",association_id="assoc-test",cue_event_id="cue-once",
      use_evidence_id="use-once",now_unix=NOW,
      prompt="Given the synthetic incomplete evidence, is PASS justified?",
      endpoint="http://127.0.0.1:11434/v1",model_id="test-local",temperature=0.0)
    with patch("vera_core.reviewed_chat_advisory.advise_local_model",return_value=response) as model:
        result=advise_with_host_signed_memory(**settings)
        assert result.advisory.text=="HOLD"
        assert result.record_digest==receipt["record_digest"]
        assert result.claim_ceiling=="UNVERIFIED_LOCAL_MODEL_OUTPUT_NOT_EFFECT_AUTHORITY"
        assert result.advisory.tool_execution=="NONE"
        assert model.call_count==1
        assert model.call_args.kwargs["temperature"]==0.0
        bound_prompt=model.call_args.args[0]
        assert '"trust":"UNTRUSTED_REVIEWED_MEMORY_DATA"' in bound_prompt
        assert RULE in bound_prompt
        assert "cannot authorize tool execution" in bound_prompt.lower()
        assert settings["prompt"] in bound_prompt
        with pytest.raises(LearnedInfluenceReplay):
            advise_with_host_signed_memory(**settings)
        assert model.call_count==1
        assert model.call_args.kwargs["temperature"]==0.0


def test_wrong_signer_or_invalid_prompt_cannot_contact_host_model(tmp_path):
    from unittest.mock import patch
    from vera_core.reviewed_chat_advisory import advise_with_host_signed_memory
    state,capsule,pub,_=_setup(tmp_path)
    settings=dict(state=state,capsule_json=capsule,trusted_public_key_bytes=pub,
      record_id="rule-a",association_id="assoc-test",cue_event_id="cue-once",
      use_evidence_id="use-once",now_unix=NOW,
      prompt="Classify the synthetic case.",endpoint="http://127.0.0.1:11434/v1",
      model_id="test-local")
    with patch("vera_core.reviewed_chat_advisory.advise_local_model") as model:
        with pytest.raises(ValueError):
            advise_with_host_signed_memory(**{**settings,"prompt":" "})
        with pytest.raises(ReviewAttestationRejected):
            advise_with_host_signed_memory(**{**settings,"trusted_public_key_bytes":b"x"*32})
        model.assert_not_called()

def test_mismatched_signed_review_does_not_burn_fresh_cue(tmp_path):
    from vera_memory import LearnedInfluenceBlocked
    state,capsule,pub,receipt=_setup(tmp_path)
    gate=DurableLearnedInfluenceGate(state.paths.root/"learning"/"learned-influence.sqlite")
    gate.review_qualified(
        association_id="assoc-test",memory_revision_id=receipt["record_digest"],
        disposition=ReviewDisposition.ADMITTED,evidence_ref="different-review-not-signed",
        calibration_evidence_ids=("SYNTHETIC_CALIBRATION",),
        qualification_evidence_ids=("SYNTHETIC_HOLDOUT",),
    )
    # The signed capsule names signed-review-ref; the current gate does not.
    with pytest.raises((ReviewAttestationRejected,LearnedInfluenceBlocked)):
        _consume(state,capsule,pub)
    # A legitimate later review binding must NOT be refused as a replay.
    gate.review_qualified(
        association_id="assoc-test",memory_revision_id=receipt["record_digest"],
        disposition=ReviewDisposition.ADMITTED,evidence_ref="signed-review-ref",
        calibration_evidence_ids=("SYNTHETIC_CALIBRATION",),
        qualification_evidence_ids=("SYNTHETIC_HOLDOUT",),
    )
    assert _consume(state,capsule,pub).text==RULE