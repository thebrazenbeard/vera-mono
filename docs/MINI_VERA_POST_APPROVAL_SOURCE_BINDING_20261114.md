# Mini-Vera post-approval PUBLIC-source binding — 2026-11-14

Status: additive, opt-in SOURCE CANDIDATE stacked on Draft PR #215.
No model weights changed and no real/private user memory admitted.

## Material falsifier

The previous synthetic public fact gate validated a request's *self-hash* and
the synthetic fact syntax, but its standalone apply() accepted a positive
synthetic fact without any proof it came from the live public-memory
approval callback. A caller capable of building a self-consistent request
could therefore get an exact source-looking answer released.

A focused red test demonstrated the behavior for both supported question
types: without post-approval binding, the old function returned
SOURCE_MATCHED_SYNTHETIC_RECORD_NOT_HOST_ATTESTATION, rather than withholding.
The same initial red run showed that the needed approval binding argument did
not exist. No claim of production exploitation follows from this isolated
direct-call vulnerability.

## Corrected boundary

public_fact_guard.apply() now takes the optional keyword-only argument
approved_state_binding=(state, key, revision). If the question has a
project reference but no such binding, the client returns UNKNOWN and
WITHHELD_NO_LIVE_SOURCE_BINDING, regardless of apparent neural agreement.

When a binding exists, the guard validates the supplied state with
compose.verify_state (the existing HMAC and exact revision checks), then
requires its complete projected record list to equal the exact records
carried in the model request, and the state SHA/revision to equal the
request provenance. Mismatch in source bytes, HMAC, state revision, state
shape or record inventory fails closed. The old model-text redaction,
envelope field whitelist and source-matched fact extraction remain intact.

The only runtime callsite is local_session.main's opt-in synthetic
fact flag. It already invokes the approved PUBLIC provider before
inference and again after inference, withholding if approval or source
integrity changes. The callsite now passes the **post-inference**
state/key/revision directly to the guard. Without a live provider, a
synthetic question with no public record is still safely answered
by the client as UNKNOWN. It never permits positive source release from
operator-loaded files in this opt-in mode.

The output separately labels source consistency
POST_APPROVAL_STATE_CONSISTENT_NOT_HOST_ATTESTED. It remains untrusted:
the caller controls the provider and the synthetic fixture's HMAC key
is source-visible. A malicious caller able to replace both request AND
provider/state/key can still manufacture internally consistent data.
This check does not provision a protected host principal, authenticate
source authorship, resist rollback, establish source correctness, or
make the neural model abstain. It closes the standalone *unbound*
source-release path while preserving those open boundaries.

## Reproduction and tests

New tests cover unbound exact responses withheld for courier directory and
cargo revision; bound exact answers allowed with source-only labeling;
freshly recomputed HMAC/revision/source-text/key/record-shape mismatches
refused; empty-memory hallucination safely withheld; and a local fake
HTTP lifecycle with two provider checks, including post-inference
revocation. Existing fact-guard unit tests are updated to pass a live
synthetic provider snapshot for positive direct-call tests.

The full regression and exact portable build are required before treating
this source candidate as verified. Avoid conflating a green fake HTTP test
with a live neural behavioral assessment.

No protected source merge, external deployment, user data import, weight
training, paid compute, shared-service restart or independent agent review
is performed by this code.
