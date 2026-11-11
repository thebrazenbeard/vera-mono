# Goal 1 private holdout custody contract — evaluator preparation

## Current decision

The four HOLDOUT input/label pairs in the public synthetic causal_trial.py are disclosed fixtures, not private qualification truth. Do not reuse them or derive a new qualification suite from their labels. A source scan alone cannot prove a dataset is unseen or independently held.

This branch intentionally does not contain a new dataset, label, seed, answer key, encrypted answer key, or generation seed. No independent custodian boundary has been observed in the available authorized context; putting newly generated truth on the same candidate-readable host or in this repository would not satisfy the requested independence. Dataset creation is therefore prepared as a custody protocol, not falsely represented as a completed private dataset.

## Required independent preparation

1. A custodian who does not operate the candidate, learner, prompts, logs, evaluator source, or model endpoint generates a fresh suite after candidate and training sources are frozen.
2. Keep case inputs, labels, generation seed, and scoring key in a separate custodian-controlled store outside candidate-readable repositories, host profiles, model context, prompts, telemetry, and logs. The custodian must retain access/audit records.
3. Use a new task generator and mapping not derivable from the public four-case synthetic fixture. Freeze a manifest containing only suite ID, case count, task-family description, creation time, generator version digest, and custodian identity; do not include seed, labels, inputs, or reversible digests of low-entropy labels.
4. Give the learner only challenge inputs. The scorer retrieves labels after predictions and the attempt log are irrevocably frozen. Score independently; return aggregate scores and a non-sensitive audit receipt, never labels or per-case feedback to the learner until the protocol allows it.
5. Record exact candidate/model artifact and source heads before the custodian opens scoring. Pre-register arms, matched budgets, exclusions, stopping rule, transfer/reversal/negative-transfer tests, and distinct-process cold restart.
6. If independent custody cannot be demonstrated, mark GOAL1_PRIVATE_HOLDOUT_GATE=BLOCKED_CUSTODY_UNAVAILABLE; absence of a literal label in source is not proof of secrecy.

## Non-goals

This contract does not create or store truth, provision accounts or credentials, change ACLs, activate services, or qualify learning. No hidden labels are included in this repository.
