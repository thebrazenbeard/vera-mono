"""Later C cue identity must not relabel prior A/B evidence as new use."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vera_core.agi_method_research import (
    CalibrationCase,
    MethodSpec,
    consume_research_method,
    save_method_choice,
    select_calibrated_method,
    selection_revision,
)
from vera_memory import (
    DurableLearnedInfluenceGate,
    LearnedInfluenceBlocked,
    ReviewDisposition,
)


class LaterCueEvidenceSplitTests(unittest.TestCase):
    def test_cue_reused_from_current_or_historical_a_b_evidence_is_blocked(self):
        with TemporaryDirectory() as root:
            selection = Path(root) / "selected.json"
            baseline = MethodSpec("press-safety", (), "proceed")
            candidate = MethodSpec(
                "press-safety", (("danger", "inspect"),), "proceed"
            )
            choice = select_calibrated_method(baseline, (candidate,), (
                CalibrationCase("A:1", "Danger at press", "inspect"),
                CalibrationCase("A:2", "Conveyor clear", "proceed"),
            ))
            save_method_choice(selection, choice)
            revision = selection_revision(selection)
            gate = DurableLearnedInfluenceGate(Path(root) / "gate.db")
            gate.review_qualified(
                association_id=revision.association_id,
                memory_revision_id=revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:B-review",
                calibration_evidence_ids=choice.calibration_ids,
                qualification_evidence_ids=("B:1",),
            )
            for prior_id in ("A:1", "B:1"):
                with self.subTest(reused_cue=prior_id):
                    with self.assertRaises(LearnedInfluenceBlocked):
                        consume_research_method(
                            gate, selection, prompt="Danger at press",
                            cue_event_id=prior_id,
                            later_use_evidence_id=f"C:use:{prior_id}",
                        )
            # Clearing the current B bindings with a new qualified review
            # must not make its historical B cue admissible as a later C cue.
            gate.review_qualified(
                association_id=revision.association_id,
                memory_revision_id=revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:B-re-review",
                calibration_evidence_ids=choice.calibration_ids,
                qualification_evidence_ids=("B:2",),
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                consume_research_method(
                    gate, selection, prompt="Danger at press",
                    cue_event_id="B:1",
                    later_use_evidence_id="C:historical-B-use",
                )


if __name__ == "__main__":
    unittest.main()
