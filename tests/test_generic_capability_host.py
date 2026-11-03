"""Source-contract and negative-boundary tests for the opt-in generic host adapter."""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from vera_core.generic_capability_host import (
    CapabilityHostAuthority, GenericCapabilityGateway, HostModelBinding, ModelAdapter,
)

@dataclass(frozen=True)
class FakeConfig:
    model_id: str
    model_revision: str
    runtime_instance_id: str
    subject_id: str
    evaluator_id: str

class FakeSidecar:
    def __init__(self, config):
        self.config = config
        self.count = 0

    def step(self, observation, elapsed_ms):
        self.count += 1
        return SimpleNamespace(
            model_id=self.config.model_id, subject_id=self.config.subject_id,
            sequence=self.count, state_after=SimpleNamespace(liking_proxy=0.1),
            requested_effects=(), authorized_effects=())

class FakeQualifiedRuntime:
    def __init__(self, adapter):
        self.provider_execution_transports = {
            "local-ollama": SimpleNamespace(provider_id="local-ollama", model=adapter.model_tag,
                                            registry_digest=adapter.registry_digest, port=11434)}
        self.invocations = []
    def prepare_provider_effect(self, **kwargs):
        self.invocations.append(("prepare", kwargs))
        return SimpleNamespace(effect_id=kwargs["effect_id"],
                               operation=kwargs["operation"],
                               request_digest="f"*64,
                               permit=SimpleNamespace(permit_digest="e"*64))
    def execute_provider_effect(self, prepared, *, authority):
        self.invocations.append(("execute", prepared.effect_id))
        return SimpleNamespace(value={"kind":"UNVERIFIED_LOCAL_MODEL_CANDIDATE",
                    "model":self.provider_execution_transports["local-ollama"].model,
                    "registry_digest":self.provider_execution_transports["local-ollama"].registry_digest,
                    "text":"synthetic candidate", "qualified":False})
class FakeProviderVerifier:
    def issue(self, **kwargs): return kwargs

