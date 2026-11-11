# Independent attack report: Vera Mono PR #86 inquiry binding

**Classification:** source-derived exploitability / contract gap. Reviewed implementation blob `2756c0c2c7e931daa531b93c84e69587526858fb` at PR #86 source revision `ba3b41013398df2919b606de757ec628aff91e12`. This report does not modify PR #86 and does not claim a live QVR/model invocation occurred.

## Attack A — fabricated journal row with internally consistent hashes

The API accepts `observed_record` as an ordinary caller-provided dictionary. Its checks validate shape, scalar types, identifier formats, and equality between the raw prompt/response hashes and the corresponding supplied record fields. The supplied `entry_digest` is only checked for 64 lowercase hex characters; this function does not recompute it from a canonical journal event or retrieve the event from a controller-owned journal.

A caller can therefore invent `runtime_pid`, `route_ref`, `model`, `observed_utc`, `sequence`, `entry_digest`, and the reported model digest, while hashing its own prompt/response consistently. The binder can return a `BoundInquiry`. The return flags remain false for `independently_witnessed`, `model_bytes_verified`, and `self_learning_verified`, which correctly limits its stated claim, but the returned object must not be treated as evidence that QVR ran.

**Required fix at the integration boundary:** accept a controller-issued, authenticated receipt ID rather than a journal-row dictionary; resolve it server-side; verify the receipt signature and attempt state; bind the observed runtime/build, route, prompt/response digest and trusted sequence to that receipt. Caller-authored fields remain claims.

## Attack B — false chronology / prediction after outcome

The binding function accepts a `sequence` integer but no evaluator-owned outcome sequence, monotonic witness, reservation receipt, or feedback-release record. The returned `preoutcome_subject_sha256` is a digest of caller-provided subject fields and prediction commitment; it is not itself a timestamp or witness.

Consequently, a row containing `sequence=1` does not establish that the prediction was committed before a label was released. A caller can create the entire record after learning the answer and still obtain a correctly formatted commitment.

**Required fix:** the independent controller must atomically reserve the attempt, commit the prediction under a server-issued monotonic sequence before feedback release, and enforce the state transition in controller-owned storage. The binder alone cannot solve chronology.

## Attack C — model identity confusion

`reported_model_digest` is format-checked and copied into the result. `model_byte_identity_verified` and `independent_attestation` are caller-provided booleans whose values are not promoted to true output flags; the result's `model_bytes_verified` and `independently_witnessed` defaults remain false. This is appropriately conservative, but a consumer that treats the reported digest or model name as verified identity would overclaim.

**Required fix:** distinguish a model-reported identifier, locally measured artifact digest, and independently attested loaded-weight identity as separate fields and evidence levels. The trusted runtime/host must produce and authenticate the receipt; the model must not be able to self-certify the weights used.

## Prompt leakage and learned influence

The schema rejects extra model-output keys and the pure function grants no authorization effects. That is useful input hygiene, not a proof of prompt secrecy or learning. A question can still be biased by information included in the prompt; this function does not inspect prompt provenance or show which prior state was supplied. The prediction commitment records a proposed label, but does not prove that the selected inquiry's answer was later acquired, that an artifact changed, that the exact artifact was loaded after restart, or that it caused improved behavior on held-out tasks.

**Required experiment:** log the exact pre-inquiry state/artifact digest, prompt digest, observed response receipt, selected inquiry, pre-feedback prediction, feedback release receipt, post-update artifact digest, and later runtime-consumption receipt under evaluator custody. After a cold process restart, test new held-out tasks and reversals against frozen, placebo, shuffled-feedback and memorizer arms with independently metered matched budgets and a predeclared negative-transfer veto.

## Evidence limits and next action

This is a source review of a pure binding helper. It is not a claim that a malicious host or model was observed in operation. The report belongs on the independent evaluator branch; PR #86's implementation remains with its owner. Until an authenticated controller boundary exists, describe these objects as **untrusted local inquiry bindings**, not verified invocation receipts or learning evidence.
