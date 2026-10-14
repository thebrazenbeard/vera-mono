# Endogenous Inquiry and Demonstrated Learning — Research Contract V1

Status: PROPOSED; source-level research only. Not implemented, installed, runtime-qualified, or evidence of AGI.
Baseline: vera-mono/main dd6fd951f2a935373d6d9e3a5958e77920626ba5, observed 2026-10-13.
Owner: Vera Mono. External training, Volition, and Conations repositories are optional research donors, not runtime dependencies.

## Research question

Can a system, without a user assigning the specific topic, identify a justified gap in its knowledge or competence, select a bounded inquiry, gather new evidence, and demonstrate that the resulting update improves later behavior on genuinely new cases?

A user authorizing the research program is distinct from a user choosing each specific inquiry. A scheduler firing is distinct from the system selecting what to learn. Generated interests, stable policy, endogenous cognition, learned behavior, independent agency, and subjective wanting remain separate claims.

## Existing verified source-level primitives

- Vera Mono already has a caller-supplied ClosedLoopTask with reason/action callbacks in packages/vera_core/src/vera_core/agi_closed_loop.py, and governed correction and learned-influence components.
- packages/vera_core/src/vera_core/agi_learning_probes.py contains developer-authored synthetic prequential, retention, and compositional learning probes. They explicitly do not establish independent qualification or AGI.
- packages/vera_core/src/vera_core/agi_long_horizon_probe.py tests bounded durability, correction and restart for a developer-authored plan, not independently selected inquiry.
- vera_memory governs learning influence, provenance and memory admission. A candidate result is not automatically a canonical memory.
- Research donor thebrazenbeard/volition, checked locally at dbc628d376515a0a523b1eecdf62129cca5d6b08, has epistemic and competence motive families, typed choices, bounded ENDOGENOUS cognition requests and effect_authority=False. These are research inputs, not proof Vera Mono consumes them.
- thebrazenbeard/vera_model_training is a separate external proxy/bootcamp workbench. Its proxy results do not establish Vera Mono native behavior.

The missing researched end-to-end proposition is independent *gap selection followed by demonstrable later-use learning* under controlled conditions. Do not implement a second motive engine or duplicate current learning machinery merely to rename it.

## Candidate evidence contract

Each proposed LearningOpportunity must preserve:
- Unique opportunity ID; original event IDs, timestamps and exact source digests; evidence class and currentness.
- A concrete falsifiable knowledge gap, contradiction or calibration deficit, along with rejected alternative explanations.
- Trigger/initiator: USER_DIRECTED, POLICY_DERIVED, MODEL_PROPOSED or ENDOGENOUS_CANDIDATE. This label is provenance, never proof of independently originated desire.
- Prior context and prompt contamination, including whether the user or developer named the question.
- Expected information gain, learning cost and risk; uncertainty; priority compared with other available gaps.
- Reason to select, defer or abstain, with deterministic budget/novelty and protection veto.
- Precommitted prediction, inquiry steps and stopping rule, recorded before evidence collection.
- Actual permitted evidence, negative results, contradictions, citations and confidence updates.
- Candidate knowledge/strategy revision, provenance, review state and exact linkage to later-use observations.
- Effect authority always false; reading/research does not grant permission to deploy, train on private materials, write canonical memory, change providers, or incur paid usage.

## Intended bounded composition

1. Detect possible gaps from already-permitted observations such as unresolved reasoning, poor calibration, recurring failure or conflicting evidence. Require fresh reappraisal: historical motives alone cannot become current drives.
2. Select a specific question or abstain under budget, duplication, safety, privacy and utility constraints. A merely echoed user request remains USER_DIRECTED.
3. Freeze a prediction, test and risk boundary before discovering the answer; preserve a replayable exact-source and exact-state cut.
4. Investigate only by permitted read-only or local sandbox methods. Protected external effects require their own qualified runtime and explicit authorization.
5. Produce a reviewable candidate update, not an automatic promotion to durable canonical/autobiographical truth. Separate remembered data, strategic adjustment and actual neural-weight training as different mechanisms.
6. Evaluate on later, unseen, non-identical cases with predict-then-score-then-update order. Include cold/restart retention and interference against previously qualified competence.
7. Reappraise, abandon or revise when evidence changes or the budget expires. The agent must be able to *stop* researching a bad question.

Composition target is the qualified host boundary vera_core.QualifiedVeraRuntime if and when separately authorized and proven installed/consumed. This document does not establish any such runtime.

## Experimental design and falsifiers

Pre-register dataset selection, evaluation metrics, source head, runtime identity, model/provider, tool access, observation budget, human intervention, failure reporting and contamination policy.

Compare four arms:
A. Candidate gap selection + bounded inquiry + reviewed candidate influence.
B. Same environment with inquiry disabled (no-learning baseline).
C. Developer/user-selected specific inquiry (prompt-following baseline).
D. Budget-matched randomized or unrelated inquiry (selection-value placebo).

Measure gap identification precision, false-positive curiosity, successful abstentions, sample/compute cost, prequential calibration, held-out later-use accuracy and gain over B/C/D, negative transfer, restart retention, and provenance/contamination. Evaluate across distinct task families and avoid using a single favorable example as qualification. The subject must not see held-out answer keys, scoring rubrics or future cases before decisions.

Qualification is BLOCKED if selection merely parrots user cues, the subject can see hidden answers, update/verification ordering is reversed, failure records disappear, unapproved effects occur, or later outcomes are no better than controls. Evidence for bounded self-selected inquiry does NOT establish self-authored desires, consciousness, generally intelligent agency or AGI.

## Narrow implementation sequence

Phase 1: exact-source inventory of current Vera Mono learning, inference, memory, dispatch and qualification primitives, and independent donor provenance. Resolve duplicate mechanisms before new code.
Phase 2: pure LearningOpportunity types with explicit initiator classification, novelty/validity gate, abstention, finite budgets, deterministic selection and rejection tests.
Phase 3: controlled local inquiry harness; precommitted predictions; sourced observations; candidate revisions without protected effects.
Phase 4: later-use A/B/C/D evaluation and cold transfer/restart metrics; evidence packets bound to exact head, held-out cut and negative results.
Phase 5: independent exact-cut hostile review. Runtime installation, live route, consumption and behavioral qualification remain separate stages needing separately verified evidence and authority.

## Internal hostile review

> Objection: Existing ClosedLoopFrontier, learned-influence gates, Volition drives and AGI probes may already cover much of this. A new learning engine risks duplicated abstractions and circular success criteria.

ACCEPTED. The smallest defensible addition is provenance-bound *gap selection* and a controlled *later-use comparison*. If source audit reveals an already equivalent end-to-end mechanism, close this proposal as duplicate and extend its actual tests.

> Objection: Any stable selection might be just an engineered ranking policy; positive behavior cannot prove volition or phenomenal experience.

ACCEPTED. Maximum defensible positive result is reproducible bounded selection of new inquiries and measured later-use adaptation under a named configuration. Neither subjective wanting nor AGI follows.

## Scope

Design/research artifact, not implemented behavior, runtime state, delegated active work, activation, independent review, or a claim that new learning has occurred. Keep main unmodified. No private conversation material or user-specific autobiographical content belongs in public training artifacts.
