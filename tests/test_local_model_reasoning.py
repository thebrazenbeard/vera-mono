"""Real loopback HTTP transport tests; model responses are stubbed, not AGI evidence."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest

from rezon.cascade import CascadeEngine, LayerResult, LayerSpec, ReasoningRequest
from vera_core import (
    ClosedLoopFrontier,
    ClosedLoopTask,
    DurableDispatchGate,
    LocalOllamaReasoningLayer,
)


@pytest.fixture
def ollama_stub():
    seen = []
    response = {"status": 200, "body": {
        "model": "tiny-model:latest", "response": "inspect", "done": True,
    }}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((
                self.path,
                json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
            ))
            if response.get("malformed_http"):
                self.wfile.write(b"NOT_HTTP_RESPONSE\r\n\r\n")
                self.close_connection = True
                return
            body = response["body"]
            wire = (json.dumps(body).encode("utf-8") if isinstance(body, dict)
                    else body)
            self.send_response(response["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, seen, response
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _task():
    return ClosedLoopTask(
        task_id="real-http-synthetic-model",
        prompt="Choose a non-destructive candidate action.",
        semantic_object={
            "schema_version": "0.1", "object_type": "node",
            "id": "NODE-78787878-7878-4787-8787-787878787878",
            "primary_label": "local model cue", "aliases": [],
            "node_kind": "concept", "notes": None,
        },
    )


def test_real_local_http_model_reply_is_only_unverified_candidate(ollama_stub):
    port, seen, _ = ollama_stub
    layer = LocalOllamaReasoningLayer(model="tiny-model:latest", port=port)
    outcome = CascadeEngine((layer.layer_spec(),)).resolve("What is the candidate?")

    assert len(seen) == 1
    assert seen[0][0] == "/api/generate"
    assert seen[0][1] == {
        "model": "tiny-model:latest",
        "prompt": "What is the candidate?",
        "stream": False,
        "options": {"num_predict": 256, "num_ctx": 1024},
        "keep_alive": "0s",
    }
    assert outcome.answer == "inspect"
    assert outcome.resolved is False
    assert outcome.confidence == 0.0
    assert outcome.unresolved == ("model_output_unverified",)
    assert len(outcome.evidence) == 1
    assert outcome.evidence[0].startswith("local-ollama:response-sha256:")


def test_unverified_model_cannot_pass_agi_dispatch_gate(ollama_stub, tmp_path):
    port, seen, _ = ollama_stub
    layer = LocalOllamaReasoningLayer(model="tiny-model:latest", port=port)
    cascade = CascadeEngine((layer.layer_spec(),))
    gate = DurableDispatchGate(
        tmp_path / "dispatch.db", lineage_id="model-candidate",
        remaining_active=1, remaining_retries=0, remaining_backend_jobs=1,
    )
    observations = []
    with pytest.raises(ValueError, match="did not resolve"):
        ClosedLoopFrontier(tmp_path / "loop").run_bounded(
            _task(), cascade=cascade, dispatch_gate=gate,
            holder="test-worker", now=10.0, ttl=30.0,
            expected_generation=0,
            act=lambda action: observations.append(action),
        )
    assert len(seen) == 1
    assert observations == []
    # Existing research frontier behavior: it admitted caller-supplied task
    # semantics before discovering the model response was unresolved.
    # This is NOT a model-derived memory write, nor zero-state-change proof.
    persisted = ClosedLoopFrontier(tmp_path / "loop").semantic.get(
        _task().semantic_object["id"]
    )
    assert persisted["primary_label"] == "local model cue"
    # No model-supplied action consumed the dispatch budget.
    admission = gate.claim(
        work_id="independent-work", holder="test-worker", now=11.0,
        ttl=30.0, expected_generation=0, retry=False,
    )
    assert admission.remaining_active == 0


def test_explicit_separate_review_layer_can_clear_unresolved_model_candidate(
    ollama_stub, tmp_path
):
    port, _, _ = ollama_stub
    layer = LocalOllamaReasoningLayer(model="tiny-model:latest", port=port)
    calls = []

    def reviewer(request):
        # Synthetic test reviewer only: no claim of independent qualification.
        calls.append((request.prior_answer, request.unresolved))
        return LayerResult(
            answer="inspect" if request.prior_answer == "inspect" else None,
            unresolved=() if request.prior_answer == "inspect" else ("answer",),
            confidence=0.9,
            evidence=("synthetic-review:test-only",),
        )

    cascade = CascadeEngine((
        layer.layer_spec(),
        LayerSpec("external-review", reviewer, min_confidence=0.8),
    ))
    gate = DurableDispatchGate(
        tmp_path / "dispatch.db", lineage_id="reviewed-candidate",
        remaining_active=1, remaining_retries=0, remaining_backend_jobs=1,
    )
    result = ClosedLoopFrontier(tmp_path / "loop").run_bounded(
        _task(), cascade=cascade, dispatch_gate=gate,
        holder="test-worker", now=10.0, ttl=30.0,
        expected_generation=0,
        act=lambda action: {"observed_action": action, "success": True},
    )
    assert calls == [("inspect", ("model_output_unverified",))]
    assert result.reasoned_action == "inspect"
    assert result.dispatch_completed is True
    assert result.authorization_effect == "NONE"


@pytest.mark.parametrize("mutation, expected", [
    ({"status": 500}, "http_error"),
    ({"body": b"not-json"}, "transport_or_decode_error"),
    ({"body": {"model": "other", "response": "inspect", "done": True}},
     "unconfirmed_model_response"),
    ({"body": {"model": "tiny-model:latest", "response": "inspect", "done": False}},
     "unconfirmed_model_response"),
    ({"body": {"model": "tiny-model:latest", "response": "", "done": True}},
     "empty_response"),
])
def test_bad_model_or_transport_response_abstains(ollama_stub, mutation, expected):
    port, _, response = ollama_stub
    response.update(mutation)
    observed = LocalOllamaReasoningLayer(
        model="tiny-model:latest", port=port,
    ).run(ReasoningRequest("candidate"))
    assert observed.answer is None
    assert observed.resolved is False
    assert observed.evidence == (f"local-ollama:{expected}",)


def test_response_size_cap_and_prompt_limit_abstain(ollama_stub):
    port, seen, response = ollama_stub
    response["body"] = b"x" * 1024
    layer = LocalOllamaReasoningLayer(
        model="tiny-model:latest", port=port, max_output_bytes=64,
    )
    result = layer.run(ReasoningRequest("bounded"))
    assert result.evidence == ("local-ollama:response_too_large",)
    large = layer.run(ReasoningRequest("a" * 32769))
    assert large.evidence == ("local-ollama:prompt_too_large",)
    assert len(seen) == 1


def test_malformed_http_abstains_without_bubbling_transport_exception(ollama_stub):
    port, _, response = ollama_stub
    response["malformed_http"] = True
    observed = LocalOllamaReasoningLayer(
        model="tiny-model:latest", port=port,
    ).run(ReasoningRequest("candidate"))
    assert observed.answer is None
    assert observed.evidence == ("local-ollama:transport_or_decode_error",)


@pytest.mark.parametrize("kwargs", [
    {"model": "-unsafe"},
    {"model": "valid", "port": True},
    {"model": "valid", "port": 0},
    {"model": "valid", "timeout_seconds": -1},
    {"model": "valid", "max_output_bytes": 1048577},
    {"model": "valid", "num_predict": 0},
    {"model": "valid", "num_ctx": 0},
    {"model": "valid", "num_ctx": 8193},
    {"model": "valid", "num_ctx": True},
])
def test_unbounded_or_invalid_model_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        LocalOllamaReasoningLayer(**kwargs)