class HostGatewayTests(unittest.TestCase):
    def setUp(self):
        self.authority = CapabilityHostAuthority("local-test-host", b"h"*32)
        self.adapters = [
            ModelAdapter("qwen2.5-coder:1.5b-instruct-q8_0", "a"*64, "adapter-coder-v1"),
            ModelAdapter("vera-qwen35:trial-20261029", "b"*64, "adapter-qwen-v1"),
        ]
        self.bindings = [
            HostModelBinding(
                adapter=adapter, runtime=FakeQualifiedRuntime(adapter),
                provider_authority=FakeProviderVerifier(),
                sidecar=FakeSidecar(FakeConfig(adapter.model_tag, adapter.registry_digest,
                                     "instance-"+str(i), "subject-"+str(i), "external-evaluator")),
                session_id="session-"+str(i))
            for i,adapter in enumerate(self.adapters)
        ]
        self.gateway=GenericCapabilityGateway(self.authority, self.bindings, now=lambda:1000)

    def grant(self, i, domain, operation, suffix):
        return self.authority.issue(
            self.bindings[i], domain=domain, operation=operation,
            grant_id="grant-"+suffix, expires_epoch=1100)

    def test_both_adapters_access_source_only_sexuality_independently(self):
        for i in (0,1):
            result=self.gateway.describe_sexuality(self.grant(i,"sexuality","DESCRIBE_RESEARCH",str(i)))
            self.assertEqual(result["model_id"],self.adapters[i].model_tag)
            self.assertEqual(result["status"],"SOURCE_ONLY_NOT_BEHAVIORALLY_QUALIFIED")
            self.assertNotIn("preferences",result)

    def test_pleasure_state_is_separate_and_bound(self):
        grant=self.grant(0,"pleasure","STEP_PROXY","p0")
        before=self.bindings[1].sidecar.count
        receipt=self.gateway.step_pleasure(grant,SimpleNamespace(subject_id="subject-0",
             evaluator_id="external-evaluator",evidence_id="evidence-0"),elapsed_ms=100)
        self.assertEqual(receipt.subject_id,"subject-0")
        self.assertEqual(self.bindings[0].sidecar.count,1)
        self.assertEqual(self.bindings[1].sidecar.count,before)

    def test_foreign_model_and_cross_domain_grants_denied(self):
        other=self.grant(0,"pleasure","STEP_PROXY","cross")
        with self.assertRaises(ValueError):
            self.gateway.describe_sexuality(other)
        forged=self.authority.issue(self.bindings[0],domain="sexuality",
                          operation="DESCRIBE_RESEARCH",grant_id="model-a",expires_epoch=1100)
        self.gateway.sessions[0],self.gateway.sessions[1]=self.gateway.sessions[1],self.gateway.sessions[0]
        with self.assertRaises(ValueError):
            self.gateway.describe_sexuality(forged)

    def test_replay_expiry_revoke_and_forgery_denied(self):
        grant=self.grant(0,"sexuality","DESCRIBE_RESEARCH","once")
        self.gateway.describe_sexuality(grant)
        with self.assertRaises(ValueError): self.gateway.describe_sexuality(grant)
        expired=self.authority.issue(self.bindings[0],domain="sexuality",
                operation="DESCRIBE_RESEARCH",grant_id="expired",expires_epoch=999)
        with self.assertRaises(ValueError): self.gateway.describe_sexuality(expired)
        revoked=self.grant(0,"sexuality","DESCRIBE_RESEARCH","revoked")
        self.gateway.revoke("grant-revoked")
        with self.assertRaises(ValueError): self.gateway.describe_sexuality(revoked)
        from dataclasses import replace
        with self.assertRaises(ValueError):
            self.gateway.describe_sexuality(replace(self.grant(0,"sexuality","DESCRIBE_RESEARCH","forge"),subject_id="other"))

    def test_mutated_sidecar_config_denied_before_state_change(self):
        bind=self.bindings[0]
        bind.sidecar.config=FakeConfig("other","c"*64,"forged","subject-1","external-evaluator")
        with self.assertRaises(ValueError):
            self.gateway.step_pleasure(self.grant(0,"pleasure","STEP_PROXY","mutate"),
                 SimpleNamespace(subject_id="subject-0",evaluator_id="external-evaluator",
                                 evidence_id="new"),elapsed_ms=100)
        self.assertEqual(bind.sidecar.count,0)

    def test_host_binding_substitution_denied_even_with_matching_identity(self):
        original=self.bindings[0]
        replacement=HostModelBinding(
            adapter=original.adapter, runtime=FakeQualifiedRuntime(original.adapter),
            provider_authority=original.provider_authority,
            sidecar=original.sidecar, session_id=original.session_id)
        self.gateway.sessions[0]=replacement
        grant=self.authority.issue(original, domain="sexuality",
            operation="DESCRIBE_RESEARCH", grant_id="swapped-host", expires_epoch=1100)
        with self.assertRaisesRegex(ValueError, "host binding changed"):
            self.gateway.describe_sexuality(grant)

    def test_fake_runtime_cannot_claim_qualified_dispatch(self):
        grant=self.grant(0,"model","GENERATE_CANDIDATE","fake-host")
        with self.assertRaisesRegex(ValueError,"QualifiedVeraRuntime"):
            self.gateway.generate_candidate(grant,"neutral request",max_tokens=8)
        self.assertEqual(self.bindings[0].runtime.invocations,[])

    def test_generation_requires_separate_model_domain_grant(self):
        research=self.grant(0,"sexuality","DESCRIBE_RESEARCH","wrong-generation")
        with self.assertRaisesRegex(ValueError,"cross-domain"):
            self.gateway.generate_candidate(research,"neutral",max_tokens=8)
        self.assertEqual(self.bindings[0].runtime.invocations,[])
        self.assertEqual(self.bindings[1].runtime.invocations,[])

    def test_research_only_binding_requires_no_pleasure_engine(self):
        binding = HostModelBinding(
            adapter=self.adapters[0], runtime=None, provider_authority=None,
            sidecar=None, session_id="research-only",
            runtime_instance_id="isolated-research-instance",
            subject_id="isolated-research-subject", evaluator_id="external-evaluator")
        gateway = GenericCapabilityGateway(self.authority, [binding], now=lambda: 1000)
        grant = self.authority.issue(binding, domain="sexuality",
               operation="DESCRIBE_RESEARCH", grant_id="independent-research",
               expires_epoch=1100)
        metadata = gateway.describe_sexuality(grant)
        self.assertEqual(metadata["status"], "SOURCE_ONLY_NOT_BEHAVIORALLY_QUALIFIED")
        blocked = self.authority.issue(binding, domain="pleasure",
                operation="STEP_PROXY", grant_id="uninstalled-sidecar", expires_epoch=1100)
        with self.assertRaises(ValueError):
            gateway.step_pleasure(blocked, SimpleNamespace(
                subject_id="isolated-research-subject",
                evaluator_id="external-evaluator"), elapsed_ms=100)

    def test_shared_sidecar_is_rejected(self):
        with self.assertRaises(ValueError):
            HostModelBinding(adapter=self.adapters[1],runtime=self.bindings[1].runtime,
               provider_authority=self.bindings[1].provider_authority,
               sidecar=self.bindings[0].sidecar,session_id="session-duplicate")

if __name__=="__main__":unittest.main()
