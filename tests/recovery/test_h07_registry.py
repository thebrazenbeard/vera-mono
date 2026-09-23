from h07_support import *
from h07_support import _recover, _worker

class TrustRegistryBindingTests(LifecycleCaseBase):

    def test_untrusted_or_mismatched_registry_fails_before_consumption(self):
        state, checkpoint, intent, exit_attestation = self.create_chain(NOW)
        registry = LifecycleRegistry(self.registry, self.registry_key)
        before = registry.current_head()
        malicious, malicious_refs = trust_registry_record(lifecycle_keys=self.lifecycle_keys, supervisor_keys=self.supervisor_keys, state_keys=self.state_keys, lifecycle_registry_path=self.registry, lifecycle_registry_key=self.registry_key, signer=lambda _: '1', registry_id='attacker-selected-registry')
        self.trust_registry_path.write_text(canonical_dumps(malicious), encoding='utf-8')
        with self.assertRaisesRegex(TrustRegistryError, 'signature'):
            self.recover_with_refs(NOW, state, checkpoint, intent, exit_attestation, malicious_refs)
        self.assertEqual(registry.current_head(), before)
        legitimate, refs = trust_registry_record(lifecycle_keys=self.lifecycle_keys, supervisor_keys=self.supervisor_keys, state_keys=self.state_keys, lifecycle_registry_path=self.registry, lifecycle_registry_key=self.registry_key)
        self.trust_registry_path.write_text(canonical_dumps(legitimate), encoding='utf-8')
        for field, value in (('trust_registry_id', 'wrong-registry'), ('trust_registry_digest', '0' * 64)):
            wrong = dict(refs)
            wrong[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(TrustRegistryError, 'identity or digest mismatch'):
                    self.recover_with_refs(NOW, state, checkpoint, intent, exit_attestation, wrong)
                self.assertEqual(registry.current_head(), before)
        wrong = dict(refs)
        wrong['trust_key_set_digests'] = dict(refs['trust_key_set_digests'])
        wrong['trust_key_set_digests']['state'] = '0' * 64
        with self.assertRaisesRegex(TrustRegistryError, 'digest reference mismatch'):
            self.recover_with_refs(NOW, state, checkpoint, intent, exit_attestation, wrong)
        self.assertEqual(registry.current_head(), before)

        scoped, scoped_refs = trust_registry_record(
            lifecycle_keys=self.lifecycle_keys,
            supervisor_keys=self.supervisor_keys,
            state_keys=self.state_keys,
            lifecycle_registry_path=self.registry,
            lifecycle_registry_key=self.registry_key,
            project_id='FOREIGN_PROJECT',
        )
        self.trust_registry_path.write_text(canonical_dumps(scoped), encoding='utf-8')
        with self.assertRaisesRegex(TrustRegistryError, 'scope mismatch'):
            self.recover_with_refs(NOW, state, checkpoint, intent, exit_attestation, scoped_refs)
        self.assertEqual(registry.current_head(), before)
