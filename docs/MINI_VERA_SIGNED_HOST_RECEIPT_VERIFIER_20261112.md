# Mini-Vera signed host receipt verifier — source candidate (2026-11-12)

## Status and scope

New source: tools/mini_vera/signed_host_receipt.py. It verifies a tightly bounded externally signed Ed25519 read-only host observation. The verifier contains no private key, grants no model tool authority, never starts inference, and does not write memory or alter host state.

The optional Python cryptography distribution supplies Ed25519 verification. If it is not installed, receipt verification refuses. Existing Mini-Vera paths never import it eagerly.

## Controller-owned inputs

An independently authorized controller outside the model must provide an approved 32-byte Ed25519 verification key, an independently pinned SHA-256 of that key, current request and turn digests, independently verified expected source digest, a fresh 128-bit challenge, and trusted UTC clock.

The receipt cannot choose its own verification key. Its issuer_id is descriptive, NOT proof of host or credential identity. Signature validity proves possession of the specified signing key, not the truth of what was signed.

## Fixed receipt contract

Receipt operation READ_ONLY_SOURCE_SHA256, source tools/mini_vera/compose.py, effect NONE. Payload includes source size and SHA-256, request and turn SHA-256, fresh challenge, UTC issuance timestamp and issuer_id. Signature is Ed25519 over canonical JSON payload bytes.

Input JSON fields and types are fixed; duplicate keys, oversized bytes, alternate operations/effects, bad signatures, mismatched key fingerprints, swapped source/request/turn/challenge, stale/future timestamp and invalid source size are all rejected.

One verifier instance accepts only one receipt. A process-local lock prevents simultaneous replay. A new challenge from a new controller session rejects previously signed bytes. The nonce itself does NOT provide durable replay protection if the controller repeats it after restart.

## Evidence and limitations

Tests use disposable Ed25519 keys, including one separate synthetic signer subprocess. They prove source-level signature verification and process crossing, NOT an authorized or protected host issuer. No production signing key, protected issuer, out-of-process source readback, trust-root onboarding or durable replay store has been installed.

A caller that supplies both its own public key and its own matching hash is not independently trusted. The source hash must also originate from an independently authorized host controller, not from the model or an unsigned local self-report.

This module is not wired into the Mini-Vera inference pipeline. It cannot justify claims of signed host evidence or model identity until a host-owned issuer, key custody, trusted challenge controller, replay governance and full live tests exist.
