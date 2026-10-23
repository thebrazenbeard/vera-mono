"""Read-only, exact-source Goal 1 inter-PR acceptance diagnostic.

Loads selected #82 local_cognition_journal, #86 revision receipt/binder and
#87 causal_trial source FILES, not a merged runtime. No model call, no remote
credential, no hidden label, no deployment, no claim of learning.

The revision class is AST-extracted from the actual #86 source so that this
minimal offline probe does not need to import unrelated Vera packages or
execute their initialization. Only that dataclass is used, not its guard
methods. Both binding functions and the evaluator controller are executed
from the original supplied source files without replacement.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("unable to load selected source")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _revision_type(path: Path):
    """Execute only the exact #86 TrialPromptReceipt class, not other imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "TrialPromptReceipt"]
    if len(matches) != 1:
        raise ValueError("missing unique real TrialPromptReceipt definition")
    module_name = "research.goal1_learning_trial.revision_context"
    module = types.ModuleType(module_name)
    module.__dict__.update({"__name__": module_name, "dataclass": dataclass})
    # Class annotations refer to built-in types only; postponed evaluation is
    # required to reproduce #86's 'from __future__ import annotations'.
    code = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        matches[0],
    ], type_ignores=[])
    ast.fix_missing_locations(code)
    sys.modules[module_name] = module
    exec(compile(code, str(path), "exec"), module.__dict__)
    return module.TrialPromptReceipt


def _must_reject(operation, phrase: str) -> bool:
    try:
        operation()
    except ValueError as exc:
        if phrase not in str(exc):
            raise AssertionError(f"unexpected rejection: {type(exc).__name__}") from exc
        return True
    raise AssertionError("a required fail-closed protocol check accepted invalid evidence")


