from __future__ import annotations
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT))
from r8a0.canonical import canonical_bytes, canonical_dumps, canonical_sha256, strict_loads
from r8a0.cli import _recover, _worker
from r8a0.lifecycle import LifecycleRegistry, LifecycleRegistryError
from r8a0.recovery import CheckpointState, RecoveryError, checkpoint_state_from_mapping, recover, write_checkpoint, write_exit_attestation, write_termination_intent
from r8a0.temporal import CLAIM_DIMENSIONS, CURRENT_TIME, REQUIRED_DIMENSIONS, ClaimScope, OrientationGate, OrientationState, TimeEvidence
import r8a0.trust as trust_module
from r8a0.trust import TRUST_KINDS, TrustRegistryError
PROJECT = 'VERA_COGNITIVE_REPAIR_R8A0'
IDENTITY = 'VERA'
NOW = datetime.now(timezone.utc).replace(microsecond=0)
N_HEX = 'cf0074096a67475691b2477fc4b78d06fdf87608580aaea9f21cc6820e6b27678571e744d86e58e8dfe74c4f6b4f51fc0ded6e678ca71a73d32b0c3c1e32b5743dcd549e1aa340f5676e77f9e0d7456db24c611009f0e15a250d2e1333bb5534436a67d6a8d8bfca19b1ae81870852a36e760eab8485fd078ef5592c860cba2f'
D_HEX = '403de0c5274b841d3ebc386a53afaf49d339efcfa91b2f97b876ebb8632728247d8a9afe87b8bf490e6be707e2c2cc2bd05ab65fd68be9aeb6836e999db9990c3a5a0a516c784e127c9723e343ef2b00d7dc3723e38b03dd8badf659f48ca6800663b2cc2cf24efc0600ae04f6090fc2a77b0fdca92ba205dcba23e04c43b8b1'
DER = bytes.fromhex('3031300d060960864801650304020105000420')

def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()

def public_key(key_id: str='test') -> dict[str, object]:
    return {'key_id': key_id, 'n_hex': N_HEX, 'e': 65537}
TEST_AUTHORITY_ROOT_ID = 'test-r8a0-authority-root-v1'
TEST_AUTHORITY_ROOT_ISSUER = 'test-r8a0-authority-root'
TEST_AUTHORITY_ROOT_KEY = public_key('test-authority-root')

def sign_with(payload: object, modulus_hex: str, private_hex: str) -> str:
    modulus = int(modulus_hex, 16)
    private = int(private_hex, 16)
    width = (modulus.bit_length() + 7) // 8
    tail = DER + hashlib.sha256(canonical_bytes(payload)).digest()
    encoded = b'\x00\x01' + b'\xff' * (width - len(tail) - 3) + b'\x00' + tail
    return format(pow(int.from_bytes(encoded, 'big'), private, modulus), 'x')

def sign(payload: object) -> str:
    return sign_with(payload, N_HEX, D_HEX)

def signed(body: dict[str, object], issuer: str) -> dict[str, object]:
    material = dict(body) | {'issuer': issuer, 'key_id': 'test'}
    return material | {'signature': sign(material)}

def time_rows(at: datetime, *, dimensions=REQUIRED_DIMENSIONS, bounded: bool=False):
    lower = (at - timedelta(minutes=1)).isoformat() if bounded else None
    upper = (at + timedelta(minutes=1)).isoformat() if bounded else None
    rows = []
    for dimension in dimensions:
        source = 'clock' if dimension == CURRENT_TIME else dimension
        body = {'dimension': dimension, 'value': at.isoformat(), 'source': source, 'source_kind': dimension, 'observed_at': at.isoformat(), 'source_digest': sha(dimension), 'source_key_id': 'test', 'lower_bound': lower, 'upper_bound': upper}
        rows.append(TimeEvidence(**body, source_signature=sign(body)))
    return rows

def temporal_keys(dimensions=REQUIRED_DIMENSIONS):
    return {'clock' if dimension == CURRENT_TIME else dimension: public_key() for dimension in dimensions}

