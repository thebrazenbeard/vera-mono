# WorkBridgeMCP current provider-boundary review

Subject: thebrazenbeard/WorkBridgeMCP main at exact head 8707a2e1eaf7de5ce2316567b5e6f1e805c0537b.

## Evidence status

Lappy does not currently expose a Go toolchain in PATH. Local exact-head Go module verification, tests, vet, and build were therefore unavailable and are not represented as having passed.

GitHub CI run 36074960707 on PR #11 completed successfully. Its exact workflow includes, on both Ubuntu and Windows for the bounded Go WorkBridge server:
- go mod verify;
- go test ./...;
- go vet ./...;
- Go build;
- Windows stdio/HTTP smoke and packaging/installer guard checks;
- a separate Windows cross-build job.

The same workflow separately verifies the exact Desktop Commander duplicate on Ubuntu and Windows. These are separate evidence classes and separate capability surfaces.

## Bounded WorkBridge mechanism

The bounded Go WorkBridge server registers tools according to loaded configuration. Read tools require admitted read roots; write tools appear only when write roots exist; process_run appears only when process execution is enabled and configured executable grants pass startup identity checks.

Its process runner accepts a grant name instead of an arbitrary executable path, resolves and hashes the executable at admission, re-resolves and re-hashes immediately before execution, invokes the executable directly without inserting a shell, uses a reduced child environment, bounds arguments/runtime/output, and re-hashes after execution.

WorkBridge's own security documentation correctly limits that claim: pre/post hashes are not a cryptographic binding to the OS executable-open operation, and a hostile local administrator remains outside the current ceiling.

## Current WorkBridge main also contains Desktop Commander

PR #11 merged an exact duplicate of Desktop Commander, preserving its unrestricted command-string execution surface. That surface is not silently promoted into Vera's PC policy merely because the source now lives in the same external repository.

The bounded WorkBridge configuration/capability model and the unrestricted Desktop Commander duplicate are treated as distinct provider mechanisms.

## Vera gap found

PCCC JobEnvelope already carried required_capability_digest, required_local_policy_digest, and read_roots_digest. Before this adaptation, Vera's injected PCExecutionTransport exposed only host_id plus execute(), and qualified dispatch compared only host identity.

An adversarial test proved that a transport with the correct host_id but a mismatched live capability digest was still executed.

## Vera adaptation

PCExecutionTransport now requires attest(). The returned live observation contains host_id, capability_digest, local_policy_digest, and read_roots_digest.

Immediately before either qualified PC execution path dispatches, Vera requires:
- observed host == transport host == job host;
- observed capability digest == job.required_capability_digest;
- observed local-policy digest == job.required_local_policy_digest;
- observed read-root digest == job.read_roots_digest.

The journal-backed adapter rejects mismatch before creating local attempt state. The direct QualifiedVeraRuntime PC path rejects mismatch before effect dispatch. A legacy transport without attest() is rejected at runtime composition.

## What is deliberately not imported

Vera does not import WorkBridge as a runtime dependency, does not install or activate WorkBridge, does not add a listener, does not copy the process runner, and does not admit unrestricted Desktop Commander execution.

PCCC phase-one restrictions remain unchanged; arbitrary shell/process execution remains forbidden by the existing pc_connection capability contract.

## Non-equivalences

matching capability digest != permission
matching capability digest != independent capability verification
matching local-policy digest != correct policy
matching read-roots digest != filesystem confinement proof
provider source != provider installation
transport observation != independent attestation
provider capability != protected-effect authority

Claim ceiling: source-level pre-dispatch live transport requirement matching only. No provider installation, selected route, independent provider qualification, external effect, or AGI claim.