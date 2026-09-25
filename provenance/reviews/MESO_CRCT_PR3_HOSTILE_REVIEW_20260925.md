# MESO-CRCT PR #3 hostile exact-head review

Subject: thebrazenbeard/meso-crct PR #3 at exact head 8316eb3c3a82705e227cb0c275877fae039ab75a.

## Independent verification

Local exact-head execution on Windows/Python 3.12: 218 passed.

This verifies the donor branch's executable consistency at that head. It does not establish that its policies are correct for Vera, that its thresholds generalize, or that the branch is installed anywhere.

## Mechanisms that survive review for Vera

The useful gap is pre-action salience and attention control, not a second action-selection stack.

Surviving mechanisms:
- typed perceptual, semantic, motivational, incentive, epistemic, hazard, avoidance, and satiation signals;
- dominant-driver arbitration instead of one global weighted utility;
- explicit nonprotective mode precedence;
- protective attention override;
- long-horizon attention-allocation auditing;
- separation of salience from truth and effect authority.

These fit upstream of Vera's existing governed InitiativeKernel and effect gates.

## Mechanisms rejected as duplicate or ownership-conflicting

Do not import:
- MESO action-tendency or intent proposal layers: Vera already has governed candidate/action selection and effect authority boundaries;
- MESO association memory/recall/review state: Vera already has memory, correction, provenance, and state owners;
- MESO provenance/transition receipt stack: Vera already has lifecycle, source, route, runtime-consumption, behavior, and independent-review receipts;
- MESO hedonic/welfare state: not required for the salience-control gap and would create a separate unresolved welfare ontology;
- MESO closed decision-cycle runtime: would create a competing planning owner.

## Hostile finding: protective saturation blind spot

MESO's audit_attention_budget excludes protective samples from ordinary allocation obligations. At the exact reviewed head, the following adversarial case was executed:

- 20/20 samples protective;
- maintenance obligation requires 50% nonprotective attention.

Observed donor result:

flags=()
goal_shares=(('goal:maintenance', 0.0),)
protective_samples=20
passed=True

This is internally consistent with MESO's rule that protection is unpreemptable, but it permits indefinite protective capture to be classified as a healthy allocation window.

Vera adaptation:
- protective attention remains unpreemptable by the salience layer;
- the audit additionally emits protective_saturation when the protective fraction exceeds policy;
- that flag is diagnostic only and grants no override or execution authority.

## Non-equivalences

salience != truth
salience != evidence
salience != authority
protective focus != effect authority
attention selection != action selection
action selection != execution
goal obligation != permission
dominant driver != semantic equivalence

## Integration target

runtime_cohesion.salience_control

The module is a pre-action attention/focus mechanism. Its outputs may inform later planning, but all action and protected-effect authority remains with existing Vera governance.

Claim ceiling: source-level bounded mechanism and tests only. No runtime installation, route selection, behavioral qualification, phenomenology, or AGI claim.