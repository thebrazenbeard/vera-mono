from h07_support import *
from h07_support import _recover, _worker

class TrustRequestBoundaryTests(LifecycleCaseBase):

    def test_checkpoint_worker_loads_only_provisioned_trust_registry(self):
        state = self.make_state(NOW - timedelta(seconds=1))
        request = {'state': state.payload(), 'state_attestations': state_attestations(state, NOW), **self.trust_refs}
        request_path = self.root / 'checkpoint-worker-input.json'
        worker_checkpoint = self.root / 'worker-checkpoint.json'
        worker_receipt = self.root / 'worker-checkpoint-receipt.json'
        worker_intent = self.root / 'worker-termination-intent.json'
        request_path.write_text(canonical_dumps(request), encoding='utf-8')
        environment = {'VERA_R8A0_LIFECYCLE_ISSUER': 'lifecycle-issuer', 'VERA_R8A0_LIFECYCLE_KEY_ID': 'test', 'VERA_R8A0_LIFECYCLE_N_HEX': N_HEX, 'VERA_R8A0_LIFECYCLE_D_HEX': D_HEX}
        with patch.dict(os.environ, environment, clear=False), patch('r8a0.recovery_evidence._utc_now', return_value=NOW):
            result = _worker(SimpleNamespace(input=str(request_path), checkpoint=str(worker_checkpoint), checkpoint_receipt=str(worker_receipt), termination_intent=str(worker_intent)))
        self.assertEqual(result, 0)
        self.assertTrue(worker_checkpoint.exists())
        self.assertTrue(worker_receipt.exists())
        self.assertTrue(worker_intent.exists())

    def test_caller_supplied_self_signed_trust_universe_is_rejected_before_consumption(self):
        state, checkpoint, intent, exit_attestation = self.create_chain(NOW)
        request = self.recovery_request(NOW, state, checkpoint, intent, exit_attestation)
        request.update({'trusted_temporal_keys': temporal_keys(), 'trusted_lifecycle_keys': self.lifecycle_keys, 'trusted_supervisor_keys': self.supervisor_keys, 'trusted_state_keys': self.state_keys, 'trust_registry_path': str(self.trust_registry_path), 'authority_root_path': str(self.authority_root_path), 'lifecycle_registry_path': str(self.root / 'attacker-lifecycle.json'), 'expected_lifecycle_registry_head': '0' * 64})
        request_path = self.root / 'caller-selected-trust-request.json'
        request_path.write_text(canonical_dumps(request), encoding='utf-8')
        registry = LifecycleRegistry(self.registry, self.registry_key)
        before = registry.current_head()
        with patch.dict(os.environ, {'VERA_R8A0_TRUST_REGISTRY_PATH': str(self.trust_registry_path), 'VERA_R8A0_REGISTRY_KEY_HEX': self.registry_key.hex()}, clear=False):
            with self.assertRaisesRegex(ValueError, 'fields are missing or unknown'):
                _recover(SimpleNamespace(checkpoint=str(self.checkpoint), input=str(request_path)))
        self.assertEqual(registry.current_head(), before)

    def test_caller_selected_lifecycle_registry_coordinates_are_rejected(self):
        state, checkpoint, intent, exit_attestation = self.create_chain(NOW)
        request = self.recovery_request(NOW, state, checkpoint, intent, exit_attestation)
        attacker_registry = self.root / 'attacker-selected-lifecycle.json'
        request['lifecycle_registry_path'] = str(attacker_registry)
        request['expected_lifecycle_registry_head'] = '0' * 64
        request_path = self.root / 'caller-selected-lifecycle-request.json'
        request_path.write_text(canonical_dumps(request), encoding='utf-8')
        before = LifecycleRegistry(self.registry, self.registry_key).current_head()
        environment = {}
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(ValueError, 'fields are missing or unknown'):
                _recover(SimpleNamespace(checkpoint=str(self.checkpoint), input=str(request_path)))
        self.assertFalse(attacker_registry.exists())
        self.assertEqual(LifecycleRegistry(self.registry, self.registry_key).current_head(), before)