def trust_registry_record(
    *,
    lifecycle_keys,
    supervisor_keys,
    state_keys,
    lifecycle_registry_path,
    lifecycle_registry_key,
    signer=sign,
    registry_id='r8a0-trust-registry-test-v1',
    project_id=PROJECT,
    identity_id=IDENTITY,
):
    key_sets = {
        'temporal': temporal_keys(),
        'lifecycle': lifecycle_keys,
        'supervisor': supervisor_keys,
        'state': state_keys,
    }
    key_set_digests = {kind: canonical_sha256(key_sets[kind]) for kind in TRUST_KINDS}
    body = {
        'schema': 'VERA_R8A0_TRUST_ANCHOR_REGISTRY_V2',
        'registry_id': registry_id,
        'generation': 1,
        'project_id': project_id,
        'identity_id': identity_id,
        'authority_root_id': TEST_AUTHORITY_ROOT_ID,
        'authority_source_id': 'owner-sequence-3059',
        'authority_source_digest': sha('owner-sequence-3059'),
        'issued_at': NOW.isoformat(),
        'key_sets': key_sets,
        'key_set_digests': key_set_digests,
        'lifecycle_registry': {
            'registry_id': 'r8a0-lifecycle-registry-test-v1',
            'path': str(Path(lifecycle_registry_path).resolve()),
            'integrity_key_id': 'test-lifecycle-integrity-key',
            'integrity_key_digest': hashlib.sha256(lifecycle_registry_key).hexdigest(),
        },
        'issuer': TEST_AUTHORITY_ROOT_ISSUER,
        'key_id': TEST_AUTHORITY_ROOT_KEY['key_id'],
    }
    record = body | {'signature': signer(body)}
    return (
        record,
        {
            'trust_registry_id': registry_id,
            'trust_registry_digest': canonical_sha256(record),
            'trust_key_set_digests': key_set_digests,
        },
    )

def state_attestations(state: CheckpointState, observed_at: datetime):
    roots = {'predecessor_checkpoint': state.predecessor_checkpoint_digest, 'memory_head': state.memory_head_digest, 'self_model_head': state.self_model_head_digest, 'authority_state': state.authority_state_digest}
    return {kind: signed({'schema': 'VERA_R8A0_STATE_ROOT_ATTESTATION_V1', 'kind': kind, 'project_id': state.project_id, 'identity_id': state.identity_id, 'digest': digest, 'generation': 1, 'observed_at': observed_at.isoformat()}, 'state-issuer') for kind, digest in roots.items()}