def inspect_contracts(journal_path: Path, revision_path: Path,
                      binding_path: Path, controller_path: Path) -> dict:
    paths = tuple(map(Path, (journal_path, revision_path, binding_path, controller_path)))
    for path in paths:
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("four bounded exact source files required")
    source_hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for name, path in zip(("qvr_journal", "revision_receipt",
                                            "learner_binding", "evaluator_controller"), paths)}

    # Install namespace only for the true #86 relative import; do not mutate
    # the repository or substitute its binder with a test double.
    for name in ("research", "research.goal1_learning_trial"):
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = []
            sys.modules[name] = package
    TrialPromptReceipt = _revision_type(paths[1])
    journal_mod = _load("goal1_exact_qvr_journal", paths[0])
    binding_mod = _load("research.goal1_learning_trial.challenge_binding", paths[2])
    eval_mod = _load("goal1_exact_evaluator_controller", paths[3])

    class FakeVerifier:
        """INTENTIONALLY UNTRUSTED simulation: NEVER independent custody."""
        def verify(self, _evidence):
            return True

    with tempfile.TemporaryDirectory(prefix="goal1-evidence-probe-") as root:
        journal = journal_mod.LocalCognitionJournal(Path(root) / "qvr.sqlite")
        timeout_id = "synthetic-ambiguous-timeout"
        journal.require_unused(timeout_id)
        # Represents the present #82 flow after generate() raised: no append.
        # This is a contract simulation, NOT an actual dispatched model timeout.
        journal.require_unused(timeout_id)
        timeout_reusable = not any(r["invocation_id"] == timeout_id
                                   for r in journal.history())

        controller = eval_mod.CausalTrialController("GOAL1-SOURCE-CONTRACT-PROBE")
        view = controller.issue("train")[0]
        task = binding_mod.format_case_task(view)
        prompt = "Predict a label for this synthetic case using only its visible evidence. " + task
        trial = TrialPromptReceipt(
            prompt=prompt, prompt_sha256=_sha(prompt), condition="FROZEN",
            case_id=view["challenge_id"], cue_event_id="synthetic-cue",
            revision_id=None, review_evidence_ref=None, later_use_evidence_id=None,
        )
        synthetic_text = "A"  # NOT a model answer or evaluator truth.
        row = journal.append(
            invocation_id="synthetic-completed-1", route_ref="LOCAL_QVR_TEST",
            model="qwen3:4b-instruct", reported_model_digest="a" * 64,
            prompt_sha256=_sha(prompt), response_sha256=_sha(synthetic_text),
        )
        reopened = journal_mod.LocalCognitionJournal(Path(root) / "qvr.sqlite")
        reopened_ok = reopened.history() == [row]
        bound = binding_mod.bind_observed_trial_prediction(
            challenge_view=view, trial_prompt=trial, raw_model_response=synthetic_text,
            observed_record=row, arm="FROZEN", invocation_id="synthetic-completed-1",
        )
        params = binding_mod.controller_commit_parameters(bound)
        packet_ok = (
            set(params) == {"arm", "challenge_id", "prediction",
                            "challenge_view_digest", "model_prompt_sha256",
                            "model_response_sha256", "budget_units"}
            and params["challenge_view_digest"] == eval_mod.digest(view)
            and params["model_prompt_sha256"] == row["prompt_sha256"]
            and params["model_response_sha256"] == row["response_sha256"]
        )
        if not packet_ok:
            raise AssertionError("actual binder/evaluator packet contract drift")

        no_witness = _must_reject(
            lambda: controller.commit_prediction(**params),
            "independently verified dispatch evidence",
        )
        base_evidence = {
            "witness_kind": "same_host_self_report",
            "attestation_id": "test-only-attestation-1",
            "invocation_id": row["invocation_id"],
            "run_id": "TEST_ONLY",
            "arm": params["arm"], "challenge_id": params["challenge_id"],
            "challenge_view_digest": params["challenge_view_digest"],
            "model_prompt_sha256": params["model_prompt_sha256"],
            "model_response_sha256": params["model_response_sha256"],
            "model_identity": "synthetic-test-model",
            "model_artifact_sha256": "a" * 64,
            "dispatch_monotonic_ns": 100, "response_monotonic_ns": 200,
            "outcome_status": "COMPLETED",
        }
        test_controller = eval_mod.CausalTrialController(
            "GOAL1-SOURCE-CONTRACT-PROBE",
            dispatch_evidence_verifier=FakeVerifier(),
        )
        self_report = _must_reject(
            lambda: test_controller.commit_prediction(**params, dispatch_evidence=base_evidence),
            "independent dispatch witness",
        )
        unknown = _must_reject(
            lambda: test_controller.commit_prediction(
                **params, dispatch_evidence=dict(
                    base_evidence, witness_kind="independent_dispatch_gateway",
                    outcome_status="OUTCOME_UNKNOWN",
                ),
            ),
            "OUTCOME_UNKNOWN",
        )
        # Positive *protocol simulation* only: a caller-supplied FakeVerifier
        # can return True. This illustrates why a real independent witness is
        # indispensable. NEVER publish this receipt as execution evidence.
        simulated = test_controller.commit_prediction(
            **params, dispatch_evidence=dict(
                base_evidence, witness_kind="independent_dispatch_gateway"
            ),
        )
        simulation_ok = bool(simulated.get("dispatch_evidence_verified"))

    return {
        "schema": "GOAL1_CROSSBRANCH_SOURCE_PROBE_V1",
        "source_sha256": source_hashes,
        "protocol": {
            "public_packet_bound_to_actual_sources": packet_ok,
            "local_qvr_receipt_reopened": reopened_ok,
            "unrecorded_timeout_id_reusable": timeout_reusable,
            "unwitnessed_commit_rejected": no_witness,
            "self_report_rejected": self_report,
            "outcome_unknown_rejected": unknown,
            "test_only_verifier_accepted_synthetic_packet": simulation_ok,
        },
        "qualification": {
            "result": "BLOCKED", "passed": False,
            "blockers": [
                "NO_RESERVED_ATTEMPT_BEFORE_DISPATCH",
                "NO_INDEPENDENT_GATEWAY_ATTESTATION",
                "NO_FOUR_ARM_COLD_RESTART_CONTROLLED_RESULT",
            ],
            "claim_ceiling": "SOURCE_API_COMPATIBILITY_AND_SYNTHETIC_NEGATIVE_TEST",
        },
    }
