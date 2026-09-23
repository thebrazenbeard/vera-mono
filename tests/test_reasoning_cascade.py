from vera_core.reasoning_cascade import CascadeEngine, LayerResult, LayerSpec


def test_escalates_only_when_lower_layer_cannot_resolve():
    calls = []

    def shallow(req):
        calls.append(("shallow", req.unresolved))
        return LayerResult("candidate", ("evidence",), 0.55)

    def deep(req):
        calls.append(("deep", req.unresolved))
        return LayerResult("verified", (), 0.92, evidence=("source:a",))

    outcome = CascadeEngine(
        (
            LayerSpec("L1", shallow, min_confidence=0.70),
            LayerSpec("L2", deep, min_confidence=0.85),
        )
    ).resolve("question")

    assert outcome.resolved is True
    assert outcome.answer == "verified"
    assert outcome.layers_used == ("L1", "L2")
    assert calls[1] == ("deep", ("evidence",))


def test_recursive_refinement_stops_when_delta_stalls():
    calls = []

    def layer(req):
        calls.append(req.iteration)
        return LayerResult("candidate", ("logic",), 0.60)

    outcome = CascadeEngine((LayerSpec("L1", layer, max_iterations=4),)).resolve("q")

    assert outcome.resolved is False
    assert outcome.iterations == 1
    assert outcome.stop_reason == "layers_exhausted"
