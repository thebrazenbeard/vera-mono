"""Networkless-cell implementation of QVR #82's optional cognition transport.

The actual QualifiedVeraRuntime (PR #82) runs in a host-side test harness; its
selected transport is pinned to a Docker networkless worker plus a HOST-OWNED
gateway callback. This does NOT move the complete QualifiedVeraRuntime process
into Docker. It cannot prove a production sole-route or independent claim.
"""
from __future__ import annotations

import hashlib
from typing import Callable

from .networkless_learner_cell import (
    IsolationFailure,
    run_networkless_learner_step,
)


class QVRCellBoundaryError(RuntimeError):
    pass


class NetworklessQVRTransport:
    """Implements the exact optional `generate` interface from PR #82."""

    def __init__(self, *, image_id: str, model: str, digest: str,
                 host_gateway_callback: Callable[..., object]):
        from vera_core.local_cognition import MODEL, DIGEST
        if type(model) is not str or MODEL.fullmatch(model) is None:
            raise ValueError("invalid QVR model")
        if type(digest) is not str or DIGEST.fullmatch(digest) is None:
            raise ValueError("invalid QVR model digest")
        if not callable(host_gateway_callback):
            raise TypeError("host gateway callback required")
        self.image_id = image_id
        self.model = model
        self.digest = digest
        self.host_gateway_callback = host_gateway_callback

    def generate(self, prompt: str, *, permit=None, max_tokens: int = 64):
        from vera_core.local_cognition import (
            InferencePermit,
            LocalTextReceipt,
            EXACT_TEST_SCOPE,
            MAX_PROMPT_BYTES,
            MAX_OUTPUT_BYTES,
        )
        if (type(permit) is not InferencePermit
                or permit.model != self.model
                or permit.digest != self.digest
                or permit.scope != EXACT_TEST_SCOPE
                or type(prompt) is not str
                or not prompt
                or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES
                or type(max_tokens) is not int
                or not 1 <= max_tokens <= 128):
            raise QVRCellBoundaryError("QVR test permit or prompt invalid")

        def gateway_requested(original_prompt: str):
            return self.host_gateway_callback(
                original_prompt, permit=permit, max_tokens=max_tokens)
        try:
            outcome = run_networkless_learner_step(
                image_id=self.image_id,
                prompt=prompt,
                gateway_callback=gateway_requested,
            )
        except IsolationFailure as exc:
            raise QVRCellBoundaryError("QVR networkless cell failed closed") from exc
        # These flags must never be sourced as positive qualification claims.
        if (outcome.isolation_observed is not True
                or outcome.host_gateway_callback_called is not True
                or outcome.gateway_effect_independently_verified is not False
                or outcome.actual_selected_qvr_route_verified is not False
                or outcome.learning_qualified is not False):
            raise QVRCellBoundaryError("inconsistent or promoted cell evidence")
        receipt = outcome.gateway_callback_result
        if type(receipt) is not LocalTextReceipt:
            raise QVRCellBoundaryError("gateway result is not the exact QVR receipt")
        if (receipt.model != permit.model
                or receipt.reported_model_digest != permit.digest
                or receipt.prompt_sha256 != hashlib.sha256(
                    prompt.encode("utf-8")).hexdigest()
                or receipt.response_sha256 != hashlib.sha256(
                    receipt.text.encode("utf-8")).hexdigest()
                or len(receipt.text.encode("utf-8")) > MAX_OUTPUT_BYTES
                or receipt.runtime_consumption_verified
                or receipt.authorized_tool_effect
                or receipt.model_byte_identity_verified
                or receipt.independent_review_verified):
            raise QVRCellBoundaryError("gateway QVR receipt invalid or overqualified")
        return receipt