class LifecycleCaseBase(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.checkpoint = self.root / 'checkpoint.json'
        self.checkpoint_receipt = self.root / 'checkpoint-receipt.json'
        self.intent = self.root / 'termination-intent.json'
        self.exit = self.root / 'exit.json'
        self.registry = self.root / 'lifecycle.json'
        self.registry_key = b'lifecycle-registry-integrity-key'
        self.state_keys = {'state-issuer': public_key()}
        self.lifecycle_keys = {'lifecycle-issuer': public_key()}
        self.supervisor_keys = {'supervisor-issuer': public_key()}
        self.authority_root_path = self.root / 'authority-root.json'
        self.authority_root_path.write_text(canonical_dumps({'schema': 'VERA_R8A0_AUTHORITY_ROOT_V1', 'root_id': TEST_AUTHORITY_ROOT_ID, 'issuer': TEST_AUTHORITY_ROOT_ISSUER, 'public_key': TEST_AUTHORITY_ROOT_KEY}), encoding='utf-8')
        self.authority_root_patcher = patch.object(trust_module, 'AUTHORITY_ROOT_CONFIG_PATH', self.authority_root_path)
        self.authority_root_patcher.start()
        self.trust_registry_path = self.root / 'trust-registry.json'
        self.trust_registry_patcher = patch.object(trust_module, 'TRUST_REGISTRY_CONFIG_PATH', self.trust_registry_path)
        self.trust_registry_patcher.start()
        self.registry_key_path = self.root / 'lifecycle-registry.key'
        self.registry_key_path.write_bytes(self.registry_key)
        self.registry_key_patcher = patch.object(trust_module, 'LIFECYCLE_REGISTRY_KEY_PATH', self.registry_key_path)
        self.registry_key_patcher.start()
        trust_registry, self.trust_refs = trust_registry_record(lifecycle_keys=self.lifecycle_keys, supervisor_keys=self.supervisor_keys, state_keys=self.state_keys, lifecycle_registry_path=self.registry, lifecycle_registry_key=self.registry_key)
        self.trust_registry_path.write_text(canonical_dumps(trust_registry), encoding='utf-8')

    def tearDown(self):
        self.registry_key_patcher.stop()
        self.trust_registry_patcher.stop()
        self.authority_root_patcher.stop()
        self.temp.cleanup()

    def make_state(self, created_at: datetime) -> CheckpointState:
        return CheckpointState(PROJECT, IDENTITY, 'runtime-before', 'instance-1', 'a' * 64, 'b' * 64, 'c' * 64, ('finish final frozen cycle',), ('Voss exact-head review',), created_at.isoformat(), 'd' * 64)

    def create_chain(self, base: datetime):
        state = self.make_state(base - timedelta(seconds=1))
        with patch('r8a0.recovery_evidence._utc_now', return_value=base):
            checkpoint = write_checkpoint(self.checkpoint, state, checkpoint_receipt_path=self.checkpoint_receipt, state_attestations=state_attestations(state, base), trusted_state_keys=self.state_keys, lifecycle_issuer='lifecycle-issuer', lifecycle_key_id='test', lifecycle_signer=sign)
        with patch('r8a0.recovery_evidence._utc_now', return_value=base + timedelta(seconds=1)):
            intent = write_termination_intent(checkpoint_receipt_path=self.checkpoint_receipt, termination_intent_path=self.intent, trusted_lifecycle_keys=self.lifecycle_keys, lifecycle_issuer='lifecycle-issuer', lifecycle_key_id='test', lifecycle_signer=sign, process_id=2147483647)
        exit_attestation = write_exit_attestation(path=self.exit, checkpoint_receipt=checkpoint, termination_intent=intent, exit_code=0, observed_at=(base + timedelta(seconds=2)).isoformat(), supervisor_issuer='supervisor-issuer', supervisor_key_id='test', supervisor_signer=sign)
        return (state, checkpoint, intent, exit_attestation)

    def recover_chain(self, base, state, checkpoint, intent, exit_attestation):
        registry = LifecycleRegistry(self.registry, self.registry_key)
        with patch('r8a0.recovery_runtime._utc_now', return_value=base + timedelta(seconds=3)):
            return recover(self.checkpoint, orientation_evidence=time_rows(base + timedelta(seconds=3)), orientation_source_mode='CURRENT_SOURCE', expected_trust_registry_id=self.trust_refs['trust_registry_id'], expected_trust_registry_digest=self.trust_refs['trust_registry_digest'], expected_trust_key_set_digests=self.trust_refs['trust_key_set_digests'], checkpoint_receipt_path=self.checkpoint_receipt, termination_intent_path=self.intent, exit_attestation_path=self.exit, expected_checkpoint_receipt_signature=checkpoint['signature'], expected_termination_intent_signature=intent['signature'], expected_exit_attestation_signature=exit_attestation['signature'], expected_project_id=PROJECT, expected_identity_id=IDENTITY, expected_predecessor_checkpoint_digest=state.predecessor_checkpoint_digest, expected_memory_head_digest=state.memory_head_digest, expected_self_model_head_digest=state.self_model_head_digest, expected_authority_state_digest=state.authority_state_digest, successor_runtime_id='runtime-after')

    def recovery_request(self, base, state, checkpoint, intent, exit_attestation):
        registry = LifecycleRegistry(self.registry, self.registry_key)
        return {'orientation_evidence': {row.dimension: row.as_dict() for row in time_rows(base + timedelta(seconds=3))}, 'orientation_source_mode': 'CURRENT_SOURCE', **self.trust_refs, 'checkpoint_receipt_path': str(self.checkpoint_receipt), 'termination_intent_path': str(self.intent), 'exit_attestation_path': str(self.exit), 'expected_checkpoint_receipt_signature': checkpoint['signature'], 'expected_termination_intent_signature': intent['signature'], 'expected_exit_attestation_signature': exit_attestation['signature'], 'expected_project_id': PROJECT, 'expected_identity_id': IDENTITY, 'expected_predecessor_checkpoint_digest': state.predecessor_checkpoint_digest, 'expected_memory_head_digest': state.memory_head_digest, 'expected_self_model_head_digest': state.self_model_head_digest, 'expected_authority_state_digest': state.authority_state_digest, 'successor_runtime_id': 'runtime-after'}

    def recover_with_refs(self, base, state, checkpoint, intent, exit_attestation, refs):
        registry = LifecycleRegistry(self.registry, self.registry_key)
        with patch('r8a0.recovery_runtime._utc_now', return_value=base + timedelta(seconds=3)):
            return recover(self.checkpoint, orientation_evidence=time_rows(base + timedelta(seconds=3)), orientation_source_mode='CURRENT_SOURCE', expected_trust_registry_id=refs['trust_registry_id'], expected_trust_registry_digest=refs['trust_registry_digest'], expected_trust_key_set_digests=refs['trust_key_set_digests'], checkpoint_receipt_path=self.checkpoint_receipt, termination_intent_path=self.intent, exit_attestation_path=self.exit, expected_checkpoint_receipt_signature=checkpoint['signature'], expected_termination_intent_signature=intent['signature'], expected_exit_attestation_signature=exit_attestation['signature'], expected_project_id=PROJECT, expected_identity_id=IDENTITY, expected_predecessor_checkpoint_digest=state.predecessor_checkpoint_digest, expected_memory_head_digest=state.memory_head_digest, expected_self_model_head_digest=state.self_model_head_digest, expected_authority_state_digest=state.authority_state_digest, successor_runtime_id='runtime-after')
