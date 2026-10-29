"""Local two-model opt-in acceptance; external script, NOT deployed.

Generates two bounded neutral responses through QualifiedVeraRuntime,
then demonstrates separately scoped generic research/affective interfaces.
Only synthetic records are admitted to temporary test state, never Vera memory.
"""
from pathlib import Path
import sys
import os
import gc
import time
import json
import subprocess
from hashlib import sha256

ROOT=Path(__file__).resolve().parents[1]
TEST_STATE_ROOT=Path(os.environ["GENERIC_HOST_ACCEPTANCE_STATE_ROOT"]).resolve()
if TEST_STATE_ROOT.exists():
    raise RuntimeError("acceptance state root already exists; use a new empty path")
PLEASURE_SOURCE_ROOT=Path(os.environ["PLEASURE_SOURCE_ROOT"]).resolve()
if not (PLEASURE_SOURCE_ROOT / "pleasure_experiment" / "runtime.py").is_file():
    raise RuntimeError("explicit Pleasure source checkout required")
EXPECTED_PLEASURE_HEAD=os.environ["PLEASURE_SOURCE_SHA"]
observed=subprocess.run(["git","-C",str(PLEASURE_SOURCE_ROOT),"rev-parse","HEAD"],
                        capture_output=True,text=True,check=True).stdout.strip()
if observed != EXPECTED_PLEASURE_HEAD:
    raise RuntimeError("Pleasure checkout head differs from exact user-selected source")
mono=ROOT
for p in (mono/"packages").glob("*/src"):
    sys.path.insert(0,str(p))
sys.path.insert(0,str(PLEASURE_SOURCE_ROOT))
from vera_core import (HmacProviderAuthority, LocalOllamaProviderTransport,
                       QualifiedVeraRuntime, VeraStateDirectory)
from vera_memory import AdmissionRequest, MemoryClass
from vera_core.generic_capability_host import (
    CapabilityHostAuthority, GenericCapabilityGateway, HostModelBinding, ModelAdapter
)
from pleasure_experiment import ExperimentalPleasureRuntime, PilotConfig, Observation

def configured_models():
    from urllib.request import urlopen
    tags=(os.environ["GENERIC_HOST_MODEL_A"],os.environ["GENERIC_HOST_MODEL_B"])
    if tags[0] == tags[1]:
        raise ValueError("two distinct model names required")
    with urlopen("http://127.0.0.1:11434/api/tags",timeout=5) as response:
        payload=json.load(response)
    models=payload.get("models",[])
    chosen=[]
    for tag in tags:
        matches=[x for x in models if x.get("name")==tag]
        if len(matches)!=1:
            raise ValueError("selected model not uniquely present in local registry")
        digest=matches[0].get("digest")
        if type(digest) is not str or len(digest)!=64 or any(x not in "0123456789abcdef" for x in digest):
            raise ValueError("invalid registry digest")
        chosen.append((tag,digest))
    if chosen[0][1] == chosen[1][1]:
        raise ValueError("two model aliases share the same registry digest")
    return tuple(chosen)

def qualified_test_host(i,tag,digest):
    dest=TEST_STATE_ROOT/("synthetic-model-"+str(i))
    dest.mkdir(parents=True,exist_ok=True)
    project="generic-host-acceptance-"+str(i)
    identity="synthetic-model-"+str(i)
    state=VeraStateDirectory(dest/"state",project_id=project,identity_id=identity)
    life=state.open()
    admitted=life.memory.admit(AdmissionRequest(
       record_id="synthetic-host-bootstrap", text="synthetic neutral test fixture",
       memory_class=MemoryClass.WORKING_PROJECT,
       source_actor="synthetic-test-host", authority_ref="synthetic:test",
       privacy_ref="synthetic:ephemeral", provenance_refs=("synthetic:fixture",),
       operation_id="bootstrap-"+str(i), project_id=project,governed_identity_id=identity),
       expected_head=life.memory.current_head)
    life.checkpoint(checkpoint_id="checkpoint-"+str(i),runtime_id="runtime-"+str(i),
       expected_memory_head=admitted["store_head"],
       expected_checkpoint_head=life.checkpoints.current_head,
       expected_currentness_generation=None)
    provider=HmacProviderAuthority("synthetic-host-"+str(i),"local-ollama",os.urandom(32))
    state.outbound_trust_registry().register(
        authority_id=provider.authority_id,role="PROVIDER",provider_id="local-ollama",
        key_id=provider.key_id,key_digest=provider.key_digest,expected_registry_generation=0)
    transport=LocalOllamaProviderTransport(model=tag,registry_digest=digest,timeout_seconds=120)
    qualified=QualifiedVeraRuntime.from_state_directory(
        state,provider_authority_verifiers={"local-ollama":provider},
        provider_execution_transports={"local-ollama":transport})
    adapter=ModelAdapter(tag,digest,adapter_id="synthetic-adapter-"+str(i))
    sidecar=ExperimentalPleasureRuntime(PilotConfig(
        model_id=tag,model_revision=digest,runtime_instance_id="synthetic-instance-"+str(i),
        subject_id=identity,evaluator_id="external-synthetic-evaluator-"+str(i),
        measurement_definition_id="synthetic-bounded-valence-v1"))
    return HostModelBinding(adapter=adapter,runtime=qualified,provider_authority=provider,
                            sidecar=sidecar,session_id="synthetic-session-"+str(i))

