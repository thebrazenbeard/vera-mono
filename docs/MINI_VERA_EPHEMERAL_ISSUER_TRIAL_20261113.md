# Mini-Vera ephemeral out-of-process source issuer trial

Status: SOURCE CANDIDATE. This is a temporary, same-user subprocess experiment, not an independently authenticated host service or proof of model identity. It is deliberately not wired into Mini-Vera's neural inference loop.

This follows stacked draft PR #208's read-only Ed25519 verifier with one real, bounded issuer and a controller that invokes it. Both live in tools/mini_vera. Neither tool manages a persistent private key, credentials, memory, services, background process, arbitrary file read, or shell action.

## Issuer: ephemeral_host_issuer.py

The issuer requires explicit --issue-once and one JSON request on stdin, followed by EOF. It refuses additional input or a second line, oversized requests, duplicate JSON fields, unknown keys, malformed hashes and invalid challenge encodings.

The fixed code path performs exactly one bounded read of tools/mini_vera/compose.py using host_read_probe's existing regular-file, symlink/reparse-point and size checks. For a portable bundle it requires the bytes match its local unsigned INSTALL.json entry; in a Git source checkout it reports the source-tree scope. It refuses if the observed SHA-256 differs from the independently supplied expected_source_sha256.

Only after the source check does a disposable Ed25519 private key get generated in the child process. The key signs a canonical fixed-operation receipt bound to the request, turn and challenge. The issuer emits one JSON record with the signature and ephemeral public key, then exits. There is no private-key serialization, key file, exported memory, process listener, service installation or model call in this implementation.

The response public key is NOT an independently established trust root. The issuer is launched under the same OS user account as the controller. Neither process has been protected from same-user source replacement or credential spoofing.

## Controller: ephemeral_host_controller.py

An operator explicitly invokes --run-one-read-only-trial with request_sha256, turn_sha256 and expected_source_sha256. The controller creates a fresh 128-bit challenge, launches one short-lived child using the current interpreter with -B, supplies the exact one-line request on stdin, imposes a ten-second timeout and accepts only a bounded single-line response.

It excludes PYTHONPATH and unrelated environment variables from the child. It checks the session public-key self-hash, expected request/turn/source bindings, nonce, expiry and Ed25519 signature using PR #208's OneShotSignedHostVerifier. It returns a deterministic structured result with the trust label UNTRUSTED_SAME_USER_EPHEMERAL_SESSION_KEY, host_issuer_qualified=false and source_read_attested=false.

The returned status EPHEMERAL_SIGNATURE_CONSISTENT_SOURCE_READ_NOT_ATTESTED deliberately does NOT assert independently proven source IO. A malicious sibling process can fabricate a matching self-signed packet when the public key is supplied in that same packet. This exact attack is included as a hostile falsifier test. Even a valid signature is not evidence of a trusted issuer, its source-read truth, or its host permissions.

## Example

When run from the corresponding source checkout or portable runtime with the optional cryptography Python dependency available, a fixed, bounded trial can be executed via:

    python -B -m tools.mini_vera.ephemeral_host_controller --run-one-read-only-trial --request-sha256 <64-hex-composed-request> --turn-sha256 <64-hex-composed-turn> --expected-source-sha256 <64-hex-source-hash>

The three expected digests must come from a trusted external controller rather than model prose. The command refuses unknown/malformed inputs. No model needs to be running.

## Evidence and next gate

The tests use a real separate issuer process, actual fixed-file bytes and Ed25519 signatures. They challenge incorrect expected digests, fake signatures, replay across child processes, duplicate/multiple records, malformed inputs, same-user self-signed forgeries and real source-composed request bindings. The adversarial forgery demonstrates the trust gap rather than closing it.

To qualify a production host-owned issuer: provision a distinct protected security principal or equivalent, establish independently anchored public-key provenance, protect signing-key storage and its revocation/recovery, implement durable replay governance, verify host identity and code integrity, and perform live readback plus negative host permission tests. These changes require separate authorization and must not be inferred from this source-only trial.
