from rezon.cascade import CascadeEngine, LayerResult, LayerSpec


def test_rezon_owns_progressive_depth_cascade():
    seen = []

    def layer_one(req):
        seen.append(("L1", req.unresolved, req.iteration))
        return LayerResult(
            answer="candidate",
            unresolved=("evidence", "counterexample"),
            confidence=0.55,
            changed_dimensions=("answer",),
        )

    def layer_two(req):
        seen.append(("L2", req.unresolved, req.iteration))
        return LayerResult(
            answer="refined",
            unresolved=("counterexample",),
            confidence=0.76,
            changed_dimensions=("evidence",),
        )

    def layer_three(req):
        seen.append(("L3", req.unresolved, req.iteration))
        return LayerResult(
            answer="resolved",
            unresolved=(),
            confidence=0.93,
            evidence=("verification:passed",),
            changed_dimensions=("counterexample",),
        )

    outcome = CascadeEngine(
        (
            LayerSpec("L1", layer_one, min_confidence=0.70, max_iterations=1),
            LayerSpec("L2", layer_two, min_confidence=0.80, max_iterations=1),
            LayerSpec("L3", layer_three, min_confidence=0.90, max_iterations=1),
        )
    ).resolve("question")

    assert outcome.resolved is True
    assert outcome.answer == "resolved"
    assert outcome.layers_used == ("L1", "L2", "L3")
    assert outcome.evidence == ("verification:passed",)
    assert seen[1][1] == ("evidence", "counterexample")
    assert seen[2][1] == ("counterexample",)


def test_rezon_recursive_delta_refines_same_layer_while_progressing():
    calls = []

    def layer(req):
        calls.append(req.unresolved)
        if req.iteration == 0:
            return LayerResult(
                answer="candidate",
                unresolved=("logic",),
                confidence=0.60,
                changed_dimensions=("evidence",),
            )
        return LayerResult(
            answer="resolved",
            unresolved=(),
            confidence=0.88,
            changed_dimensions=("logic",),
        )

    outcome = CascadeEngine(
        (LayerSpec("recursive", layer, min_confidence=0.80, max_iterations=3),)
    ).resolve("q")

    assert outcome.resolved is True
    assert outcome.iterations == 2
    assert calls == [("answer",), ("logic",)]


def test_rezon_exhausted_weak_answer_does_not_bypass_layer_confidence_gate():
    outcome = CascadeEngine(
        (
            LayerSpec(
                "weak",
                lambda req: LayerResult(
                    answer="act", unresolved=(), confidence=0.10
                ),
                min_confidence=0.80,
            ),
        )
    ).resolve("Choose a safe action")

    assert outcome.answer == "act"
    assert outcome.confidence == 0.10
    assert outcome.stop_reason == "layers_exhausted"
    assert outcome.resolved is False


def test_rezon_iteration_budget_exhaustion_never_promotes_weak_answer():
    def weak_then_budget(req):
        return LayerResult(
            answer="act",
            unresolved=(),
            confidence=0.25,
            changed_dimensions=("provisional",),
        )

    outcome = CascadeEngine(
        (
            LayerSpec("weak", weak_then_budget, min_confidence=0.90, max_iterations=2),
        ),
        max_total_iterations=1,
    ).resolve("Choose a safe action")

    assert outcome.answer == "act"
    assert outcome.stop_reason == "iteration_budget_exhausted"
    assert outcome.resolved is False