def main():
    bindings=[qualified_test_host(i,*spec) for i,spec in enumerate(configured_models())]
    issuer=CapabilityHostAuthority("synthetic-test-host",os.urandom(32))
    gateway=GenericCapabilityGateway(issuer,bindings,now=lambda:int(time.time()))
    observed=[]
    for i,b in enumerate(bindings):
        def grant(domain,operation,suffix):
            return issuer.issue(b,domain=domain,operation=operation,
              grant_id="accept-"+str(i)+"-"+suffix,expires_epoch=int(time.time())+180)
        research=gateway.describe_sexuality(grant("sexuality","DESCRIBE_RESEARCH","research"))
        proxy=gateway.step_pleasure(grant("pleasure","STEP_PROXY","proxy"),
             Observation(subject_id=b.sidecar.config.subject_id,
                         evaluator_id=b.sidecar.config.evaluator_id,
                         evidence_id="synthetic-external-evidence-"+str(i),
                         context_id="test-context-"+str(i),reward=0.25,
                         novelty=0.10),elapsed_ms=100)
        generated=gateway.generate_candidate(grant("model","GENERATE_CANDIDATE","generated"),
                "Reply with one neutral word.",max_tokens=16)
        assert generated["model"]==b.adapter.model_tag and generated["qualified"] is False
        assert research["model_id"]==b.adapter.model_tag
        assert proxy.subject_id==b.sidecar.config.subject_id
        observed.append({"model":b.adapter.model_tag,
                         "registry_digest":b.adapter.registry_digest,
                         "research_status":research["status"],
                         "proxy_sequence":proxy.sequence,
                         "proxy_model":proxy.model_id,
                         "inference_kind":generated["kind"],
                         "inference_sha256":generated["response_sha256"]})
    assert observed[0]["model"] != observed[1]["model"]
    assert observed[0]["proxy_model"] != observed[1]["proxy_model"]
    assert bindings[0].sidecar.state.sequence == 1
    assert bindings[1].sidecar.state.sequence == 1
    # A's HMAC permission does not become B's; a subject swap invalidates MAC.
    from dataclasses import replace
    forbidden=issuer.issue(bindings[0],domain="pleasure",operation="STEP_PROXY",
                           grant_id="cross-attack",expires_epoch=int(time.time())+180)
    try:
        gateway.step_pleasure(replace(forbidden,model_tag=bindings[1].adapter.model_tag),
            Observation(subject_id=bindings[1].sidecar.config.subject_id,
                        evaluator_id=bindings[1].sidecar.config.evaluator_id,
                        evidence_id="cross-evidence",context_id="cross",
                        reward=0.5),elapsed_ms=100)
    except ValueError:
        pass
    else:
        raise AssertionError("Cross-model forged grant unexpectedly succeeded")
    assert bindings[1].sidecar.state.sequence == 1
    print(json.dumps({"scope":"LOCAL_SYNTHETIC_HOST_TEST_ONLY",
      "provider_identity":"OLLAMA_REGISTRY_SELF_REPORTED",
      "qualified_deployment":False,"model_visible_tool_registry":False,
      "model_count":len(observed),"models":observed,
      "cross_model_permission_denied":True,
      "independent_sidecar_state":True},indent=2))
if __name__=="__main__":
    main()
