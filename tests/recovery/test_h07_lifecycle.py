from h07_support import *
from h07_support import _recover, _worker

class LifecycleTimeTests(LifecycleCaseBase):

    def test_valid_order_is_bound_and_second_successor_is_rejected(self):
        state, checkpoint, intent, exit_attestation = self.create_chain(NOW)
        pre_head = LifecycleRegistry(self.registry, self.registry_key).current_head()
        receipt = self.recover_chain(NOW, state, checkpoint, intent, exit_attestation)
        self.assertEqual(receipt['result'], 'RECOVERED_FROM_VERIFIED_CHECKPOINT')
        self.assertLessEqual(receipt['checkpoint_created_at'], receipt['checkpoint_observed_at'])
        self.assertLessEqual(receipt['checkpoint_observed_at'], receipt['termination_intent_at'])
        self.assertLessEqual(receipt['termination_intent_at'], receipt['exit_observed_at'])
        self.assertLessEqual(receipt['exit_observed_at'], receipt['recovery_evaluated_at'])
        self.assertEqual(receipt['trust_binding']['trust_registry_id'], self.trust_refs['trust_registry_id'])
        self.assertEqual(receipt['trust_binding']['trust_registry_digest'], self.trust_refs['trust_registry_digest'])
        self.assertEqual(receipt['trust_binding']['trust_key_set_digests'], self.trust_refs['trust_key_set_digests'])
        self.assertEqual(receipt['trust_binding']['trust_authority_root_id'], TEST_AUTHORITY_ROOT_ID)
        self.assertEqual(receipt['trust_binding']['trust_authority_root_digest'], canonical_sha256({'schema': 'VERA_R8A0_AUTHORITY_ROOT_V1', 'root_id': TEST_AUTHORITY_ROOT_ID, 'issuer': TEST_AUTHORITY_ROOT_ISSUER, 'public_key': TEST_AUTHORITY_ROOT_KEY}))
        self.assertEqual(receipt['lifecycle_registry_pre_head'], pre_head)
        self.assertEqual(receipt['lifecycle_registry_post_head'], LifecycleRegistry(self.registry, self.registry_key).current_head())
        self.assertEqual(receipt['trust_binding']['trust_project_id'], PROJECT)
        self.assertEqual(receipt['trust_binding']['trust_identity_id'], IDENTITY)
        self.assertEqual(receipt['trust_binding']['lifecycle_registry_id'], 'r8a0-lifecycle-registry-test-v1')
        self.assertEqual(receipt['trust_binding']['lifecycle_registry_path_digest'], canonical_sha256(str(self.registry.resolve())))
        self.assertEqual(receipt['trust_binding']['lifecycle_integrity_key_digest'], hashlib.sha256(self.registry_key).hexdigest())
        with self.assertRaises(LifecycleRegistryError):
            self.recover_chain(NOW, state, checkpoint, intent, exit_attestation)

    def test_future_stale_and_reordered_lifecycle_are_rejected(self):
        future = self.make_state(NOW + timedelta(minutes=10))
        with patch('r8a0.recovery_evidence._utc_now', return_value=NOW):
            with self.assertRaisesRegex(RecoveryError, 'future'):
                write_checkpoint(self.checkpoint, future, checkpoint_receipt_path=self.checkpoint_receipt, state_attestations=state_attestations(future, NOW), trusted_state_keys=self.state_keys, lifecycle_issuer='lifecycle-issuer', lifecycle_key_id='test', lifecycle_signer=sign)
        old = NOW - timedelta(hours=2)
        state, checkpoint, intent, exit_attestation = self.create_chain(old)
        registry = LifecycleRegistry(self.registry, self.registry_key)
        with patch('r8a0.recovery_runtime._utc_now', return_value=NOW):
            with self.assertRaisesRegex(RecoveryError, 'stale'):
                recover(self.checkpoint, orientation_evidence=time_rows(NOW), orientation_source_mode='CURRENT_SOURCE', expected_trust_registry_id=self.trust_refs['trust_registry_id'], expected_trust_registry_digest=self.trust_refs['trust_registry_digest'], expected_trust_key_set_digests=self.trust_refs['trust_key_set_digests'], checkpoint_receipt_path=self.checkpoint_receipt, termination_intent_path=self.intent, exit_attestation_path=self.exit, expected_checkpoint_receipt_signature=checkpoint['signature'], expected_termination_intent_signature=intent['signature'], expected_exit_attestation_signature=exit_attestation['signature'], expected_project_id=PROJECT, expected_identity_id=IDENTITY, expected_predecessor_checkpoint_digest=state.predecessor_checkpoint_digest, expected_memory_head_digest=state.memory_head_digest, expected_self_model_head_digest=state.self_model_head_digest, expected_authority_state_digest=state.authority_state_digest, successor_runtime_id='runtime-after')
        self.temp.cleanup()
        self.setUp()
        state, checkpoint, intent, exit_attestation = self.create_chain(NOW)
        checkpoint_body = {k: v for k, v in checkpoint.items() if k != 'signature'}
        checkpoint_body['checkpoint_observed_at'] = (NOW + timedelta(minutes=2)).isoformat()
        checkpoint = checkpoint_body | {'signature': sign(checkpoint_body)}
        self.checkpoint_receipt.write_text(canonical_dumps(checkpoint), encoding='utf-8')
        intent_body = {k: v for k, v in intent.items() if k != 'signature'}
        intent_body['checkpoint_receipt_signature'] = checkpoint['signature']
        intent = intent_body | {'signature': sign(intent_body)}
        self.intent.write_text(canonical_dumps(intent), encoding='utf-8')
        exit_body = {k: v for k, v in exit_attestation.items() if k != 'signature'}
        exit_body['checkpoint_receipt_signature'] = checkpoint['signature']
        exit_body['termination_intent_signature'] = intent['signature']
        exit_attestation = exit_body | {'signature': sign(exit_body)}
        self.exit.write_text(canonical_dumps(exit_attestation), encoding='utf-8')
        with self.assertRaisesRegex(RecoveryError, 'termination intent predates checkpoint'):
            self.recover_chain(NOW, state, checkpoint, intent, exit_attestation)
